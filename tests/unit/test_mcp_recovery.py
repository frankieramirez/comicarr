#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""MCP recovery writes: retry_post_processing, resolve_attention, cancel_in_flight (#1310)."""

import threading
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

import comicarr
from comicarr.app.acquisition.maintenance import MaintenanceController, ensure_acquisition_schema
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.activity import queries as activity_queries
from comicarr.app.attention import read as read_attention
from comicarr.app.core import runtime
from comicarr.app.core.db import get_engine
from comicarr.app.core.tables import activity_events, issues
from comicarr.app.downloads import journal, postprocessing, sab_reconcile
from tests.mcp_harness import KEY, make_app, mcp_client, seed_library, teardown_library

AUTH = {"Authorization": "Bearer " + KEY}
PAYLOAD = {"issueid": "5001", "comicid": "1001", "comicname": "Saga", "issuenumber": "66", "provider": "nzbgeek"}


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
    monkeypatch.delenv("COMICARR_ACQUISITION_MAINTENANCE", raising=False)
    monkeypatch.setattr(runtime.current(), "api_lock", threading.Lock(), raising=False)
    monkeypatch.setattr(comicarr, "PROVIDER_BLOCKLIST", {}, raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            FAILED_DOWNLOAD_HANDLING=True,
            FAILED_AUTO=False,
            HIGHCOUNT=0,
            DDL_LOCATION=str(tmp_path / "ddl"),
            CACHE_DIR=str(tmp_path / "cache"),
            DESTINATION_DIR=str(tmp_path / "library"),
        ),
        raising=False,
    )
    assert ensure_acquisition_schema(get_engine()).ready
    yield
    teardown_library()


def _app():
    app = make_app(writes=True)
    app.state.ctx.provider_blocklist = {}
    return app


def _journal_row(release_key, stage):
    journal.record_transition(release_key, journal.SNATCHED, payload=PAYLOAD, issueid="5001", provider="nzbgeek")
    if stage != journal.SNATCHED:
        journal.record_transition(release_key, stage, payload=PAYLOAD, issueid="5001", provider="nzbgeek")


@pytest.mark.asyncio
async def test_retry_post_processing_is_busy_while_the_processing_lock_is_held(monkeypatch):
    _journal_row("saga-66|nzbgeek", journal.POST_PROCESSING)
    runtime.current().api_lock.acquire()
    try:
        async with mcp_client(_app(), **AUTH) as mcp:
            result = await mcp.call_tool("retry_post_processing", {"release_key": "saga-66|nzbgeek"})
    finally:
        runtime.current().api_lock.release()
    assert result.is_error
    assert result.structured_content["code"] == "busy"
    assert result.structured_content["retryable"] is True


@pytest.mark.asyncio
async def test_retry_post_processing_continues_a_row_through_journal_recovery(monkeypatch):
    _journal_row("saga-66|nzbgeek", journal.POST_PROCESSING)
    recovered = []

    def recover(release_key):
        recovered.append(release_key)
        return postprocessing.PostProcessResult("processed", action="post_processing-redrive")

    monkeypatch.setattr(postprocessing, "recover", recover)
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool("retry_post_processing", {"release_key": "saga-66|nzbgeek"})
    assert not result.is_error, result.content[0].text
    assert result.structured_content == {"release_key": "saga-66|nzbgeek", "status": "processed"}
    assert recovered == ["saga-66|nzbgeek"]


@pytest.mark.asyncio
async def test_retry_post_processing_queues_a_finished_download_like_activity_does(monkeypatch):
    _journal_row("saga-66|nzbgeek", journal.SNATCHED)
    queued = []
    monkeypatch.setattr(sab_reconcile, "retry_postprocess", lambda key: queued.append(key) or {"success": True})
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool("retry_post_processing", {"release_key": "saga-66|nzbgeek"})
        missing = await mcp.call_tool("retry_post_processing", {"release_key": "nope"})
    assert result.structured_content == {"release_key": "saga-66|nzbgeek", "status": "queued"}
    assert queued == ["saga-66|nzbgeek"]
    assert missing.is_error and missing.structured_content["code"] == "not_found"


