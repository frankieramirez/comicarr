#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Rematch a manga series folder using BareNumberMode.

``updater.forceRescan`` uses FileChecker and comic booktypes. Manga refresh
calls forceRescan after add, so volume files must go through the manga parser.
"""

import os

from sqlalchemy import select

from comicarr import db, logger
from comicarr.app.manga.parse import parse_in_series_context
from comicarr.scanutil import COMIC_EXTENSIONS
from comicarr.tables import issues as t_issues

MANGA_EXTENSIONS = COMIC_EXTENSIONS


def list_manga_files(directory):
    """Absolute paths of comic archives under ``directory``."""
    found = []
    if not directory or not os.path.isdir(directory):
        return found
    for root, _dirs, names in os.walk(directory):
        for name in names:
            if os.path.splitext(name)[1].lower() in MANGA_EXTENSIONS:
                found.append(os.path.join(root, name))
    found.sort()
    return found


def parse_folder_files(series, filenames, *, issues=None, series_name=None):
    """Parse sibling files with the series BareNumberMode."""
    name = series_name or (series or {}).get("ComicName")
    return [
        (
            path,
            parse_in_series_context(
                os.path.basename(path),
                series=series,
                filenames=filenames,
                series_name=name,
                issues=issues,
            ),
        )
        for path in filenames
    ]


def mark_parsed_files_downloaded(comic_id, files):
    """Mark matching chapter/volume rows Downloaded. Returns the mark count."""
    all_issues = db.select_all(select(t_issues).where(t_issues.c.ComicID == comic_id))
    if not all_issues:
        return 0

    chapter_lookup = {}
    volume_lookup = {}
    for issue in all_issues:
        ch = issue.get("ChapterNumber")
        vol = issue.get("VolumeNumber")
        if ch not in (None, ""):
            try:
                chapter_lookup[float(ch)] = issue
            except (TypeError, ValueError):
                pass
        if vol not in (None, ""):
            try:
                vol_key = int(float(vol))
                volume_lookup.setdefault(vol_key, []).append(issue)
            except (TypeError, ValueError):
                pass

    count = 0
    for filepath, parsed in files:
        if not parsed:
            continue
        filename = os.path.basename(filepath)
        matched = []
        if parsed.get("chapter_number") is not None:
            match = chapter_lookup.get(float(parsed["chapter_number"]))
            if match:
                matched = [match]
        if not matched and parsed.get("volume_number") is not None:
            matched = volume_lookup.get(int(parsed["volume_number"]), [])
        for issue in matched:
            if issue.get("Status") == "Downloaded":
                continue
            db.upsert(
                "issues",
                {"Status": "Downloaded", "Location": filename},
                {"IssueID": issue["IssueID"]},
            )
            issue["Status"] = "Downloaded"
            count += 1
            logger.fdebug("[MANGA-RESCAN] Marked as downloaded: %s -> %s" % (filename, issue["IssueID"]))

    if count > 0:
        have = db.select_all(select(t_issues).where(t_issues.c.ComicID == comic_id, t_issues.c.Status == "Downloaded"))
        db.upsert("comics", {"Have": len(have)}, {"ComicID": comic_id})
    return count


def rescan_manga_series(series, *, directory=None):
    """Walk the series folder and rematch files with the manga parser."""
    folder = directory or (series or {}).get("ComicLocation")
    comic_id = (series or {}).get("ComicID")
    logger.info("[MANGA-RESCAN] Checking files for %s in %s" % ((series or {}).get("ComicName"), folder))
    paths = list_manga_files(folder)
    if not comic_id:
        return 0
    issue_rows = db.select_all(select(t_issues).where(t_issues.c.ComicID == comic_id))
    parsed = parse_folder_files(series, paths, issues=issue_rows)
    return mark_parsed_files_downloaded(comic_id, parsed)
