#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Drive /mcp with the SDK's client once per protocol era (#1303).

The app runs in-process behind its real middleware. ``CALLS`` holds one
sample call per tool; a tool missing from it fails the test, so each new tool
adds its call here.
"""

import queue

import pytest

import comicarr
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.db import get_engine
from tests.mcp_harness import (
    INIT,
    KEY,
    LEGACY,
    MODERN,
    STREAM_HEADERS,
    http,
    make_app,
    mcp_client,
    seed_library,
    teardown_library,
)

ERAS = [pytest.param("legacy", LEGACY, id=LEGACY), pytest.param(MODERN, MODERN, id=MODERN)]

CALLS = {
    "list_series": ({"kind": "manga"}, lambda page: [s["series_id"] for s in page["series"]] == ["md-abc"]),
    "get_series": ({"series_id": "1001"}, lambda out: out["name"] == "Saga" and out["counts"]["issues"] == 2),
    "list_issues": (
        {"series_id": "1001", "state": "Missing"},
        lambda page: [i["issue_id"] for i in page["issues"]] == ["5001"],
    ),
    "list_wanted": ({"group_by": "series"}, lambda page: page["group_by"] == "series" and page["total"] == 0),
    "get_issue_story": ({"issue_id": "5001"}, lambda out: out["state"] == "Missing" and out["last_search"] is None),
    "list_activity": ({"series_id": "1001"}, lambda page: page["total"] == 0 and page["events"] == []),
    "list_in_flight": ({}, lambda page: page["total"] == 0 and page["stuck"] == 0),
    "list_attention": ({}, lambda page: page["total"] == 0 and page["problems"] == []),
    "list_download_history": ({"status": "Failed"}, lambda page: page["downloads"] == []),
    "list_download_queue": ({}, lambda page: page["total"] == 0),
    # The pull-list fetch is faked to fail, so the week reads as unavailable.
    "get_weekly_releases": ({}, lambda out: out["source"] == "unavailable" and out["releases"] == []),
    "get_system_health": ({}, lambda out: out["can_search"] is True and out["jobs"] == []),
    "find_series": ({"name": "Saga"}, lambda page: [r["provider_id"] for r in page["results"]] == ["1001"]),
    # An unknown run proves the tool is wired; real runs are in test_mcp_system_reads.py.
    "get_search_run": ({"run_id": "run-x"}, lambda out: out["code"] == "not_found"),
}
EXPECTED_READ_ERRORS = {"get_search_run"}

WRITE_CALLS = {
    "set_issue_status": ({"issue_id": "5001", "status": "wanted"}, lambda out: out["status"] == "Wanted"),
    "pause_series": ({"series_id": "1001"}, lambda out: out["status"] == "Paused"),
    "resume_series": ({"series_id": "1001"}, lambda out: out["status"] == "Active"),
    # Runs after set_issue_status made 5001 Wanted.
    "search_issue": ({"issue_id": "5001"}, lambda out: out["accepted"] == 1 and out["run_id"]),
    "search_missing": ({"series_id": "1002"}, lambda out: out["status"] == "noop"),
    # An unknown run proves the tool is wired; a real retry is in test_mcp_search.py.
    "retry_search_run": ({"run_id": "no-such-run"}, lambda out: out["code"] == "not_found"),
    # Already in the library, so nothing is queued on a real worker.
    "add_series": (
        {"provider": "comicvine", "provider_id": "1001", "kind": "comic"},
        lambda out: out["already_in_library"] is True,
    ),
    "refresh_series": ({"series_id": "nope"}, lambda out: out["code"] == "not_found"),
    # Unknown ids prove the recovery tools are wired; tests/unit/test_mcp_recovery.py does the real work.
    "retry_post_processing": ({"release_key": "nope"}, lambda out: out["code"] == "not_found"),
    "resolve_attention": ({"action": "retry", "release_keys": ["nope"]}, lambda out: out["code"] == "not_found"),
    "cancel_in_flight": ({"kind": "journal", "release_key": "nope"}, lambda out: out["code"] == "not_found"),
}
EXPECTED_ERRORS = {
    "retry_search_run",
    "refresh_series",
    "retry_post_processing",
    "resolve_attention",
    "cancel_in_flight",
}


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
    monkeypatch.setattr(comicarr, "SEARCH_QUEUE", queue.Queue(), raising=False)
    monkeypatch.delenv("COMICARR_ACQUISITION_MAINTENANCE", raising=False)
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *_a, **_k: {"viable_route": True, "routes": {"ddl": {"ready": True}, "nzb": {}, "torrent": {}}},
    )
    monkeypatch.setattr("comicarr.app.weekly.service._fetch_week", lambda *_a: None)
    monkeypatch.setattr(
        "comicarr.mb.findComic",
        lambda *_a, **_k: [{"name": "Saga", "comicyear": "2012", "comicid": "1001", "issues": "66", "haveit": "1001"}],
    )
    assert ensure_acquisition_schema(get_engine()).ready
    yield
    teardown_library()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, version", ERAS)
async def test_every_tool_answers_in_each_protocol_era(mode, version):
    async with mcp_client(make_app(), mode=mode, Authorization="Bearer " + KEY) as mcp:
        assert mcp.session.protocol_version == version
        names = sorted(tool.name for tool in (await mcp.list_tools()).tools)
        assert names == sorted(CALLS), "add a sample call for each new tool to CALLS"
        for name, (arguments, check) in CALLS.items():
            result = await mcp.call_tool(name, arguments)
            assert result.is_error == (name in EXPECTED_READ_ERRORS), (name, result.content)
            assert check(result.structured_content), (name, result.structured_content)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, version", ERAS)
async def test_writes_off_then_on_in_each_protocol_era(mode, version):
    app = make_app(writes=False)
    async with mcp_client(app, mode=mode, Authorization="Bearer " + KEY) as mcp:
        assert sorted(tool.name for tool in (await mcp.list_tools()).tools) == sorted(CALLS)
        refused = await mcp.call_tool("pause_series", {"series_id": "1001"})
        assert refused.is_error and refused.structured_content["code"] == "writes_disabled"

        app.state.ctx.config.MCP_WRITE_ENABLED = True
        names = sorted(tool.name for tool in (await mcp.list_tools(cache_mode="refresh")).tools)
        assert names == sorted({**CALLS, **WRITE_CALLS}), "add a sample call for each new write tool"
        for name, (arguments, check) in WRITE_CALLS.items():
            result = await mcp.call_tool(name, arguments)
            assert result.is_error == (name in EXPECTED_ERRORS), (name, result.content)
            assert check(result.structured_content), (name, result.structured_content)


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [LEGACY, MODERN])
async def test_disabled_bad_key_and_foreign_origin_in_each_era(version):
    headers = {**STREAM_HEADERS, "MCP-Protocol-Version": version}
    app = make_app()
    async with http(app) as client:
        bad_key = await client.post("/mcp", json=INIT, headers={**headers, "Authorization": "Bearer wrong"})
        assert bad_key.status_code == 401
        foreign = await client.post(
            "/mcp",
            json=INIT,
            headers={**headers, "Authorization": "Bearer " + KEY, "Origin": "https://elsewhere.example"},
        )
        assert foreign.status_code == 403
        app.state.ctx.config.MCP_ENABLED = False
        disabled = await client.post("/mcp", json=INIT, headers={**headers, "Authorization": "Bearer " + KEY})
        assert disabled.status_code == 404
