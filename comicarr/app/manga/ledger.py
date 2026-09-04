#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Chapter and volume ledger contract for manga Series.

MangaDex is the sole ledger source. Volumes come from the cover feed;
chapters and volume→chapter containment come from unfiltered `/aggregate`.
Owning a volume covers only the chapters that mapping actually lists.
"""

import re
from decimal import Decimal, InvalidOperation

from comicarr.app.acquisition.models import Fulfillment

_OPERATOR_FIELDS = ("Status", "AcquisitionIntent", "Location", "status", "acquisitionIntent", "location")
_NON_VOLUME = frozenset({"", "none", "null", "unknown"})
# Only strips a marker that actually introduces a number, so "vTPB" is left
# alone and never compares equal to a real volume.
_VOLUME_MARKER = re.compile(r"^v(?:ol(?:ume)?)?\.?\s*(?=\d)", re.IGNORECASE)


def normalize_volume_number(value):
    """Canonical volume number, or None when the source has no volume."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in _NON_VOLUME:
        return None
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return str(int(number))
    return format(number, "g")


def is_volume_target(chapter_number, volume_number):
    """Is this pair a volume rather than a chapter?

    The single owner of the volume-vs-chapter rule: a volume has a volume
    number and no chapter number. Stated once because getting it wrong in
    either direction is silently destructive — a chapter treated as a volume
    lets a pack claim "chapter 7" as "volume 7", and a volume treated as a
    chapter is searched as ``c001`` and never matches a ``v01`` release.
    """
    return volume_number not in (None, "") and chapter_number in (None, "")


def volume_numbers_match(left, right):
    """Do two volume references denote the same volume?

    The same volume is written differently everywhere it appears: a release
    says ``v01``, the ledger stores ``1``, a pack range yields the integer 1.
    Both sides are stripped of a leading volume marker and canonicalised
    through :func:`normalize_volume_number` before comparison.

    Returns False whenever either side has no usable volume, so a parse
    failure can never be read as a match and claim an arbitrary volume.
    """
    left_value = _exact_volume(_strip_volume_marker(left))
    right_value = _exact_volume(_strip_volume_marker(right))
    if left_value is None or right_value is None:
        return False
    return left_value == right_value


