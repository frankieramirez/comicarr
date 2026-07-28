#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Search domain contract tests for force search outcomes."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import comicarr
from comicarr.app.core.context import AppContext
from comicarr.app.search import service as search_service


def _ctx():
    return AppContext(config=SimpleNamespace())


def test_force_search_reports_blocked_when_no_viable_route(monkeypatch):
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *_args, **_kwargs: {
            "viable_route": False,
            "routes": {
                "ddl": {"ready": False, "reason": "disabled"},
                "nzb": {"ready": False, "reason": "client_not_ready"},
                "torrent": {"ready": False, "reason": "disabled"},
            },
        },
    )
    search_for_issue = MagicMock()
    monkeypatch.setattr(comicarr, "search", SimpleNamespace(searchforissue=search_for_issue), raising=False)

    result = search_service.force_search(_ctx())

    assert result["success"] is False
    assert result["status"] == "blocked"
    # The nearest-to-ready route names the gap, not the disabled majority.
    assert result["error"] == "client_not_ready"
    search_for_issue.assert_not_called()


def test_force_search_accepts_when_route_is_ready(monkeypatch):
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *_args, **_kwargs: {
            "viable_route": True,
            "routes": {"ddl": {"ready": True}, "nzb": {"ready": False}, "torrent": {"ready": False}},
        },
    )
    ledger = MagicMock()
    ledger.get_run.return_value = {
        "run_id": "manual-run",
        "completion_state": "running",
        "accepted_count": 2,
    }
    monkeypatch.setattr("comicarr.app.acquisition.runs.RunLedger", lambda: ledger)
    monkeypatch.setattr("comicarr.app.search.service.uuid.uuid4", lambda: "manual-run")
    search_for_issue = MagicMock(return_value={"status": "QUEUED", "queued_count": 2})
    monkeypatch.setattr(comicarr, "search", SimpleNamespace(searchforissue=search_for_issue), raising=False)

    result = search_service.force_search(_ctx())

    assert result["success"] is True
    assert result["status"] == "accepted"
    assert result["run_id"] == "manual-run"
    assert result["accepted"] == 2
    search_for_issue.assert_called_once()
    assert search_for_issue.call_args.kwargs["acquisition_run_id"] == "manual-run"
    assert search_for_issue.call_args.kwargs["acquisition_trigger"] == "manual_wanted_scan"


def test_force_search_reports_no_match_with_a_terminal_empty_run(monkeypatch):
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *_args, **_kwargs: {
            "viable_route": True,
            "routes": {"ddl": {"ready": True}, "nzb": {}, "torrent": {}},
        },
    )
    ledger = MagicMock()
    ledger.get_run.return_value = {
        "run_id": "manual-run",
        "completion_state": "completed",
        "accepted_count": 0,
    }
    monkeypatch.setattr("comicarr.app.acquisition.runs.RunLedger", lambda: ledger)
    monkeypatch.setattr("comicarr.app.search.service.uuid.uuid4", lambda: "manual-run")
    search_for_issue = MagicMock(return_value={"status": "QUEUED", "queued_count": 0})
    monkeypatch.setattr(comicarr, "search", SimpleNamespace(searchforissue=search_for_issue), raising=False)

    result = search_service.force_search(_ctx())

    assert result == {
        "success": True,
        "status": "no_match",
        "run_id": "manual-run",
        "accepted": 0,
        "message": "No eligible Wanted issues were queued",
    }
    ledger.complete_empty_run.assert_called_once_with("manual-run")


def test_force_search_reports_partial_when_some_wanted_handoffs_fail(monkeypatch):
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *_args, **_kwargs: {
            "viable_route": True,
            "routes": {"ddl": {"ready": True}, "nzb": {}, "torrent": {}},
        },
    )
    ledger = MagicMock()
    ledger.get_run.return_value = {
        "run_id": "manual-run",
        "completion_state": "running",
        "accepted_count": 2,
    }
    monkeypatch.setattr("comicarr.app.acquisition.runs.RunLedger", lambda: ledger)
    monkeypatch.setattr("comicarr.app.search.service.uuid.uuid4", lambda: "manual-run")
    search_for_issue = MagicMock(return_value={"status": "QUEUED", "queued_count": 2, "error_count": 1})
    monkeypatch.setattr(comicarr, "search", SimpleNamespace(searchforissue=search_for_issue), raising=False)

    result = search_service.force_search(_ctx())

    assert result == {
        "success": True,
        "status": "partial",
        "run_id": "manual-run",
        "accepted": 2,
        "error": "Some Wanted issues could not be queued",
        "message": "Search queued 2 Wanted issues; 1 could not be queued",
    }
    ledger.record_dispatch.assert_called_once_with("manual-run", "error")


