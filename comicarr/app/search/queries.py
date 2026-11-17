#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Search domain queries — provider, run, and worker health projections.

Most search operations go through search.py and mb.findComic rather
than direct DB access. This module covers auxiliary query needs.
"""

from sqlalchemy import func, select

from comicarr.app.core import db
from comicarr.app.core.db import get_engine
from comicarr.app.core.tables import (
    acquisition_run_items,
    acquisition_runs,
    jobhistory,
)
from comicarr.app.core.tables import (
    provider_searches as t_provider_searches,
)


def get_provider_stats(engine=None):
    """Get provider search statistics (last run, hit counts)."""
    stmt = select(t_provider_searches).order_by(t_provider_searches.c.provider)
    if engine is not None:
        with engine.connect() as conn:
            return [dict(row._mapping) for row in conn.execute(stmt)]
    return db.select_all(stmt)


def get_acquisition_run_rows(engine=None, limit=100):
    """Return recent durable acquisition runs without conflating dispatch and completion."""
    engine = engine or get_engine()
    stmt = select(acquisition_runs).order_by(acquisition_runs.c.created_at.desc()).limit(int(limit))
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(stmt)]


def get_oldest_acquisition_backlogs(engine=None):
    """Return the oldest nonterminal item timestamp for each command kind."""
    engine = engine or get_engine()
    stmt = (
        select(acquisition_run_items.c.command_kind, func.min(acquisition_run_items.c.created_at))
        .where(acquisition_run_items.c.state.in_(["accepted", "running"]))
        .group_by(acquisition_run_items.c.command_kind)
    )
    with engine.connect() as conn:
        return {row[0]: row[1] for row in conn.execute(stmt)}


def get_health_history_rows(engine=None, prefix=None):
    """Read durable job/worker/route history rows used by health endpoints."""
    engine = engine or get_engine()
    stmt = select(jobhistory)
    if prefix:
        stmt = stmt.where(jobhistory.c.JobName.like("%s%%" % prefix))
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(stmt)]
