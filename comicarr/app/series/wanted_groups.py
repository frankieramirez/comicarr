#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Wanted, folded by series.

The Wanted page's default view is one row per series: how many issues are
missing, which ones, and why they are still missing. Grouping is pure; it
takes the Wanted rows ``get_wanted`` already annotates with their latest
search run item and never re-reads acquisition state.
"""

import re

from comicarr import series_kind

# Why an issue is still missing, from its latest search run item.
NOT_FOUND = "not_found"
SEARCHING = "searching"
QUEUED = "queued"
BUCKETS = (NOT_FOUND, SEARCHING, QUEUED)

_LIVE_STATES = frozenset({"accepted", "running"})
_TROUBLE_STATES = frozenset({"no_match", "failed", "blocked", "quarantined"})

SORTS = ("problems", "missing", "name")
KINDS = ("all", "comic", "manga")

# "#1-249, #301-310, +12": segments shown before the rest fold into a count.
WHICH_SEGMENTS = 3


def bucket_of(acquisition):
    """Map one row's acquisition annotation to not_found, searching or queued.

    Never searched, and a finished search that left the issue Wanted, both
    read as queued: auto-search will reach it again.
    """
    state = str((acquisition or {}).get("state") or "").strip().lower()
    if state in _LIVE_STATES:
        return SEARCHING
    if state in _TROUBLE_STATES:
        return NOT_FOUND
    return QUEUED


def _number_key(value):
    text = str(value or "").strip()
    try:
        return (0, float(text), text)
    except ValueError:
        return (1, 0.0, text.casefold())


def _as_int(value):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else None


def which_label(issue_numbers):
    """Compress issue numbers into "#1-249, #301-310, +12".

    Consecutive whole numbers collapse into a range; anything else (#12.1,
    #½, #AU) stands alone. After ``WHICH_SEGMENTS`` segments the remaining
    issue count folds into "+N".
    """
    numbers = sorted({str(n).strip() for n in issue_numbers if str(n or "").strip()}, key=_number_key)
    segments = []  # (label, issue_count)
    start = prev = None
    count = 0

    def close():
        if start is None:
            return
        label = "#%d" % start if start == prev else "#%d-%d" % (start, prev)
        segments.append((label, count))

    for text in numbers:
        value = _as_int(text)
        if value is not None and prev is not None and value == prev + 1:
            prev = value
            count += 1
            continue
        close()
        if value is None:
            segments.append(("#%s" % re.sub(r"^#", "", text), 1))
            start = prev = None
            count = 0
        else:
            start = prev = value
            count = 1
    close()

    shown = segments[:WHICH_SEGMENTS]
    rest = sum(n for _, n in segments[WHICH_SEGMENTS:])
    label = ", ".join(text for text, _ in shown)
    return "%s, +%d" % (label, rest) if rest else label


def _kind_of(row):
    return "manga" if series_kind.is_manga(row) else "comic"


def _name_key(group):
    return str(group["comic_name"] or "").casefold()


def group_wanted(rows, *, state="all", kind="all", sort="problems"):
    """Fold annotated Wanted rows into series groups plus per-bucket counts.

    ``counts`` describe every row that passes the kind filter, so the tabs
    keep their numbers while one of them is selected; ``series`` holds only
    rows in the selected ``state`` bucket.
    """
    counts = {"all": 0, NOT_FOUND: 0, SEARCHING: 0, QUEUED: 0}
    groups = {}
    order = []

    for row in rows or []:
        row_kind = _kind_of(row)
        if kind in ("comic", "manga") and row_kind != kind:
            continue
        acquisition = row.get("acquisition")
        bucket = bucket_of(acquisition)
        counts["all"] += 1
        counts[bucket] += 1
        if state in BUCKETS and bucket != state:
            continue

        comic_id = str(row.get("ComicID") or "")
        group = groups.get(comic_id)
        if group is None:
            group = {
                "comicid": comic_id,
                "comic_name": row.get("ComicName"),
                "comic_year": row.get("ComicYear"),
                "publisher": row.get("ComicPublisher"),
                "kind": row_kind,
                "missing": 0,
                "buckets": {NOT_FOUND: 0, SEARCHING: 0, QUEUED: 0},
                "max_attempts": 0,
                "last_searched_at": None,
                "_numbers": [],
            }
            groups[comic_id] = group
            order.append(comic_id)

        group["missing"] += 1
        group["buckets"][bucket] += 1
        group["_numbers"].append(row.get("Issue_Number"))
        if acquisition:
            attempts = acquisition.get("attempt_count") or 0
            if bucket == NOT_FOUND and attempts > group["max_attempts"]:
                group["max_attempts"] = attempts
            searched = acquisition.get("updated_at")
            if searched and (group["last_searched_at"] is None or str(searched) > str(group["last_searched_at"])):
                group["last_searched_at"] = searched

    series = []
    for comic_id in order:
        group = groups[comic_id]
        group["which"] = which_label(group.pop("_numbers"))
        # The row's headline reason is its most urgent bucket.
        for bucket in BUCKETS:
            if group["buckets"][bucket]:
                group["why"] = bucket
                break
        series.append(group)

    if sort == "name":
        series.sort(key=_name_key)
    elif sort == "missing":
        series.sort(key=lambda g: (-g["missing"], _name_key(g)))
    else:
        series.sort(
            key=lambda g: (
                -g["buckets"][NOT_FOUND],
                -g["buckets"][SEARCHING],
                -g["missing"],
                _name_key(g),
            )
        )
    return {"series": series, "counts": counts}