@pytest.mark.asyncio
async def test_retry_post_processing_during_maintenance_starts_nothing(monkeypatch):
    _journal_row("saga-66|nzbgeek", journal.POST_PROCESSING)
    monkeypatch.setattr(postprocessing, "recover", lambda _key: pytest.fail("recover ran during maintenance"))
    MaintenanceController().acquire_fence("test", "maint-1", "test maintenance")
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool("retry_post_processing", {"release_key": "saga-66|nzbgeek"})
    assert result.is_error and result.structured_content["code"] == "maintenance"


@pytest.mark.asyncio
async def test_resolve_attention_removes_the_item_from_attention():
    with get_engine().begin() as conn:
        conn.execute(update(issues).where(issues.c.IssueID == "5001").values(Status="Failed"))
    _journal_row("saga-66|nzbgeek", journal.SNATCHED)
    journal.mark_failed(
        "saga-66|nzbgeek", "download_failed_no_auto_handling", payload=PAYLOAD, issueid="5001", provider="nzbgeek"
    )
    keys = [m.release_key for g in read_attention().groups for m in g.members]
    assert keys == ["saga-66|nzbgeek"]
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool(
            "resolve_attention", {"action": "stop_wanting", "release_keys": ["saga-66|nzbgeek"]}
        )
        unknown = await mcp.call_tool("resolve_attention", {"action": "retry", "release_keys": ["nope"]})
    assert not result.is_error, result.content[0].text
    assert (result.structured_content["succeeded"], result.structured_content["failed"]) == (1, 0)
    assert [m.release_key for g in read_attention().groups for m in g.members] == []
    assert unknown.is_error and unknown.structured_content["code"] == "not_found"


@pytest.mark.asyncio
async def test_resolve_attention_does_not_offer_import():
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool("resolve_attention", {"action": "import", "release_keys": ["k"]})
    assert result.is_error and result.structured_content["code"] == "invalid_argument"


@pytest.mark.asyncio
async def test_cancel_in_flight_removes_a_queued_search_item_and_records_it_via_mcp():
    ledger = RunLedger()
    ledger.create_run("run-cancel", command_kind="search", trigger="manual")
    item = ledger.accept_item("run-cancel", entity_type="issue", entity_id="5001")
    assert any(row.get("item_id") == item["item_id"] for row in activity_queries.list_in_flight_items())
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool("cancel_in_flight", {"kind": "run", "item_id": item["item_id"]})
        again = await mcp.call_tool("cancel_in_flight", {"kind": "run", "item_id": item["item_id"]})
        incomplete = await mcp.call_tool("cancel_in_flight", {"kind": "journal"})
    assert not result.is_error, result.content[0].text
    assert result.structured_content["state"] == "cancelled"
    assert not any(row.get("item_id") == item["item_id"] for row in activity_queries.list_in_flight_items())
    with get_engine().connect() as conn:
        row = conn.execute(
            select(activity_events.c.activity, activity_events.c.status, activity_events.c.actor).where(
                activity_events.c.subject_id == "5001"
            )
        ).one()
    assert tuple(row) == ("search", "cancelled", "mcp")
    assert again.is_error and again.structured_content["code"] == "not_found"
    assert "already finished" in again.structured_content["message"]
    assert incomplete.is_error and incomplete.structured_content["code"] == "invalid_argument"


@pytest.mark.asyncio
async def test_cancel_in_flight_cancels_a_download():
    _journal_row("saga-66|nzbgeek", journal.SNATCHED)
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool("cancel_in_flight", {"kind": "journal", "release_key": "saga-66|nzbgeek"})
    assert not result.is_error, result.content[0].text
    assert journal.read_one("saga-66|nzbgeek")["stage"] == journal.CANCELLED
