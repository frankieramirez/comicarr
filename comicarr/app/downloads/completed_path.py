#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Resolve the file Completed Download Handling should open on disk."""

from pathlib import Path

from comicarr import logger

_COMPLETED_ARCHIVE_SUFFIXES = (".cbr", ".cbz", ".cb7", ".cbt", ".pdf", ".zip", ".rar", ".7z")


def _is_regular_file(path):
    try:
        return path.is_file()
    except Exception as e:
        logger.fdebug("[DOWNLOADS-CDH] Could not stat %s: %s" % (path, e))
        return False


def _file_size(path):
    try:
        return path.stat().st_size
    except Exception as e:
        logger.fdebug("[DOWNLOADS-CDH] Could not size %s: %s" % (path, e))
        return -1


def resolve_completed_download_file(location, name=None):
    """Pick the completed-download file sitting on disk.

    NZBGet's location is already the job folder; history Name is the release
    name and is usually not a child file. SAB still reports parent + filename.
    A missing location/name path is never treated as the file to open.
    """
    if not location:
        return None
    loc = Path(location)
    if _is_regular_file(loc):
        return loc

    if name:
        named = loc / name
        if _is_regular_file(named):
            return named

    try:
        if not loc.is_dir():
            return None
        children = list(loc.iterdir())
    except Exception as e:
        logger.fdebug("[DOWNLOADS-CDH] Could not list completed folder %s: %s" % (location, e))
        return None

    regular = []
    archives = []
    for child in children:
        if not _is_regular_file(child):
            continue
        regular.append(child)
        if child.suffix.lower() in _COMPLETED_ARCHIVE_SUFFIXES:
            archives.append(child)

    if archives:
        return max(archives, key=_file_size)
    if len(regular) == 1:
        return regular[0]
    return None
