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
from comicarr.tables import comics as t_comics
from comicarr.tables import issues as t_issues
from comicarr.tables import weekly as t_weekly


def get_weekly_releases(week, year):
    """Return one week's industry releases using the legacy unpadded week key."""
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
            t_weekly.c.format,
            t_weekly.c.rowid,
        )
        .where(t_weekly.c.weeknumber == normalized_week, t_weekly.c.year == year)
        .order_by(t_weekly.c.COMIC.asc())
    )
    return db.select_all(stmt)


def get_weekly_row(rowid):
    """Return one stored pull-list row by its primary key."""
    stmt = select(
        t_weekly.c.COMIC,
        t_weekly.c.ISSUE,
        t_weekly.c.ComicID,
        t_weekly.c.IssueID,
        t_weekly.c.rowid,
    ).where(t_weekly.c.rowid == rowid)
    return db.select_one(stmt)


def has_week(week, year):
    """Return whether any pull-list rows are stored for the week."""
    stmt = (
        select(t_weekly.c.rowid).where(t_weekly.c.weeknumber == str(int(week)), t_weekly.c.year == str(year)).limit(1)
    )
    return db.select_one(stmt) is not None


def get_library_series(comic_ids):
    """Return library series keyed by ComicID for the given ids."""
    ids = sorted({str(comic_id) for comic_id in comic_ids if comic_id})
    if not ids:
        return {}
    stmt = select(t_comics.c.ComicID, t_comics.c.Status).where(t_comics.c.ComicID.in_(ids))
    return {row["ComicID"]: row for row in db.select_all(stmt)}


def get_library_issues(comic_ids):
    """Return library issues for the given series, keyed by IssueID."""
    ids = sorted({str(comic_id) for comic_id in comic_ids if comic_id})
    if not ids:
        return {}
    stmt = select(
        t_issues.c.IssueID,
        t_issues.c.ComicID,
        t_issues.c.Issue_Number,
        t_issues.c.Status,
    ).where(t_issues.c.ComicID.in_(ids))
    return {row["IssueID"]: row for row in db.select_all(stmt)}
