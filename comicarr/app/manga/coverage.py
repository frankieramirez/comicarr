#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Which chapters each manga volume holds, and which chapters an owned volume covers.

The one owner of volume→chapter ranges (ADR-0004). A volume's range comes
from, in order:

1. ``user``: the operator set it on the volume row.
2. ``mangadex``: chapter rows whose VolumeNumber is that volume (aggregate).
3. ``estimated``: MangaDex lists nothing for it, so the chapters between the
   nearest listed volumes are shared out evenly. Volumes 8–60 of a long
   series are often like this.

Volumes after the last listed one get no estimate: nothing bounds them.

The volume roster is every whole number from 1 to the highest known volume,
because volumes are published in order; a hole in MangaDex's data is not a
missing book.

Coverage is read by the series page and by automatic search through the same
function, so what the page shows as "in vol 20" is what search skips.
"""

from decimal import Decimal, InvalidOperation

from comicarr.app.manga.ledger import normalize_volume_number

USER = "user"
MANGADEX = "mangadex"
ESTIMATED = "estimated"

# Ownership statuses on a manga_volumes row (see volumes.py). Wanted and
# Skipped rows carry the operator's want decision for an unowned volume.
_PLACED = frozenset({"Downloaded", "Archived"})
_IN_FLIGHT = frozenset({"Snatched"})
WANTED = "Wanted"
SKIPPED = "Skipped"

# A volume number this large is a parse accident, not a book; it must not
# make the roster run to it.
_MAX_ROSTER_VOLUME = 400


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
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _chapter_number(row):
    return _decimal(_field(row, "chapterNumber", "ChapterNumber"))


def _chapter_volume(row):
    return normalize_volume_number(_field(row, "volumeNumber", "VolumeNumber"))


def _chapter_id(row):
    return _field(row, "id", "IssueID")


def _display(number):
    if number is None:
        return None
    return normalize_volume_number(str(number))


def _sort_key(volume):
    number = _decimal(volume)
    return (0, number, "") if number is not None else (1, Decimal(0), str(volume))


def volume_roster(chapters, volume_rows):
    """Every volume number the series has: 1..highest known, plus fractional ones."""
    known = set()
    for row in chapters or ():
        volume = _chapter_volume(row)
        if volume is not None:
            known.add(volume)
    for row in volume_rows or ():
        volume = normalize_volume_number(row.get("VolumeNumber"))
        if volume is not None:
            known.add(volume)
    whole = [_decimal(v) for v in known]
    highest = max((n for n in whole if n is not None and n <= _MAX_ROSTER_VOLUME), default=None)
    roster = {v for v in known if _decimal(v) is None or _decimal(v) <= _MAX_ROSTER_VOLUME}
    if highest is not None and highest >= 1:
        roster.update(str(n) for n in range(1, int(highest) + 1))
    return sorted(roster, key=_sort_key)


def volume_ranges(chapters, volume_rows):
    """``{volume: {"first", "last", "source", "chapters": [ids]}}`` for every roster volume.

    ``first``/``last`` are Decimals or None (contents unknown).
    """
    rows_by_volume = {}
    for row in volume_rows or ():
        volume = normalize_volume_number(row.get("VolumeNumber"))
        if volume is not None:
            rows_by_volume[volume] = row

    listed = {}
    for row in chapters or ():
        volume = _chapter_volume(row)
        number = _chapter_number(row)
        if volume is None or number is None:
            continue
        listed.setdefault(volume, []).append(number)

    ranges = {}
    for volume in volume_roster(chapters, volume_rows):
        row = rows_by_volume.get(volume) or {}
        first = _decimal(row.get("FirstChapter"))
        last = _decimal(row.get("LastChapter"))
        if first is not None and last is not None and first <= last:
            ranges[volume] = {"first": first, "last": last, "source": USER}
        elif listed.get(volume):
            ranges[volume] = {"first": min(listed[volume]), "last": max(listed[volume]), "source": MANGADEX}
        else:
            ranges[volume] = {"first": None, "last": None, "source": None}

    _estimate_gaps(ranges)

    for entry in ranges.values():
        entry["chapters"] = []
    for row in chapters or ():
        identity = _chapter_id(row)
        number = _chapter_number(row)
        if identity is None or number is None:
            continue
        holder = volume_holding(row, ranges)
        if holder is not None:
            ranges[holder]["chapters"].append(identity)
    return ranges


def _estimate_gaps(ranges):
    """Share the chapters between two bounded volumes evenly across the unknown ones between them."""
    ordered = sorted(ranges, key=_sort_key)
    whole = [v for v in ordered if _decimal(v) is not None and _decimal(v) == _decimal(v).to_integral_value()]
    # A virtual volume 0 ending at chapter 0 bounds the series' first volumes.
    anchors = [(Decimal(0), Decimal(0), Decimal(0))]
    for volume in whole:
        entry = ranges[volume]
        if entry["source"] is not None:
            anchors.append((_decimal(volume), entry["first"], entry["last"]))
    for (low_volume, _low_first, low_last), (high_volume, high_first, _high_last) in zip(
        anchors, anchors[1:], strict=False
    ):
        gap = [v for v in whole if low_volume < _decimal(v) < high_volume and ranges[v]["source"] is None]
        if not gap:
            continue
        start = int(low_last.to_integral_value(rounding="ROUND_FLOOR")) + 1
        end = int(high_first.to_integral_value(rounding="ROUND_CEILING")) - 1
        span = end - start + 1
        if span < len(gap):
            continue
        size = Decimal(span) / len(gap)
        for index, volume in enumerate(gap):
            first = start + int((size * index).to_integral_value(rounding="ROUND_HALF_UP"))
            last = start + int((size * (index + 1)).to_integral_value(rounding="ROUND_HALF_UP")) - 1
            ranges[volume] = {"first": Decimal(first), "last": Decimal(last), "source": ESTIMATED}


def volume_holding(chapter, ranges):
    """The volume a chapter belongs to, or None.

    An operator range wins (the operator is correcting the data). Then
    MangaDex's own assignment. A chapter MangaDex left without a volume goes
    to the listed or estimated span it falls in.
    """
    own = _chapter_volume(chapter)
    number = _chapter_number(chapter)
    if number is not None:
        for volume, entry in ranges.items():
            if entry["source"] == USER and entry["first"] <= number <= entry["last"]:
                return volume
    if own is not None:
        entry = ranges.get(own)
        return own if entry is not None and entry["source"] != USER else None
    if number is None:
        return None
    # A chapter MangaDex left without a volume that sits inside a listed
    # volume's span belongs to it; otherwise to the estimate around it.
    for source in (MANGADEX, ESTIMATED):
        for volume, entry in ranges.items():
            if entry["source"] == source and entry["first"] <= number <= entry["last"]:
                return volume
    return None


def covered_chapters(chapters, volume_rows, ranges=None):
    """``{chapter id: (volume, estimated)}`` for chapters inside a placed volume."""
    ranges = ranges if ranges is not None else volume_ranges(chapters, volume_rows)
    placed = {
        normalize_volume_number(row.get("VolumeNumber")) for row in volume_rows or () if row.get("Status") in _PLACED
    }
    covered = {}
    for volume in placed:
        entry = ranges.get(volume)
        if not entry:
            continue
        for identity in entry["chapters"]:
            covered[identity] = (volume, entry["source"] == ESTIMATED)
    return covered


def volume_entries(chapters, volume_rows, *, monitor_mode="blended", ranges=None):
    """The series page's volume list, newest first, with each volume's state."""
    ranges = ranges if ranges is not None else volume_ranges(chapters, volume_rows)
    rows_by_volume = {normalize_volume_number(row.get("VolumeNumber")): row for row in volume_rows or ()}
    entries = []
    for volume in sorted(ranges, key=_sort_key, reverse=True):
        entry = ranges[volume]
        row = rows_by_volume.get(volume) or {}
        status = row.get("Status")
        if status in _PLACED:
            state = "Have"
        elif status in _IN_FLIGHT:
            state = "Snatched"
        elif status == SKIPPED or (status != WANTED and monitor_mode == "chapters"):
            state = "Not wanted"
        else:
            state = "Wanted"
        entries.append(
            {
                "number": volume,
                "firstChapter": _display(entry["first"]),
                "lastChapter": _display(entry["last"]),
                "rangeSource": entry["source"],
                "chapterCount": len(entry["chapters"]),
                "status": status,
                "displayState": state,
                "owned": status in _PLACED,
                "location": row.get("Location") if status in _PLACED else None,
                "explicitIntent": status in (WANTED, SKIPPED),
            }
        )
    return entries


def skipped_volumes(volume_rows):
    """Volumes the operator marked not wanted; search leaves them alone."""
    return {
        normalize_volume_number(row.get("VolumeNumber")) for row in volume_rows or () if row.get("Status") == SKIPPED
    } - {None}
