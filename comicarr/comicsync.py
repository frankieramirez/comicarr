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
Comic library scanner — walks COMIC_DIR, groups files by series,
matches against ComicVine metadata, and presents results for user
selection before importing.

Mirrors mangasync.py structure but for comic content with a
scan-then-select flow.
"""

import os
import re
import threading
import time

from sqlalchemy import or_, select

import comicarr
from comicarr import db, logger, updater
from comicarr.scanutil import COMIC_EXTENSIONS, find_best_match, normalize_title
from comicarr.tables import comics

COMIC_SCAN_STATUS = None
COMIC_SCAN_PROGRESS = {
    "total_files": 0,
    "processed_files": 0,
    "series_found": 0,
    "series_matched": 0,
    "series_reconciled": 0,
    "current_series": None,
    "errors": [],
}

COMIC_SCAN_RESULTS = None
COMIC_SCAN_ID = None

_SCAN_LOCK = threading.Lock()


def comicScan(scan_dir=None):
    """Scan a comic directory for existing comic files.

    Walks the directory tree, groups files by series (using parent directory
    name), matches series against ComicVine, and stores results for user
    selection. Does NOT auto-import.

    Returns dict with scan results.
    """
    global COMIC_SCAN_STATUS, COMIC_SCAN_PROGRESS, COMIC_SCAN_RESULTS, COMIC_SCAN_ID

    if not _SCAN_LOCK.acquire(blocking=False):
        logger.warning("[COMIC-SCAN] Scan already in progress, skipping")
        return {"status": "already_running"}

    comic_dir = scan_dir or comicarr.CONFIG.COMIC_DIR
    if not comic_dir:
        _SCAN_LOCK.release()
        logger.warning("[COMIC-SCAN] No COMIC_DIR configured, skipping comic scan")
        return {"status": "skipped", "reason": "no_comic_dir"}

    if not os.path.isdir(comic_dir):
        _SCAN_LOCK.release()
        logger.warning("[COMIC-SCAN] Cannot find comic directory: %s" % comic_dir)
        return {"status": "error", "reason": "directory_not_found", "path": comic_dir}

    COMIC_SCAN_STATUS = "scanning"
    COMIC_SCAN_PROGRESS = {
        "total_files": 0,
        "processed_files": 0,
        "series_found": 0,
        "series_matched": 0,
        "series_reconciled": 0,
        "current_series": None,
        "errors": [],
    }
    COMIC_SCAN_RESULTS = None
    COMIC_SCAN_ID = None

    logger.info("[COMIC-SCAN] Starting comic library scan: %s" % comic_dir)

    results = {
        "status": "completed",
        "series_found": 0,
        "series_matched": 0,
        "series_reconciled": 0,
        "scan_results": [],
        "errors": [],
    }

    try:
        series_map = _collect_series_files(comic_dir)

        COMIC_SCAN_PROGRESS["series_found"] = len(series_map)
        results["series_found"] = len(series_map)
        logger.info("[COMIC-SCAN] Found %d series directories" % len(series_map))

        existing_series = _load_existing_series()

        for series_name, files in series_map.items():
            COMIC_SCAN_PROGRESS["current_series"] = series_name

            try:
                match_result = _match_series(series_name, files, existing_series)
                results["scan_results"].append(match_result)
                if match_result.get("matched"):
                    results["series_matched"] += 1
                    COMIC_SCAN_PROGRESS["series_matched"] += 1
                if match_result.get("reconciled"):
                    results["series_reconciled"] += 1
                    COMIC_SCAN_PROGRESS["series_reconciled"] += 1
            except Exception as e:
                logger.error("[COMIC-SCAN] Error processing series '%s': %s" % (series_name, e))
                error_entry = {
                    "series_name": series_name,
                    "file_count": len(files),
                    "matched": False,
                    "error": str(e),
                }
                results["scan_results"].append(error_entry)
                results["errors"].append({"series": series_name, "error": str(e)})
                COMIC_SCAN_PROGRESS["errors"].append(str(e))

            COMIC_SCAN_PROGRESS["processed_files"] += len(files)

        COMIC_SCAN_ID = str(int(time.time()))
        COMIC_SCAN_RESULTS = results["scan_results"]

        logger.info(
            "[COMIC-SCAN] Scan complete. Reconciled: %d, matched: %d/%d series"
            % (results["series_reconciled"], results["series_matched"], results["series_found"])
        )
    except Exception as e:
        logger.error("[COMIC-SCAN] Fatal error during scan: %s" % e)
        results["status"] = "error"
        results["errors"].append({"series": "scan", "error": str(e)})
        COMIC_SCAN_PROGRESS["errors"].append(str(e))
    finally:
        COMIC_SCAN_STATUS = "completed" if results["status"] != "error" else "error"
        COMIC_SCAN_PROGRESS["current_series"] = None
        _SCAN_LOCK.release()

    return results


def _collect_series_files(comic_dir):
    """Walk comic_dir and group files by series directory.

    Expects structure: comic_dir/Series Name/files.cbz
    Returns dict: {series_name: [filepath, ...]}
    """
    series_map = {}

    for root, _dirs, files in os.walk(comic_dir):
        for filename in files:
            if not any(filename.lower().endswith(ext) for ext in COMIC_EXTENSIONS):
                continue

            filepath = os.path.join(root, filename)

            rel_path = os.path.relpath(root, comic_dir)
            if rel_path == ".":
                series_name = _guess_series_from_filename(filename)
            else:
                series_name = rel_path.split(os.sep)[0]

            if not series_name:
                logger.fdebug("[COMIC-SCAN] Could not determine series for: %s" % filepath)
                continue

            COMIC_SCAN_PROGRESS["total_files"] += 1

            if series_name not in series_map:
                series_map[series_name] = []
            series_map[series_name].append(filepath)

    return series_map


def _guess_series_from_filename(filename):
    """Extract a series name from a filename when no directory context is available."""
    name = os.path.splitext(filename)[0]
    if not name or name.startswith("."):
        return None
    name = re.sub(r"\s+(#?\d+[\.\d]*)$", "", name).strip()
    name = re.sub(r"\s*\(\d{4}\)\s*$", "", name).strip()
    return name if name else None


def _load_existing_series():
    """Index existing comic series by normalized display names."""
    existing = {}
    try:
        with db.get_engine().connect() as conn:
            stmt = select(
                comics.c.ComicID,
                comics.c.ComicName,
                comics.c.ComicSortName,
                comics.c.DynamicComicName,
                comics.c.ComicYear,
                comics.c.ComicLocation,
            ).where(or_(comics.c.ContentType.is_(None), comics.c.ContentType != "manga"))
            for row in conn.execute(stmt):
                row_dict = dict(row._mapping)
                for name in (
                    row_dict.get("ComicName", ""),
                    row_dict.get("ComicSortName", ""),
                    row_dict.get("DynamicComicName", ""),
                ):
                    normalized_name = normalize_title(name) if name else ""
                    if not normalized_name:
                        continue
                    candidates = existing.setdefault(normalized_name, [])
                    if not any(candidate["ComicID"] == row_dict["ComicID"] for candidate in candidates):
                        candidates.append(row_dict)
    except Exception as e:
        logger.error("[COMIC-SCAN] Error loading existing series: %s" % e)
    return existing


def _split_trailing_year(series_name):
    """Return a folder's display title and optional trailing series year."""
    match = re.match(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)\s*$", series_name)
    if not match:
        return series_name, None
    return match.group("title").strip(), match.group("year")


