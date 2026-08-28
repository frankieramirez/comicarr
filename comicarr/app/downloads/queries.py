#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Downloads domain queries — snatched history, DDL queue, nzblog, failed.

Uses SQLAlchemy Core via the existing db module.
"""

from sqlalchemy import delete, func, or_, select, update

from comicarr import db
from comicarr.app.core.database import paginated_query as _paginated_query
from comicarr.tables import annuals as t_annuals
from comicarr.tables import comics as t_comics
from comicarr.tables import ddl_info as t_ddl_info
from comicarr.tables import issues as t_issues
from comicarr.tables import snatched as t_snatched


def _apply_activity_filters(stmt, status_column, search=None, status=None, search_columns=()):
    if search:
        pattern = "%%%s%%" % search.strip().lower()
        stmt = stmt.where(or_(*[column.ilike(pattern) for column in search_columns]))
    if status:
        stmt = stmt.where(func.lower(func.coalesce(status_column, "")) == status.strip().lower())
    return stmt


def _apply_activity_sort(stmt, sort, order, allowed_columns, default_column, tie_breaker):
    sort_column = allowed_columns.get(sort, default_column)
    direction = sort_column.asc() if str(order).lower() == "asc" else sort_column.desc()
    return stmt.order_by(direction, tie_breaker.desc())


def get_history(limit=None, offset=None, search=None, status=None, sort=None, order="desc"):
    """Get searchable, sortable download history, optionally paginated."""
    stmt = _apply_activity_filters(
        select(t_snatched),
        t_snatched.c.Status,
        search=search,
        status=status,
        search_columns=(
            t_snatched.c.ComicName,
            t_snatched.c.Issue_Number,
            t_snatched.c.Provider,
            t_snatched.c.Status,
            t_snatched.c.FolderName,
        ),
    )
    stmt = _apply_activity_sort(
        stmt,
        sort,
        order,
        {
            "series": t_snatched.c.ComicName,
            "issue": t_snatched.c.Issue_Number,
            "provider": t_snatched.c.Provider,
            "status": t_snatched.c.Status,
            "date": t_snatched.c.DateAdded,
        },
        t_snatched.c.DateAdded,
        t_snatched.c.IssueID,
    )
    if limit is not None:
        return _paginated_query(stmt, limit=limit, offset=offset)
    return db.select_all(stmt)


def clear_history(status_type=None):
    """Clear history entries, optionally filtered by status."""
    if status_type:
        db.raw_execute("DELETE from snatched WHERE Status=?", [status_type])
    else:
        db.raw_execute("DELETE from snatched")


ACTIVE_DDL_STATUSES = ("Queued", "Downloading", "Failed")


def active_ddl_condition():
    """Return the shared predicate for queue rows that still need attention."""
    return or_(
        t_ddl_info.c.status.is_(None),
        t_ddl_info.c.status.in_(ACTIVE_DDL_STATUSES),
    )


def count_active_ddl_items():
    stmt = select(func.count().label("queue_count")).select_from(t_ddl_info).where(active_ddl_condition())
    row = db.select_one(stmt)
    return (row or {}).get("queue_count", 0) or 0


def get_active_ddl_preview(limit=5):
    """Return the newest active queue rows for compact operational summaries."""
    stmt = (
        select(t_ddl_info)
        .where(active_ddl_condition())
        .order_by(t_ddl_info.c.updated_date.desc(), t_ddl_info.c.ID.desc())
        .limit(limit)
    )
    return db.select_all(stmt)


def get_ddl_queue(limit=None, offset=None, search=None, status=None, sort=None, order="desc"):
    """Get active DDL queue items with search, sorting, and pagination."""
    stmt = select(t_ddl_info).where(active_ddl_condition())
    stmt = _apply_activity_filters(
        stmt,
        t_ddl_info.c.status,
        search=search,
        status=status,
        search_columns=(
            t_ddl_info.c.series,
            t_ddl_info.c.filename,
            t_ddl_info.c.site,
            t_ddl_info.c.status,
        ),
    )
    stmt = _apply_activity_sort(
        stmt,
        sort,
        order,
        {
            "series": t_ddl_info.c.series,
            "file": t_ddl_info.c.filename,
            "site": t_ddl_info.c.site,
            "status": t_ddl_info.c.status,
            "updated": t_ddl_info.c.updated_date,
            "submitted": t_ddl_info.c.submit_date,
        },
        t_ddl_info.c.updated_date,
        t_ddl_info.c.ID,
    )
    if limit is not None:
        return _paginated_query(stmt, limit=limit, offset=offset)
    return db.select_all(stmt)


def get_queued_ddl_items():
    """Get durable outbox rows that have not started downloading yet."""
    stmt = (
        select(t_ddl_info)
        .where(t_ddl_info.c.status == "Queued")
        .order_by(t_ddl_info.c.updated_date.asc(), t_ddl_info.c.ID.asc())
    )
    return db.select_all(stmt)


def get_ddl_item(item_id):
    """Get a single DDL queue item."""
    return db.select_one(select(t_ddl_info).where(t_ddl_info.c.ID == item_id))


def delete_ddl_item(item_id):
    """Delete a DDL queue item."""
    with db.get_engine().begin() as conn:
        conn.execute(delete(t_ddl_info).where(t_ddl_info.c.ID == item_id))


def update_ddl_status(item_id, status):
    """Update DDL queue item status."""
    db.upsert("ddl_info", {"status": status}, {"ID": item_id})


def claim_failed_ddl_retry(item_id):
    """Atomically move one terminal failure into the durable outbox."""

    with db.get_engine().begin() as conn:
        result = conn.execute(
            update(t_ddl_info)
            .where(t_ddl_info.c.ID == str(item_id))
            .where(t_ddl_info.c.status == "Failed")
            .values(status="Queued")
        )
    return result.rowcount == 1


def get_issue_file_info(issue_id):
    """Look up the file location for an issue by joining comics and issues.

    Checks issues table first, then annuals. Returns a dict with
    ComicLocation and Location, or None if not found.
    """
    stmt = (
        select(t_comics.c.ComicLocation, t_issues)
        .select_from(t_comics.join(t_issues, t_comics.c.ComicID == t_issues.c.ComicID))
        .where(t_issues.c.IssueID == issue_id)
    )
    result = db.select_one(stmt)
    if result:
        return result

    stmt = (
        select(t_comics.c.ComicLocation, t_annuals)
        .select_from(t_comics.join(t_annuals, t_comics.c.ComicID == t_annuals.c.ComicID))
        .where(t_annuals.c.IssueID == issue_id)
    )
    return db.select_one(stmt)
