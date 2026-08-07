#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Validated, reconstructable commands consumed by the search worker."""

import uuid
from dataclasses import dataclass, replace
from typing import Any, Mapping

import comicarr
from comicarr.app.acquisition.models import DispatchState, ItemOutcome
from comicarr.app.acquisition.policy import EligibilityInput, evaluate_eligibility, project_legacy_state
from comicarr.app.search.queue import INTERACTIVE, RECOVERY, ROUTINE


class SearchCommandError(ValueError):
    """Raised when queued search work cannot be identified safely."""


def evaluate_search_candidate(candidate, *, release_date, digital_date, issue_date):
    """Apply the shared U8 eligibility policy to a database candidate."""
    values = {str(key).lower(): value for key, value in candidate.items()}
    projection = project_legacy_state(values.get("acquisitionintent"), values.get("legacystatus"))
    raw_series_status = values.get("seriesstatus")
    series_status = str(raw_series_status).strip().lower() if raw_series_status else None
    decision = evaluate_eligibility(
        EligibilityInput(
            # A missing series is retained only for legacy one-off story arcs.
            # Paused is recognized separately; only active/loading can pass.
            series_active=series_status is None or series_status in {"active", "loading", "paused"},
            paused=series_status == "paused",
            intent=projection.intent,
            fulfillment=projection.fulfillment,
            release_date=release_date,
            digital_date=digital_date,
            issue_date=issue_date,
        )
    )
    return {"status": decision.eligible, "reason": None if decision.eligible else decision.reason}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _required_text(values: Mapping[str, Any], key: str) -> str:
    value = _optional_text(values.get(key))
    if value is None:
        raise SearchCommandError("Missing required search field: %s" % key)
    return value


def _bool_value(value: Any, key: str) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"", "0", "false", "no", "off", "none"}:
            return False
        raise SearchCommandError("Invalid boolean search field: %s" % key)
    return bool(value)


def _entity_type(value: Any) -> str:
    normalized = str(value or "issue").strip().lower()
    if normalized not in {"issue", "annual"}:
        raise SearchCommandError("Invalid search entity type")
    return normalized


def _queue_priority(value: Any) -> str:
    priority = str(value or ROUTINE).strip().lower()
    if priority not in {INTERACTIVE, ROUTINE, RECOVERY}:
        raise SearchCommandError("Invalid search queue priority")
    return priority


def queue_priority_for_trigger(trigger: str, *, manual: bool = False) -> str:
    """Map durable intent to the in-memory fairness class."""
    if manual or str(trigger).strip().lower() in {
        "manual_wanted_scan",
        "search_all_missing",
        "issue_wanted",
        "storyarc_wanted",
        "band_retry",
        "band_search_again",
        "issue_retry",
    }:
        return INTERACTIVE
    return ROUTINE


