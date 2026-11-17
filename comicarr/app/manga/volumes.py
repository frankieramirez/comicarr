#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Owned, grabbed and operator-edited manga volumes (ADR-0004: volumes are not issues).

A volume grab is recorded Snatched; the volume file landing records it
Downloaded with its Location. The chapters a Downloaded volume contains then
read as Covered (``ledger.apply_volume_coverage``), and the volume leaves the
blended search frontier (#1278). An operator can also mark a volume Wanted
or Skipped, or state which chapters it holds (``edit_volume``); which
chapters each volume holds is worked out in ``coverage``.
"""

import datetime

from sqlalchemy import and_, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from comicarr import db
from comicarr.app.manga.ledger import normalize_volume_number, volume_id
from comicarr.tables import manga_volumes

SNATCHED = "Snatched"
DOWNLOADED = "Downloaded"
# Statuses a later Snatched must not overwrite: the file is already here.
_PLACED = frozenset({DOWNLOADED, "Archived"})
# Statuses whose volume covers its chapters.
COVERING = _PLACED


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _insert_if_absent(dialect):
    if dialect == "postgresql":
        return pg_insert(manga_volumes).on_conflict_do_nothing(index_elements=["VolumeID"])
    if dialect == "sqlite":
        return sqlite_insert(manga_volumes).on_conflict_do_nothing(index_elements=["VolumeID"])
    return insert(manga_volumes).prefix_with("IGNORE")


def record_volume(comic_id, volume_number, status, location=None):
    """Record a volume's status; return its VolumeID, or None for no volume."""
    number = normalize_volume_number(volume_number)
    identity = volume_id(comic_id, number)
    if identity is None:
        return None
    with db.get_engine().begin() as conn:
        # Insert-if-absent in one statement, so a grab and a post-process
        # racing on the same volume cannot both try to create it.
        created = conn.execute(
            _insert_if_absent(conn.dialect.name).values(
                VolumeID=identity,
                ComicID=comic_id,
                VolumeNumber=number,
                Status=status,
                Location=location,
                updated_at=_now(),
            )
        ).rowcount
        if created:
            return identity
        values = {"Status": status, "updated_at": _now()}
        if location is not None:
            values["Location"] = location
        predicate = manga_volumes.c.VolumeID == identity
        if status == SNATCHED:
            # The database applies the guard to the current row: a later grab
            # never un-owns a volume whose file is already here.
            predicate = and_(predicate, manga_volumes.c.Status.notin_(sorted(_PLACED)))
        conn.execute(update(manga_volumes).where(predicate).values(**values))
    return identity


def volume_states(comic_id):
    """``{volume number: status}`` for every recorded volume of a series."""
    if not comic_id:
        return {}
    rows = db.select_all(
        select(manga_volumes.c.VolumeNumber, manga_volumes.c.Status).where(
            and_(manga_volumes.c.ComicID == str(comic_id))
        )
    )
    return {row["VolumeNumber"]: row["Status"] for row in rows or ()}


def covering_volumes(states):
    """The volume numbers whose chapters read as Covered."""
    return {number for number, status in (states or {}).items() if status in COVERING}


def volume_rows(comic_id):
    """Every recorded volume row of a series, with any operator chapter range."""
    if not comic_id:
        return []
    rows = db.select_all(
        select(
            manga_volumes.c.VolumeNumber,
            manga_volumes.c.Status,
            manga_volumes.c.Location,
            manga_volumes.c.FirstChapter,
            manga_volumes.c.LastChapter,
        ).where(manga_volumes.c.ComicID == str(comic_id))
    )
    return [dict(row) for row in rows or ()]


# Want decisions an operator can set on a volume. An empty Status is a row
# that only carries a chapter range: no decision, the monitor mode decides.
WANTED = "Wanted"
SKIPPED = "Skipped"
NO_DECISION = ""
_DECISIONS = frozenset({WANTED, SKIPPED, NO_DECISION})


class VolumeEditError(ValueError):
    """An operator edit to a volume that cannot be applied."""


def _chapter_text(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError as e:
        raise VolumeEditError("chapter numbers must be numbers") from e
    if number < 0:
        raise VolumeEditError("chapter numbers must not be negative")
    return format(number, "g") if not number.is_integer() else str(int(number))


def edit_volume(comic_id, volume_number, *, status=None, first_chapter=None, last_chapter=None, clear_range=False):
    """Apply an operator's want decision and/or chapter range to one volume.

    A decision never un-owns a volume: a grabbed or placed volume keeps its
    Status, and only its range changes. Returns the stored row.
    """
    number = normalize_volume_number(volume_number)
    identity = volume_id(comic_id, number)
    if identity is None:
        raise VolumeEditError("not a volume number")
    if status is not None and status not in _DECISIONS:
        raise VolumeEditError("status must be Wanted, Skipped or empty")
    values = {}
    if clear_range:
        values["FirstChapter"] = None
        values["LastChapter"] = None
    elif first_chapter is not None or last_chapter is not None:
        first = _chapter_text(first_chapter)
        last = _chapter_text(last_chapter)
        if first is None or last is None:
            raise VolumeEditError("give both the first and the last chapter")
        if float(first) > float(last):
            raise VolumeEditError("the first chapter comes after the last")
        values["FirstChapter"] = first
        values["LastChapter"] = last
    if status is None and not values:
        raise VolumeEditError("nothing to change")

    with db.get_engine().begin() as conn:
        conn.execute(
            _insert_if_absent(conn.dialect.name).values(
                VolumeID=identity,
                ComicID=str(comic_id),
                VolumeNumber=number,
                Status=status if status is not None else NO_DECISION,
                updated_at=_now(),
            )
        )
        predicate = manga_volumes.c.VolumeID == identity
        if values:
            conn.execute(update(manga_volumes).where(predicate).values(updated_at=_now(), **values))
        if status is not None:
            # The guard runs in the database: a decision never overwrites a
            # grab or a file that is already here.
            conn.execute(
                update(manga_volumes)
                .where(and_(predicate, manga_volumes.c.Status.notin_(sorted(_PLACED | {SNATCHED}))))
                .values(Status=status, updated_at=_now())
            )
        row = conn.execute(select(manga_volumes).where(predicate)).mappings().one()
    return dict(row)


def series_view(comic_id, projected_issues, *, monitor_mode="blended"):
    """Volumes, chapter coverage and progress for a manga series page.

    Returns ``(issues, volumes, progress)``. Each chapter row gains
    ``holdingVolume`` (the volume it belongs to, MangaDex's or estimated)
    and ``holdingEstimated``; a chapter inside a placed volume reads Covered
    with ``coveredByVolume`` set, the same coverage search skips.
    """
    from comicarr.app.manga import coverage
    from comicarr.app.manga.ledger import apply_volume_coverage

    rows = volume_rows(comic_id)
    chapters = [row for row in projected_issues if row.get("chapterNumber") not in (None, "")]
    ranges = coverage.volume_ranges(chapters, rows)
    covered = coverage.covered_chapters(chapters, rows, ranges)

    holding = {}
    for volume, entry in ranges.items():
        for identity in entry["chapters"]:
            holding[identity] = (volume, entry["source"] == coverage.ESTIMATED)

    containment = {}
    for identity, (volume, _estimated) in covered.items():
        containment.setdefault(volume, set()).add(identity)
    issues = apply_volume_coverage(projected_issues, set(containment), containment) if containment else projected_issues
    for row in issues:
        identity = row.get("id")
        volume, estimated = holding.get(identity, (None, False))
        row["holdingVolume"] = volume
        row["holdingEstimated"] = bool(volume) and estimated
        row["coveredByVolume"] = covered[identity][0] if row.get("covered") and identity in covered else None

    volumes = coverage.volume_entries(chapters, rows, monitor_mode=monitor_mode, ranges=ranges)
    return issues, volumes, _progress(issues, volumes)


def _progress(issues, volumes):
    chapters = []
    for row in issues:
        if row.get("chapterNumber") in (None, "") or row.get("annual"):
            continue
        try:
            number = float(row["chapterNumber"])
        except (TypeError, ValueError):
            continue
        if row.get("covered"):
            kind = "volume"
        elif row.get("owned"):
            kind = "chapter"
        elif row.get("inFlight"):
            kind = "inFlight"
        elif row.get("monitored"):
            kind = "wanted"
        else:
            kind = "notWanted"
        chapters.append((number, kind))
    chapters.sort()
    readable = [number for number, kind in chapters if kind in ("volume", "chapter")]
    run_end = max(readable) if readable else None
    segments = []
    for number, kind in chapters:
        if kind in ("wanted", "notWanted") and run_end is not None and number < run_end:
            kind = "gap"
        if segments and segments[-1]["kind"] == kind:
            segments[-1]["to"] = number
            segments[-1]["count"] += 1
        else:
            segments.append({"kind": kind, "from": number, "to": number, "count": 1})
    for segment in segments:
        segment["from"] = format(segment["from"], "g")
        segment["to"] = format(segment["to"], "g")
    return {
        "volumesTotal": len(volumes),
        "volumesOwned": sum(1 for volume in volumes if volume["owned"]),
        "volumesEstimated": sum(1 for volume in volumes if volume["rangeSource"] == "estimated"),
        "volumesUnknown": sum(1 for volume in volumes if volume["rangeSource"] is None),
        "chaptersTotal": len(chapters),
        "chaptersOwned": sum(1 for _number, kind in chapters if kind == "chapter"),
        "chaptersCovered": sum(1 for _number, kind in chapters if kind == "volume"),
        "chaptersReadable": len(readable),
        "chaptersGap": sum(segment["count"] for segment in segments if segment["kind"] == "gap"),
        "segments": segments,
    }
