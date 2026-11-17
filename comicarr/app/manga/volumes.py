#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Owned and grabbed manga volumes (ADR-0004: volumes are not issues).

A volume grab is recorded Snatched; the volume file landing records it
Downloaded with its Location. The chapters a Downloaded volume contains then
read as Covered (``ledger.apply_volume_coverage``), and the volume leaves the
blended search frontier (#1278). Which chapters each volume holds is worked
out in ``coverage``; an operator can correct it by saying which chapter a
volume ends at (``set_volume_end``).
"""

import datetime

from sqlalchemy import and_, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from comicarr.app.core import db
from comicarr.app.core.tables import manga_volumes
from comicarr.app.manga.ledger import normalize_volume_number, volume_id

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
    """Every recorded volume row of a series, with any operator-set end chapter."""
    if not comic_id:
        return []
    rows = db.select_all(
        select(
            manga_volumes.c.VolumeNumber,
            manga_volumes.c.Status,
            manga_volumes.c.Location,
            manga_volumes.c.LastChapter,
        ).where(manga_volumes.c.ComicID == str(comic_id))
    )
    return [dict(row) for row in rows or ()]


# The Status of a row that only carries an operator's end chapter for a
# volume the library neither owns nor has grabbed.
NOT_OWNED = ""


def set_volume_end(comic_id, volume_number, last_chapter):
    """Record the chapter an operator says a volume ends at; None clears it.

    Ownership is untouched. Raises ValueError for a value that is not a
    volume or a chapter number.
    """
    number = normalize_volume_number(volume_number)
    identity = volume_id(comic_id, number)
    if identity is None:
        raise ValueError("not a volume number")
    if last_chapter in (None, ""):
        end = None
    else:
        try:
            value = float(str(last_chapter).strip())
        except ValueError as e:
            raise ValueError("the last chapter must be a number") from e
        if value <= 0:
            raise ValueError("the last chapter must be above zero")
        end = format(value, "g")
    with db.get_engine().begin() as conn:
        conn.execute(
            _insert_if_absent(conn.dialect.name).values(
                VolumeID=identity,
                ComicID=str(comic_id),
                VolumeNumber=number,
                Status=NOT_OWNED,
                updated_at=_now(),
            )
        )
        conn.execute(
            update(manga_volumes).where(manga_volumes.c.VolumeID == identity).values(LastChapter=end, updated_at=_now())
        )
    return end


def series_view(comic_id, projected_issues):
    """Volumes, chapter coverage and progress for a manga series page.

    Returns ``(issues, volumes, progress)``. Each chapter row gains
    ``holdingVolume`` (the volume it falls in) and ``holdingEstimated``; a
    chapter inside a placed volume reads Covered, the same coverage search
    skips.
    """
    from comicarr.app.manga import coverage
    from comicarr.app.manga.ledger import apply_volume_coverage

    rows = {row["VolumeNumber"]: row for row in volume_rows(comic_id)}
    ranges = coverage.volume_ranges(projected_issues, rows.values())
    owned = covering_volumes({number: row["Status"] for number, row in rows.items()})

    holding = {identity: volume for volume, entry in ranges.items() for identity in entry["chapters"]}
    containment = {volume: set(ranges[volume]["chapters"]) for volume in owned if volume in ranges}
    issues = apply_volume_coverage(projected_issues, owned, containment)
    for row in issues:
        volume = holding.get(row.get("id"))
        row["holdingVolume"] = volume
        row["holdingEstimated"] = volume is not None and ranges[volume]["source"] == coverage.ESTIMATED

    volumes = []
    # Newest first, like the chapter list. A recorded volume outside the
    # numbered run (a "1.5") is still listed, with unknown contents.
    for number in [*reversed(ranges), *(number for number in rows if number not in ranges)]:
        entry = ranges.get(number) or {"first": None, "last": None, "source": None}
        row = rows.get(number) or {}
        volumes.append(
            {
                "number": number,
                "firstChapter": None if entry["first"] is None else format(entry["first"], "f"),
                "lastChapter": None if entry["last"] is None else format(entry["last"], "f"),
                "rangeSource": entry["source"],
                "owned": number in owned,
                "inFlight": row.get("Status") == SNATCHED,
                "location": row.get("Location") if number in owned else None,
            }
        )
    return issues, volumes, _progress(issues, volumes)


def _progress(issues, volumes):
    """Counts for the series header, and the chapter run as coloured segments."""
    chapters = []
    for row in issues:
        try:
            number = float(row.get("chapterNumber"))
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
    latest_held = max((number for number, kind in chapters if kind in ("volume", "chapter")), default=None)
    segments = []
    for number, kind in chapters:
        # A hole below the highest chapter you have, wanted or not.
        if kind in ("wanted", "notWanted") and latest_held is not None and number < latest_held:
            kind = "gap"
        if segments and segments[-1]["kind"] == kind:
            segments[-1]["to"] = format(number, "g")
            segments[-1]["count"] += 1
        else:
            segments.append({"kind": kind, "from": format(number, "g"), "to": format(number, "g"), "count": 1})
    return {
        "volumesTotal": len(volumes),
        "volumesOwned": sum(1 for volume in volumes if volume["owned"]),
        "volumesEstimated": sum(1 for volume in volumes if volume["rangeSource"] == "estimated"),
        "chaptersOwned": sum(segment["count"] for segment in segments if segment["kind"] == "chapter"),
        "chaptersGap": sum(segment["count"] for segment in segments if segment["kind"] == "gap"),
        "segments": segments,
    }
