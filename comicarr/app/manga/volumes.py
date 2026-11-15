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


def record_volume(comic_id, volume_number, status, location=None):
    """Record a volume's status; return its VolumeID, or None for no volume."""
    number = normalize_volume_number(volume_number)
    identity = volume_id(comic_id, number)
    if identity is None:
        return None
    with db.get_engine().begin() as conn:
        row = conn.execute(select(manga_volumes).where(manga_volumes.c.VolumeID == identity)).mappings().first()
        if row is None:
            conn.execute(
                insert(manga_volumes).values(
                    VolumeID=identity,
                    ComicID=comic_id,
                    VolumeNumber=number,
                    Status=status,
                    Location=location,
                    updated_at=_now(),
                )
            )
            return identity
        if status == SNATCHED and row["Status"] in _PLACED:
            return identity
        values = {"Status": status, "updated_at": _now()}
        if location is not None:
            values["Location"] = location
        conn.execute(update(manga_volumes).where(manga_volumes.c.VolumeID == identity).values(**values))
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
