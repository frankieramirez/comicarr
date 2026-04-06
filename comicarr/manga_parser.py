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
    Title 001.cbz              (bare number = chapter)
    Title v01.cbz              (volume only)
"""

import os
import re

VALID_EXTENSIONS = {".cbr", ".cbz", ".cb7", ".pdf"}

# Pre-compiled patterns, ordered from most specific to least specific.
# Each pattern is a tuple of (compiled_regex, field_mapping) where
# field_mapping is a dict mapping group names to result keys.

# Pattern 1: [Group] Title - c001 (v01) [quality]
_PAT_GROUP_FULL = re.compile(
    r"^\[(?P<group>[^\]]+)\]\s*"
    r"(?P<series>.+?)\s*"
    r"-\s*c(?P<chapter>\d+(?:\.\d+)?)"
    r"(?:\s*-\s*c\d+(?:\.\d+)?)?"  # optional range end (ignored)
    r"(?:\s*\(v(?P<volume>\d+)\))?"
    r"(?:\s*\[(?P<quality>[^\]]+)\])?"
    r"\s*$",
    re.IGNORECASE,
)

# Pattern 2: [Group] Title - c001-003 [quality]  (no volume)
_PAT_GROUP_CHAPTER = re.compile(
    r"^\[(?P<group>[^\]]+)\]\s*"
    r"(?P<series>.+?)\s*"
    r"-\s*c(?P<chapter>\d+(?:\.\d+)?)"
    r"(?:\s*-\s*c?\d+(?:\.\d+)?)?"  # optional range end
    r"(?:\s*\[(?P<quality>[^\]]+)\])?"
    r"\s*$",
    re.IGNORECASE,
)

# Pattern 3: Title Vol.01 Ch.001  or  Title Vol 01 Ch 001
_PAT_VOL_CH_ABBR = re.compile(
    r"^(?P<series>.+?)\s+"
    r"[Vv]ol\.?\s*(?P<volume>\d+)\s+"
    r"[Cc]h\.?\s*(?P<chapter>\d+(?:\.\d+)?)"
    r"\s*$",
)

# Pattern 4: Title v01 c001
_PAT_V_C = re.compile(
    r"^(?P<series>.+?)\s+"
    r"[Vv](?P<volume>\d+)\s+"
    r"[Cc](?P<chapter>\d+(?:\.\d+)?)"
    r"\s*$",
)

# Pattern 5: Title - Chapter 001
_PAT_CHAPTER_LABEL = re.compile(
    r"^(?P<series>.+?)\s*"
    r"-\s*[Cc]hapter\s+(?P<chapter>\d+(?:\.\d+)?)"
    r"\s*$",
)

# Pattern 6: Title c001-003  (chapter with optional range, no group brackets)
_PAT_CHAPTER_PREFIX = re.compile(
    r"^(?P<series>.+?)\s+"
    r"[Cc](?P<chapter>\d+(?:\.\d+)?)"
    r"(?:\s*-\s*c?\d+(?:\.\d+)?)?"
    r"\s*$",
)

# Pattern 7: Title v01  (volume only, e.g. "Bleach v1")
_PAT_VOLUME_ONLY = re.compile(
    r"^(?P<series>.+?)\s+"
    r"[Vv](?P<volume>\d+)"
    r"\s*$",
)

# Pattern 8: Title 001  (bare number = chapter, e.g. "Chainsaw Man 165")
_PAT_BARE_NUMBER = re.compile(
    r"^(?P<series>.+?)\s+"
    r"(?P<chapter>\d+(?:\.\d+)?)"
    r"\s*$",
)

# Ordered list — first match wins.
_PATTERNS = [
    _PAT_GROUP_FULL,
    _PAT_GROUP_CHAPTER,
    _PAT_VOL_CH_ABBR,
    _PAT_V_C,
    _PAT_CHAPTER_LABEL,
    _PAT_CHAPTER_PREFIX,
    _PAT_VOLUME_ONLY,
    _PAT_BARE_NUMBER,
]


def parse_manga_filename(filename):
    """Parse a manga filename and return extracted metadata.

    Args:
        filename: The filename (with or without directory path) to parse.

    Returns:
        A dict with keys ``series_name``, ``chapter_number`` (float or None),
        ``volume_number`` (int or None), ``group`` (str or None), and
        ``quality`` (str or None).  Returns ``None`` when the filename
        cannot be parsed or has an invalid extension.
    """
    # Strip directory components if present.
    basename = os.path.basename(filename)

    # Split extension and validate.
    stem, ext = os.path.splitext(basename)
    if ext.lower() not in VALID_EXTENSIONS:
        return None

    stem = stem.strip()
    if not stem:
        return None

    for pattern in _PATTERNS:
        m = pattern.match(stem)
        if m:
            return _build_result(m)

    # No pattern matched — unparseable.
    return None


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

    # If we got neither a chapter nor a volume, it's not useful.
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
        # Return int-like floats as float to keep the contract consistent.
        return value
    except (ValueError, TypeError):
        return None
