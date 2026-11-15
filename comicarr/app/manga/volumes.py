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
blended search frontier (#1278).
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
