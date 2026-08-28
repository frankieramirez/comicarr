#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Durable preview/confirm boundary for series-scoped Search all missing."""

import datetime
import hashlib
import hmac
import json
import secrets
import uuid

from sqlalchemy import delete, insert, select, update

from comicarr.app.acquisition.models import DispatchState, ItemOutcome, RunState
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.search.commands import SearchCommand, dispatch_pending_search_commands
from comicarr.tables import (
    acquisition_run_items,
    acquisition_runs,
    acquisition_search_previews,
    annuals,
    issues,
)

PREVIEW_TTL_SECONDS = 15 * 60
MAX_SELECTION_BYTES = 256 * 1024
_SOURCE_TABLES = {"issue": issues, "annual": annuals}


class SearchMissingError(RuntimeError):
    """Base class for safe bulk-search confirmation failures."""


class SearchMissingConfirmationError(SearchMissingError):
    """A preview token is invalid, expired, or owned by another session."""


class SearchMissingStalePreview(SearchMissingError):
    """The source state changed after its read-only preview."""


def _now(value=None):
    value = value or datetime.datetime.now(datetime.timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def _iso(value=None):
    return _now(value).isoformat()


def _digest(value):
    return hashlib.sha256(str(value).encode("utf-8", "replace")).hexdigest()


def _encode(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_SELECTION_BYTES:
        raise SearchMissingError("bulk search selection exceeds the safe preview limit")
    return encoded


def _decode(value):
    try:
        result = json.loads(value)
    except (TypeError, ValueError) as e:
        raise SearchMissingError("stored bulk search preview is malformed") from e
    if not isinstance(result, list):
        raise SearchMissingError("stored bulk search preview is malformed")
    return result


def _value_predicate(column, value):
    return column.is_(None) if value is None else column == value


def selection_from_detail(detail):
    """Return canonical eligible source records for a projected series detail."""

    comic_rows = detail.get("comic") or []
    comic = comic_rows[0] if isinstance(comic_rows, list) and comic_rows else comic_rows
    if not comic:
        return []
    series_status = comic.get("Status")
    candidates = []
    for row in list(detail.get("issues") or []) + list(detail.get("annuals") or []):
        if not row.get("eligible") or row.get("owned") or row.get("inFlight"):
            continue
        entity_id = row.get("id") or row.get("issueId") or row.get("IssueID")
        if entity_id is None:
            continue
        entity_type = "annual" if row.get("annual") else "issue"
        candidates.append(
            {
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "issue_number": row.get("number") or row.get("issueNumber") or row.get("Issue_Number"),
                "source": {
                    "status": row.get("legacyStatus"),
                    "intent": row.get("rawAcquisitionIntent"),
                    "location": row.get("location") or row.get("Location"),
                    "release_date": row.get("releaseDate") or row.get("ReleaseDate"),
                    "digital_date": row.get("digitalDate") or row.get("DigitalDate"),
                    "issue_date": row.get("issueDate") or row.get("IssueDate"),
                    "series_status": series_status,
                },
            }
        )
    return sorted(candidates, key=lambda item: (item["entity_type"], item["entity_id"]))


def fingerprint(selection):
    return hashlib.sha256(_encode(selection).encode("utf-8")).hexdigest()


def create_preview(engine, *, series_id, actor, session_id, selection, now=None):
    """Persist a session-bound, one-shot preview for an already projected selection."""

    if not actor or not session_id:
        raise ValueError("bulk search preview requires an authenticated session")
    created = _now(now)
    token = secrets.token_urlsafe(32)
    preview_id = str(uuid.uuid4())
    selected_json = _encode(selection)
    selection_fingerprint = hashlib.sha256(selected_json.encode("utf-8")).hexdigest()
    with engine.begin() as conn:
        conn.execute(
            delete(acquisition_search_previews)
            .where(acquisition_search_previews.c.expires_at <= created.isoformat())
            .where(acquisition_search_previews.c.state == "previewed")
        )
        conn.execute(
            insert(acquisition_search_previews).values(
                preview_id=preview_id,
                series_id=str(series_id),
                actor_id=str(actor),
                session_digest=_digest(session_id),
                token_digest=_digest(token),
                fingerprint=selection_fingerprint,
                eligible_json=selected_json,
                state="previewed",
                run_id=None,
                created_at=created.isoformat(),
                expires_at=(created + datetime.timedelta(seconds=PREVIEW_TTL_SECONDS)).isoformat(),
                confirmed_at=None,
                updated_at=created.isoformat(),
            )
        )
    return {"preview_token": token, "fingerprint": selection_fingerprint}


def _read_preview(engine, token):
    with engine.connect() as conn:
        row = (
            conn.execute(
                select(acquisition_search_previews).where(acquisition_search_previews.c.token_digest == _digest(token))
            )
            .mappings()
            .first()
        )
    return dict(row) if row is not None else None


def _authorize_preview(row, *, actor, session_id, token, supplied_fingerprint, now):
    if row is None:
        raise SearchMissingConfirmationError("unknown bulk search preview")
    if row["actor_id"] != str(actor):
        raise SearchMissingConfirmationError("bulk search preview is owned by a different actor")
    if not hmac.compare_digest(_digest(session_id), row["session_digest"]):
        raise SearchMissingConfirmationError("bulk search preview is bound to a different session")
    if not hmac.compare_digest(_digest(token), row["token_digest"]):
        raise SearchMissingConfirmationError("invalid bulk search preview token")
    if not hmac.compare_digest(str(supplied_fingerprint or ""), row["fingerprint"]):
        raise SearchMissingConfirmationError("bulk search preview fingerprint does not match")
    if row["state"] != "accepted" and now > _now(datetime.datetime.fromisoformat(row["expires_at"])):
        raise SearchMissingConfirmationError("bulk search preview expired")


def read_preview(
    engine,
    *,
    actor,
    session_id,
    preview_token,
    supplied_fingerprint,
    now=None,
):
    """Authorize and return the minimal durable state for a confirmation retry."""

    row = _read_preview(engine, preview_token)
    _authorize_preview(
        row,
        actor=actor,
        session_id=session_id,
        token=preview_token,
        supplied_fingerprint=supplied_fingerprint,
        now=_now(now),
    )
    return {"series_id": row["series_id"], "state": row["state"], "run_id": row["run_id"]}


def _source_update_statement(item):
    table = _SOURCE_TABLES[item["entity_type"]]
    source = item["source"]
    statement = update(table).where(table.c.IssueID == item["entity_id"])
    for column_name, value in (
        ("Status", source.get("status")),
        ("AcquisitionIntent", source.get("intent")),
        ("Location", source.get("location")),
        ("ReleaseDate", source.get("release_date")),
        ("DigitalDate", source.get("digital_date")),
        ("IssueDate", source.get("issue_date")),
    ):
        if column_name in table.c:
            statement = statement.where(_value_predicate(table.c[column_name], value))
    if item["entity_type"] == "annual":
        statement = statement.where((table.c.Deleted.is_(None)) | (table.c.Deleted != 1))
    return statement.values(AcquisitionIntent="wanted", Status="Wanted")


def _create_run_values(run_id, series_id, now, *, trigger="search_all_missing", scope_type="series", scope_id=None):
    return {
        "run_id": run_id,
        "command_kind": "search",
        "trigger": trigger,
        "scope_type": scope_type,
        "scope_id": str(scope_id if scope_id is not None else series_id),
        "dispatch_state": DispatchState.PENDING.value,
        "completion_state": RunState.PENDING.value,
        "accepted_count": 0,
        "terminal_count": 0,
        "succeeded_count": 0,
        "no_match_count": 0,
        "blocked_count": 0,
        "failed_count": 0,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }


def _item_values(command, run_id, now):
    return {
        "run_id": run_id,
        "command_kind": "search",
        "entity_type": command.entity_type,
        "entity_id": command.issueid,
        "state": ItemOutcome.ACCEPTED.value,
        "dispatch_state": DispatchState.PENDING.value,
        "payload_json": _encode(command.persisted_payload()),
        "attempt_count": 0,
        "next_attempt_at": None,
        "reason": None,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }


def confirm_preview(
    engine,
    *,
    series_id,
    actor,
    session_id,
    preview_token,
    supplied_fingerprint,
    current_selection,
    work_queue=None,
    maintenance=None,
    now=None,
    trigger="search_all_missing",
    scope_type="series",
    scope_id=None,
):
    """Atomically create one source-intent + durable-run transaction.

    The in-memory handoff happens *after* the transaction. A process failure
    between those two boundaries leaves accepted rows for normal startup
    replay; a browser retry returns the same run instead of resubmitting.
    """

    now_value = _now(now)
    row = _read_preview(engine, preview_token)
    _authorize_preview(
        row,
        actor=actor,
        session_id=session_id,
        token=preview_token,
        supplied_fingerprint=supplied_fingerprint,
        now=now_value,
    )
    if row["series_id"] != str(series_id):
        raise SearchMissingConfirmationError("bulk search preview belongs to a different series")
    if row["state"] == "accepted":
        dispatch = dispatch_pending_search_commands(
            row["run_id"], work_queue=work_queue, ledger=RunLedger(engine), maintenance=maintenance
        )
        return {
            "run_id": row["run_id"],
            "accepted": len(_decode(row["eligible_json"])),
            "idempotent": True,
            "dispatch_error": dispatch["errors"][0] if dispatch["errors"] else None,
        }
    if row["state"] != "previewed":
        raise SearchMissingConfirmationError("bulk search preview was already consumed")
    current_fingerprint = fingerprint(current_selection)
    if not hmac.compare_digest(current_fingerprint, row["fingerprint"]):
        raise SearchMissingStalePreview("series acquisition state changed; create a fresh preview")

    selection = _decode(row["eligible_json"])
    run_id = str(uuid.uuid4())
    when = now_value.isoformat()
    commands = [
        SearchCommand.from_mapping(
            {
                "issueid": item["entity_id"],
                "comicid": str(series_id),
                "run_id": run_id,
                "entity_type": item["entity_type"],
            }
        )
        for item in selection
    ]
    idempotent = False
    with engine.begin() as conn:
        consumed = conn.execute(
            update(acquisition_search_previews)
            .where(acquisition_search_previews.c.preview_id == row["preview_id"])
            .where(acquisition_search_previews.c.state == "previewed")
            .where(acquisition_search_previews.c.token_digest == _digest(preview_token))
            .values(state="accepted", run_id=run_id, confirmed_at=when, updated_at=when)
        )
        if consumed.rowcount != 1:
            current = (
                conn.execute(
                    select(acquisition_search_previews).where(
                        acquisition_search_previews.c.preview_id == row["preview_id"]
                    )
                )
                .mappings()
                .first()
            )
            if current is not None and current["state"] == "accepted":
                run_id = current["run_id"]
                idempotent = True
            else:
                raise SearchMissingConfirmationError("bulk search preview was consumed concurrently")
        else:
            conn.execute(
                insert(acquisition_runs).values(
                    **_create_run_values(
                        run_id,
                        series_id,
                        when,
                        trigger=trigger,
                        scope_type=scope_type,
                        scope_id=scope_id,
                    )
                )
            )
            for item, command in zip(selection, commands, strict=True):
                if conn.execute(_source_update_statement(item)).rowcount != 1:
                    raise SearchMissingStalePreview("series acquisition state changed during confirmation")
                conn.execute(insert(acquisition_run_items).values(**_item_values(command, run_id, when)))

    ledger = RunLedger(engine)
    ledger.reconcile(run_id)
    dispatch = dispatch_pending_search_commands(run_id, work_queue=work_queue, ledger=ledger, maintenance=maintenance)
    return {
        "run_id": run_id,
        "accepted": len(selection),
        "idempotent": idempotent,
        "dispatch_error": dispatch["errors"][0] if dispatch["errors"] else None,
    }
