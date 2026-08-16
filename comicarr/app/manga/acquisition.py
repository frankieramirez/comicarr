#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""What automatic search should enqueue for a manga Series."""

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


def _pad_volume(number):
    try:
        return "%02d" % int(float(number))
    except (TypeError, ValueError):
        return str(number) if number not in (None, "") else None


def _pad_chapter(number):
    try:
        value = float(number)
    except (TypeError, ValueError):
        return str(number) if number not in (None, "") else None
    if value == int(value):
        return "%03d" % int(value)
    return "%03d.%s" % (int(value), str(round(value % 1, 1))[2:])


def _as_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
