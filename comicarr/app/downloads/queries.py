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

from sqlalchemy import delete, select

from comicarr import db
from comicarr.app.core.database import paginated_query as _paginated_query
from comicarr.tables import annuals as t_annuals
from comicarr.tables import comics as t_comics
from comicarr.tables import ddl_info as t_ddl_info
from comicarr.tables import issues as t_issues
from comicarr.tables import snatched as t_snatched

# ---------------------------------------------------------------------------
# Snatched history
# ---------------------------------------------------------------------------


def get_history(limit=None, offset=None):
    """Get download history ordered by date, optionally paginated."""
    stmt = select(t_snatched).order_by(t_snatched.c.DateAdded.desc())
    if limit is not None:
        return _paginated_query(stmt, limit=limit, offset=offset)
    return db.select_all(stmt)


def clear_history(status_type=None):
    """Clear history entries, optionally filtered by status."""
    if status_type:
        db.raw_execute("DELETE from snatched WHERE Status=?", [status_type])
    else:
        db.raw_execute("DELETE from snatched")


# ---------------------------------------------------------------------------
# DDL queue
# ---------------------------------------------------------------------------


def get_ddl_queue():
    """Get all DDL queue items ordered by submit date."""
    stmt = select(t_ddl_info).order_by(t_ddl_info.c.submit_date.desc())
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


# ---------------------------------------------------------------------------
# Issue file lookup (for file download endpoint)
# ---------------------------------------------------------------------------


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

    # Fall back to annuals
    stmt = (
        select(t_comics.c.ComicLocation, t_annuals)
        .select_from(t_comics.join(t_annuals, t_comics.c.ComicID == t_annuals.c.ComicID))
        .where(t_annuals.c.IssueID == issue_id)
    )
    return db.select_one(stmt)
