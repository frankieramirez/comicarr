#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""What automatic search should enqueue for a manga Series."""

from decimal import Decimal, InvalidOperation

from comicarr.app.manga.ledger import last_released_volume, normalize_volume_number

MONITOR_MODES = frozenset({"blended", "volumes", "chapters"})
DEFAULT_MONITOR_MODE = "blended"


def normalize_monitor_mode(value):
    if value is None:
        return DEFAULT_MONITOR_MODE
    mode = str(value).strip().lower()
    return mode if mode in MONITOR_MODES else DEFAULT_MONITOR_MODE


def blended_search_targets(
    volumes,
    chapters,
    *,
    owned_volumes=None,
    covered_chapter_ids=None,
    owned_chapter_ids=None,
    mode="blended",
):
    """Return the missing volumes and/or chapters to search.

    blended (default): unowned released volumes + unowned/uncovered chapters
    beyond the last released volume.
    volumes: only missing released volumes.
    chapters: only missing chapters (not covered-by-volume).
    """
    mode = normalize_monitor_mode(mode)
    owned_vols = {normalize_volume_number(item) for item in (owned_volumes or ())}
    owned_vols.discard(None)
    covered = set(covered_chapter_ids or ())
    owned_chs = set(owned_chapter_ids or ())
    last = last_released_volume(volumes)
    last_n = _as_float(last)

    missing_volumes = []
    for volume in volumes or ():
        number = normalize_volume_number(volume.get("VolumeNumber") if isinstance(volume, dict) else volume)
        if number is None or number in owned_vols:
            continue
        missing_volumes.append({"kind": "volume", "number": number})

    missing_chapters = []
    beyond_chapters = []
    for chapter in chapters or ():
        identity = chapter.get("id") or chapter.get("IssueID")
        if identity in owned_chs or identity in covered:
            continue
        volume_n = _as_float(normalize_volume_number(chapter.get("VolumeNumber") or chapter.get("volumeNumber")))
        item = {
            "kind": "chapter",
            "id": identity,
            "number": chapter.get("chapterNumber") or chapter.get("ChapterNumber"),
        }
        missing_chapters.append(item)
        if last_n is None or volume_n is None or volume_n > last_n:
            beyond_chapters.append(item)

    if mode == "volumes":
        return missing_volumes
    if mode == "chapters":
        return missing_chapters
    return missing_volumes + beyond_chapters


def search_terms_for_target(series_name, target):
    """Volume targets search vNN; chapter targets search cNNN — never both."""
    if not series_name or not target:
        return []
    name = series_name.strip()
    if target.get("kind") == "volume":
        padded = _pad_volume(target.get("number"))
        return ["%s v%s" % (name, padded)] if padded else []
    padded = _pad_chapter(target.get("number"))
    if not padded:
        return []
    return ["%s c%s" % (name, padded), "%s chapter %s" % (name, padded)]


def booktype_bypasses_format_gates(booktype):
    """Manga is not TPB/HC/GN; it must not be rejected by those gates."""
    return str(booktype or "").strip().lower() == "manga"


_OWNED_STATUSES = frozenset({"Downloaded", "Snatched", "Archived", "Have", "Reserved"})
_COVERED_STATUSES = frozenset({"Covered"})


def classify_series_issues(issues):
    """Split a series issue list into ledger rows and ownership sets."""
    volumes = []
    seen_volumes = set()
    chapters = []
    owned_volumes = set()
    owned_chapter_ids = set()
    covered_chapter_ids = set()
    for issue in issues or ():
        volume = normalize_volume_number(issue.get("VolumeNumber"))
        if volume is not None and volume not in seen_volumes:
            seen_volumes.add(volume)
            volumes.append({"VolumeNumber": volume})
        identity = issue.get("IssueID") or issue.get("id")
        chapter_number = issue.get("ChapterNumber") if issue.get("ChapterNumber") not in (None, "") else None
        status = issue.get("Status")
        item = {
            "id": identity,
            "IssueID": identity,
            "chapterNumber": chapter_number or issue.get("Issue_Number"),
            "VolumeNumber": volume,
            "Status": status,
        }
        if chapter_number is not None:
            chapters.append(item)
            if status in _OWNED_STATUSES:
                owned_chapter_ids.add(identity)
            if status in _COVERED_STATUSES:
                covered_chapter_ids.add(identity)
        elif volume is not None and status in _OWNED_STATUSES:
            owned_volumes.add(volume)
    return {
        "volumes": volumes,
        "chapters": chapters,
        "owned_volumes": owned_volumes,
        "owned_chapter_ids": owned_chapter_ids,
        "covered_chapter_ids": covered_chapter_ids,
    }


def search_plan_for_series(series, issues):
    """Blended-frontier search targets for one series' issue list."""
    classified = classify_series_issues(issues)
    mode = normalize_monitor_mode((series or {}).get("MonitorMode"))
    return blended_search_targets(
        classified["volumes"],
        classified["chapters"],
        owned_volumes=classified["owned_volumes"],
        covered_chapter_ids=classified["covered_chapter_ids"],
        owned_chapter_ids=classified["owned_chapter_ids"],
        mode=mode,
    )


def _pad_number(number, width):
    """Zero-pad a volume or chapter number, keeping its fraction EXACTLY.

    Half instalments are real ("v01.5", "c001.5"), and truncating one searches
    the wrong book -- the exact comparison in _pack_row_matches then rejects
    the 1 it got against the 1.5 it wanted, so the row can never snatch.

    The fraction is carried as text rather than through float arithmetic.
    `round(value % 1, 1)` keeps only ONE fractional digit, so it silently
    rewrote the number it was meant to preserve: 1.25 searched "v01.2" and
    1.75 searched "v01.8" -- not a truncation of the wanted volume but a
    DIFFERENT one, which the same exact comparison then rejects.

    A non-numeric value is returned as given: some series number instalments
    in ways no padding rule can improve on, and inventing one would be worse
    than leaving it alone.
    """
    if number in (None, ""):
        return None
    text = str(number).strip()
    try:
        value = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return text
    if value == value.to_integral_value():
        return "%0*d" % (width, int(value))
    whole, _, fraction = format(value, "f").partition(".")
    return "%0*d.%s" % (width, int(whole), fraction)


def _pad_volume(number):
    return _pad_number(number, 2)


def _pad_chapter(number):
    return _pad_number(number, 3)


def _as_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
