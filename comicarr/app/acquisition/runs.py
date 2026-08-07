#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""SQLAlchemy Core persistence for generic acquisition commands and items."""

import datetime
import json

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from comicarr import logger
from comicarr.app.acquisition.models import DispatchState, ItemOutcome, RunState
from comicarr.app.common.redaction import redact_sensitive_text
from comicarr.db import get_engine
from comicarr.tables import acquisition_run_items, acquisition_runs

MAX_PAYLOAD_BYTES = 16 * 1024

# How many times crash recovery may re-drive one non-terminal item before it is
# quarantined instead. Three restarts is generous for a genuinely interrupted
# obligation and decisive for a stuck one (#555).
MAX_RECOVERY_ATTEMPTS = 3
PAYLOAD_FIELDS = {
    "search": frozenset(
        {
            "comicid",
            "issueid",
            "comicname",
            "issue_number",
            "seriesyear",
            "mode",
            "manual",
            "annual",
            "entity_type",
            "storyarc",
        }
    ),
    "refresh": frozenset(
        {
            "comicid",
            "comicname",
            "seriesyear",
            "r_mode",
            "calledfrom",
            "serieslast_updated",
            "manual_comicid",
        }
    ),
}


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _value(value):
    return value.value if hasattr(value, "value") else str(value)


def _redact_reason(reason):
    """Persist operator-visible reasons through the canonical redactor (#430 A2)."""
    if reason in (None, ""):
        return None
    return redact_sensitive_text(str(reason))[:1000]


def is_retry_pending(item):
    """True when an item is awaiting another attempt (retry guard, #430 A1).

    Discriminator: state is ACCEPTED and attempt_count > 0. ``next_attempt_at``
    is never written; this is the only honest "retry pending" signal.
    """
    if not item:
        return False
    try:
        attempts = int(item.get("attempt_count") or 0)
    except (TypeError, ValueError):
        attempts = 0
    return item.get("state") == ItemOutcome.ACCEPTED.value and attempts > 0


def _emit_run_completion_safe(run):
    """Best-effort search run bracket; never raises into the ledger path."""
    try:
        from comicarr.app.activity.producers import emit_run_completion

        emit_run_completion(run)
    except Exception as e:
        from comicarr import logger

        logger.fdebug("[ACTIVITY] run completion emit skipped: %s" % e)


def _row_dict(row):
    return dict(row._mapping) if row is not None else None


def _payload_json(command_kind, payload):
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("acquisition payload must be a dictionary")
    allowed = PAYLOAD_FIELDS.get(command_kind)
    if allowed is None:
        raise ValueError("payloads are not enabled for command kind %s" % command_kind)
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise ValueError("payload contains non-allowlisted fields: %s" % ", ".join(unexpected))
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise ValueError("acquisition payload must be JSON serializable") from e
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("acquisition payload exceeds %s bytes" % MAX_PAYLOAD_BYTES)
    return encoded


def _decode_payload(encoded):
    return json.loads(encoded) if encoded else None


