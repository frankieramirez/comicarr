#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Shared pagination for SQLAlchemy domain queries."""

from sqlalchemy import func, select

from comicarr import db


def paginated_query(stmt, limit=None, offset=None):
    """Execute a statement with optional pagination. Returns dict with results/total/has_more."""
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
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
