#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Folder-aware parse kwargs for the manga filename parser.

Production callers must pass the series BareNumberMode and the folder's
bare numbers so ``Naruto 12.cbr`` can be a volume.
"""

import os
import re

from comicarr.app.manga.bare_numbers import normalize_mode
from comicarr.app.manga.ledger import normalize_volume_number

_BARE_NUMBER = re.compile(
    r"^(?P<series>.+?)\s+(?P<number>\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)


def collect_folder_bare_numbers(filenames):
    """Bare trailing numbers from sibling filenames (``Naruto 12.cbr``)."""
    numbers = []
    for name in filenames or ():
        stem = os.path.splitext(os.path.basename(name))[0].strip()
        match = _BARE_NUMBER.match(stem)
        if match:
            numbers.append(match.group("number"))
    return numbers


def ledger_counts_from_issues(issues):
    """Distinct volume numbers and chapter rows from a series issue list."""
    volumes = set()
    chapters = 0
    for issue in issues or ():
        volume = normalize_volume_number(issue.get("VolumeNumber"))
        if volume is not None:
            volumes.add(volume)
        if issue.get("ChapterNumber") not in (None, ""):
            chapters += 1
    return len(volumes), chapters


def parse_kwargs_for_series(series, filenames, *, volume_count=None, chapter_count=None):
    """Keyword arguments for ``parse_manga_filename`` on this folder."""
    mode = normalize_mode((series or {}).get("BareNumberMode"))
    return {
        "bare_number_mode": mode,
        "bare_numbers": collect_folder_bare_numbers(filenames),
        "volume_count": volume_count,
        "chapter_count": chapter_count,
    }


def parse_in_series_context(filename, *, series=None, filenames=None, series_name=None, issues=None):
    """Parse one file with the series setting and sibling folder counts."""
    from comicarr.manga_parser import parse_manga_filename

    siblings = list(filenames or (filename,))
    vol_count, ch_count = (None, None)
    if issues is not None:
        vol_count, ch_count = ledger_counts_from_issues(issues)
    kwargs = parse_kwargs_for_series(series, siblings, volume_count=vol_count, chapter_count=ch_count)
    return parse_manga_filename(filename, series_name=series_name, **kwargs)