def _find_existing_series(series_name, existing_series):
    """Return one unambiguous existing series for a scanned folder name."""
    title, folder_year = _split_trailing_year(series_name)
    candidates = existing_series.get(normalize_title(title), [])
    if folder_year:
        candidates = [candidate for candidate in candidates if str(candidate.get("ComicYear") or "") == folder_year]
    return candidates[0] if len(candidates) == 1 else None


def _series_directory(files):
    """Return the scanned series directory shared by a group of files."""
    if len(files) == 1:
        return os.path.dirname(files[0])
    return os.path.commonpath(files)


def _reconcile_existing_series(existing_series, files):
    """Point an existing series at scanned files, then reuse the issue rescan."""
    comic_id = existing_series["ComicID"]
    scanned_location = _series_directory(files)
    previous_location = existing_series.get("ComicLocation")
    changed_location = os.path.normcase(os.path.normpath(str(previous_location or ""))) != os.path.normcase(
        os.path.normpath(scanned_location)
    )

    if changed_location:
        db.upsert("comics", {"ComicLocation": scanned_location}, {"ComicID": comic_id})

    try:
        updater.forceRescan(comic_id)
    except Exception:
        if changed_location:
            db.upsert("comics", {"ComicLocation": previous_location}, {"ComicID": comic_id})
        raise


