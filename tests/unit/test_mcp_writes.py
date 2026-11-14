#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""MCP write tools: the MCP_WRITE_ENABLED switch and the status writes (#1307)."""

import pytest
from sqlalchemy import select, update

from comicarr.db import get_engine
from comicarr.tables import activity_events, comics, issues
from tests.mcp_harness import KEY, make_app, mcp_client, seed_library, teardown_library

WRITES = {"set_issue_status", "pause_series", "resume_series", "search_issue", "search_missing", "retry_search_run"}
AUTH = {"Authorization": "Bearer " + KEY}


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
    yield
    teardown_library()


def _issue_status(issue_id):
    with get_engine().connect() as conn:
        return conn.execute(select(issues.c.Status).where(issues.c.IssueID == issue_id)).scalar()


def _series_status(series_id):
    with get_engine().connect() as conn:
        return conn.execute(select(comics.c.Status).where(comics.c.ComicID == series_id)).scalar()


def _activity():
    with get_engine().connect() as conn:
        rows = conn.execute(select(activity_events).order_by(activity_events.c.event_id)).fetchall()
    return [dict(row._mapping) for row in rows]


@pytest.mark.asyncio
async def test_writes_off_hides_write_tools_and_refuses_them():
    async with mcp_client(make_app(writes=False), **AUTH) as mcp:
        names = {tool.name for tool in (await mcp.list_tools()).tools}
        assert names.isdisjoint(WRITES)
        result = await mcp.call_tool("set_issue_status", {"issue_id": "5001", "status": "wanted"})
    assert result.is_error
    assert result.structured_content["code"] == "writes_disabled"
    assert _issue_status("5001") == "Skipped"


@pytest.mark.asyncio
async def test_toggling_writes_applies_without_restart():
    app = make_app(writes=False)
    async with mcp_client(app, **AUTH) as mcp:
        assert WRITES.isdisjoint(tool.name for tool in (await mcp.list_tools()).tools)
        app.state.ctx.config.MCP_WRITE_ENABLED = True
        assert WRITES <= {tool.name for tool in (await mcp.list_tools(cache_mode="refresh")).tools}
        assert not (await mcp.call_tool("pause_series", {"series_id": "1001"})).is_error


@pytest.mark.asyncio
async def test_set_issue_status_marks_wanted_records_mcp_activity_and_repeats_as_a_no_op():
    async with mcp_client(make_app(writes=True), **AUTH) as mcp:
        first = await mcp.call_tool("set_issue_status", {"issue_id": "5001", "status": "wanted"})
        again = await mcp.call_tool("set_issue_status", {"issue_id": "5001", "status": "wanted"})
    assert not first.is_error
    assert first.structured_content == {
        "issue_id": "5001",
        "entity_type": "issue",
        "status": "Wanted",
        "changed": True,
    }
    assert again.structured_content["changed"] is False
    assert _issue_status("5001") == "Wanted"
    rows = _activity()
    assert len(rows) == 1
    row = rows[0]
    assert (row["activity"], row["status"], row["subject_type"], row["subject_id"]) == (
        "status_change",
        "succeeded",
        "issue",
        "5001",
    )
    assert (row["subject_label"], row["reason_detail"], row["actor"], row["parent_series_id"]) == (
        "Saga #66",
        "Wanted",
        "mcp",
        "1001",
    )


@pytest.mark.asyncio
async def test_set_issue_status_writes_explicit_intent_even_when_status_already_matches():
    with get_engine().begin() as conn:
        conn.execute(update(issues).where(issues.c.IssueID == "5001").values(AcquisitionIntent="policy"))
    async with mcp_client(make_app(writes=True), **AUTH) as mcp:
        result = await mcp.call_tool("set_issue_status", {"issue_id": "5001", "status": "skipped"})
    assert result.structured_content["changed"] is False
    with get_engine().connect() as conn:
        intent = conn.execute(select(issues.c.AcquisitionIntent).where(issues.c.IssueID == "5001")).scalar()
    assert intent == "skipped"
    assert _activity() == []


@pytest.mark.asyncio
async def test_set_issue_status_reaches_annuals_and_refuses_other_statuses_and_unknown_ids():
    async with mcp_client(make_app(writes=True), **AUTH) as mcp:
        annual = await mcp.call_tool("set_issue_status", {"issue_id": "6001", "status": "wanted"})
        archived = await mcp.call_tool("set_issue_status", {"issue_id": "5001", "status": "archived"})
        missing = await mcp.call_tool("set_issue_status", {"issue_id": "nope", "status": "skipped"})
    assert annual.structured_content["entity_type"] == "annual" and annual.structured_content["changed"]
    # An annual with Deleted NULL still gets narrated.
    assert [(r["subject_type"], r["subject_id"]) for r in _activity()] == [("annual", "6001")]
    assert archived.structured_content["code"] == "invalid_argument"
    assert missing.structured_content["code"] == "not_found"
    assert _issue_status("5001") == "Skipped"


@pytest.mark.asyncio
async def test_pause_then_resume_round_trips_and_repeats_are_no_ops():
    async with mcp_client(make_app(writes=True), **AUTH) as mcp:
        paused = await mcp.call_tool("pause_series", {"series_id": "1001"})
        assert _series_status("1001") == "Paused"
        paused_again = await mcp.call_tool("pause_series", {"series_id": "1001"})
        resumed = await mcp.call_tool("resume_series", {"series_id": "1001"})
        resumed_again = await mcp.call_tool("resume_series", {"series_id": "1001"})
        missing = await mcp.call_tool("pause_series", {"series_id": "9999"})
    assert [r.structured_content["changed"] for r in (paused, paused_again, resumed, resumed_again)] == [
        True,
        False,
        True,
        False,
    ]
    assert _series_status("1001") == "Active"
    assert missing.structured_content["code"] == "not_found"
    rows = _activity()
    assert [(r["subject_type"], r["reason_detail"], r["actor"]) for r in rows] == [
        ("series", "Paused", "mcp"),
        ("series", "Active", "mcp"),
    ]
    assert rows[0]["subject_label"] == "Saga (2012)"
