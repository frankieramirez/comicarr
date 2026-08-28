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

import json

from sqlalchemy import and_, func, or_, select

from comicarr import db
from comicarr.app.acquisition.models import ItemOutcome
from comicarr.app.attention import Scope, read
from comicarr.app.attention._read import list_rows as _list_attention_rows
from comicarr.app.attention._read import unresolved_condition as _unresolved_attention_condition
from comicarr.app.attention._serialization import serialize_groups as _serialize_attention_groups
from comicarr.app.core.database import paginated_query
from comicarr.app.downloads.journal import OPEN_STAGES, load_payload
from comicarr.tables import acquisition_run_items, activity_events, pipeline_journal

TIMELINE_LIMIT_MIN = 1
TIMELINE_LIMIT_MAX = 100
TIMELINE_LIMIT_DEFAULT = 50

TIMELINE_SCOPE_TYPES = frozenset({"issue", "annual", "series"})

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
    """Compatibility alias for the predicate now owned by Attention."""
    return _unresolved_attention_condition()


def _attention_scope(scope_type, scope_id):
    normalized_type, normalized_id = _normalize_scope(scope_type, scope_id)
    if normalized_type is None:
        return None
    return Scope(type=normalized_type, id=normalized_id)


def list_attention_band(scope_type=None, scope_id=None):
    """Compatibility reader for callers awaiting migration to ``attention.read``."""
    return _list_attention_rows(scope=_attention_scope(scope_type, scope_id))


def count_attention_band(scope_type=None, scope_id=None):
    """Compatibility count derived from one Attention view."""
    return read(scope=_attention_scope(scope_type, scope_id)).member_total


def list_attention_groups(scope_type=None, scope_id=None):
    """Compatibility projection of ``AttentionView.groups``."""
    return _serialize_attention_groups(read(scope=_attention_scope(scope_type, scope_id)).groups)


def count_attention_groups(scope_type=None, scope_id=None):
    """Compatibility projection of ``AttentionView.total``."""
    return read(scope=_attention_scope(scope_type, scope_id)).total


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


def _text(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _json_object(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _run_item_label(row, payload):
    name = _text(payload.get("comicname"))
    number = _text(payload.get("issue_number")) or _text(payload.get("issuenumber"))
    if name and number:
        return "%s #%s" % (name, number)
    if name:
        return name
    entity_type = _text(row.get("entity_type")) or "item"
    entity_id = _text(row.get("entity_id"))
    if entity_id:
        return "%s %s" % (entity_type, entity_id)
    return _text(row.get("command_kind")) or "search"


def _journal_item_label(row, payload):
    name = _text(payload.get("comicname")) or _text(payload.get("ComicName"))
    number = _text(payload.get("issuenumber")) or _text(payload.get("Issue_Number"))
    if name and number:
        return "%s #%s" % (name, number)
    if name:
        return name
    nzbname = _text(payload.get("nzbname")) or _text(payload.get("nzb_name")) or _text(row.get("nzbname"))
    if nzbname:
        return nzbname
    issueid = _text(row.get("issueid")) or _text(payload.get("issueid"))
    if issueid:
        return "issue %s" % issueid
    return _text(row.get("release_key")) or "download"


def _shape_run_item(row):
    payload = _json_object(row.get("payload_json"))
    entity_type = _text(row.get("entity_type"))
    entity_id = _text(row.get("entity_id"))
    issueid = _text(payload.get("issueid"))
    if issueid is None and entity_type in ("issue", "annual"):
        issueid = entity_id
    return {
        "kind": "run",
        "item_id": row.get("item_id"),
        "run_id": row.get("run_id"),
        "state": row.get("state"),
        "label": _run_item_label(row, payload),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "comicid": _text(payload.get("comicid")),
        "issueid": issueid,
        "command_kind": row.get("command_kind"),
        "updated_at": row.get("updated_at"),
    }


def _shape_journal_item(row):
    payload = _json_object(load_payload(row.get("payload_json")))
    issueid = _text(row.get("issueid")) or _text(payload.get("issueid"))
    return {
        "kind": "journal",
        "release_key": row.get("release_key"),
        "stage": row.get("stage"),
        "label": _journal_item_label(row, payload),
        "issueid": issueid,
        "comicid": _text(payload.get("comicid")) or _text(payload.get("ComicID")),
        "provider": _text(row.get("provider")),
        "updated_at": row.get("updated_date"),
    }


def _in_flight_sort_key(item):
    identity = item.get("item_id") if item.get("kind") == "run" else item.get("release_key")
    return (item.get("updated_at") or "", item.get("kind") or "", str(identity or ""))


def list_in_flight_items():
    """Return the same rows ``get_open_work_counts()['in_flight']`` counts.

    Membership is the count predicates — accepted|running run items plus
    OPEN_STAGES journal rows. Each item carries a stable identity (``kind``
    plus ``item_id`` or ``release_key``) so a later cancel can target a row
    without inventing a second list (#676 / #677).
    """
    run_rows = db.select_all(
        select(acquisition_run_items).where(acquisition_run_items.c.state.in_(IN_FLIGHT_ITEM_STATES))
    )
    journal_rows = db.select_all(select(pipeline_journal).where(pipeline_journal.c.stage.in_(OPEN_STAGES)))
    items = [_shape_run_item(row) for row in run_rows]
    items.extend(_shape_journal_item(row) for row in journal_rows)
    items.sort(key=_in_flight_sort_key, reverse=True)
    return items


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
    attention = read()
    return {
        "in_flight": count_in_flight_run_items() + count_open_journal_stages(),
        "recovery_pending": count_recovery_pending_run_items(),
        "attention": attention.total,
        "attention_members": attention.member_total,
    }
