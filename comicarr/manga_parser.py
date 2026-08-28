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
Manga filename parser.

Pure-function module that extracts series name, chapter number, volume number,
and optional metadata (scanlation group, quality tags) from manga filenames.

Handles common naming conventions found in manga libraries:
    [Group] Title - c001 (v01) [quality].cbz
    Title v01 c001.cbz
    Title - Chapter 001.cbz
    Title Vol.01 Ch.001.cbz
    Title 001.cbz              (bare number; volumes/chapters/auto)
    Title v01.cbz              (volume only)
    chapter 001.cbz            (when series_name is supplied)
"""

import os
import re

VALID_EXTENSIONS = {".cbr", ".cbz", ".cb7", ".pdf"}


_PAT_GROUP_FULL = re.compile(
    r"^\[(?P<group>[^\]]+)\]\s*"
    r"(?P<series>.+?)\s*"
    r"-\s*c(?P<chapter>\d+(?:\.\d+)?)"
    r"(?:\s*-\s*c?\d+(?:\.\d+)?)?"
    r"(?:\s*\(v(?P<volume>\d+)\))?"
    r"(?:\s*\[(?P<quality>[^\]]+)\])?"
    r"\s*$",
    re.IGNORECASE,
)


_PAT_VOL_CH_ABBR = re.compile(
    r"^(?P<series>.+?)\s+"
    r"[Vv]ol\.?\s*(?P<volume>\d+)\s+"
    r"[Cc]h\.?\s*(?P<chapter>\d+(?:\.\d+)?)"
    r"\s*$",
)

_PAT_V_C = re.compile(
    r"^(?P<series>.+?)\s+"
    r"[Vv](?P<volume>\d+)\s+"
    r"[Cc](?P<chapter>\d+(?:\.\d+)?)"
    r"\s*$",
)

_PAT_CHAPTER_LABEL = re.compile(
    r"^(?P<series>.+?)\s*"
    r"-\s*[Cc]hapter\s+(?P<chapter>\d+(?:\.\d+)?)"
    r"\s*$",
)

_PAT_CHAPTER_PREFIX = re.compile(
    r"^(?P<series>.+?)\s+"
    r"[Cc](?P<chapter>\d+(?:\.\d+)?)"
    r"(?:\s*-\s*c?\d+(?:\.\d+)?)?"
    r"\s*$",
)

_PAT_VOLUME_ONLY = re.compile(
    r"^(?P<series>.+?)\s+"
    r"[Vv](?P<volume>\d+)"
    r"\s*$",
)

_PAT_BARE_NUMBER = re.compile(
    r"^(?P<series>.+?)\s+"
    r"(?P<chapter>\d+(?:\.\d+)?)"
    r"\s*$",
)

_PAT_CHAPTER_ONLY_LABEL = re.compile(
    r"^(?:[Cc]h(?:apter)?\.?)\s*(?P<chapter>\d+(?:\.\d+)?)"
    r"\s*$",
)

_PAT_CHAPTER_ONLY_NUMBER = re.compile(
    r"^(?P<chapter>\d+(?:\.\d+)?)"
    r"\s*$",
)

_PATTERNS = [
    _PAT_GROUP_FULL,
    _PAT_VOL_CH_ABBR,
    _PAT_V_C,
    _PAT_CHAPTER_LABEL,
    _PAT_CHAPTER_PREFIX,
    _PAT_VOLUME_ONLY,
    _PAT_BARE_NUMBER,
]


def parse_manga_filename(
    filename,
    series_name=None,
    bare_number_mode="auto",
    bare_numbers=None,
    volume_count=None,
    chapter_count=None,
):
    """Parse a manga filename and return extracted metadata.

    Args:
        filename: The filename (with or without directory path) to parse.
        series_name: Optional folder-derived series name. When supplied, the
            parser can infer chapter-only names like ``chapter 1.cbz`` without
            replacing the caller's series name.
        bare_number_mode: ``volumes``, ``chapters``, or ``auto``.
        bare_numbers: Folder-level bare numbers used by auto.
        volume_count: Known volume-ledger size for auto.
        chapter_count: Known chapter-ledger size for auto.

    Returns:
        A dict with keys ``series_name``, ``chapter_number`` (float or None),
        ``volume_number`` (int or None), ``group`` (str or None), and
        ``quality`` (str or None).  Returns ``None`` when the filename
        cannot be parsed or has an invalid extension.
    """
    basename = os.path.basename(filename)

    stem, ext = os.path.splitext(basename)
    if ext.lower() not in VALID_EXTENSIONS:
        return None

    stem = stem.strip()
    if not stem or len(stem) > 512:
        return None

    chapter_only = _parse_chapter_only_stem(stem)
    if chapter_only is not None:
        if not series_name:
            return None
        return _build_context_result(series_name, chapter_only)

    from comicarr.app.manga.bare_numbers import apply_bare_number, interpret_bare_numbers

    resolved_mode = interpret_bare_numbers(
        bare_number_mode,
        bare_numbers=bare_numbers,
        volume_count=volume_count,
        chapter_count=chapter_count,
    )
    for pattern in _PATTERNS:
        m = pattern.match(stem)
        if m:
            result = _build_result(m)
            if result is not None and pattern is _PAT_BARE_NUMBER:
                return apply_bare_number(result, resolved_mode)
            return result

    if series_name:
        chapter = parse_manga_chapter_number(filename)
        if chapter is not None:
            return {
                "series_name": str(series_name).strip(),
                "chapter_number": chapter,
                "volume_number": None,
                "group": None,
                "quality": None,
            }

    return None


def parse_manga_chapter_number(filename):
    """Return an inferred chapter number from a manga filename, or None."""
    basename = os.path.basename(filename)
    stem, ext = os.path.splitext(basename)
    if ext.lower() not in VALID_EXTENSIONS:
        return None

    stem = stem.strip()
    if not stem or len(stem) > 512:
        return None

    for pattern in _PATTERNS:
        m = pattern.match(stem)
        if m:
            groups = m.groupdict()
            return _to_chapter_number(groups.get("chapter"))

    return _parse_chapter_only_stem(stem)


def _parse_chapter_only_stem(stem):
    """Parse chapter-only filename stems."""
    for pattern in (_PAT_CHAPTER_ONLY_LABEL, _PAT_CHAPTER_ONLY_NUMBER):
        m = pattern.match(stem)
        if m:
            return _to_chapter_number(m.group("chapter"))
    return None


def _build_context_result(series_name, chapter):
    series = str(series_name).strip()
    if not series:
        return None
    return {
        "series_name": series,
        "chapter_number": chapter,
        "volume_number": None,
        "group": None,
        "quality": None,
    }


def _build_result(match):
    """Build a result dict from a regex match object."""
    groups = match.groupdict()

    series = groups.get("series")
    if series:
        series = series.strip().rstrip("-").strip()
    if not series:
        return None

    chapter_raw = groups.get("chapter")
    chapter = _to_chapter_number(chapter_raw)

    volume_raw = groups.get("volume")
    volume = int(volume_raw) if volume_raw is not None else None

    group = groups.get("group")
    if group:
        group = group.strip() or None

    quality = groups.get("quality")
    if quality:
        quality = quality.strip() or None

    if chapter is None and volume is None:
        return None

    return {
        "series_name": series,
        "chapter_number": chapter,
        "volume_number": volume,
        "group": group,
        "quality": quality,
    }


def _to_chapter_number(raw):
    """Convert a raw chapter string to a float, or None if absent."""
    if raw is None:
        return None
    try:
        value = float(raw)
        return value
    except (ValueError, TypeError):
        return None