def _exact_volume(value):
    """A volume reference as an exact number, or None when it is not one.

    normalize_volume_number is a DISPLAY normaliser: it preserves arbitrary
    text and formats floats to six significant digits. Comparing through it
    therefore made "TPB" equal "TPB" -- two releases with no volume at all
    reading as the same volume -- and "1.0000001" equal "1". Neither is a
    volume identity, and the contract above says so.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text).normalize()
    except (InvalidOperation, TypeError, ValueError):
        return None


def _strip_volume_marker(value):
    if value is None:
        return None
    return _VOLUME_MARKER.sub("", str(value).strip())


def chapter_id(comic_id, chapter_number):
    """Stable chapter IssueID — matches `_populate_manga_chapters`."""
    return "%s-ch%s" % (comic_id, chapter_number)


def volume_id(comic_id, volume_number):
    """Stable volume identity. Volumes are not issues."""
    normalized = normalize_volume_number(volume_number)
    if not comic_id or normalized is None:
        return None
    return "%s-v%s" % (comic_id, normalized)


def last_released_volume(cover_volumes):
    """Last released volume is the highest cover-feed volume number.

    Cover `createdAt` is a known-to-exist bound, never a street date.
    """
    numbers = []
    for volume in cover_volumes or ():
        normalized = normalize_volume_number(_cover_volume_number(volume))
        if normalized is None:
            continue
        try:
            numbers.append((float(normalized), normalized))
        except ValueError:
            continue
    if not numbers:
        return None
    return max(numbers, key=lambda item: item[0])[1]


def covers_to_volume_rows(comic_id, covers):
    """Project MangaDex cover-feed entries into first-class volume rows."""
    rows = []
    seen = set()
    for cover in covers or ():
        number = normalize_volume_number(_cover_volume_number(cover))
        identity = volume_id(comic_id, number)
        if identity is None or identity in seen:
            continue
        seen.add(identity)
        attrs = cover.get("attributes") if isinstance(cover, dict) else None
        attrs = attrs if isinstance(attrs, dict) else cover if isinstance(cover, dict) else {}
        rows.append(
            {
                "VolumeID": identity,
                "ComicID": comic_id,
                "VolumeNumber": number,
                "KnownAt": attrs.get("createdAt") or attrs.get("knownAt"),
                "CoverLocale": attrs.get("locale"),
                "CoverFileName": attrs.get("fileName"),
            }
        )
    return rows


def merge_refresh_row(existing, incoming):
    """Refresh-safe merge: incoming metadata, preserved operator state."""
    merged = dict(incoming or {})
    if not existing:
        return merged
    for field in _OPERATOR_FIELDS:
        value = existing.get(field)
        if value not in (None, ""):
            merged[field] = value
    return merged


def apply_volume_coverage(chapters, owned_volumes, containment):
    """Mark mapped chapters Covered when an owned volume lists them.

    A volume present in the cover feed but absent from `containment` covers
    nothing — unknown contents stay missing. Physical ownership and in-flight
    states win. Explicit skip/ignore stays on the chapter.
    """
    owned = {normalize_volume_number(volume) for volume in owned_volumes or ()}
    owned.discard(None)
    covered_ids = set()
    for volume, chapter_ids in (containment or {}).items():
        if normalize_volume_number(volume) in owned:
            covered_ids.update(chapter_ids)

    projected = []
    for chapter in chapters or ():
        row = dict(chapter)
        fulfillment = row.get("fulfillment")
        if fulfillment in {
            Fulfillment.DOWNLOADED.value,
            Fulfillment.ARCHIVED.value,
            Fulfillment.RESERVED.value,
            Fulfillment.SNATCHED.value,
        }:
            projected.append(row)
            continue
        if row.get("acquisitionIntent") in {"skipped", "ignored"}:
            projected.append(row)
            continue
        identity = row.get("id") or row.get("IssueID")
        if identity in covered_ids:
            row["fulfillment"] = Fulfillment.COVERED.value
            row["displayState"] = "Covered"
            row["covered"] = True
            row["owned"] = False
            row["missing"] = False
            row["eligible"] = False
            row["eligibilityReason"] = "covered"
        projected.append(row)
    return projected


def blended_progress(volumes, chapters, *, owned_volumes=None, containment=None):
    """Have / total / missing under the blended frontier.

    Missing = unowned released volumes + unowned/uncovered chapters beyond
    the last released volume. Chapters inside a released volume are counted
    on the volume, not twice.
    """
    volume_numbers = []
    for volume in volumes or ():
        number = normalize_volume_number(volume.get("VolumeNumber") if isinstance(volume, dict) else volume)
        if number is not None:
            volume_numbers.append(number)
    last = last_released_volume(volumes)
    owned = {normalize_volume_number(item) for item in (owned_volumes or ())}
    owned.discard(None)

    last_numeric = _as_float(last)
    beyond = []
    for chapter in chapters or ():
        number = normalize_volume_number(
            chapter.get("volumeNumber") or chapter.get("VolumeNumber") if isinstance(chapter, dict) else None
        )
        chapter_volume = _as_float(number)
        if last_numeric is None or chapter_volume is None or chapter_volume > last_numeric:
            beyond.append(chapter)

    covered_beyond = apply_volume_coverage(beyond, owned, containment or {})
    volume_have = sum(1 for number in volume_numbers if number in owned)
    chapter_have = sum(
        1
        for row in covered_beyond
        if row.get("owned")
        or row.get("covered")
        or row.get("fulfillment") in {Fulfillment.DOWNLOADED.value, Fulfillment.COVERED.value}
    )
    volume_missing = len(volume_numbers) - volume_have
    chapter_missing = len(beyond) - chapter_have
    total = len(volume_numbers) + len(beyond)
    have = volume_have + chapter_have
    return {
        "volumeTotal": len(volume_numbers),
        "volumeHave": volume_have,
        "volumeMissing": volume_missing,
        "chapterBeyondTotal": len(beyond),
        "chapterBeyondHave": chapter_have,
        "chapterBeyondMissing": chapter_missing,
        "total": total,
        "have": have,
        "missing": volume_missing + chapter_missing,
        "lastReleasedVolume": last,
        "completionPercent": round((have / total) * 100) if total else 0,
    }


def _cover_volume_number(cover):
    if not isinstance(cover, dict):
        return cover
    attrs = cover.get("attributes")
    if isinstance(attrs, dict) and "volume" in attrs:
        return attrs.get("volume")
    return cover.get("volume") or cover.get("VolumeNumber")


def _as_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
