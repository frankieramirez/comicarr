#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Private persistence implementation for the Needs attention read interface."""

from sqlalchemy import and_, or_, select, union

from comicarr import db
from comicarr.app.attention._grouping import build_groups
from comicarr.app.attention._policy import TROUBLE_STAGES, actionable_reason_condition
from comicarr.app.attention.contracts import AttentionView, Scope
from comicarr.app.downloads.journal import RESOLVED_STATUSES
from comicarr.tables import annuals, issues, pipeline_journal

SCOPE_TYPES = frozenset({"issue", "annual", "series"})


def _normalize_scope(scope):
    if scope is None:
        return None
    if not isinstance(scope, Scope):
        raise TypeError("scope must be a Scope or None")
    if scope.type is None or scope.id is None:
        raise ValueError("scope_type and scope_id must be provided together")
    scope_type = str(scope.type).strip().lower()
    scope_id = str(scope.id).strip()
    if not scope_type or not scope_id:
        raise ValueError("scope_type and scope_id must be provided together")
    if scope_type not in SCOPE_TYPES:
        raise ValueError("scope_type must be one of: issue, annual, series")
    return Scope(type=scope_type, id=scope_id)


def unresolved_condition():
    """Return the canonical admission predicate for unresolved obligations."""
    return and_(
        pipeline_journal.c.stage.in_(TROUBLE_STAGES),
        or_(
            pipeline_journal.c.status.is_(None),
            pipeline_journal.c.status.notin_(RESOLVED_STATUSES),
        ),
        actionable_reason_condition(pipeline_journal.c.fail_reason),
    )


def _series_member_issue_ids(series_id):
    issue_ids = select(issues.c.IssueID).where(issues.c.ComicID == series_id)
    annual_ids = select(annuals.c.IssueID).where(annuals.c.ComicID == series_id)
    return union(issue_ids, annual_ids).subquery()


def _scope_condition(scope):
    if scope.type in ("issue", "annual"):
        return pipeline_journal.c.issueid == scope.id
    members = _series_member_issue_ids(scope.id)
    return pipeline_journal.c.issueid.in_(select(members.c.IssueID))


def list_rows(scope=None):
    """Read admitted journal rows, filtered before grouping."""
    normalized = _normalize_scope(scope)
    stmt = select(pipeline_journal).where(unresolved_condition())
    if normalized is not None:
        stmt = stmt.where(_scope_condition(normalized))
    stmt = stmt.order_by(
        pipeline_journal.c.updated_date.desc(),
        pipeline_journal.c.release_key.desc(),
    )
    return db.select_all(stmt)


def read(scope=None):
    """Return groups and both totals from one admitted-row snapshot."""
    groups = build_groups(list_rows(scope=scope))
    return AttentionView(
        groups=groups,
        total=len(groups),
        member_total=sum(group.member_count for group in groups),
    )
