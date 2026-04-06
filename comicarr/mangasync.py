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

MANGA_EXTENSIONS = (".cbr", ".cbz", ".cb7", ".pdf")


def mangaScan(dir=None, queue=None):
    """Scan a manga directory for existing manga files.

    Walks the directory tree, groups files by series (using parent directory
    name), parses filenames for chapter/volume info, matches series against
    MangaDex, and populates the library.

    Returns dict with scan results.
    """
    global MANGA_SCAN_STATUS, MANGA_SCAN_PROGRESS

    manga_dir = dir or getattr(comicarr.CONFIG, "MANGA_DIR", None)
    if not manga_dir:
        logger.warn("[MANGA-SCAN] No MANGA_DIR configured, skipping manga scan")
        return {"status": "skipped", "reason": "no_manga_dir"}

    if not os.path.isdir(manga_dir):
        logger.warn("[MANGA-SCAN] Cannot find manga directory: %s" % manga_dir)
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

    # Step 1: Walk directory and group files by series folder
    series_map = _collect_series_files(manga_dir)

    MANGA_SCAN_PROGRESS["series_found"] = len(series_map)
    logger.info("[MANGA-SCAN] Found %d series directories" % len(series_map))

    # Step 2: For each series, try to match against MangaDex and import
    results = {
        "status": "completed",
        "series_found": len(series_map),
        "series_matched": 0,
        "series_imported": 0,
        "chapters_marked_downloaded": 0,
        "unmatched_series": [],
        "errors": [],
    }

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

    MANGA_SCAN_STATUS = "completed"
    MANGA_SCAN_PROGRESS["current_series"] = None

    logger.info(
        "[MANGA-SCAN] Scan complete. Matched: %d/%d series, %d chapters marked downloaded"
        % (results["series_matched"], results["series_found"], results["chapters_marked_downloaded"])
    )

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


def _match_and_import_series(series_name, files):
    """Match a series against MangaDex and import it.

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

    # Search MangaDex for the series
    logger.info("[MANGA-SCAN] Searching MangaDex for: %s" % series_name)
    search_results = mangadex.search_manga(series_name, limit=5)

    if not search_results or not search_results.get("results"):
        logger.info("[MANGA-SCAN] No MangaDex match found for: %s" % series_name)
        return {"matched": False}

    # Auto-match on high confidence: exact name match (case-insensitive)
    best_match = None
    for result in search_results["results"]:
        result_name = result.get("name", "")
        if result_name.lower() == series_name.lower():
            best_match = result
            break

    # Fall back to first result if no exact match
    if not best_match:
        best_match = search_results["results"][0]
        confidence = _name_similarity(series_name, best_match.get("name", ""))
        if confidence < 0.7:
            logger.info(
                "[MANGA-SCAN] Low confidence match for '%s' -> '%s' (%.1f%%), skipping"
                % (series_name, best_match.get("name", ""), confidence * 100)
            )
            return {"matched": False}

    manga_id = best_match.get("comicid", "")
    if not manga_id:
        return {"matched": False}

    logger.info("[MANGA-SCAN] Matched '%s' to MangaDex: %s (%s)" % (series_name, best_match.get("name", ""), manga_id))

    # Import the manga using existing addMangaToDB
    importer.addMangaToDB(manga_id)

    # After import, mark chapters as Downloaded for files found on disk
    chapters_downloaded = _mark_chapters_downloaded(manga_id, files)

    return {"matched": True, "chapters_downloaded": chapters_downloaded, "mangadex_name": best_match.get("name", "")}


def _name_similarity(name1, name2):
    """Simple similarity score between two names (0.0 to 1.0)."""
    s1 = set(name1.lower().split())
    s2 = set(name2.lower().split())
    if not s1 or not s2:
        return 0.0
    intersection = s1 & s2
    union = s1 | s2
    return len(intersection) / len(union)


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
                volume_lookup[int(float(vol))] = issue
            except (ValueError, TypeError):
                pass

    for filepath, parsed in files:
        if not parsed:
            continue

        filename = os.path.basename(filepath)
        matched_issue = None

        # Try chapter match first
        if parsed.get("chapter_number") is not None:
            matched_issue = chapter_lookup.get(parsed["chapter_number"])

        # Fall back to volume match
        if not matched_issue and parsed.get("volume_number") is not None:
            matched_issue = volume_lookup.get(parsed["volume_number"])

        if matched_issue and matched_issue.get("Status") != "Downloaded":
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
