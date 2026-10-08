#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""SQLAlchemy Core projections owned by the weekly domain."""

from sqlalchemy import select

from comicarr import db
from comicarr.tables import weekly as t_weekly


def get_weekly_releases(week, year):
    """Return current-week industry releases using the legacy unpadded week key."""
    normalized_week = str(int(week))
    stmt = (
        select(
            t_weekly.c.COMIC,
            t_weekly.c.ISSUE,
            t_weekly.c.PUBLISHER,
            t_weekly.c.SHIPDATE,
            t_weekly.c.STATUS,
            t_weekly.c.ComicID,
            t_weekly.c.IssueID,
            t_weekly.c.rowid,
        )
        .where(t_weekly.c.weeknumber == normalized_week, t_weekly.c.year == year)
        .order_by(t_weekly.c.COMIC.asc())
    )
    return db.select_all(stmt)
