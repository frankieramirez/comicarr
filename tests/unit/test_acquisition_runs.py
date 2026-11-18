#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Durable acquisition run and item ledger tests."""

import pytest

from comicarr.app.acquisition.models import DispatchState, ItemOutcome, RunState
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.core import runtime
from comicarr.app.core.db import get_engine, shutdown_engine
from comicarr.app.core.tables import metadata


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "data_dir", str(tmp_path))
    monkeypatch.setattr(runtime.current(), "config", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    metadata.create_all(get_engine())
    yield
    shutdown_engine()


def test_duplicate_acceptance_updates_one_obligation_and_exact_counts():
    ledger = RunLedger(get_engine())
    ledger.create_run("run-1", command_kind="search", trigger="manual", scope_type="series", scope_id="160294")

    first = ledger.accept_item("run-1", entity_type="issue", entity_id="issue-12")
    duplicate = ledger.accept_item("run-1", entity_type="issue", entity_id="issue-12")
    run = ledger.get_run("run-1")

    assert duplicate["item_id"] == first["item_id"]
    assert run["accepted_count"] == 1
    assert run["terminal_count"] == 0
    assert run["completion_state"] == RunState.RUNNING.value


def test_command_kind_and_entity_identity_are_part_of_the_durable_contract():
    ledger = RunLedger(get_engine())
    ledger.create_run("search-run", command_kind="search", trigger="scheduler")
    ledger.create_run("refresh-run", command_kind="refresh", trigger="manual")

    search_item = ledger.accept_item("search-run", entity_type="issue", entity_id="same-id")
    refresh_item = ledger.accept_item("refresh-run", entity_type="series", entity_id="same-id")

    assert search_item["command_kind"] == "search"
    assert search_item["entity_type"] == "issue"
    assert refresh_item["command_kind"] == "refresh"
    assert refresh_item["entity_type"] == "series"


def test_conflicting_run_id_preserves_value_error_contract():
    ledger = RunLedger(get_engine())
    ledger.create_run("same-run", command_kind="search", trigger="manual")

    with pytest.raises(ValueError, match="different acquisition command"):
        ledger.create_run("same-run", command_kind="refresh", trigger="manual")


def test_conflicting_item_payload_preserves_value_error_contract():
    ledger = RunLedger(get_engine())
    ledger.create_run("payload-run", command_kind="search", trigger="manual")
    ledger.accept_item("payload-run", entity_type="issue", entity_id="issue-1", payload={"issueid": "first"})

    with pytest.raises(ValueError, match="payload is immutable"):
        ledger.accept_item("payload-run", entity_type="issue", entity_id="issue-1", payload={"issueid": "second"})


def test_reconstructable_payload_is_allowlisted_bounded_and_recoverable():
    ledger = RunLedger(get_engine())
    ledger.create_run("refresh-replay", command_kind="refresh", trigger="manual")
    ledger.accept_item(
        "refresh-replay",
        entity_type="series",
        entity_id="160294",
        payload={"comicid": "160294", "comicname": "Absolute Batman", "seriesyear": "2024"},
    )
    assert ledger.claim_item("refresh-replay", "series", "160294") is True

    restarted_ledger = RunLedger(get_engine())
    recoverable = restarted_ledger.list_recoverable_items("refresh")
    assert recoverable[0]["attempt_count"] == 1
    assert recoverable[0]["payload"] == {
        "comicid": "160294",
        "comicname": "Absolute Batman",
        "seriesyear": "2024",
    }

    restarted_ledger.record_requeue("refresh-replay", "series", "160294", reason="worker restarted")
    assert restarted_ledger.get_item("refresh-replay", "series", "160294")["state"] == "accepted"

    with pytest.raises(ValueError, match="non-allowlisted"):
        restarted_ledger.accept_item(
            "refresh-replay",
            entity_type="series",
            entity_id="other",
            payload={"comicid": "other", "api_key": "must-never-persist"},
        )


def test_dispatch_state_cannot_close_item_completion():
    ledger = RunLedger(get_engine())
    ledger.create_run("run-2", command_kind="search", trigger="scheduler")
    ledger.accept_item("run-2", entity_type="issue", entity_id="a")

    ledger.record_dispatch("run-2", DispatchState.ACCEPTED)
    run = ledger.get_run("run-2")

    assert run["dispatch_state"] == DispatchState.ACCEPTED.value
    assert run["completion_state"] == RunState.RUNNING.value
    assert run["completed_at"] is None


def test_empty_manual_scan_has_a_terminal_run_without_inventing_an_item():
    ledger = RunLedger(get_engine())
    ledger.create_run("empty-run", command_kind="search", trigger="manual_wanted_scan")

    completed = ledger.complete_empty_run("empty-run")

    assert completed["dispatch_state"] == DispatchState.ACCEPTED.value
    assert completed["completion_state"] == RunState.COMPLETED.value
    assert completed["accepted_count"] == 0
    assert completed["terminal_count"] == 0
    assert completed["completed_at"] is not None

    with pytest.raises(ValueError, match="terminal acquisition runs"):
        ledger.accept_item("empty-run", entity_type="issue", entity_id="late")


def test_terminal_item_outcomes_reconcile_run_counts_and_close_exactly_once():
    ledger = RunLedger(get_engine())
    ledger.create_run("run-3", command_kind="search", trigger="manual")
    ledger.accept_item("run-3", entity_type="issue", entity_id="a")
    ledger.accept_item("run-3", entity_type="issue", entity_id="b")

    ledger.record_outcome("run-3", "issue", "a", ItemOutcome.NO_MATCH)
    halfway = ledger.get_run("run-3")
    assert halfway["terminal_count"] == 1
    assert halfway["completion_state"] == RunState.RUNNING.value

    ledger.record_outcome("run-3", "issue", "b", ItemOutcome.SUCCEEDED)
    complete = ledger.get_run("run-3")
    assert complete["accepted_count"] == 2
    assert complete["terminal_count"] == 2
    assert complete["no_match_count"] == 1
    assert complete["succeeded_count"] == 1
    assert complete["completion_state"] == RunState.COMPLETED.value
    assert complete["completed_at"] is not None

    ledger.record_outcome("run-3", "issue", "b", ItemOutcome.SUCCEEDED)
    assert ledger.get_run("run-3")["terminal_count"] == 2
