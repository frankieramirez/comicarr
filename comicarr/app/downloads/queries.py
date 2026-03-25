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

from sqlalchemy import delete, func, select

from comicarr import db
from comicarr.tables import ddl_info as t_ddl_info
from comicarr.tables import snatched as t_snatched

# ---------------------------------------------------------------------------
# Pagination helper (shared pattern with series/queries.py)
# ---------------------------------------------------------------------------

def _paginated_query(stmt, limit=None, offset=None):
    """Execute a statement with optional pagination."""
    count_stmt = select(func.count()).select_from(stmt.subquery())
    with db.get_engine().connect() as conn:
        total = conn.execute(count_stmt).scalar() or 0

    current_limit = int(limit) if limit is not None else total
    current_offset = int(offset) if offset else 0

    paginated_stmt = stmt
    if limit is not None:
        paginated_stmt = paginated_stmt.limit(int(limit))
        if offset is not None and int(offset) > 0:
            paginated_stmt = paginated_stmt.offset(int(offset))

    results = db.select_all(paginated_stmt)
    has_more = (current_offset + len(results)) < total

    return {
        "results": results,
        "total": total,
        "limit": current_limit,
        "offset": current_offset,
        "has_more": has_more,
    }


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
    return db.select_one(
        select(t_ddl_info).where(t_ddl_info.c.ID == item_id)
    )


def delete_ddl_item(item_id):
    """Delete a DDL queue item."""
    with db.get_engine().begin() as conn:
        conn.execute(delete(t_ddl_info).where(t_ddl_info.c.ID == item_id))


def update_ddl_status(item_id, status):
    """Update DDL queue item status."""
    db.upsert("ddl_info", {"status": status}, {"ID": item_id})
