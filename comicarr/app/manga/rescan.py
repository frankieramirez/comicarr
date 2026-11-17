#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Rematch a manga series folder using BareNumberMode.

``folder_rescan.force_rescan`` uses FileChecker and comic booktypes. Manga refresh
calls the rescan after add, so volume files must go through the manga parser.
"""

import os

from sqlalchemy import select

from comicarr import db, logger
from comicarr.app.imports.scanutil import COMIC_EXTENSIONS
from comicarr.app.manga.parse import parse_in_series_context
from comicarr.tables import comics as t_comics
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


def _same_stem_different_ext(stored_name, filename):
    stored_stem, stored_ext = os.path.splitext(stored_name)
    file_stem, file_ext = os.path.splitext(filename)
    if not stored_stem or not stored_ext or not file_ext:
        return False
    return stored_stem == file_stem and stored_ext.lower() != file_ext.lower()


def _is_directly_in_directory(filepath, directory):
    if not filepath or not directory:
        return False
    parent = os.path.normpath(os.path.dirname(os.path.abspath(filepath)))
    root = os.path.normpath(os.path.abspath(directory))
    return parent == root


def _series_directory(comic_id, directory=None):
    if directory:
        return directory
    row = db.select_one(select(t_comics.c.ComicLocation).where(t_comics.c.ComicID == comic_id))
    if not row:
        return None
    return row.get("ComicLocation")


def _can_repoint_downloaded_location(directory, stored, filepath):
    """True when a Downloaded row should follow ``filepath``.

    Same-stem extension change at the series root (``.cbr`` -> ``.cbz``),
    or the stored basename is gone there and the candidate exists there.
    Nested leftovers and different-stem matches stay put.
    """
    filename = os.path.basename(filepath)
    stored_name = os.path.basename(stored) if stored else ""
    if stored_name == filename:
        return False
    if not _is_directly_in_directory(filepath, directory):
        return False
    if _same_stem_different_ext(stored_name, filename):
        return True
    stored_path = os.path.join(directory, stored_name) if directory and stored_name else None
    stored_missing = not stored_path or not os.path.isfile(stored_path)
    candidate_path = os.path.join(directory, filename) if directory else None
    return stored_missing and bool(candidate_path) and os.path.isfile(candidate_path)


def mark_parsed_files_downloaded(comic_id, files, *, directory=None):
    """Mark matching chapter rows Downloaded and record volume files. Returns the mark count.

    A volume file (a volume number and no chapter number) is recorded in
    ``manga_volumes`` as Downloaded (ADR-0004: volumes are not issues), the
    same as post-processing does. The chapters it contains then read as
    Covered, and the volume leaves the search frontier. A volume file is
    recorded even when MangaDex lists no chapters for that volume, so it is
    never dropped.

    Already-Downloaded rows keep their Status. Location is rewritten only
    for a same-stem extension change at the series root (e.g. metatag
    exported ``.cbr`` to ``.cbz``), or when the stored basename is gone
    there and the candidate exists there.
    """
    from comicarr.app.manga import volumes as manga_volumes
    from comicarr.app.manga.ledger import is_volume_target, normalize_volume_number

    all_issues = db.select_all(select(t_issues).where(t_issues.c.ComicID == comic_id))
    series_dir = _series_directory(comic_id, directory)

    chapter_lookup = {}
    for issue in all_issues or ():
        ch = issue.get("ChapterNumber")
        if ch not in (None, ""):
            try:
                chapter_lookup[float(ch)] = issue
            except (TypeError, ValueError):
                pass

    count = 0
    volume_files = {}
    for filepath, parsed in files:
        if not parsed:
            continue
        filename = os.path.basename(filepath)
        chapter_number = parsed.get("chapter_number")
        volume_number = normalize_volume_number(parsed.get("volume_number"))
        if is_volume_target(chapter_number, volume_number):
            volume_files.setdefault(volume_number, filename)
            continue
        if chapter_number is None:
            continue
        issue = chapter_lookup.get(float(chapter_number))
        if not issue:
            continue
        if issue.get("Status") == "Downloaded":
            if issue.get("Location") != filename and _can_repoint_downloaded_location(
                series_dir, issue.get("Location"), filepath
            ):
                db.upsert(
                    "issues",
                    {"Location": filename},
                    {"IssueID": issue["IssueID"]},
                )
                issue["Location"] = filename
                logger.fdebug("[MANGA-RESCAN] Updated location: %s -> %s" % (filename, issue["IssueID"]))
            continue
        db.upsert(
            "issues",
            {"Status": "Downloaded", "Location": filename},
            {"IssueID": issue["IssueID"]},
        )
        issue["Status"] = "Downloaded"
        issue["Location"] = filename
        count += 1
        logger.fdebug("[MANGA-RESCAN] Marked as downloaded: %s -> %s" % (filename, issue["IssueID"]))

    if volume_files:
        recorded = manga_volumes.volume_states(comic_id)
        for volume_number, filename in sorted(volume_files.items(), key=lambda item: _volume_sort_key(item[0])):
            if recorded.get(volume_number) not in manga_volumes.COVERING:
                count += 1
            manga_volumes.record_volume(comic_id, volume_number, manga_volumes.DOWNLOADED, location=filename)
            logger.fdebug("[MANGA-RESCAN] Volume %s is in the library: %s" % (volume_number, filename))
        count += _release_chapters_held_by_volume_files(all_issues or (), volume_files.values())

    if count > 0:
        db.upsert("comics", {"Have": owned_chapter_count(comic_id)}, {"ComicID": comic_id})
    return count


def _release_chapters_held_by_volume_files(issues, volume_filenames):
    """Hand chapters an older rescan marked Downloaded with a volume file back to their volume.

    Older rescans stored a volume file as the Location of every
    chapter row in that volume. Those chapters are not files of their own:
    the volume now records the file, and they read as Covered through it.
    A stored ``.cbr`` still matches a volume file re-exported as ``.cbz``.
    Returns how many rows changed.
    """
    stems = {os.path.splitext(name)[0] for name in volume_filenames}
    changed = 0
    for issue in issues:
        if issue.get("Status") != "Downloaded" or issue.get("ChapterNumber") in (None, ""):
            continue
        location = os.path.basename(issue.get("Location") or "")
        if not location or os.path.splitext(location)[0] not in stems:
            continue
        # Keep an explicit Wanted decision readable; otherwise the policy
        # default. Either way the owned volume covers the chapter.
        status = "Wanted" if str(issue.get("AcquisitionIntent") or "").lower() == "wanted" else "Skipped"
        db.upsert("issues", {"Status": status, "Location": None}, {"IssueID": issue["IssueID"]})
        changed += 1
        logger.fdebug(
            "[MANGA-RESCAN] %s is covered by volume file %s, not a file of its own"
            % (issue["IssueID"], issue.get("Location"))
        )
    return changed


def owned_chapter_count(comic_id):
    """Chapters the library can read: their own file, or inside an owned volume file."""
    from comicarr.app.manga import volumes as manga_volumes
    from comicarr.app.manga.ledger import normalize_volume_number

    placed = manga_volumes.covering_volumes(manga_volumes.volume_states(comic_id))
    rows = db.select_all(
        select(t_issues.c.Status, t_issues.c.ChapterNumber, t_issues.c.VolumeNumber).where(
            t_issues.c.ComicID == comic_id
        )
    )
    have = 0
    for row in rows or ():
        if row.get("Status") == "Downloaded":
            have += 1
        elif row.get("ChapterNumber") not in (None, "") and normalize_volume_number(row.get("VolumeNumber")) in placed:
            have += 1
    return have


def _volume_sort_key(number):
    try:
        return (0, float(number), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(number))


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
    return mark_parsed_files_downloaded(comic_id, parsed, directory=folder)
