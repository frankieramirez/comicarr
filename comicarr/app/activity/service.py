#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Activity Center read service — shapes query results for HTTP handlers."""

from comicarr.app.acquisition.models import ItemOutcome
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.activity import queries
from comicarr.app.activity.producers import emit_search_cancelled
from comicarr.app.attention import PREVIEW_CAP, Scope, read
from comicarr.app.attention._serialization import serialize_view
from comicarr.app.downloads import journal

ATTENTION_PREVIEW_CAP = PREVIEW_CAP


def get_timeline(limit=None, offset=None, scope_type=None, scope_id=None):
    """Paginated narrative timeline events (not pre-grouped stories)."""
    return queries.list_timeline_events(
        limit=limit,
        offset=offset,
        scope_type=scope_type,
        scope_id=scope_id,
    )


def get_attention_band(scope_type=None, scope_id=None):
    """Deprecated Activity adapter for the canonical Attention read interface."""
    normalized_type, normalized_id = queries._normalize_scope(scope_type, scope_id)
    scope = None
    if normalized_type is not None:
        scope = Scope(type=normalized_type, id=normalized_id)
    return serialize_view(read(scope=scope), preview_cap=ATTENTION_PREVIEW_CAP)


def get_status():
    """Open-work counts for the global quiet-counts status indicator."""
    return queries.get_open_work_counts()


def get_in_flight():
    """Rows counted as in-flight — same membership as ``get_status()['in_flight']``."""
    items = queries.list_in_flight_items()
    return {"results": items, "total": len(items)}


class InFlightCancelError(ValueError):
    """Operator cancel could not be applied to the named in-flight item."""

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def cancel_in_flight(kind, item_id=None, release_key=None):
    """Stop an in-flight run item or journal row into the existing cancelled state."""
    kind = str(kind or "").strip().lower()
    if kind == "run":
        if item_id in (None, ""):
            raise InFlightCancelError("item_id is required for a run item")
        ledger = RunLedger()
        try:
            item = ledger.get_item_by_id(item_id)
        except (TypeError, ValueError) as e:
            raise InFlightCancelError("item_id is invalid") from e
        if item is None:
            raise InFlightCancelError("in-flight item not found", status_code=404)
        current = ItemOutcome(item["state"])
        if current.terminal:
            raise InFlightCancelError("item is no longer in flight", status_code=409)
        ledger.record_outcome(
            item["run_id"],
            item["entity_type"],
            item["entity_id"],
            ItemOutcome.CANCELLED,
            reason="cancelled_by_operator",
        )
        try:
            emit_search_cancelled(
                item["entity_type"],
                item["entity_id"],
                label=item.get("entity_id"),
            )
        except Exception as e:
            from comicarr import logger

            logger.fdebug("[ACTIVITY] search.cancelled emit skipped: %s" % e)
        updated = ledger.get_item_by_id(item["item_id"])
        return {
            "ok": True,
            "kind": "run",
            "item_id": item["item_id"],
            "state": (updated or {}).get("state") or ItemOutcome.CANCELLED.value,
        }

    if kind == "journal":
        key = str(release_key or "").strip()
        if not key:
            raise InFlightCancelError("release_key is required for a journal item")
        row = journal.read_one(key)
        if row is None:
            raise InFlightCancelError("in-flight item not found", status_code=404)
        if journal.is_terminal(row.get("stage")):
            raise InFlightCancelError("item is no longer in flight", status_code=409)
        payload = journal.load_payload(row.get("payload_json"))
        won = journal.record_transition(
            key,
            journal.CANCELLED,
            payload=payload,
            issueid=row.get("issueid"),
            provider=row.get("provider"),
            downloader_type=row.get("downloader_type"),
        )
        if not won:
            raise InFlightCancelError("item is no longer in flight", status_code=409)
        return {
            "ok": True,
            "kind": "journal",
            "release_key": key,
            "state": journal.CANCELLED,
        }

    raise InFlightCancelError("kind must be run or journal")
