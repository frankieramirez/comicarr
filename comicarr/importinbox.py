#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""
Import Inbox scanner — monitors IMPORT_DIR for new comic/manga files,
auto-imports high-confidence matches against library series, and queues
unmatched/low-confidence files into importresults for manual review.
"""

import hashlib
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select

import comicarr
from comicarr import db, logger
from comicarr.tables import comics

# Scan status globals (for UI polling)
INBOX_SCAN_STATUS = None
INBOX_SCAN_PROGRESS = {
    "total_files": 0,
    "processed_files": 0,
    "auto_imported": 0,
    "queued_for_review": 0,
    "current_group": None,
    "errors": [],
}

_SCAN_LOCK = threading.Lock()

COMIC_EXTENSIONS = (".cbr", ".cbz", ".cb7", ".pdf")

# Auto-import threshold (matches comicsync/mangasync ConfidenceBadge green)
AUTO_IMPORT_CONFIDENCE = 80


def inboxScan():
    """Scan IMPORT_DIR for new comic/manga files.

    Groups files by parent directory, fuzzy-matches each group against
    series already in the library. High-confidence matches (>=80) are
    auto-imported. Lower matches go to importresults for manual review.

    Returns dict with scan results.
    """
    global INBOX_SCAN_STATUS, INBOX_SCAN_PROGRESS

    if not _SCAN_LOCK.acquire(blocking=False):
        logger.warning("[IMPORT-INBOX] Scan already in progress, skipping")
        return {"status": "already_running"}

    import_dir = getattr(comicarr.CONFIG, "IMPORT_DIR", None) if comicarr.CONFIG else None
    if not import_dir:
        _SCAN_LOCK.release()
        logger.warning("[IMPORT-INBOX] Import directory not configured, skipping scan")
        return {"status": "skipped", "reason": "no_import_dir"}

    if not os.path.isdir(import_dir):
        _SCAN_LOCK.release()
        logger.warning("[IMPORT-INBOX] Cannot find import directory: %s" % import_dir)
        return {"status": "error", "reason": "directory_not_found", "path": import_dir}

    INBOX_SCAN_STATUS = "scanning"
    INBOX_SCAN_PROGRESS = {
        "total_files": 0,
        "processed_files": 0,
        "auto_imported": 0,
        "queued_for_review": 0,
        "current_group": None,
        "errors": [],
    }

    logger.info("[IMPORT-INBOX] Starting import inbox scan: %s" % import_dir)

    results = {
        "status": "completed",
        "total_files": 0,
        "auto_imported": 0,
        "queued_for_review": 0,
        "errors": [],
    }

    try:
        # Step 1: Walk import directory and group files by parent folder
        file_groups = _collect_file_groups(import_dir)

        total_files = sum(len(files) for files in file_groups.values())
        INBOX_SCAN_PROGRESS["total_files"] = total_files
        results["total_files"] = total_files
        logger.info("[IMPORT-INBOX] Found %d files in %d groups" % (total_files, len(file_groups)))

        if not file_groups:
            logger.info("[IMPORT-INBOX] No comic files found in import directory")
        else:
            # Step 2: Load series list from library once
            series_list = _load_library_series()

            # Step 3: Match each group against library series using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {}
                for group_name, files in file_groups.items():
                    future = executor.submit(_match_group, group_name, files, series_list)
                    futures[future] = group_name

                for future in as_completed(futures):
                    group_name = futures[future]
                    INBOX_SCAN_PROGRESS["current_group"] = group_name

                    try:
                        match_result = future.result()
                        results["auto_imported"] += match_result["auto_imported"]
                        results["queued_for_review"] += match_result["queued_for_review"]
                        INBOX_SCAN_PROGRESS["auto_imported"] += match_result["auto_imported"]
                        INBOX_SCAN_PROGRESS["queued_for_review"] += match_result["queued_for_review"]
                    except Exception as e:
                        logger.error("[IMPORT-INBOX] Error processing group '%s': %s" % (group_name, e))
                        results["errors"].append({"group": group_name, "error": str(e)})
                        INBOX_SCAN_PROGRESS["errors"].append(str(e))

                    INBOX_SCAN_PROGRESS["processed_files"] += len(file_groups[group_name])

        logger.info(
            "[IMPORT-INBOX] Scan complete. Auto-imported: %d, Queued: %d"
            % (results["auto_imported"], results["queued_for_review"])
        )
    except Exception as e:
        logger.error("[IMPORT-INBOX] Fatal error during scan: %s" % e)
        results["status"] = "error"
        results["errors"].append({"group": "scan", "error": str(e)})
        INBOX_SCAN_PROGRESS["errors"].append(str(e))
    finally:
        INBOX_SCAN_STATUS = "completed" if results["status"] != "error" else "error"
        INBOX_SCAN_PROGRESS["current_group"] = None
        _SCAN_LOCK.release()

    return results


def _collect_file_groups(import_dir):
    """Walk import_dir and group comic files by parent directory.

    Returns dict: {group_name: [filepath, ...]}
    """
    file_groups = {}

    for root, _dirs, files in os.walk(import_dir):
        for filename in files:
            if not any(filename.lower().endswith(ext) for ext in COMIC_EXTENSIONS):
                continue

            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(root, import_dir)

            if rel_path == ".":
                # Files directly in import_dir — each is its own group
                group_name = os.path.splitext(filename)[0]
            else:
                # Use top-level directory name as group
                group_name = rel_path.split(os.sep)[0]

            if group_name not in file_groups:
                file_groups[group_name] = []
            file_groups[group_name].append(filepath)

    return file_groups


def _load_library_series():
    """Load all comic series from the library for matching.

    Returns list of dicts with ComicID, ComicName, ComicSortName, DynamicName.
    """
    series_list = []
    try:
        with db.get_engine().connect() as conn:
            stmt = select(
                comics.c.ComicID,
                comics.c.ComicName,
                comics.c.ComicSortName,
                comics.c.DynamicName,
            )
            for row in conn.execute(stmt):
                series_list.append(dict(row._mapping))
    except Exception as e:
        logger.error("[IMPORT-INBOX] Error loading library series: %s" % e)
    return series_list


def _match_group(group_name, files, series_list):
    """Match a file group against library series.

    If best match >= AUTO_IMPORT_CONFIDENCE, auto-import all files.
    Otherwise, queue each file in importresults for manual review.

    Returns dict with auto_imported and queued_for_review counts.
    """
    from comicarr.comicsync import _name_similarity, _normalize_title

    result = {"auto_imported": 0, "queued_for_review": 0}

    best_match = None
    best_score = 0.0

    normalized_group = _normalize_title(group_name)

    for series in series_list:
        for name_field in ["ComicName", "ComicSortName", "DynamicName"]:
            candidate = series.get(name_field)
            if not candidate:
                continue

            normalized_candidate = _normalize_title(candidate)
            if normalized_group == normalized_candidate:
                best_match = series
                best_score = 1.0
                break

            score = _name_similarity(group_name, candidate)
            if score > best_score:
                best_score = score
                best_match = series

        if best_score == 1.0:
            break

    confidence = int(best_score * 100)

    if best_match and confidence >= AUTO_IMPORT_CONFIDENCE:
        # Auto-import: mark files as belonging to this series
        logger.info(
            "[IMPORT-INBOX] Auto-matching group '%s' to '%s' (%d%% confidence)"
            % (group_name, best_match.get("ComicName", ""), confidence)
        )
        for filepath in files:
            _auto_import_file(filepath, best_match, confidence)
            result["auto_imported"] += 1
    else:
        # Queue for manual review
        suggested_id = best_match["ComicID"] if best_match else None
        suggested_name = best_match.get("ComicName", "") if best_match else None
        logger.info(
            "[IMPORT-INBOX] Queuing group '%s' for review (best match: %s at %d%%)"
            % (group_name, suggested_name or "none", confidence)
        )
        for filepath in files:
            _queue_for_review(filepath, group_name, suggested_id, suggested_name, confidence)
            result["queued_for_review"] += 1

    return result


def _filepath_to_impid(filepath):
    """Generate a deterministic impID from a filepath for dedup across re-scans."""
    return hashlib.sha256(filepath.encode("utf-8")).hexdigest()[:32]


def _auto_import_file(filepath, series, confidence):
    """Record an auto-imported file in importresults with status=Imported."""
    filename = os.path.basename(filepath)
    imp_id = _filepath_to_impid(filepath)
    import_date = time.strftime("%Y-%m-%d %H:%M:%S")

    db.upsert(
        "importresults",
        {
            "ComicName": series.get("ComicName", ""),
            "Status": "Imported",
            "ImportDate": import_date,
            "ComicFilename": filename,
            "ComicLocation": filepath,
            "ComicID": series["ComicID"],
            "MatchConfidence": confidence,
            "SuggestedComicID": series["ComicID"],
            "SuggestedComicName": series.get("ComicName", ""),
            "MatchSource": "inbox",
            "DynamicName": series.get("DynamicName", ""),
        },
        {"impID": imp_id},
    )

    logger.fdebug("[IMPORT-INBOX] Auto-imported: %s -> %s" % (filename, series.get("ComicName", "")))


def _queue_for_review(filepath, group_name, suggested_id, suggested_name, confidence):
    """Queue a file in importresults for manual review."""
    filename = os.path.basename(filepath)
    imp_id = _filepath_to_impid(filepath)
    import_date = time.strftime("%Y-%m-%d %H:%M:%S")

    db.upsert(
        "importresults",
        {
            "ComicName": group_name,
            "Status": "Not Imported",
            "ImportDate": import_date,
            "ComicFilename": filename,
            "ComicLocation": filepath,
            "MatchConfidence": confidence if suggested_id else 0,
            "SuggestedComicID": suggested_id,
            "SuggestedComicName": suggested_name,
            "MatchSource": "inbox",
        },
        {"impID": imp_id},
    )

    logger.fdebug("[IMPORT-INBOX] Queued for review: %s" % filename)


def run():
    """Entry point for APScheduler — wraps inboxScan with graceful skip."""
    import_dir = getattr(comicarr.CONFIG, "IMPORT_DIR", None) if comicarr.CONFIG else None
    if not import_dir:
        logger.info("[IMPORT-INBOX] Import directory not configured, skipping scan")
        return

    logger.info("[IMPORT-INBOX] Scheduled scan starting")
    try:
        inboxScan()
    except Exception as e:
        logger.error("[IMPORT-INBOX] Scheduled scan failed: %s" % e)


def get_scan_progress():
    """Return current scan progress for UI polling."""
    return {
        "status": INBOX_SCAN_STATUS,
        "progress": INBOX_SCAN_PROGRESS.copy(),
    }
