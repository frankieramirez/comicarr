#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""MCP search writes: search_issue, search_missing, retry_search_run (#1308)."""

import queue

import pytest
from sqlalchemy import select, update

import comicarr
from comicarr.app.acquisition.maintenance import MaintenanceController, ensure_acquisition_schema
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.search import bulk
from comicarr.db import get_engine
from comicarr.tables import acquisition_run_items, acquisition_runs, activity_events, annuals, issues
from tests.mcp_harness import KEY, make_app, mcp_client, seed_library, teardown_library

AUTH = {"Authorization": "Bearer " + KEY}


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
    monkeypatch.setattr(comicarr, "SEARCH_QUEUE", queue.Queue(), raising=False)
    monkeypatch.delenv("COMICARR_ACQUISITION_MAINTENANCE", raising=False)
    assert ensure_acquisition_schema(get_engine()).ready
    with get_engine().begin() as conn:
        conn.execute(update(issues).where(issues.c.IssueID == "5001").values(Status="Wanted", ReleaseDate="2020-01-01"))
        conn.execute(update(annuals).where(annuals.c.IssueID == "6001").values(Status="Wanted"))
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *_a, **_k: {"viable_route": True, "routes": {"ddl": {"ready": True}, "nzb": {}, "torrent": {}}},
    )
    yield
    teardown_library()


def _app():
    app = make_app(writes=True)
    app.state.ctx.config.ANNUALS_ON = True
    return app


def _runs():
    with get_engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(select(acquisition_runs)).fetchall()]


def _run_rows():
    with get_engine().connect() as conn:
        rows = conn.execute(select(activity_events).where(activity_events.c.subject_type == "run")).fetchall()
    return [dict(r._mapping) for r in rows]


@pytest.mark.asyncio
async def test_search_issue_queues_one_run_attributed_to_mcp():
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool("search_issue", {"issue_id": "5001"})
    assert not result.is_error, result.content[0].text
    started = result.structured_content
    assert started["accepted"] == 1 and started["status"] == "accepted"
    run = RunLedger().get_run(started["run_id"])
    assert run is not None and run["command_kind"] == "search"
    assert (run["scope_type"], run["scope_id"]) == ("issue", "5001")
    assert comicarr.SEARCH_QUEUE.get_nowait()["issueid"] == "5001"
    [row] = _run_rows()
    assert (row["activity"], row["status"], row["actor"]) == ("search", "started", "mcp")
    assert row["run_id"] == started["run_id"]


@pytest.mark.asyncio
async def test_search_missing_queues_the_series_wanted_issues():
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool("search_missing", {"series_id": "1001"})
    assert not result.is_error, result.content[0].text
    started = result.structured_content
    assert started["series_id"] == "1001" and started["accepted"] >= 1
    assert RunLedger().get_run(started["run_id"])["scope_id"] == "1001"
    assert _run_rows()[0]["actor"] == "mcp"


@pytest.mark.asyncio
async def test_search_missing_with_nothing_wanted_starts_nothing():
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool("search_missing", {"series_id": "1002"})
    assert not result.is_error
    assert result.structured_content == {"run_id": None, "series_id": "1002", "accepted": 0, "status": "noop"}
    assert _runs() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "issue_id, code",
    [("5002", "invalid_argument"), ("6001", "invalid_argument"), ("nope", "not_found")],
)
async def test_search_issue_refuses_an_issue_that_is_not_wanted(issue_id, code):
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool("search_issue", {"issue_id": issue_id})
    assert result.is_error and result.structured_content["code"] == code
    assert _runs() == []


@pytest.mark.asyncio
async def test_a_fingerprint_change_between_preview_and_confirm_is_stale_preview(monkeypatch):
    real_create = bulk.create_preview

    def create_then_change(*args, **kwargs):
        minted = real_create(*args, **kwargs)
        with get_engine().begin() as conn:
            conn.execute(update(issues).where(issues.c.IssueID == "5001").values(AcquisitionIntent="changed"))
        return minted

    monkeypatch.setattr(bulk, "create_preview", create_then_change)
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool("search_issue", {"issue_id": "5001"})
    assert result.is_error
    assert result.structured_content["code"] == "stale_preview"
    assert result.structured_content["retryable"] is True
    assert _runs() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool, arguments",
    [
        ("search_issue", {"issue_id": "5001"}),
        ("search_missing", {"series_id": "1001"}),
        ("retry_search_run", {"run_id": "any"}),
    ],
)
async def test_maintenance_refuses_every_search_and_starts_nothing(tool, arguments):
    MaintenanceController().acquire_fence("test", "maint-1", "test maintenance")
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool(tool, arguments)
    assert result.is_error
    assert result.structured_content["code"] == "maintenance"
    assert result.structured_content["retryable"] is True
    assert _runs() == []
    assert comicarr.SEARCH_QUEUE.empty()


@pytest.mark.asyncio
async def test_retry_search_run_redrives_items_still_waiting_for_a_worker():
    async with mcp_client(_app(), **AUTH) as mcp:
        run_id = (await mcp.call_tool("search_issue", {"issue_id": "5001"})).structured_content["run_id"]
        comicarr.SEARCH_QUEUE.get_nowait()
        with get_engine().begin() as conn:
            conn.execute(
                update(acquisition_run_items)
                .where(acquisition_run_items.c.run_id == run_id)
                .values(dispatch_state="pending")
            )
        retried = await mcp.call_tool("retry_search_run", {"run_id": run_id})
        missing = await mcp.call_tool("retry_search_run", {"run_id": "no-such-run"})
    assert not retried.is_error, retried.content[0].text
    assert retried.structured_content == {"run_id": run_id, "dispatched": 1, "pending": 0}
    assert comicarr.SEARCH_QUEUE.get_nowait()["issueid"] == "5001"
    assert missing.is_error and missing.structured_content["code"] == "not_found"
