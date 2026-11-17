#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Which chapters each manga volume holds (ADR-0004).

Volumes are published in order, so the whole model is one list: the chapter
each volume **ends at**. Volume N holds the chapters after volume N-1's end,
up to its own. An end comes from, in order:

1. ``user``: the operator set it on the volume row (``LastChapter``).
2. ``mangadex``: the highest chapter MangaDex lists in that volume, or the
   chapter before the lowest one it lists in the next volume. Only the ends
   are taken from MangaDex; a stray chapter it files under another volume
   goes where its number falls.
3. ``estimated``: neither is known, so the ends between the two nearest
   known ones are spaced evenly. Volumes 8–60 of a long series are often
   like this: MangaDex lists no chapters for them at all.

Volumes after the last known end hold nothing known: nothing bounds them.

The series page and automatic search both read chapter→volume from here, so
what the page shows as "in vol 20" is what search skips.
"""

from bisect import bisect_left
from decimal import Decimal, InvalidOperation

from comicarr.app.manga.ledger import normalize_volume_number

USER = "user"
MANGADEX = "mangadex"
ESTIMATED = "estimated"

# A volume number this large is a parse accident (a year read as a volume),
# not a book; the volume list must not run to it.
_MAX_VOLUME = 400


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _field(row, *names):
    for name in names:
        if row.get(name) not in (None, ""):
            return row[name]
    return None


def _chapter_number(row):
    return _decimal(_field(row, "chapterNumber", "ChapterNumber"))


def _whole_volume(value):
    """A volume number as an int in 1.._MAX_VOLUME, or None."""
    number = _decimal(normalize_volume_number(value))
    if number is None or number != number.to_integral_value() or not 1 <= number <= _MAX_VOLUME:
        return None
    return int(number)


def _volume_ends(chapters, volume_rows):
    """``{volume: (end chapter, source)}`` for volumes 1..highest known; end is None when unknown."""
    listed = {}
    for row in chapters or ():
        volume = _whole_volume(_field(row, "volumeNumber", "VolumeNumber"))
        number = _chapter_number(row)
        if volume is not None and number is not None:
            low, high = listed.get(volume, (number, number))
            listed[volume] = (min(low, number), max(high, number))
    user = {}
    recorded = set()
    for row in volume_rows or ():
        volume = _whole_volume(row.get("VolumeNumber"))
        if volume is None:
            continue
        recorded.add(volume)
        end = _decimal(row.get("LastChapter"))
        if end is not None:
            user[volume] = end

    highest = max(listed.keys() | recorded, default=0)
    # Volume 0 "ends" at chapter 0. Ends must rise with the volume number:
    # an operator end that does not is ignored, and so is a MangaDex end
    # that contradicts an operator end or the ends before it.
    ends = {0: (Decimal(0), MANGADEX)}
    last = Decimal(0)
    for volume in sorted(user):
        if user[volume] > last:
            ends[volume] = (user[volume], USER)
            last = user[volume]
    user_volumes = sorted(volume for volume in ends if volume)
    last = Decimal(0)
    for volume in range(1, highest + 1):
        if volume in ends:
            last = ends[volume][0]
            continue
        if volume in listed:
            end = listed[volume][1]
        elif volume + 1 in listed:
            end = listed[volume + 1][0] - 1
        else:
            continue
        ceiling = next((ends[later][0] for later in user_volumes if later > volume), None)
        if end > last and (ceiling is None or end < ceiling):
            ends[volume] = (end, MANGADEX)
            last = end

    anchors = sorted(ends)
    for low, high in zip(anchors, anchors[1:], strict=False):
        missing = high - low - 1
        span = ends[high][0] - ends[low][0]
        if missing and span > missing:
            step = span / (high - low)
            for offset in range(1, high - low):
                end = (ends[low][0] + step * offset).to_integral_value(rounding="ROUND_HALF_UP")
                ends[low + offset] = (end, ESTIMATED)
    return {volume: ends.get(volume, (None, None)) for volume in range(0, highest + 1)}


def volume_ranges(chapters, volume_rows):
    """``{volume: {"first", "last", "source", "chapters": [ids]}}`` for volumes 1..highest known.

    Keys are normalized volume numbers (``"20"``). ``first``/``last`` are
    Decimals, or None when the volume's contents are unknown. ``source`` is
    where the volume's end comes from, or ``estimated`` when its start is a
    guess and its end is not the operator's.
    """
    ends = _volume_ends(chapters, volume_rows)
    ranges = {}
    for volume in range(1, len(ends)):
        (before, before_source), (end, source) = ends[volume - 1], ends[volume]
        if before is None or end is None:
            ranges[str(volume)] = {"first": None, "last": None, "source": None, "chapters": []}
            continue
        if source != USER and before_source == ESTIMATED:
            source = ESTIMATED
        ranges[str(volume)] = {"first": before + 1, "last": end, "source": source, "chapters": []}
    bounded = _bounded(ranges)
    for row in chapters or ():
        identity = _field(row, "id", "IssueID")
        holder = _holder(_chapter_number(row), ranges, bounded)
        if identity is not None and holder is not None:
            ranges[holder]["chapters"].append(identity)
    return ranges


def _bounded(ranges):
    # Built in volume order, and ends rise with it, so this is sorted by end.
    return [(entry["last"], volume) for volume, entry in ranges.items() if entry["last"] is not None]


def _holder(number, ranges, bounded):
    if number is None:
        return None
    index = bisect_left(bounded, number, key=lambda item: item[0])
    if index == len(bounded):
        return None
    volume = bounded[index][1]
    # A fractional chapter between two volumes (62.5) goes to the later one.
    return volume if number > ranges[volume]["first"] - 1 else None


def volume_holding(chapter, ranges):
    """The volume whose range a chapter falls in, or None."""
    return _holder(_chapter_number(chapter), ranges, _bounded(ranges))