def _match_series(series_name, files, existing_series):
    """Match a series folder against ComicVine and return structured result.

    Does NOT import — just returns match information for user selection.
    """
    from comicarr import mb

    result = {
        "series_name": series_name,
        "file_count": len(files),
        "matched": False,
        "already_in_library": False,
        "match": None,
    }

    existing = _find_existing_series(series_name, existing_series)
    if existing:
        _reconcile_existing_series(existing, files)
        result["already_in_library"] = True
        result["existing_comic_id"] = existing["ComicID"]
        result["reconciled"] = True
        logger.info("[COMIC-SCAN] Reconciled existing series '%s'" % series_name)
        return result

    logger.info("[COMIC-SCAN] Searching ComicVine for: %s" % series_name)
    try:
        search_results = mb.findComic(
            series_name,
            "series",
            issue=None,
            limit=5,
        )
    except Exception as e:
        logger.error("[COMIC-SCAN] ComicVine search failed for '%s': %s" % (series_name, e))
        result["error"] = "ComicVine search failed: %s" % str(e)
        return result

    if not search_results:
        logger.info("[COMIC-SCAN] No match found for: %s" % series_name)
        return result

    if isinstance(search_results, dict):
        comic_list = search_results.get("results", [])
    elif isinstance(search_results, list):
        comic_list = search_results
    else:
        logger.info("[COMIC-SCAN] No match found for: %s" % series_name)
        return result

    if not comic_list:
        logger.info("[COMIC-SCAN] No match found for: %s" % series_name)
        return result

    best_match, best_score = find_best_match(series_name, comic_list)

    if not best_match or best_score < 0.5:
        logger.info("[COMIC-SCAN] No confident match for '%s' (best score: %.1f%%)" % (series_name, best_score * 100))
        return result

    confidence = int(best_score * 100)
    result["matched"] = True
    result["match"] = {
        "comicid": best_match.get("comicid"),
        "name": best_match.get("name", ""),
        "year": best_match.get("comicyear", ""),
        "publisher": best_match.get("publisher", ""),
        "issues": best_match.get("issues", "0"),
        "image": best_match.get("comicthumb") or best_match.get("comicimage"),
        "confidence": confidence,
    }

    if best_score < 1.0:
        logger.info(
            "[COMIC-SCAN] Fuzzy match for '%s' -> '%s' (%d%%)" % (series_name, best_match.get("name", ""), confidence)
        )
    else:
        logger.info(
            "[COMIC-SCAN] Matched '%s' to ComicVine: %s (%s)"
            % (series_name, best_match.get("name", ""), best_match.get("comicid"))
        )

    return result


def import_selected_series(selected_ids, scan_id):
    """Import user-selected series from scan results.

    Args:
        selected_ids: List of ComicVine IDs to import
        scan_id: Timestamp of the scan these results came from

    Returns dict with import results.
    """
    global COMIC_SCAN_RESULTS, COMIC_SCAN_ID

    from comicarr import importer

    if COMIC_SCAN_ID != scan_id:
        return {
            "success": False,
            "error": "Scan results have changed, please review again",
            "stale": True,
        }

    if not selected_ids:
        return {"success": False, "error": "No series selected"}

    if not COMIC_SCAN_RESULTS:
        return {"success": False, "error": "No scan results available"}

    allowed_ids = {r["match"]["comicid"] for r in COMIC_SCAN_RESULTS if r.get("matched") and r.get("match")}

    imported = 0
    errors = []

    for comic_id in selected_ids:
        if comic_id not in allowed_ids:
            logger.warning("[COMIC-SCAN] Rejected ID not in scan results: %s" % comic_id)
            errors.append({"comicid": comic_id, "error": "ID not found in scan results"})
            continue
        try:
            logger.info("[COMIC-SCAN] Importing series: %s" % comic_id)
            importer.addComictoDB(comic_id)
            imported += 1
        except Exception as e:
            logger.error("[COMIC-SCAN] Failed to import %s: %s" % (comic_id, e))
            errors.append({"comicid": comic_id, "error": str(e)})

    if not errors:
        COMIC_SCAN_RESULTS = None
        COMIC_SCAN_ID = None

    return {
        "success": len(errors) == 0,
        "imported": imported,
        "errors": errors,
    }


def get_scan_progress():
    """Return current scan progress for UI polling."""
    return {
        "status": COMIC_SCAN_STATUS,
        "progress": COMIC_SCAN_PROGRESS.copy(),
        "scan_id": COMIC_SCAN_ID,
        "results": COMIC_SCAN_RESULTS,
    }