@dataclass(frozen=True)
class SearchCommand:
    """The stable identity and display context for one issue search."""

    issueid: str
    comicid: str | None
    manual: bool = False
    run_id: str | None = None
    comicname: str | None = None
    seriesyear: str | None = None
    issuenumber: str | None = None
    booktype: str | None = None
    entity_type: str = "issue"
    queue_priority: str = ROUTINE

    @classmethod
    def from_mapping(cls, raw_values: Mapping[str, Any]) -> "SearchCommand":
        if not isinstance(raw_values, Mapping):
            raise SearchCommandError("Search command must be an object")

        values = {str(key).lower(): value for key, value in raw_values.items()}
        return cls(
            issueid=_required_text(values, "issueid"),
            comicid=_optional_text(values.get("comicid")),
            manual=_bool_value(values.get("manual", False), "manual"),
            run_id=_optional_text(values.get("run_id")),
            comicname=_optional_text(values.get("comicname")),
            seriesyear=_optional_text(values.get("seriesyear")),
            issuenumber=_optional_text(values.get("issuenumber") or values.get("issue_number")),
            booktype=_optional_text(values.get("booktype")),
            entity_type=_entity_type(
                values.get("entity_type")
                or ("annual" if _bool_value(values.get("annual", False), "annual") else "issue")
            ),
            queue_priority=_queue_priority(values.get("queue_priority")),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Return the bounded allowlisted payload safe to persist or requeue."""
        return {
            "issueid": self.issueid,
            "comicid": self.comicid,
            "manual": self.manual,
            "run_id": self.run_id,
            "comicname": self.comicname,
            "seriesyear": self.seriesyear,
            "issuenumber": self.issuenumber,
            "booktype": self.booktype,
            "entity_type": self.entity_type,
            "queue_priority": self.queue_priority,
        }

    def persisted_payload(self) -> dict[str, Any]:
        """Return the U8 allowlisted subset needed to replay this search."""
        return {
            "issueid": self.issueid,
            "comicid": self.comicid,
            "manual": self.manual,
            "comicname": self.comicname,
            "seriesyear": self.seriesyear,
            "issue_number": self.issuenumber,
            "entity_type": self.entity_type,
        }


def enqueue_search_command(
    raw_values,
    *,
    trigger,
    work_queue=None,
    ledger=None,
    run_id=None,
    maintenance=None,
    scope_type=None,
    scope_id=None,
):
    """Persist one search obligation before handing it to the in-memory queue."""
    from comicarr.app.acquisition.runs import RunLedger

    command = SearchCommand.from_mapping(raw_values)
    command = replace(command, queue_priority=queue_priority_for_trigger(trigger, manual=command.manual))
    effective_run_id = _optional_text(run_id) or command.run_id or str(uuid.uuid4())
    command = replace(command, run_id=effective_run_id)
    ledger = ledger or RunLedger()
    work_queue = work_queue or comicarr.SEARCH_QUEUE

    ledger.create_run(
        effective_run_id,
        command_kind="search",
        trigger=trigger,
        scope_type=scope_type or "issue",
        scope_id=scope_id or command.issueid,
    )
    ledger.accept_item(
        effective_run_id,
        entity_type=command.entity_type,
        entity_id=command.issueid,
        payload=command.persisted_payload(),
        queue_priority=command.queue_priority,
    )
    try:
        dispatch_persisted_search_command(command, work_queue=work_queue, maintenance=maintenance)
    except Exception as e:
        ledger.record_item_dispatch(
            effective_run_id,
            command.entity_type,
            command.issueid,
            DispatchState.ERROR,
            reason=type(e).__name__,
        )
        ledger.record_dispatch(effective_run_id, DispatchState.ERROR)
        raise
    ledger.record_item_dispatch(
        effective_run_id,
        command.entity_type,
        command.issueid,
        DispatchState.ACCEPTED,
    )
    ledger.record_dispatch(effective_run_id, DispatchState.ACCEPTED)
    return command


def enqueue_failed_download_retry(
    failure,
    *,
    work_queue=None,
    ledger=None,
    run_id=None,
    maintenance=None,
):
    """Persist and dispatch a manual retry from legacy failed-download data."""
    if not isinstance(failure, Mapping):
        raise SearchCommandError("Failed-download retry must be an object")

    values = {str(key).lower(): value for key, value in failure.items()}
    entity_type = "annual" if str(values.get("annchk", "no")).strip().lower() != "no" else "issue"
    return enqueue_search_command(
        {
            "issueid": values.get("issueid"),
            "comicid": values.get("comicid"),
            "comicname": values.get("comicname"),
            "issuenumber": values.get("issuenumber"),
            "manual": True,
            "entity_type": entity_type,
        },
        trigger="failed_download_retry",
        work_queue=work_queue,
        ledger=ledger,
        run_id=run_id,
        maintenance=maintenance,
        scope_type=entity_type,
        scope_id=values.get("issueid"),
    )


def _put_with_maintenance_lease(command, work_queue, maintenance=None):
    from comicarr.app.acquisition.maintenance import MaintenanceController

    controller = maintenance or MaintenanceController()
    with controller.lease(
        "search-producer",
        work_kind="search_queue_handoff",
        entity_type=command.entity_type,
        entity_id=command.issueid,
    ) as lease:
        controller.assert_lease_current(lease)
        work_queue.put(command.to_mapping())


def dispatch_persisted_search_command(command, *, work_queue=None, maintenance=None):
    """Hand off an already-ledgered command without creating a second item.

    Bulk confirmation persists all source and ledger changes in one database
    transaction before it touches the in-memory queue.  Reusing this boundary
    keeps that flow subject to the same maintenance fence as ordinary search
    producers while avoiding a second ``accept_item`` call during a browser
    retry.
    """

    work_queue = work_queue or comicarr.SEARCH_QUEUE
    _put_with_maintenance_lease(command, work_queue, maintenance)


def dispatch_pending_search_commands(run_id, *, work_queue=None, ledger=None, maintenance=None):
    """Dispatch only durable search items that were never handed to a worker.

    The row-level dispatch state prevents an idempotent browser retry from
    enqueuing an already accepted item while its original worker may be
    running. A crash after ``Queue.put`` is still safe because worker claiming
    is compare-and-set, and a later process restart reconciles that boundary.
    """

    from comicarr.app.acquisition.runs import RunLedger

    ledger = ledger or RunLedger()
    run = ledger.get_run(run_id)
    if run is None:
        raise KeyError("unknown acquisition run %s" % run_id)
    work_queue = work_queue or comicarr.SEARCH_QUEUE
    dispatched = 0
    errors = []
    for item in ledger.list_pending_dispatch_items(run_id):
        entity_type = item["entity_type"]
        entity_id = item["entity_id"]
        if not ledger.claim_item_dispatch(run_id, entity_type, entity_id):
            continue
        try:
            command = SearchCommand.from_mapping(
                {**(item["payload"] or {}), "run_id": run_id, "entity_type": entity_type}
            )
            command = replace(command, queue_priority=queue_priority_for_trigger(run["trigger"], manual=command.manual))
            ledger.set_item_queue_priority(run_id, entity_type, entity_id, command.queue_priority)
        except SearchCommandError as e:
            ledger.record_outcome(run_id, entity_type, entity_id, ItemOutcome.QUARANTINED, reason=str(e))
            errors.append(type(e).__name__)
            continue
        try:
            dispatch_persisted_search_command(command, work_queue=work_queue, maintenance=maintenance)
        except Exception as e:
            ledger.record_item_dispatch(
                run_id,
                entity_type,
                entity_id,
                DispatchState.ERROR,
                reason=type(e).__name__,
            )
            errors.append(type(e).__name__)
            continue
        ledger.record_item_dispatch(run_id, entity_type, entity_id, DispatchState.ACCEPTED)
        dispatched += 1

    ledger.record_dispatch(run_id, DispatchState.ERROR if errors else DispatchState.ACCEPTED)
    return {"dispatched": dispatched, "errors": errors}


def replay_search_obligations(*, work_queue=None, ledger=None, maintenance=None):
    """Requeue accepted/running search items after a process restart."""
    from comicarr.app.acquisition.runs import RunLedger

    ledger = ledger or RunLedger()
    work_queue = work_queue or comicarr.SEARCH_QUEUE
    replayed = 0
    for item in ledger.list_recoverable_items("search"):
        run_id = item["run_id"]
        entity_id = item["entity_id"]
        # Bound the re-drive before doing any work: an item that has survived
        # MAX_RECOVERY_ATTEMPTS restarts without terminalising is stuck, not
        # interrupted, and claim_recovery quarantines it instead (#555).
        if not ledger.claim_recovery(item):
            continue
        try:
            command = SearchCommand.from_mapping(
                {**(item["payload"] or {}), "run_id": run_id, "entity_type": item["entity_type"]}
            )
            command = replace(command, queue_priority=RECOVERY)
            ledger.set_item_queue_priority(run_id, item["entity_type"], entity_id, command.queue_priority)
        except SearchCommandError as e:
            ledger.record_outcome(run_id, item["entity_type"], entity_id, ItemOutcome.QUARANTINED, reason=str(e))
            continue
        if item["state"] == ItemOutcome.RUNNING.value:
            ledger.record_requeue(run_id, item["entity_type"], entity_id, reason="worker restart", replay=True)
        _put_with_maintenance_lease(command, work_queue, maintenance)
        ledger.record_item_dispatch(run_id, item["entity_type"], entity_id, DispatchState.ACCEPTED)
        ledger.record_dispatch(run_id, DispatchState.ACCEPTED)
        replayed += 1
    return replayed
