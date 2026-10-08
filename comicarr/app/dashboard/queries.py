#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""SQLAlchemy Core projections owned by the dashboard domain."""

from sqlalchemy import func, select

from comicarr import db
from comicarr.series_kind import comic_sql_clause, manga_sql_clause
from comicarr.tables import activity_events
from comicarr.tables import comics as t_comics


def get_recent_activity(cutoff, limit=10):
    """Return a bounded newest-first narrative preview at an inclusive cutoff.

    Ordered time slice of ``activity_events`` only — never a count, group, or
    status filter over the narrative table (Activity Center ADR authority rule;
    docs/architecture/dashboard-spec.md §3.4). Failures that never reached
    ``t_snatched`` appear here the same way successes do.
    """
    stmt = (
        select(activity_events)
        .where(activity_events.c.created_at >= cutoff)
        .order_by(
            activity_events.c.created_at.desc(),
            activity_events.c.event_id.desc(),
        )
        .limit(int(limit))
    )
    return db.select_all(stmt)


def get_library_stats(content_type=None):
    """Return combined, manga-only, or comic-only library aggregates."""
    if content_type == "manga":
        columns = (
            func.count().label("manga_series"),
            func.coalesce(func.sum(t_comics.c.Have), 0).label("manga_have"),
            func.coalesce(func.sum(t_comics.c.Total), 0).label("manga_total"),
        )
        conditions = (
            t_comics.c.Status != "Paused",
            manga_sql_clause(t_comics.c.ComicID, t_comics.c.ContentType),
        )
    elif content_type == "comic":
        columns = (
            func.count().label("comic_series"),
            func.coalesce(func.sum(t_comics.c.Have), 0).label("comic_have"),
            func.coalesce(func.sum(t_comics.c.Total), 0).label("comic_total"),
        )
        conditions = (
            t_comics.c.Status != "Paused",
            comic_sql_clause(t_comics.c.ComicID, t_comics.c.ContentType),
        )
    else:
        columns = (
            func.count().label("total_series"),
            func.coalesce(func.sum(t_comics.c.Have), 0).label("total_issues"),
            func.coalesce(func.sum(t_comics.c.Total), 0).label("total_expected"),
        )
        conditions = (t_comics.c.Status != "Paused",)

    return db.select_one(select(*columns).select_from(t_comics).where(*conditions))
