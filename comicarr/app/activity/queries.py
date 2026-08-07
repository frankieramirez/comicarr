#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""SQLAlchemy Core projections for Activity Center read surfaces.

Authority rule (Activity Center ADR §3): derived state is authoritative for
every count. These queries never aggregate ``activity_events`` for open-work
or attention numbers — only ordered time slices of that table are allowed.
"""

from sqlalchemy import and_, func, or_, select, union

from comicarr import db
from comicarr.app.acquisition.models import ItemOutcome
from comicarr.app.activity import grouping
from comicarr.app.activity.reasons import actionable_reason_condition
from comicarr.app.core.database import paginated_query
from comicarr.app.downloads.journal import FAILED, MANUAL_REVIEW, OPEN_STAGES
from comicarr.tables import acquisition_run_items, activity_events, annuals, issues, pipeline_journal

# Pagination pages *events* (not pre-grouped stories). Story grouping of 25 is
# a UI concern; the client may request more events than stories to fill a page.
TIMELINE_LIMIT_MIN = 1
TIMELINE_LIMIT_MAX = 100
TIMELINE_LIMIT_DEFAULT = 50

TIMELINE_SCOPE_TYPES = frozenset({"issue", "annual", "series"})

# R9 resolution statuses that remove a journal row from the needs-attention band.
BAND_RESOLVED_STATUSES = ("retried", "ignored", "imported")
BAND_TROUBLE_STAGES = (FAILED, MANUAL_REVIEW)

IN_FLIGHT_ITEM_STATES = (ItemOutcome.ACCEPTED.value, ItemOutcome.RUNNING.value)


def _clamp_timeline_limit(limit):
    if limit is None:
        return TIMELINE_LIMIT_DEFAULT
    try:
        value = int(limit)
    except (TypeError, ValueError) as e:
        raise ValueError("limit must be an integer") from e
    if value < TIMELINE_LIMIT_MIN:
        return TIMELINE_LIMIT_MIN
    if value > TIMELINE_LIMIT_MAX:
        return TIMELINE_LIMIT_MAX
    return value


def _normalize_offset(offset):
    if offset is None:
        return 0
    try:
        value = int(offset)
    except (TypeError, ValueError) as e:
        raise ValueError("offset must be an integer") from e
    return max(0, value)


def _normalize_scope(scope_type, scope_id):
    """Return (scope_type, scope_id) or (None, None). Raise on partial/invalid."""
    has_type = scope_type is not None and str(scope_type).strip() != ""
    has_id = scope_id is not None and str(scope_id).strip() != ""
    if not has_type and not has_id:
        return None, None
    if not has_type or not has_id:
        raise ValueError("scope_type and scope_id must be provided together")
    normalized_type = str(scope_type).strip().lower()
    if normalized_type not in TIMELINE_SCOPE_TYPES:
        raise ValueError("scope_type must be one of: issue, annual, series")
    return normalized_type, str(scope_id).strip()


def _timeline_scope_condition(scope_type, scope_id):
    if scope_type in ("issue", "annual"):
        return and_(
            activity_events.c.subject_type == scope_type,
            activity_events.c.subject_id == scope_id,
        )
    # series rollup: parent_series_id + series subject + series-scoped run events
    return or_(
        activity_events.c.parent_series_id == scope_id,
        and_(
            activity_events.c.subject_type == "series",
            activity_events.c.subject_id == scope_id,
        ),
        and_(
            activity_events.c.subject_type == "run",
            activity_events.c.scope_type == "series",
            activity_events.c.scope_id == scope_id,
        ),
    )


def list_timeline_events(limit=None, offset=None, scope_type=None, scope_id=None):
    """Return a newest-first page of narrative events.

    Pages events ordered by ``created_at`` (then ``event_id``). Does not
    pre-group into stories — clients group by ``(subject_type, subject_id)``
    per the Activity Center ADR.
    """
    scope_type, scope_id = _normalize_scope(scope_type, scope_id)
    page_limit = _clamp_timeline_limit(limit)
    page_offset = _normalize_offset(offset)

    stmt = select(activity_events)
    if scope_type is not None:
        stmt = stmt.where(_timeline_scope_condition(scope_type, scope_id))
    stmt = stmt.order_by(
        activity_events.c.created_at.desc(),
        activity_events.c.event_id.desc(),
    )
    return paginated_query(stmt, limit=page_limit, offset=page_offset)


def unresolved_band_condition():
    """R9 needs-attention predicate (Activity Center ADR §2 / #541).

    ``stage IN ('failed', 'manual_review')``, status is null or not a
    resolution status (``retried`` / ``ignored`` / ``imported``), and the
    ``fail_reason`` base token is actionable (#523). Non-actionable reasons
    leave the band only because their writers reconcile the issue (clause 2).
    """
    return and_(
        pipeline_journal.c.stage.in_(BAND_TROUBLE_STAGES),
        or_(
            pipeline_journal.c.status.is_(None),
            pipeline_journal.c.status.notin_(BAND_RESOLVED_STATUSES),
        ),
        actionable_reason_condition(pipeline_journal.c.fail_reason),
    )


def _series_member_issue_ids(series_id):
    """Issue/annual IssueIDs belonging to a series (for band scope)."""
    issue_ids = select(issues.c.IssueID).where(issues.c.ComicID == series_id)
    annual_ids = select(annuals.c.IssueID).where(annuals.c.ComicID == series_id)
    return union(issue_ids, annual_ids).subquery()


def _band_scope_condition(scope_type, scope_id):
    if scope_type in ("issue", "annual"):
        return pipeline_journal.c.issueid == scope_id
    # series: journal rows whose issueid is a member of the series
    members = _series_member_issue_ids(scope_id)
    return pipeline_journal.c.issueid.in_(select(members.c.IssueID))


def list_attention_band(scope_type=None, scope_id=None):
    """Return unresolved needs-attention journal rows, newest first."""
    scope_type, scope_id = _normalize_scope(scope_type, scope_id)
    stmt = select(pipeline_journal).where(unresolved_band_condition())
    if scope_type is not None:
        stmt = stmt.where(_band_scope_condition(scope_type, scope_id))
    stmt = stmt.order_by(
        pipeline_journal.c.updated_date.desc(),
        pipeline_journal.c.release_key.desc(),
    )
    return db.select_all(stmt)


def count_attention_band(scope_type=None, scope_id=None):
    """Count unresolved needs-attention journal *rows* (derived ledger only)."""
    scope_type, scope_id = _normalize_scope(scope_type, scope_id)
    stmt = (
        select(func.count().label("attention_count")).select_from(pipeline_journal).where(unresolved_band_condition())
    )
    if scope_type is not None:
        stmt = stmt.where(_band_scope_condition(scope_type, scope_id))
    row = db.select_one(stmt)
    return int((row or {}).get("attention_count", 0) or 0)


def list_attention_groups(scope_type=None, scope_id=None):
    """Group the unresolved band by ``(comicid, base_reason)``, newest first."""
    return grouping.build_groups(list_attention_band(scope_type=scope_type, scope_id=scope_id))


def count_attention_groups(scope_type=None, scope_id=None):
    """Count band *groups* — the number the status line reports.

    Runs the same builder as ``list_attention_groups`` rather than a separate
    SQL expression. Grouping keys off ``payload_json``, which no portable
    dialect expression can reach, so a second implementation would be the only
    way the band and the status count could ever disagree (#524).
    """
    return len(list_attention_groups(scope_type=scope_type, scope_id=scope_id))


def count_in_flight_run_items():
    """Count accepted|running acquisition_run_items."""
    stmt = (
        select(func.count().label("item_count"))
        .select_from(acquisition_run_items)
        .where(acquisition_run_items.c.state.in_(IN_FLIGHT_ITEM_STATES))
    )
    row = db.select_one(stmt)
    return int((row or {}).get("item_count", 0) or 0)


def count_recovery_pending_run_items():
    """Non-terminal run items that have already survived at least one restart.

    Reported alongside ``in_flight`` rather than folded into it so the health
    number can read "N in flight (K recovered from a restart)". One opaque
    number could not distinguish live work from obligations that keep coming
    back, which is what made the old count untrustworthy (#555).
    """
    stmt = (
        select(func.count().label("item_count"))
        .select_from(acquisition_run_items)
        .where(acquisition_run_items.c.state.in_(IN_FLIGHT_ITEM_STATES))
        .where(acquisition_run_items.c.recovery_count > 0)
    )
    row = db.select_one(stmt)
    return int((row or {}).get("item_count", 0) or 0)


def count_open_journal_stages():
    """Count pipeline_journal rows still in OPEN_STAGES."""
    stmt = (
        select(func.count().label("journal_count"))
        .select_from(pipeline_journal)
        .where(pipeline_journal.c.stage.in_(OPEN_STAGES))
    )
    row = db.select_one(stmt)
    return int((row or {}).get("journal_count", 0) or 0)


def get_open_work_counts():
    """Quiet-count DTO inputs from derived ledgers only.

    ``in_flight`` = accepted|running run items + OPEN_STAGES journal rows.
    ``recovery_pending`` = the subset of those run items that has already
    survived a restart — a qualifier on ``in_flight``, not an addition to it.
    ``attention`` = unresolved band **group** count — the number of distinct
    problems, which is what the band shows and what the operator has to act on.
    ``attention_members`` keeps the underlying row count available for copy that
    needs "N issues across K problems".
    Never reads ``activity_events``.
    """
    return {
        "in_flight": count_in_flight_run_items() + count_open_journal_stages(),
        "recovery_pending": count_recovery_pending_run_items(),
        "attention": count_attention_groups(),
        "attention_members": count_attention_band(),
    }
