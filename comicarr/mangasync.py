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
Manga library scanner — walks MANGA_DIR, groups files by series,
matches against MangaDex metadata, and populates the library.

Mirrors librarysync.py but for manga content.
"""

import os
import re
import threading

from sqlalchemy import select

import comicarr
from comicarr import db, logger
from comicarr.manga_parser import parse_manga_filename
from comicarr.tables import comics, issues

# Scan status globals (for UI polling)
MANGA_SCAN_STATUS = None
MANGA_SCAN_PROGRESS = {
    "total_files": 0,
    "processed_files": 0,
    "series_found": 0,
    "series_matched": 0,
    "series_imported": 0,
    "current_series": None,
    "errors": [],
}

_SCAN_LOCK = threading.Lock()

MANGA_EXTENSIONS = (".cbr", ".cbz", ".cb7", ".pdf")


def mangaScan(scan_dir=None, queue=None):
    """Scan a manga directory for existing manga files.

    Walks the directory tree, groups files by series (using parent directory
    name), parses filenames for chapter/volume info, matches series against
    MangaDex, and populates the library.

    Returns dict with scan results.
    """
    global MANGA_SCAN_STATUS, MANGA_SCAN_PROGRESS

    if not _SCAN_LOCK.acquire(blocking=False):
        logger.warning("[MANGA-SCAN] Scan already in progress, skipping")
        return {"status": "already_running"}

    manga_dir = scan_dir or comicarr.CONFIG.MANGA_DIR
    if not manga_dir:
        _SCAN_LOCK.release()
        logger.warning("[MANGA-SCAN] No MANGA_DIR configured, skipping manga scan")
        return {"status": "skipped", "reason": "no_manga_dir"}

    if not os.path.isdir(manga_dir):
        _SCAN_LOCK.release()
        logger.warning("[MANGA-SCAN] Cannot find manga directory: %s" % manga_dir)
        return {"status": "error", "reason": "directory_not_found", "path": manga_dir}

    MANGA_SCAN_STATUS = "scanning"
    MANGA_SCAN_PROGRESS = {
        "total_files": 0,
        "processed_files": 0,
        "series_found": 0,
        "series_matched": 0,
        "series_imported": 0,
        "current_series": None,
        "errors": [],
    }

    logger.info("[MANGA-SCAN] Starting manga library scan: %s" % manga_dir)

    results = {
        "status": "completed",
        "series_found": 0,
        "series_matched": 0,
        "series_imported": 0,
        "chapters_marked_downloaded": 0,
        "unmatched_series": [],
        "errors": [],
    }

    try:
        # Step 1: Walk directory and group files by series folder
        series_map = _collect_series_files(manga_dir)

        MANGA_SCAN_PROGRESS["series_found"] = len(series_map)
        results["series_found"] = len(series_map)
        logger.info("[MANGA-SCAN] Found %d series directories" % len(series_map))

        # Step 2: For each series, try to match against MangaDex and import
        for series_name, files in series_map.items():
            MANGA_SCAN_PROGRESS["current_series"] = series_name

            try:
                match_result = _match_and_import_series(series_name, files)
                if match_result["matched"]:
                    results["series_matched"] += 1
                    results["series_imported"] += 1
                    results["chapters_marked_downloaded"] += match_result.get("chapters_downloaded", 0)
                    MANGA_SCAN_PROGRESS["series_matched"] += 1
                    MANGA_SCAN_PROGRESS["series_imported"] += 1
                else:
                    results["unmatched_series"].append(series_name)
            except Exception as e:
                logger.error("[MANGA-SCAN] Error processing series '%s': %s" % (series_name, e))
                results["errors"].append({"series": series_name, "error": str(e)})
                MANGA_SCAN_PROGRESS["errors"].append(str(e))

            MANGA_SCAN_PROGRESS["processed_files"] += len(files)

        logger.info(
            "[MANGA-SCAN] Scan complete. Matched: %d/%d series, %d chapters marked downloaded"
            % (results["series_matched"], results["series_found"], results["chapters_marked_downloaded"])
        )
    except Exception as e:
        logger.error("[MANGA-SCAN] Fatal error during scan: %s" % e)
        results["status"] = "error"
        results["errors"].append({"series": "scan", "error": str(e)})
        MANGA_SCAN_PROGRESS["errors"].append(str(e))
    finally:
        MANGA_SCAN_STATUS = "completed" if results["status"] != "error" else "error"
        MANGA_SCAN_PROGRESS["current_series"] = None
        _SCAN_LOCK.release()

    return results


def _collect_series_files(manga_dir):
    """Walk manga_dir and group files by series directory.

    Expects structure: manga_dir/Series Name/files.cbz
    Returns dict: {series_name: [(filepath, parsed_info), ...]}
    """
    series_map = {}

    for root, _dirs, files in os.walk(manga_dir):
        for filename in files:
            if not any(filename.lower().endswith(ext) for ext in MANGA_EXTENSIONS):
                continue

            filepath = os.path.join(root, filename)
            parsed = parse_manga_filename(filename)

            # Use the immediate parent directory as the series name
            # e.g., /manga/Bleach/Bleach v1.cbz -> series = "Bleach"
            rel_path = os.path.relpath(root, manga_dir)
            if rel_path == ".":
                # Files directly in manga_dir — use parsed series name
                series_name = parsed["series_name"] if parsed else _guess_series_from_filename(filename)
            else:
                # Use top-level directory name as series name
                series_name = rel_path.split(os.sep)[0]

            if not series_name:
                logger.fdebug("[MANGA-SCAN] Could not determine series for: %s" % filepath)
                continue

            MANGA_SCAN_PROGRESS["total_files"] += 1

            if series_name not in series_map:
                series_map[series_name] = []
            series_map[series_name].append((filepath, parsed))

    return series_map


def _guess_series_from_filename(filename):
    """Extract a series name from a filename when no directory context is available."""
    # Strip extension
    name = os.path.splitext(filename)[0]
    # Remove trailing numbers (likely chapter/volume)
    name = re.sub(r"\s+(v?\d+[\.\d]*)$", "", name).strip()
    return name if name else None


def _find_best_match(series_name, results):
    """Find the best matching result from a search results list.

    Checks primary title and alt titles for each result using fuzzy matching.

    Returns (best_match_dict, best_score) or (None, 0.0).
    """
    best_match = None
    best_score = 0.0
    normalized_search = _normalize_title(series_name)

    for result in results:
        candidate_names = [result.get("name", "")]
        candidate_names.extend(result.get("alt_titles", []))

        for candidate in candidate_names:
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


def _match_and_import_series(series_name, files):
    """Match a series against MAL (if enabled) or MangaDex and import it.

    Returns dict with 'matched' bool and details.
    """
    from comicarr import importer, mangadex

    # Check if series already exists in library by name
    with db.get_engine().connect() as conn:
        stmt = select(comics).where(
            comics.c.ComicName == series_name,
            comics.c.ContentType == "manga",
        )
        existing = next((dict(row._mapping) for row in conn.execute(stmt)), None)

    if existing:
        logger.info("[MANGA-SCAN] Series '%s' already in library, updating chapter statuses" % series_name)
        chapters_downloaded = _mark_chapters_downloaded(existing["ComicID"], files)
        return {"matched": True, "chapters_downloaded": chapters_downloaded, "already_existed": True}

    # Try MAL first if enabled
    mal_enabled = getattr(comicarr.CONFIG, "MAL_ENABLED", False)
    mal_client_id = getattr(comicarr.CONFIG, "MAL_CLIENT_ID", None)

    if mal_enabled and mal_client_id:
        from comicarr import myanimelist

        logger.info("[MANGA-SCAN] Searching MAL for: %s" % series_name)
        try:
            search_results = myanimelist.search_manga(series_name, limit=5)
            if search_results and search_results.get("results"):
                best_match, best_score = _find_best_match(series_name, search_results["results"])
                if best_match and best_score >= 0.6:
                    manga_id = best_match.get("comicid", "")
                    if manga_id:
                        if best_score < 1.0:
                            logger.info(
                                "[MANGA-SCAN] MAL fuzzy match for '%s' -> '%s' (%.1f%%)"
                                % (series_name, best_match.get("name", ""), best_score * 100)
                            )
                        logger.info(
                            "[MANGA-SCAN] Matched '%s' to MAL: %s (%s)"
                            % (series_name, best_match.get("name", ""), manga_id)
                        )
                        importer.addMangaToDB_MAL(manga_id)
                        chapters_downloaded = _mark_chapters_downloaded(manga_id, files)
                        return {
                            "matched": True,
                            "chapters_downloaded": chapters_downloaded,
                            "source": "mal",
                            "matched_name": best_match.get("name", ""),
                        }
        except Exception as e:
            logger.error("[MANGA-SCAN] MAL search failed for '%s': %s" % (series_name, e))

    # Fall back to MangaDex
    logger.info("[MANGA-SCAN] Searching MangaDex for: %s" % series_name)
    search_results = mangadex.search_manga(series_name, limit=5)

    if not search_results or not search_results.get("results"):
        logger.info("[MANGA-SCAN] No match found for: %s" % series_name)
        return {"matched": False}

    best_match, best_score = _find_best_match(series_name, search_results["results"])

    if not best_match or best_score < 0.6:
        logger.info(
            "[MANGA-SCAN] No confident match for '%s' (best score: %.1f%%), skipping"
            % (series_name, best_score * 100)
        )
        return {"matched": False}

    if best_score < 1.0:
        logger.info(
            "[MANGA-SCAN] Fuzzy match for '%s' -> '%s' (%.1f%%)"
            % (series_name, best_match.get("name", ""), best_score * 100)
        )

    manga_id = best_match.get("comicid", "")
    if not manga_id:
        return {"matched": False}

    logger.info("[MANGA-SCAN] Matched '%s' to MangaDex: %s (%s)" % (series_name, best_match.get("name", ""), manga_id))

    importer.addMangaToDB(manga_id)
    chapters_downloaded = _mark_chapters_downloaded(manga_id, files)

    return {"matched": True, "chapters_downloaded": chapters_downloaded, "mangadex_name": best_match.get("name", "")}


def _normalize_title(name):
    """Normalize a title for comparison: lowercase, strip punctuation and common particles."""
    name = name.lower().strip()
    # Remove common subtitle separators and everything after
    # e.g. "Hajime no Ippo: The Fighting!" -> "hajime no ippo"
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

    # Exact match after normalization
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


def _mark_chapters_downloaded(comic_id, files):
    """Mark chapters as Downloaded based on files found on disk.

    Matches parsed chapter/volume numbers from filenames to existing
    issue records in the database.

    Returns count of chapters marked.
    """
    count = 0

    # Get all issues for this comic
    with db.get_engine().connect() as conn:
        stmt = select(issues).where(issues.c.ComicID == comic_id)
        all_issues = [dict(row._mapping) for row in conn.execute(stmt)]

    if not all_issues:
        return 0

    # Build lookup by chapter number and volume number
    # Volume lookup maps to a list since multiple chapters share a volume
    chapter_lookup = {}
    volume_lookup = {}
    for issue in all_issues:
        ch = issue.get("ChapterNumber")
        vol = issue.get("VolumeNumber")
        if ch:
            try:
                chapter_lookup[float(ch)] = issue
            except (ValueError, TypeError):
                pass
        if vol:
            try:
                vol_key = int(float(vol))
                if vol_key not in volume_lookup:
                    volume_lookup[vol_key] = []
                volume_lookup[vol_key].append(issue)
            except (ValueError, TypeError):
                pass

    for filepath, parsed in files:
        if not parsed:
            continue

        filename = os.path.basename(filepath)
        matched_issues = []

        # Try chapter match first
        if parsed.get("chapter_number") is not None:
            match = chapter_lookup.get(parsed["chapter_number"])
            if match:
                matched_issues = [match]

        # Fall back to volume match — mark all chapters in the volume
        if not matched_issues and parsed.get("volume_number") is not None:
            matched_issues = volume_lookup.get(parsed["volume_number"], [])

        for matched_issue in matched_issues:
            if matched_issue.get("Status") != "Downloaded":
                issue_id = matched_issue["IssueID"]
                db.upsert(
                    "issues",
                    {"Status": "Downloaded", "Location": filename},
                    {"IssueID": issue_id},
                )
                count += 1
                logger.fdebug("[MANGA-SCAN] Marked as downloaded: %s -> %s" % (filename, issue_id))

    # Update the Have count for the comic
    if count > 0:
        with db.get_engine().connect() as conn:
            stmt = select(issues).where(
                issues.c.ComicID == comic_id,
                issues.c.Status == "Downloaded",
            )
            have_count = len([dict(row._mapping) for row in conn.execute(stmt)])
        db.upsert("comics", {"Have": have_count}, {"ComicID": comic_id})

    return count


def get_scan_progress():
    """Return current scan progress for UI polling."""
    return {
        "status": MANGA_SCAN_STATUS,
        "progress": MANGA_SCAN_PROGRESS.copy(),
    }
