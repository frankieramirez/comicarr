#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Daily retention sweep for the five unbounded operational ledgers.

Public entrypoint: ``run_ledger_retention(now=...)``. The scheduler job id is
``ledger_retention`` (display name **Ledger Retention**). Parameters are module
constants only — no operator knobs (#464). Eligibility and delete order match
#463; journal stage/resolution predicates come from
``comicarr.app.downloads.journal``.
"""

from __future__ import annotations

import datetime

from sqlalchemy import and_, delete, exists, func, or_, select, true

from comicarr import logger
from comicarr.app.acquisition.models import ItemOutcome
from comicarr.app.downloads.journal import (
    FAILED,
    MANUAL_REVIEW,
    POST_PROCESSED,
    RESOLVED_STATUSES,
)
from comicarr.db import get_engine
from comicarr.tables import (
    acquisition_maintenance_events,
    acquisition_run_items,
    acquisition_runs,
    ai_activity_log,
    pipeline_journal,
)

DELETE_BATCH_SIZE = 500

ITEMS_AGE_DAYS = 90
ITEMS_KEEP_NEWEST = 50_000

RUNS_AGE_DAYS = 90
RUNS_KEEP_NEWEST = 2_000

JOURNAL_AGE_DAYS = 365

MAINTENANCE_AGE_DAYS = 90
MAINTENANCE_KEEP_NEWEST = 5_000

AI_AGE_DAYS = 90
AI_KEEP_NEWEST = 10_000

_NONTERMINAL_ITEM_STATES = (ItemOutcome.ACCEPTED.value, ItemOutcome.RUNNING.value)


def run_ledger_retention(now=None):
    """Run one shared daily ledger retention pass.

    Delete order (#463):

    1. Eligible terminal ``acquisition_run_items``
    2. Eligible completed ``acquisition_runs`` with zero remaining items
    3. Eligible ``pipeline_journal`` terminals
    4. ``acquisition_maintenance_events``
    5. ``ai_activity_log``

    Fail-soft: log any error and return ``None`` without raising so the process
    and scheduler stay up. Returns a per-table deleted-row summary on success.
    """
    try:
        when = _as_utc_datetime(now)
        engine = get_engine()
        summary = {
            "acquisition_run_items": 0,
            "acquisition_runs": 0,
            "pipeline_journal": 0,
            "acquisition_maintenance_events": 0,
            "ai_activity_log": 0,
        }
        logger.info("[LEDGER-RETENTION] Starting sweep (now=%s)" % when.isoformat())
        with engine.begin() as conn:
            summary["acquisition_run_items"] = _purge_acquisition_run_items(conn, when)
        with engine.begin() as conn:
            summary["acquisition_runs"] = _purge_acquisition_runs(conn, when)
        with engine.begin() as conn:
            summary["pipeline_journal"] = _purge_pipeline_journal(conn, when)
        with engine.begin() as conn:
            summary["acquisition_maintenance_events"] = _purge_maintenance_events(conn, when)
        with engine.begin() as conn:
            summary["ai_activity_log"] = _purge_ai_activity_log(conn, when)
        logger.info(
            "[LEDGER-RETENTION] Sweep complete: items=%s runs=%s journal=%s "
            "maintenance=%s ai=%s"
            % (
                summary["acquisition_run_items"],
                summary["acquisition_runs"],
                summary["pipeline_journal"],
                summary["acquisition_maintenance_events"],
                summary["ai_activity_log"],
            )
        )
        return summary
    except Exception as e:
        logger.error("[LEDGER-RETENTION] Sweep failed: %s" % e)
        return None


def _purge_acquisition_run_items(conn, when):
    age_expr = func.coalesce(acquisition_run_items.c.completed_at, acquisition_run_items.c.updated_at)
    eligible = acquisition_run_items.c.state.notin_(_NONTERMINAL_ITEM_STATES)
    cutoff = _iso_cutoff(when, ITEMS_AGE_DAYS)
    return _batched_hybrid_delete(
        conn,
        table=acquisition_run_items,
        pk_col=acquisition_run_items.c.item_id,
        age_expr=age_expr,
        eligible_clause=eligible,
        cutoff=cutoff,
        keep_newest=ITEMS_KEEP_NEWEST,
    )


def _purge_acquisition_runs(conn, when):
    age_expr = func.coalesce(acquisition_runs.c.completed_at, acquisition_runs.c.updated_at)
    has_items = exists(select(1).where(acquisition_run_items.c.run_id == acquisition_runs.c.run_id))
    eligible = and_(
        acquisition_runs.c.completed_at.isnot(None),
        ~has_items,
    )
    cutoff = _iso_cutoff(when, RUNS_AGE_DAYS)
    return _batched_hybrid_delete(
        conn,
        table=acquisition_runs,
        pk_col=acquisition_runs.c.run_id,
        age_expr=age_expr,
        eligible_clause=eligible,
        cutoff=cutoff,
        keep_newest=RUNS_KEEP_NEWEST,
    )


def _purge_pipeline_journal(conn, when):
    eligible = or_(
        pipeline_journal.c.stage == POST_PROCESSED,
        and_(
            pipeline_journal.c.stage.in_((FAILED, MANUAL_REVIEW)),
            pipeline_journal.c.status.in_(RESOLVED_STATUSES),
        ),
    )
    cutoff = _journal_cutoff(when, JOURNAL_AGE_DAYS)
    return _batched_age_only_delete(
        conn,
        table=pipeline_journal,
        pk_col=pipeline_journal.c.release_key,
        age_expr=pipeline_journal.c.updated_date,
        eligible_clause=eligible,
        cutoff=cutoff,
    )


def _purge_maintenance_events(conn, when):
    cutoff = _iso_cutoff(when, MAINTENANCE_AGE_DAYS)
    return _batched_hybrid_delete(
        conn,
        table=acquisition_maintenance_events,
        pk_col=acquisition_maintenance_events.c.event_id,
        age_expr=acquisition_maintenance_events.c.created_at,
        eligible_clause=true(),
        cutoff=cutoff,
        keep_newest=MAINTENANCE_KEEP_NEWEST,
    )


def _purge_ai_activity_log(conn, when):
    cutoff = _iso_cutoff(when, AI_AGE_DAYS)
    return _batched_hybrid_delete(
        conn,
        table=ai_activity_log,
        pk_col=ai_activity_log.c.id,
        age_expr=ai_activity_log.c.timestamp,
        eligible_clause=true(),
        cutoff=cutoff,
        keep_newest=AI_KEEP_NEWEST,
    )


def _batched_hybrid_delete(conn, table, pk_col, age_expr, eligible_clause, cutoff, keep_newest):
    """Delete eligible rows older than *cutoff* and outside the newest N.

    Hybrid formula (#464): delete only when
    ``eligible AND age > horizon AND not in newest N eligible (age DESC, pk DESC)``.
    """
    deleted_total = 0
    while True:
        keepers = (
            select(pk_col.label("keep_id"))
            .where(eligible_clause)
            .order_by(age_expr.desc(), pk_col.desc())
            .limit(int(keep_newest))
        )
        candidates = (
            select(pk_col)
            .where(
                eligible_clause,
                age_expr < cutoff,
                pk_col.notin_(keepers),
            )
            .limit(DELETE_BATCH_SIZE)
        )
        ids = [row[0] for row in conn.execute(candidates)]
        if not ids:
            break
        result = conn.execute(delete(table).where(pk_col.in_(ids)))
        batch = result.rowcount if result.rowcount is not None else len(ids)
        deleted_total += batch
        if len(ids) < DELETE_BATCH_SIZE:
            break
    return deleted_total


def _batched_age_only_delete(conn, table, pk_col, age_expr, eligible_clause, cutoff):
    """Delete eligible rows older than *cutoff* (no newest-N floor)."""
    deleted_total = 0
    while True:
        candidates = select(pk_col).where(eligible_clause, age_expr < cutoff).limit(DELETE_BATCH_SIZE)
        ids = [row[0] for row in conn.execute(candidates)]
        if not ids:
            break
        result = conn.execute(delete(table).where(pk_col.in_(ids)))
        batch = result.rowcount if result.rowcount is not None else len(ids)
        deleted_total += batch
        if len(ids) < DELETE_BATCH_SIZE:
            break
    return deleted_total


def _as_utc_datetime(now):
    if now is None:
        return datetime.datetime.now(datetime.timezone.utc)
    if not isinstance(now, datetime.datetime):
        raise TypeError("now must be a datetime or None")
    if now.tzinfo is None or now.utcoffset() is None:
        return now.replace(tzinfo=datetime.timezone.utc)
    return now.astimezone(datetime.timezone.utc)


def _iso_cutoff(when, days):
    """Cutoff string for tables that store UTC ISO timestamps."""
    return (when - datetime.timedelta(days=int(days))).isoformat()


def _journal_cutoff(when, days):
    """Cutoff for pipeline_journal.updated_date (``YYYY-MM-DD HH:MM:SS``)."""
    return (when - datetime.timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
