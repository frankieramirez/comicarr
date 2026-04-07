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

from sqlalchemy import select

import comicarr
from comicarr import db, logger
from comicarr.tables import comics

# Scan status globals (for UI polling)
COMIC_SCAN_STATUS = None
COMIC_SCAN_PROGRESS = {
    "total_files": 0,
    "processed_files": 0,
    "series_found": 0,
    "series_matched": 0,
    "current_series": None,
    "errors": [],
}

# Scan results held for user selection
COMIC_SCAN_RESULTS = None
COMIC_SCAN_ID = None

_SCAN_LOCK = threading.Lock()

COMIC_EXTENSIONS = (".cbr", ".cbz", ".cb7", ".pdf")


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
        "scan_results": [],
        "errors": [],
    }

    try:
        # Step 1: Walk directory and group files by series folder
        series_map = _collect_series_files(comic_dir)

        COMIC_SCAN_PROGRESS["series_found"] = len(series_map)
        results["series_found"] = len(series_map)
        logger.info("[COMIC-SCAN] Found %d series directories" % len(series_map))

        # Load existing library series for de-duplication
        existing_series = _load_existing_series()

        # Step 2: For each series, try to match against ComicVine
        for series_name, files in series_map.items():
            COMIC_SCAN_PROGRESS["current_series"] = series_name

            try:
                match_result = _match_series(series_name, files, existing_series)
                results["scan_results"].append(match_result)
                if match_result.get("matched"):
                    results["series_matched"] += 1
                    COMIC_SCAN_PROGRESS["series_matched"] += 1
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

        # Store results for user selection
        COMIC_SCAN_ID = str(int(time.time()))
        COMIC_SCAN_RESULTS = results["scan_results"]

        logger.info(
            "[COMIC-SCAN] Scan complete. Matched: %d/%d series" % (results["series_matched"], results["series_found"])
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

            # Use the immediate parent directory as the series name
            rel_path = os.path.relpath(root, comic_dir)
            if rel_path == ".":
                # Files directly in comic_dir — guess series from filename
                series_name = _guess_series_from_filename(filename)
            else:
                # Use top-level directory name as series name
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
    # Remove trailing numbers (likely issue numbers)
    name = re.sub(r"\s+(#?\d+[\.\d]*)$", "", name).strip()
    # Remove trailing parenthetical year
    name = re.sub(r"\s*\(\d{4}\)\s*$", "", name).strip()
    return name if name else None


def _load_existing_series():
    """Load existing comic series from the library for de-duplication."""
    existing = {}
    try:
        with db.get_engine().connect() as conn:
            stmt = select(
                comics.c.ComicID,
                comics.c.ComicName,
                comics.c.ComicSortName,
                comics.c.DynamicName,
            ).where(comics.c.ContentType != "manga")
            for row in conn.execute(stmt):
                row_dict = dict(row._mapping)
                name = row_dict.get("ComicName", "")
                if name:
                    existing[_normalize_title(name)] = row_dict["ComicID"]
                sort_name = row_dict.get("ComicSortName", "")
                if sort_name:
                    existing[_normalize_title(sort_name)] = row_dict["ComicID"]
                dynamic_name = row_dict.get("DynamicName", "")
                if dynamic_name:
                    existing[_normalize_title(dynamic_name)] = row_dict["ComicID"]
    except Exception as e:
        logger.error("[COMIC-SCAN] Error loading existing series: %s" % e)
    return existing


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

    # Check if series already exists in library
    normalized = _normalize_title(series_name)
    if normalized in existing_series:
        result["already_in_library"] = True
        result["existing_comic_id"] = existing_series[normalized]
        logger.info("[COMIC-SCAN] Series '%s' already in library" % series_name)
        return result

    # Search ComicVine
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

    # Handle various return types from mb.findComic
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

    # Find best match using fuzzy name matching
    best_match, best_score = _find_best_match(series_name, comic_list)

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


def _find_best_match(series_name, results):
    """Find the best matching result from ComicVine search results.

    Returns (best_match_dict, best_score) or (None, 0.0).
    """
    best_match = None
    best_score = 0.0
    normalized_search = _normalize_title(series_name)

    for result in results:
        candidate = result.get("name", "")
        if not candidate:
            continue

        normalized_candidate = _normalize_title(candidate)

        if normalized_search == normalized_candidate:
            return result, 1.0

        score = _name_similarity(series_name, candidate)
        if score > best_score:
            best_score = score
            best_match = result

    return best_match, best_score


def _normalize_title(name):
    """Normalize a title for comparison: lowercase, strip punctuation and common particles."""
    name = name.lower().strip()
    # Remove common subtitle separators and everything after
    name = re.split(r"\s*[:\-–—~]\s*", name)[0]
    # Remove punctuation
    name = re.sub(r"[^\w\s]", "", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _name_similarity(name1, name2):
    """Similarity score between two names (0.0 to 1.0).

    Uses SequenceMatcher on normalized strings for character-level similarity,
    combined with Jaccard word overlap to handle word reordering.
    """
    from difflib import SequenceMatcher

    n1 = _normalize_title(name1)
    n2 = _normalize_title(name2)

    if not n1 or not n2:
        return 0.0

    if n1 == n2:
        return 1.0

    # Character-level sequence similarity
    seq_score = SequenceMatcher(None, n1, n2).ratio()

    # Word-level Jaccard similarity (handles reordering)
    s1 = set(n1.split())
    s2 = set(n2.split())
    jaccard = len(s1 & s2) / len(s1 | s2) if (s1 | s2) else 0.0

    # Containment check: if one name fully contains the other
    containment = 0.0
    if n1 in n2 or n2 in n1:
        containment = min(len(n1), len(n2)) / max(len(n1), len(n2))

    return max(seq_score, jaccard, containment)


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

    # Whitelist: only allow IDs that appeared in the scan results
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

    # Clear results after import
    COMIC_SCAN_RESULTS = None
    COMIC_SCAN_ID = None

    return {
        "success": True,
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
