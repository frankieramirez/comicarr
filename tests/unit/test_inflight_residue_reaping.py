#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Stale in-flight residue is reaped by a restart bound, not a clock (#555).

Crash replay is a re-driver, not a reaper: it faithfully re-queues every
non-terminal item. Correct for an obligation a restart interrupted; useless
for one that cannot make progress, which is then replayed forever and counted
as live work — the residue behind the "940 in flight" number.

The bound counts restarts because a clock cannot tell a stuck item from one
queued behind a long backlog, while surviving MAX_RECOVERY_ATTEMPTS restarts
without terminalising can only mean stuck.
"""

import pytest
from sqlalchemy import select, update

import comicarr
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.acquisition.models import ItemOutcome
from comicarr.app.acquisition.runs import MAX_RECOVERY_ATTEMPTS, RunLedger
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import acquisition_run_items, metadata


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    engine = get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready
    yield
    shutdown_engine()


def _ledger():
    return RunLedger(get_engine())


def _seed_item(ledger, run_id="run-1", entity_id="issue-1"):
    ledger.create_run(run_id, command_kind="search", trigger="manual")
    return ledger.accept_item(run_id, entity_type="issue", entity_id=entity_id)


def _item(ledger, run_id="run-1", entity_id="issue-1"):
    return ledger.get_item(run_id, "issue", entity_id)


# ---------------------------------------------------------------------------
# The bound
# ---------------------------------------------------------------------------


def test_a_fresh_item_is_redriven_and_counted():
    ledger = _ledger()
    _seed_item(ledger)

    assert ledger.claim_recovery(_item(ledger)) is True

    item = _item(ledger)
    assert item["recovery_count"] == 1
    assert item["state"] == ItemOutcome.ACCEPTED.value


def test_recovery_is_bounded_and_then_quarantines():
    ledger = _ledger()
    _seed_item(ledger)

    for expected in range(1, MAX_RECOVERY_ATTEMPTS + 1):
        assert ledger.claim_recovery(_item(ledger)) is True
        assert _item(ledger)["recovery_count"] == expected

    # The item has now survived MAX_RECOVERY_ATTEMPTS restarts without ever
    # reaching a terminal outcome. It is stuck, not interrupted.
    assert ledger.claim_recovery(_item(ledger)) is False

    item = _item(ledger)
    assert item["state"] == ItemOutcome.QUARANTINED.value
    assert item["reason"] == "recovery_attempts_exhausted"
    assert item["completed_at"] is not None


def test_a_reaped_item_is_no_longer_recoverable_or_in_flight():
    ledger = _ledger()
    _seed_item(ledger)
    with get_engine().begin() as conn:
        conn.execute(update(acquisition_run_items).values(recovery_count=MAX_RECOVERY_ATTEMPTS))

    ledger.claim_recovery(_item(ledger))

    assert ledger.list_recoverable_items("search") == []
    assert ledger.count_recovery_pending() == 0


def test_an_item_that_terminalises_normally_is_never_reaped():
    """Recovery counting must not leak into the ordinary success path."""
    ledger = _ledger()
    _seed_item(ledger)
    ledger.claim_recovery(_item(ledger))

    ledger.record_outcome("run-1", "issue", "issue-1", ItemOutcome.SUCCEEDED)

    item = _item(ledger)
    assert item["state"] == ItemOutcome.SUCCEEDED.value
    assert item["reason"] is None
    assert ledger.list_recoverable_items("search") == []


def test_recovery_count_is_independent_of_attempt_count():
    """attempt_count counts worker claims; an item can be re-driven without one."""
    ledger = _ledger()
    _seed_item(ledger)

    ledger.claim_recovery(_item(ledger))
    ledger.claim_recovery(_item(ledger))

    item = _item(ledger)
    assert item["recovery_count"] == 2
    assert item["attempt_count"] == 0


# ---------------------------------------------------------------------------
# The counter
# ---------------------------------------------------------------------------


def test_recovery_pending_qualifies_in_flight_without_inflating_it():
    from comicarr.app.activity import queries

    ledger = _ledger()
    ledger.create_run("run-1", command_kind="search", trigger="manual")
    ledger.accept_item("run-1", entity_type="issue", entity_id="fresh")
    ledger.accept_item("run-1", entity_type="issue", entity_id="recovered")
    ledger.claim_recovery(ledger.get_item("run-1", "issue", "recovered"))

    counts = queries.get_open_work_counts()

    assert counts["in_flight"] == 2
    assert counts["recovery_pending"] == 1


# ---------------------------------------------------------------------------
# The one-time migration for residue that predates the bound
# ---------------------------------------------------------------------------


def test_schema_v7_cancels_residue_that_predates_the_bound(tmp_path, monkeypatch):
    """Frankie's 940 stranded rows, cleared on the first start after upgrade.

    Safe because the run ledger records attempts, not intent: wanting lives on
    issues.Status, so cancelling a dead attempt row cannot lose a want.
    """
    from comicarr.app.acquisition import maintenance

    ledger = _ledger()
    ledger.create_run("old-run", command_kind="search", trigger="scheduled")
    ledger.accept_item("old-run", entity_type="issue", entity_id="stranded-1")
    ledger.accept_item("old-run", entity_type="issue", entity_id="stranded-2")
    ledger.accept_item("old-run", entity_type="issue", entity_id="done")
    ledger.record_outcome("old-run", "issue", "done", ItemOutcome.SUCCEEDED)

    maintenance._cancel_prebound_residue(get_engine())

    with get_engine().connect() as conn:
        rows = {
            row["entity_id"]: dict(row)
            for row in (r._mapping for r in conn.execute(select(acquisition_run_items)))
        }

    assert rows["stranded-1"]["state"] == ItemOutcome.CANCELLED.value
    assert rows["stranded-1"]["reason"] == "stale_before_recovery_bound"
    assert rows["stranded-2"]["state"] == ItemOutcome.CANCELLED.value
    # An already-terminal item is untouched.
    assert rows["done"]["state"] == ItemOutcome.SUCCEEDED.value
    assert rows["done"]["reason"] is None

    assert ledger.list_recoverable_items() == []


def test_schema_v7_is_applied_and_verified():
    from comicarr.app.acquisition import maintenance

    status = ensure_acquisition_schema(get_engine())

    assert status.ready is True
    assert maintenance.SCHEMA_VERSION >= 7
    assert status.version == maintenance.SCHEMA_VERSION