@pytest.mark.parametrize(
    ("search_result", "expected_status", "completion_state"),
    [
        ({"status": "IN PROGRESS"}, "blocked", "blocked"),
        (RuntimeError("provider setup failed"), "failed", "failed"),
    ],
)
def test_force_search_closes_rejected_empty_runs(monkeypatch, search_result, expected_status, completion_state):
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *_args, **_kwargs: {
            "viable_route": True,
            "routes": {"ddl": {"ready": True}, "nzb": {}, "torrent": {}},
        },
    )
    ledger = MagicMock()
    monkeypatch.setattr("comicarr.app.acquisition.runs.RunLedger", lambda: ledger)
    monkeypatch.setattr("comicarr.app.search.service.uuid.uuid4", lambda: "manual-run")
    search_for_issue = MagicMock()
    if isinstance(search_result, Exception):
        search_for_issue.side_effect = search_result
    else:
        search_for_issue.return_value = search_result
    monkeypatch.setattr(comicarr, "search", SimpleNamespace(searchforissue=search_for_issue), raising=False)

    result = search_service.force_search(_ctx())

    assert result["status"] == expected_status
    assert result["run_id"] == "manual-run"
    ledger.complete_empty_run.assert_called_once()
    assert ledger.complete_empty_run.call_args.args == ("manual-run",)
    assert ledger.complete_empty_run.call_args.kwargs["completion_state"].value == completion_state


def test_get_run_status_only_skips_item_deserialization(monkeypatch):
    ledger = MagicMock()
    ledger.get_run.return_value = {
        "run_id": "search-run",
        "command_kind": "search",
        "trigger": "manual",
        "scope_type": "series",
        "scope_id": "160294",
        "dispatch_state": "accepted",
        "completion_state": "running",
        "accepted_count": 2,
        "terminal_count": 0,
        "succeeded_count": 0,
        "no_match_count": 0,
        "blocked_count": 0,
        "failed_count": 0,
        "created_at": "t0",
        "updated_at": "t1",
        "completed_at": None,
    }
    monkeypatch.setattr("comicarr.app.acquisition.runs.RunLedger", lambda: ledger)

    result = search_service.get_run(_ctx(), "search-run", include_items=False)

    assert result["success"] is True
    assert result["run"]["queue_priority"] == "routine"
    assert result["items"] == []
    ledger.list_items.assert_not_called()


def test_get_run_exposes_sanitized_item_attempt_status(monkeypatch):
    ledger = MagicMock()
    ledger.get_run.return_value = {
        "run_id": "search-run",
        "command_kind": "search",
        "trigger": "search_all_missing",
        "scope_type": "series",
        "scope_id": "160294",
        "dispatch_state": "accepted",
        "completion_state": "running",
        "accepted_count": 1,
        "terminal_count": 0,
        "succeeded_count": 0,
        "no_match_count": 0,
        "blocked_count": 0,
        "failed_count": 0,
        "created_at": "t0",
        "updated_at": "t1",
        "completed_at": None,
    }
    ledger.list_items.return_value = [
        {
            "entity_type": "issue",
            "entity_id": "issue-1",
            "state": "accepted",
            "attempt_count": 0,
            "reason": None,
            "updated_at": "t1",
            "completed_at": None,
            "queue_priority": "recovery",
        }
    ]
    monkeypatch.setattr("comicarr.app.acquisition.runs.RunLedger", lambda: ledger)

    result = search_service.get_run(_ctx(), "search-run")

    assert result["run"]["queue_priority"] == "recovery"
    assert result["items"] == [
        {
            "entity_type": "issue",
            "entity_id": "issue-1",
            "state": "accepted",
            "attempt_count": 0,
            "reason": None,
            "updated_at": "t1",
            "completed_at": None,
            "queue_priority": "recovery",
            "attempt_status": "queued",
        }
    ]
