#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Detect multi-issue/volume pack releases from provider result titles.

DDL providers detect packs upstream (``getcomics.check_for_pack`` /
``rsscheck.ddlrss_pack_detect``) and hand ``search_filer`` a pre-parsed
entry. Every other provider only supplies a raw title, so pack-shaped
releases like ``Solo Leveling v01-14 (2021-2025)`` used to die in the
single-issue parser (#730). This module is the title-only detector for
those providers.
"""

import re

# Range spans above this are assumed to be noise (e.g. phone-number-like
# digit runs), not a real pack.
_MAX_RANGE_SPAN = 2000

# Both endpoints written as full 4-digit years means a publication-year
# range (e.g. "Batman 1999-2005"), not an issue range.
_YEAR_RANGE = re.compile(r"^(?:19|20)\d{2}$")

_PARENTHESIZED = re.compile(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}")

_VOLUME_RANGE = re.compile(
    r"\bv(?:ol(?:ume)?s?)?\.?\s*(?P<start>\d{1,3})\s*[-–]\s*(?:v(?:ol(?:ume)?s?)?\.?\s*)?(?P<end>\d{1,3})(?!\d)",
    re.IGNORECASE,
)
_CHAPTER_RANGE = re.compile(
    r"\bc(?:h(?:apter)?s?)?\.?\s*(?P<start>\d{1,4}(?:\.\d+)?)\s*[-–]\s*c?h?\.?\s*(?P<end>\d{1,4}(?:\.\d+)?)(?!\d)",
    re.IGNORECASE,
)
_ISSUE_RANGE = re.compile(r"(?P<marker>#)?\s*(?P<start>\d{1,4})\s*[-–]\s*#?(?P<end>\d{1,4})(?!\d)")

# An unmarked bare range spanning only two numbers ("Series 05-06") is more
# often a date fragment than a pack, so it needs a '#' marker to be trusted.
_MIN_UNMARKED_SPAN = 2

_FIRST_YEAR = re.compile(r"[(\[{]\s*((?:19|20)\d{2})")

# A bracketed multi-year span ("(2021-2026)", "{2021-2023}") is the one
# signal a numberless complete-series pack carries; a single year would
# equally describe a lone volume or one-shot, so it is not trusted.
_YEAR_SPAN_GROUP = re.compile(r"[(\[{]\s*((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})\s*[)\]}]")

# Any digit range left in the title once the year span is removed means a
# numbered (partial) release hiding inside bracketed metadata ("[v01-05]"),
# which the group-stripping digit check below cannot see.
_HIDDEN_RANGE = re.compile(r"\d\s*[-–]\s*\d")

# Range expansion downstream is integer-only, so a fractional endpoint
# ("c001.5-003.5") cannot be represented: truncating it to 1-3 would claim
# chapter 1, which the pack does not contain. Refuse the whole title rather
# than let a looser pattern re-match the same text into a wrong range.
_FRACTIONAL_ENDPOINT = re.compile(r"\d+\.\d+\s*[-–]|[-–]\s*[a-z]*\.?\s*\d+\.\d+", re.IGNORECASE)


def _range_values(match, kind):
    raw_start = match.group("start")
    raw_end = match.group("end")
    try:
        start = int(raw_start)
        end = int(raw_end)
    except (TypeError, ValueError):
        return None
    if start >= end or (end - start) > _MAX_RANGE_SPAN:
        return None
    if _YEAR_RANGE.match(raw_start) and _YEAR_RANGE.match(raw_end):
        return None
    if kind == "issue" and match.groupdict().get("marker") is None:
        # zero-padded issue numbering ("001-144") is itself a pack marker.
        padded = len(raw_start) >= 3 and raw_start.startswith("0")
        if not padded and (end - start) < _MIN_UNMARKED_SPAN:
            return None
    return start, end


def _series_before(text, match_start):
    series = text[:match_start]
    series = re.sub(r"[#\-–\s]+$", "", series).strip()
    if not re.search(r"[A-Za-z]", series):
        return None
    return series


def parse_pack_title(title):
    """Return pack info parsed from a release title, or None.

    The result mirrors what the DDL pack detectors feed ``search_filer``:
    ``{"series", "issues", "kind", "year", "booktype"}`` where ``issues``
    is a normalized ``"start-end"`` range string and ``kind`` is one of
    ``"volume"``, ``"chapter"``, or ``"issue"``.
    """
    if not title or not isinstance(title, str):
        return None

    stripped = _PARENTHESIZED.sub(" ", title)
    if _FRACTIONAL_ENDPOINT.search(stripped):
        return None

    for pattern, kind, booktype in (
        (_VOLUME_RANGE, "volume", "TPB"),
        (_CHAPTER_RANGE, "chapter", "issue"),
        (_ISSUE_RANGE, "issue", "issue"),
    ):
        match = pattern.search(stripped)
        if match is None:
            continue
        values = _range_values(match, kind)
        if values is None:
            continue
        series = _series_before(stripped, match.start())
        if series is None:
            continue
        year_match = _FIRST_YEAR.search(title)
        return {
            "series": series,
            "issues": "%d-%d" % values,
            "kind": kind,
            "year": year_match.group(1) if year_match else None,
            "booktype": booktype,
        }
    return None


def parse_series_pack_title(title):
    """Return complete-series pack info parsed from a numberless title, or None.

    Detects releases like ``Solo Leveling (2021-2026) (Digital) (1r0n)``:
    a series name whose only digits live inside bracketed metadata groups,
    one of which is a multi-year span. ``parse_pack_title`` deliberately
    refuses these (a year range is not an issue range), so this is a
    separate, riskier detector: callers must gate it behind *Allow packs*,
    a manga booktype, and normal series-name matching. On a print comic a
    bracketed span usually states when the *series* ran rather than what
    the release holds, and a false positive here claims the whole series
    at once. ``issues`` is the marker string ``"all"`` — the pack claims
    every issue of the matched series.

    A digit left outside the metadata groups means an issue, volume, or
    chapter marker (or a numbered series name indistinguishable from one),
    so the title is refused rather than risk claiming a partial release.
    A digit range surviving anywhere else in the title once the year span
    is removed ("Series [v01-05] (2021-2022)") is a partial release whose
    range hides inside a bracketed group — also refused. ``year_end`` is
    the span's final year: the pack cannot contain anything published
    after it, and coverage claims must honor that cutoff.
    """
    if not title or not isinstance(title, str):
        return None
    year_match = _YEAR_SPAN_GROUP.search(title)
    if year_match is None:
        return None
    year_start, year_end = int(year_match.group(1)), int(year_match.group(2))
    if year_start >= year_end:
        return None
    remainder = _YEAR_SPAN_GROUP.sub(" ", title)
    if _VOLUME_RANGE.search(remainder) or _CHAPTER_RANGE.search(remainder) or _HIDDEN_RANGE.search(remainder):
        return None
    stripped = _PARENTHESIZED.sub(" ", title).strip()
    if not re.search(r"[A-Za-z]", stripped) or re.search(r"\d", stripped):
        return None
    return {
        "series": re.sub(r"\s+", " ", stripped),
        "issues": "all",
        "kind": "series",
        "year": str(year_start),
        "year_end": str(year_end),
        "booktype": "issue",
    }


def pack_shaped(title):
    """Cheap gate: could this title be any kind of pack release?

    The bare-title search pass can return a provider's whole series
    listing; entries failing this check skip the far costlier per-entry
    evaluation (file parsing plus a DB coverage lookup per candidate).
    """
    return parse_pack_title(title) is not None or parse_series_pack_title(title) is not None
