#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Activity Center write facade — sole legal writer of ``activity_events``.

Producers call :func:`record_activity` (and, when they own the transaction,
:func:`publish_activity` after commit). Do not insert into ``activity_events``
directly and do not call ``event_bus.publish_sync("activity", …)`` elsewhere.

Contract (Activity Center ADR §7 / #479):

* When ``conn`` is supplied, the insert co-commits in the caller's transaction
  and this module does **not** publish. The caller publishes after their
  commit succeeds (Core has no after-commit hook). Insert failures propagate
  so the caller can roll back the transaction they own.
* When ``conn`` is omitted, this module owns a short transaction, commits, then
  publishes best-effort. Insert failures are logged and swallowed (``None``).
* Journal-backed producers pass ``won`` from ``record_transition``; ``won=False``
  is a full no-op (no insert, no publish) so concurrent losers stay silent.
* Illegal ``(activity, status, subject_type)`` cells and missing ``reason_code``
  when severity ≠ ``normal`` are rejected (no-op + warning).
* Publish never announces a row that is not durable.
"""

from __future__ import annotations

import datetime

from sqlalchemy import insert

from comicarr import logger
from comicarr.app.core.runtime import get_runtime_if_initialized
from comicarr.db import get_engine
from comicarr.tables import activity_events

ACTIVITIES = frozenset({"search", "grab", "download", "import", "refresh", "add", "tag"})

STATUSES = frozenset(
    {
        "started",
        "succeeded",
        "no_match",
        "cancelled",
        "failed",
        "blocked",
        "needs_attention",
    }
)

SUBJECT_TYPES = frozenset({"issue", "annual", "series", "arc", "run"})

_SEVERITY_BY_STATUS = {
    "started": "normal",
    "succeeded": "normal",
    "no_match": "normal",
    "cancelled": "normal",
    "failed": "action_required",
    "blocked": "action_required",
    "needs_attention": "action_required",
}

ACTION_REQUIRED_STATUSES = frozenset(status for status, severity in _SEVERITY_BY_STATUS.items() if severity != "normal")

_RELEASE_KEY_ACTIVITIES = frozenset({"download", "import"})

LEGAL_CELLS = frozenset(
    {
        ("search", "started", "run"),
        ("search", "succeeded", "run"),
        ("search", "cancelled", "issue"),
        ("search", "cancelled", "annual"),
        ("search", "failed", "issue"),
        ("search", "failed", "annual"),
        ("search", "blocked", "issue"),
        ("search", "blocked", "annual"),
        ("search", "needs_attention", "issue"),
        ("search", "needs_attention", "annual"),
        ("grab", "succeeded", "issue"),
        ("grab", "succeeded", "annual"),
        ("grab", "failed", "issue"),
        ("grab", "failed", "annual"),
        ("grab", "blocked", "issue"),
        ("grab", "blocked", "annual"),
        ("grab", "cancelled", "issue"),
        ("grab", "cancelled", "annual"),
        ("grab", "cancelled", "series"),
        ("download", "succeeded", "issue"),
        ("download", "succeeded", "annual"),
        ("download", "failed", "issue"),
        ("download", "failed", "annual"),
        ("download", "cancelled", "issue"),
        ("download", "cancelled", "annual"),
        ("import", "started", "issue"),
        ("import", "started", "annual"),
        ("import", "succeeded", "issue"),
        ("import", "succeeded", "annual"),
        ("import", "failed", "issue"),
        ("import", "failed", "annual"),
        ("import", "needs_attention", "issue"),
        ("import", "needs_attention", "annual"),
        ("import", "cancelled", "issue"),
        ("import", "cancelled", "annual"),
        ("refresh", "started", "series"),
        ("refresh", "started", "issue"),
        ("refresh", "started", "arc"),
        ("refresh", "succeeded", "series"),
        ("refresh", "succeeded", "issue"),
        ("refresh", "succeeded", "arc"),
        ("refresh", "failed", "series"),
        ("refresh", "failed", "issue"),
        ("refresh", "failed", "arc"),
        ("add", "started", "series"),
        ("add", "started", "arc"),
        ("add", "succeeded", "series"),
        ("add", "succeeded", "arc"),
        ("add", "failed", "series"),
        ("add", "failed", "arc"),
        ("tag", "started", "issue"),
        ("tag", "started", "series"),
        ("tag", "succeeded", "issue"),
        ("tag", "succeeded", "series"),
        ("tag", "failed", "issue"),
        ("tag", "failed", "series"),
        ("tag", "needs_attention", "issue"),
        ("tag", "needs_attention", "series"),
    }
)

SSE_EVENT_TYPE = "activity"

_PAYLOAD_KEYS = (
    "event_id",
    "created_at",
    "activity",
    "status",
    "subject_type",
    "subject_id",
    "subject_label",
    "reason_code",
    "reason_detail",
    "provider",
    "run_id",
    "release_key",
    "parent_series_id",
    "scope_type",
    "scope_id",
)


def severity_for(status: str) -> str:
    """Return the severity rung for ``status`` (pure function; not stored)."""
    return _SEVERITY_BY_STATUS.get(status, "action_required")


def is_legal_cell(activity: str, status: str, subject_type: str) -> bool:
    """True iff ``(activity, status, subject_type)`` is a narratable cell."""
    return (activity, status, subject_type) in LEGAL_CELLS


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _validate(
    activity: str,
    status: str,
    subject_type: str,
    *,
    reason_code,
    release_key,
    run_id,
    provider,
    scope_type,
    scope_id,
) -> str | None:
    """Return a rejection reason string, or None if the write is allowed."""
    if activity not in ACTIVITIES:
        return "unknown activity %r" % (activity,)
    if status not in STATUSES:
        return "unknown status %r" % (status,)
    if subject_type not in SUBJECT_TYPES:
        return "unknown subject_type %r" % (subject_type,)
    if not is_legal_cell(activity, status, subject_type):
        return "illegal cell (%s, %s, %s)" % (activity, status, subject_type)
    if severity_for(status) != "normal" and not reason_code:
        return "reason_code required when severity is not normal (status=%s)" % status
    if activity in _RELEASE_KEY_ACTIVITIES and not release_key:
        return "release_key required for activity %r" % (activity,)
    if run_id and activity != "search":
        return "run_id is only valid for activity 'search'"
    if activity == "grab" and not provider:
        return "provider required for activity 'grab'"
    if (scope_type or scope_id) and subject_type != "run":
        return "scope_type/scope_id are only valid when subject_type is 'run'"
    if (scope_type is None) != (scope_id is None):
        return "scope_type and scope_id must be provided together"
    return None


def _row_payload(event_id, created_at, values: dict) -> dict:
    payload = {"event_id": event_id, "created_at": created_at}
    payload.update(values)
    return {key: payload.get(key) for key in _PAYLOAD_KEYS}


def _insert_row(conn, values: dict) -> dict:
    """Insert one narrative row on ``conn`` and return the typed payload."""
    created_at = values.get("created_at") or _now_iso()
    insert_values = dict(values)
    insert_values["created_at"] = created_at
    result = conn.execute(insert(activity_events).values(**insert_values))
    event_id = result.inserted_primary_key[0]
    return _row_payload(event_id, created_at, insert_values)


def publish_activity(payload: dict | None) -> bool:
    """Best-effort ``activity`` SSE publish of an already-durable row.

    Never raises. Returns True only when ``publish_sync`` was invoked and
    returned truthy. Refuses empty payloads so a missing row is never announced.
    """
    if not payload or not payload.get("event_id"):
        return False
    try:
        ctx = get_runtime_if_initialized()
        event_bus = getattr(ctx, "event_bus", None) if ctx is not None else None
        if event_bus is None:
            return False
        typed = {key: payload.get(key) for key in _PAYLOAD_KEYS}
        return bool(event_bus.publish_sync(SSE_EVENT_TYPE, typed))
    except Exception as e:
        logger.fdebug("[ACTIVITY] publish failed (best-effort): %s" % e)
        return False


def record_activity(
    activity: str,
    status: str,
    subject_type: str,
    subject_id: str,
    subject_label: str,
    *,
    reason_code: str | None = None,
    reason_detail: str | None = None,
    provider: str | None = None,
    run_id: str | None = None,
    release_key: str | None = None,
    parent_series_id: str | None = None,
    scope_type: str | None = None,
    scope_id: str | None = None,
    conn=None,
    won: bool = True,
    created_at: str | None = None,
) -> dict | None:
    """Insert a narrative activity row and publish after durable commit.

    Parameters
    ----------
    conn:
        Optional caller-owned SQLAlchemy connection. When provided, the insert
        joins that transaction and **publish is left to the caller** after their
        commit (call :func:`publish_activity` with the returned payload). Insert
        failures **propagate** on this path so the caller can roll back; only
        the owned-transaction path (``conn=None``) swallows them.
    won:
        Journal-backed gate. Pass ``record_transition``'s return value. When
        False, this is a full no-op (no insert, no publish).
    """
    if not won:
        return None

    if not subject_id or not subject_label:
        logger.warn("[ACTIVITY] rejected write: subject_id and subject_label are required")
        return None

    rejection = _validate(
        activity,
        status,
        subject_type,
        reason_code=reason_code,
        release_key=release_key,
        run_id=run_id,
        provider=provider,
        scope_type=scope_type,
        scope_id=scope_id,
    )
    if rejection is not None:
        logger.warn("[ACTIVITY] rejected write: %s" % rejection)
        return None

    values = {
        "activity": activity,
        "status": status,
        "subject_type": subject_type,
        "subject_id": str(subject_id),
        "subject_label": subject_label,
        "reason_code": reason_code,
        "reason_detail": reason_detail,
        "provider": provider,
        "run_id": run_id,
        "release_key": release_key,
        "parent_series_id": parent_series_id,
        "scope_type": scope_type,
        "scope_id": scope_id,
    }
    if created_at is not None:
        values["created_at"] = created_at

    if conn is not None:
        return _insert_row(conn, values)

    try:
        engine = get_engine()
        with engine.begin() as owned_conn:
            payload = _insert_row(owned_conn, values)
        publish_activity(payload)
        return payload
    except Exception as e:
        logger.error("[ACTIVITY] failed to record activity: %s" % e)
        return None