class RunLedger:
    """Durable run/item owner shared by refresh, search, and later adapters."""

    def __init__(self, engine=None):
        self.engine = engine or get_engine()

    def create_run(self, run_id, command_kind, trigger, scope_type=None, scope_id=None):
        command_kind = str(command_kind).strip().lower()
        if not run_id or not command_kind or not trigger:
            raise ValueError("run_id, command_kind, and trigger are required")
        now = _utcnow()
        values = {
            "run_id": str(run_id),
            "command_kind": command_kind,
            "trigger": str(trigger),
            "scope_type": str(scope_type) if scope_type is not None else None,
            "scope_id": str(scope_id) if scope_id is not None else None,
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
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(acquisition_runs).values(**values))
        except IntegrityError:
            existing = self.get_run(run_id)
            immutable = ("command_kind", "trigger", "scope_type", "scope_id")
            if existing is None or any(existing[key] != values[key] for key in immutable):
                raise ValueError("run_id already belongs to a different acquisition command") from None
        return self.get_run(run_id)

    def get_run(self, run_id):
        with self.engine.connect() as conn:
            row = conn.execute(select(acquisition_runs).where(acquisition_runs.c.run_id == str(run_id))).first()
        return _row_dict(row)

    def _require_run(self, run_id):
        run = self.get_run(run_id)
        if run is None:
            raise KeyError("unknown acquisition run %s" % run_id)
        return run

    def accept_item(self, run_id, entity_type, entity_id, payload=None, command_kind=None, queue_priority="routine"):
        run = self._require_run(run_id)
        if run["completion_state"] not in {RunState.PENDING.value, RunState.RUNNING.value}:
            raise ValueError("terminal acquisition runs cannot accept new items")
        effective_kind = str(command_kind or run["command_kind"]).strip().lower()
        if effective_kind != run["command_kind"]:
            raise ValueError("item command_kind must match its acquisition run")
        encoded = _payload_json(effective_kind, payload)
        now = _utcnow()
        values = {
            "run_id": str(run_id),
            "command_kind": effective_kind,
            "entity_type": str(entity_type),
            "entity_id": str(entity_id),
            "state": ItemOutcome.ACCEPTED.value,
            "dispatch_state": DispatchState.PENDING.value,
            "queue_priority": str(queue_priority),
            "payload_json": encoded,
            "attempt_count": 0,
            "recovery_count": 0,
            "next_attempt_at": None,
            "reason": None,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
        }
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(acquisition_run_items).values(**values))
        except IntegrityError:
            existing = self.get_item(run_id, entity_type, entity_id)
            if existing is None:
                raise
            if encoded is not None and existing["payload_json"] not in (None, encoded):
                raise ValueError("accepted acquisition item payload is immutable") from None
            if existing["payload_json"] is None and encoded is not None:
                with self.engine.begin() as conn:
                    conn.execute(
                        update(acquisition_run_items)
                        .where(acquisition_run_items.c.item_id == existing["item_id"])
                        .where(
                            acquisition_run_items.c.state.in_([ItemOutcome.ACCEPTED.value, ItemOutcome.RUNNING.value])
                        )
                        .values(payload_json=encoded, updated_at=now)
                    )
        self.reconcile(run_id)
        return self.get_item(run_id, entity_type, entity_id)

    def set_item_queue_priority(self, run_id, entity_type, entity_id, queue_priority):
        item = self.get_item(run_id, entity_type, entity_id)
        if item is None:
            raise KeyError("unknown acquisition item")
        with self.engine.begin() as conn:
            conn.execute(
                update(acquisition_run_items)
                .where(acquisition_run_items.c.item_id == item["item_id"])
                .where(acquisition_run_items.c.state.in_([ItemOutcome.ACCEPTED.value, ItemOutcome.RUNNING.value]))
                .values(queue_priority=str(queue_priority), updated_at=_utcnow())
            )
        return self.get_item(run_id, entity_type, entity_id)

    def get_item(self, run_id, entity_type, entity_id):
        run = self._require_run(run_id)
        stmt = select(acquisition_run_items).where(
            acquisition_run_items.c.run_id == str(run_id),
            acquisition_run_items.c.command_kind == run["command_kind"],
            acquisition_run_items.c.entity_type == str(entity_type),
            acquisition_run_items.c.entity_id == str(entity_id),
        )
        with self.engine.connect() as conn:
            row = conn.execute(stmt).first()
        return _row_dict(row)

    def record_dispatch(self, run_id, state):
        self._require_run(run_id)
        state = DispatchState(_value(state))
        with self.engine.begin() as conn:
            conn.execute(
                update(acquisition_runs)
                .where(acquisition_runs.c.run_id == str(run_id))
                .values(dispatch_state=state.value, updated_at=_utcnow())
            )
        return self.get_run(run_id)

    def record_item_dispatch(self, run_id, entity_type, entity_id, state, reason=None):
        """Record queue handoff separately from the item's worker outcome."""

        item = self.get_item(run_id, entity_type, entity_id)
        if item is None:
            raise KeyError("unknown acquisition item")
        state = DispatchState(_value(state))
        if state not in {DispatchState.PENDING, DispatchState.ACCEPTED, DispatchState.ERROR}:
            raise ValueError("invalid acquisition item dispatch state")
        with self.engine.begin() as conn:
            result = conn.execute(
                update(acquisition_run_items)
                .where(acquisition_run_items.c.item_id == item["item_id"])
                .where(acquisition_run_items.c.state.in_([ItemOutcome.ACCEPTED.value, ItemOutcome.RUNNING.value]))
                .values(
                    dispatch_state=state.value,
                    reason=str(reason)[:1000] if reason else None,
                    updated_at=_utcnow(),
                )
            )
        if result.rowcount != 1:
            # Queue.put can hand the item to a very fast worker before the
            # producer writes its accepted handoff marker. The terminal
            # worker result is stronger evidence than that marker, so leave
            # it untouched instead of turning a successful handoff into an
            # API error.
            current = self.get_item(run_id, entity_type, entity_id)
            if current is not None and ItemOutcome(current["state"]).terminal:
                return current
            raise ValueError("acquisition item changed before dispatch state could be recorded")
        return self.get_item(run_id, entity_type, entity_id)

    def claim_item_dispatch(self, run_id, entity_type, entity_id):
        """Reserve one pending handoff so concurrent redrives cannot duplicate it."""
        item = self.get_item(run_id, entity_type, entity_id)
        if item is None:
            raise KeyError("unknown acquisition item")
        with self.engine.begin() as conn:
            result = conn.execute(
                update(acquisition_run_items)
                .where(acquisition_run_items.c.item_id == item["item_id"])
                .where(acquisition_run_items.c.state == ItemOutcome.ACCEPTED.value)
                .where(
                    acquisition_run_items.c.dispatch_state.in_([DispatchState.PENDING.value, DispatchState.ERROR.value])
                )
                .values(dispatch_state=DispatchState.ACCEPTED.value, updated_at=_utcnow())
            )
        return result.rowcount == 1

    def complete_empty_run(
        self,
        run_id,
        *,
        completion_state=RunState.COMPLETED,
        dispatch_state=DispatchState.ACCEPTED,
    ):
        """Close an intentionally empty manual/scheduled scan truthfully.

        A scan that found no eligible obligations still needs a durable run ID
        for the operator, but must not pretend that an item was accepted or
        that a provider was consulted. Empty runs therefore retain zero item
        counters and close to an explicit completed or failed scan result
        rather than a fabricated ``no_match`` item.
        """

        self._require_run(run_id)
        completion_state = RunState(_value(completion_state))
        dispatch_state = DispatchState(_value(dispatch_state))
        if completion_state in {RunState.PENDING, RunState.RUNNING}:
            raise ValueError("empty acquisition runs must close to a terminal state")
        with self.engine.begin() as conn:
            item_count = conn.execute(
                select(func.count())
                .select_from(acquisition_run_items)
                .where(acquisition_run_items.c.run_id == str(run_id))
            ).scalar_one()
            if item_count:
                raise ValueError("only runs without accepted items can be completed as empty")
            now = _utcnow()
            conn.execute(
                update(acquisition_runs)
                .where(acquisition_runs.c.run_id == str(run_id))
                .values(
                    dispatch_state=dispatch_state.value,
                    completion_state=completion_state.value,
                    updated_at=now,
                    completed_at=now,
                )
            )
        run = self.get_run(run_id)
        _emit_run_completion_safe(run)
        return run

    def claim_item(self, run_id, entity_type, entity_id):
        item = self.get_item(run_id, entity_type, entity_id)
        if item is None:
            raise KeyError("unknown acquisition item")
        if item["state"] != ItemOutcome.ACCEPTED.value:
            return False
        now = _utcnow()
        with self.engine.begin() as conn:
            result = conn.execute(
                update(acquisition_run_items)
                .where(acquisition_run_items.c.item_id == item["item_id"])
                .where(acquisition_run_items.c.state == ItemOutcome.ACCEPTED.value)
                .values(
                    state=ItemOutcome.RUNNING.value,
                    attempt_count=acquisition_run_items.c.attempt_count + 1,
                    next_attempt_at=None,
                    updated_at=now,
                )
            )
        return result.rowcount == 1

    def record_requeue(self, run_id, entity_type, entity_id, reason, next_attempt_at=None, *, replay=False):
        """Re-accept a non-terminal item after a fault (or crash-replay).

        ``replay=True`` marks crash-recovery requeues (worker restart). Any
        future narrative producer **must** skip when the returned item has
        ``replay=True`` so restarts are not reported as retries (#430 A4).
        The flag is not a DB column — it is returned on the item dict only.
        Degraded/retrying never narrates today; the flag still makes the
        call-site decision greppable and enforceable.
        """
        item = self.get_item(run_id, entity_type, entity_id)
        if item is None:
            raise KeyError("unknown acquisition item")
        current = ItemOutcome(item["state"])
        if current.terminal:
            raise ValueError("terminal acquisition items cannot be requeued implicitly")
        safe_reason = _redact_reason(reason)
        with self.engine.begin() as conn:
            conn.execute(
                update(acquisition_run_items)
                .where(acquisition_run_items.c.item_id == item["item_id"])
                .values(
                    state=ItemOutcome.ACCEPTED.value,
                    reason=safe_reason,
                    next_attempt_at=next_attempt_at,
                    updated_at=_utcnow(),
                )
            )
        self.reconcile(run_id)
        updated = self.get_item(run_id, entity_type, entity_id)
        if updated is not None:
            # Transient call-site contract — not persisted (#430 A4).
            updated["replay"] = bool(replay)
        return updated

    def record_outcome(self, run_id, entity_type, entity_id, outcome, reason=None):
        item = self.get_item(run_id, entity_type, entity_id)
        if item is None:
            raise KeyError("unknown acquisition item")
        outcome = ItemOutcome(_value(outcome))
        if not outcome.terminal:
            raise ValueError("record_outcome requires a terminal item outcome")
        current = ItemOutcome(item["state"])
        if current.terminal and current is not outcome:
            raise ValueError("terminal acquisition outcome cannot be replaced")
        if current is not outcome:
            now = _utcnow()
            safe_reason = _redact_reason(reason)
            with self.engine.begin() as conn:
                conn.execute(
                    update(acquisition_run_items)
                    .where(acquisition_run_items.c.item_id == item["item_id"])
                    .where(acquisition_run_items.c.state.in_([ItemOutcome.ACCEPTED.value, ItemOutcome.RUNNING.value]))
                    .values(
                        state=outcome.value,
                        reason=safe_reason,
                        next_attempt_at=None,
                        updated_at=now,
                        completed_at=now,
                    )
                )
        return self.reconcile(run_id)

    def list_recoverable_items(self, command_kind=None):
        stmt = (
            select(acquisition_run_items)
            .where(acquisition_run_items.c.state.in_([ItemOutcome.ACCEPTED.value, ItemOutcome.RUNNING.value]))
            .order_by(acquisition_run_items.c.item_id)
        )
        if command_kind is not None:
            stmt = stmt.where(acquisition_run_items.c.command_kind == str(command_kind).strip().lower())
        with self.engine.connect() as conn:
            rows = [dict(row._mapping) for row in conn.execute(stmt)]
        for row in rows:
            row["payload"] = _decode_payload(row["payload_json"])
        return rows

    def claim_recovery(self, item):
        """Count one crash-recovery re-drive, or reap the item if it is spent.

        Replay is a re-driver, not a reaper: it faithfully re-queues every
        non-terminal item, which is correct for an obligation interrupted by a
        restart and useless for one that cannot make progress at all. Without a
        bound the second kind is replayed forever and reported as in-flight
        work — the residue behind the "940 in flight" number (#555).

        The bound counts **restarts, not time**. A clock cannot tell a stuck
        item from one queued behind a long backlog; surviving
        ``MAX_RECOVERY_ATTEMPTS`` restarts without ever reaching a terminal
        outcome can only mean stuck.

        Returns True when the caller should re-drive the item, False when this
        call terminalised it as ``quarantined``.
        """
        run_id = item["run_id"]
        entity_type = item["entity_type"]
        entity_id = item["entity_id"]
        try:
            recovered = int(item.get("recovery_count") or 0)
        except (TypeError, ValueError):
            recovered = 0

        if recovered >= MAX_RECOVERY_ATTEMPTS:
            self.record_outcome(
                run_id,
                entity_type,
                entity_id,
                ItemOutcome.QUARANTINED,
                reason="recovery_attempts_exhausted",
            )
            logger.warn(
                "[ACQUISITION] %s %s/%s quarantined after %s crash recoveries without "
                "reaching a terminal outcome (#555)." % (item["command_kind"], entity_type, entity_id, recovered)
            )
            return False

        now = _utcnow()
        with self.engine.begin() as conn:
            conn.execute(
                update(acquisition_run_items)
                .where(acquisition_run_items.c.item_id == item["item_id"])
                .values(
                    recovery_count=acquisition_run_items.c.recovery_count + 1,
                    updated_at=now,
                )
            )
        return True

    def count_recovery_pending(self):
        """Non-terminal items that have already survived at least one restart.

        Separating these from the raw in-flight total is what makes the health
        number readable: "N in flight (K recovered from a restart)" says
        something an operator can act on, where one opaque number did not.
        """
        stmt = (
            select(func.count().label("item_count"))
            .select_from(acquisition_run_items)
            .where(acquisition_run_items.c.state.in_([ItemOutcome.ACCEPTED.value, ItemOutcome.RUNNING.value]))
            .where(acquisition_run_items.c.recovery_count > 0)
        )
        with self.engine.connect() as conn:
            return int(conn.execute(stmt).scalar() or 0)

    def list_pending_dispatch_items(self, run_id):
        """Return accepted items that have not reached the worker queue."""

        run = self._require_run(run_id)
        with self.engine.connect() as conn:
            rows = [
                _row_dict(row)
                for row in conn.execute(
                    select(acquisition_run_items)
                    .where(acquisition_run_items.c.run_id == str(run_id))
                    .where(acquisition_run_items.c.command_kind == run["command_kind"])
                    .where(acquisition_run_items.c.state == ItemOutcome.ACCEPTED.value)
                    .where(
                        acquisition_run_items.c.dispatch_state.in_(
                            [DispatchState.PENDING.value, DispatchState.ERROR.value]
                        )
                    )
                    .order_by(acquisition_run_items.c.item_id)
                )
            ]
        for row in rows:
            row["payload"] = _decode_payload(row["payload_json"])
        return rows

    def list_items(self, run_id):
        """Return the bounded, sanitized item outcomes for one durable run."""
        run = self._require_run(run_id)
        with self.engine.connect() as conn:
            rows = [
                _row_dict(row)
                for row in conn.execute(
                    select(acquisition_run_items)
                    .where(acquisition_run_items.c.run_id == str(run_id))
                    .where(acquisition_run_items.c.command_kind == run["command_kind"])
                    .order_by(acquisition_run_items.c.item_id)
                )
            ]
        for row in rows:
            row["payload"] = _decode_payload(row.pop("payload_json", None))
        return rows

    def reconcile(self, run_id):
        self._require_run(run_id)
        previous = self.get_run(run_id)
        previous_completion = str(previous.get("completion_state") or "") if previous else ""
        with self.engine.begin() as conn:
            counts = dict(
                tuple(row)
                for row in conn.execute(
                    select(acquisition_run_items.c.state, func.count())
                    .where(acquisition_run_items.c.run_id == str(run_id))
                    .group_by(acquisition_run_items.c.state)
                )
            )
            accepted_count = sum(counts.values())
            terminal_count = sum(count for state, count in counts.items() if ItemOutcome(state).terminal)
            succeeded = counts.get(ItemOutcome.SUCCEEDED.value, 0)
            no_match = counts.get(ItemOutcome.NO_MATCH.value, 0)
            blocked = counts.get(ItemOutcome.BLOCKED.value, 0)
            failed = sum(
                counts.get(state.value, 0)
                for state in (ItemOutcome.FAILED, ItemOutcome.QUARANTINED, ItemOutcome.CANCELLED)
            )

            if accepted_count == 0:
                completion = RunState.PENDING
            elif terminal_count < accepted_count:
                completion = RunState.RUNNING
            elif failed == accepted_count:
                completion = RunState.FAILED
            elif blocked == accepted_count:
                completion = RunState.BLOCKED
            elif failed or blocked:
                completion = RunState.PARTIAL
            else:
                completion = RunState.COMPLETED
            now = _utcnow()
            completed_at = now if terminal_count == accepted_count and accepted_count else None
            conn.execute(
                update(acquisition_runs)
                .where(acquisition_runs.c.run_id == str(run_id))
                .values(
                    completion_state=completion.value,
                    accepted_count=accepted_count,
                    terminal_count=terminal_count,
                    succeeded_count=succeeded,
                    no_match_count=no_match,
                    blocked_count=blocked,
                    failed_count=failed,
                    updated_at=now,
                    completed_at=completed_at,
                )
            )
        run = self.get_run(run_id)
        # Narrate completion once when the run first becomes terminal (#484).
        # In-flight progress stays derived (no search.started @ run here).
        new_completion = str(run.get("completion_state") or "") if run else ""
        was_open = previous_completion in ("", "pending", "running")
        is_closed = new_completion not in ("", "pending", "running")
        if was_open and is_closed:
            _emit_run_completion_safe(run)
        return run
