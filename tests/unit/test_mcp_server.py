#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""The MCP endpoint at /mcp: gating, authentication and list_series (#1302)."""

import socket
import threading
import time
from contextlib import asynccontextmanager

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from comicarr.app.mcp.contracts import ContractError
from comicarr.app.system.service import login_rate_limiter
from tests.mcp_harness import INIT, KEY, STREAM_HEADERS, http, make_app, mcp_client, seed_library, teardown_library


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
    yield
    teardown_library()


@pytest.fixture
def app():
    return make_app()


@pytest.mark.asyncio
async def test_tools_list_and_list_series_through_the_sdk_client(app):
    async with mcp_client(app, Authorization="Bearer " + KEY) as mcp:
        tools = (await mcp.list_tools()).tools
        assert [t.name for t in tools] == ["list_series"]
        tool = tools[0]
        assert tool.title == "List series"
        assert tool.annotations.read_only_hint is True
        assert sorted(tool.output_schema["required"]) == ["next_offset", "series", "total"]

        result = await mcp.call_tool("list_series", {})
        assert not result.is_error
        page = result.structured_content
        assert page["total"] == 4 and page["next_offset"] is None
        assert [s["name"] for s in page["series"]] == ["Dandadan", "Paper Girls", "Saga", "Wired"]
        saga = page["series"][2]
        assert saga == {
            "series_id": "1001",
            "name": "Saga",
            "year": "2012",
            "publisher": "Image",
            "kind": "comic",
            "status": "Active",
            "have": 60,
            "total": 66,
            "latest_issue": "66",
        }
        assert result.content[0].text == "4 of 4 series."


@pytest.mark.asyncio
async def test_list_series_filters_and_pages(app):
    async with mcp_client(app, Authorization="Bearer " + KEY) as mcp:
        page = (await mcp.call_tool("list_series", {"limit": 2})).structured_content
        assert (len(page["series"]), page["total"], page["next_offset"]) == (2, 4, 2)
        page = (await mcp.call_tool("list_series", {"limit": 2, "offset": 2})).structured_content
        assert [s["name"] for s in page["series"]] == ["Saga", "Wired"] and page["next_offset"] is None

        manga = (await mcp.call_tool("list_series", {"kind": "manga"})).structured_content
        assert [(s["name"], s["kind"]) for s in manga["series"]] == [("Dandadan", "manga")]
        comic = (await mcp.call_tool("list_series", {"kind": "comic"})).structured_content
        assert [s["name"] for s in comic["series"]] == ["Paper Girls", "Saga", "Wired"]
        magazine = (await mcp.call_tool("list_series", {"kind": "magazine"})).structured_content
        assert [(s["name"], s["kind"]) for s in magazine["series"]] == [("Wired", "magazine")]
        paused = (await mcp.call_tool("list_series", {"status": "Paused"})).structured_content
        assert [s["name"] for s in paused["series"]] == ["Paper Girls"]
        named = (await mcp.call_tool("list_series", {"name": "GIRL"})).structured_content
        assert [s["name"] for s in named["series"]] == ["Paper Girls"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments, field",
    [({"kind": "comics"}, "kind"), ({"status": "Dormant"}, "status"), ({"limit": 101}, "limit")],
)
async def test_an_unknown_filter_value_is_invalid_argument(app, arguments, field):
    async with mcp_client(app, Authorization="Bearer " + KEY) as mcp:
        result = await mcp.call_tool("list_series", arguments)
    assert result.is_error
    assert result.structured_content == {
        "code": "invalid_argument",
        "message": "Invalid value for %s." % field,
        "retryable": False,
    }
    assert str(next(iter(arguments.values()))) not in result.content[0].text


@pytest.mark.asyncio
async def test_a_contract_error_keeps_its_code_and_a_crash_is_internal_without_its_text(app):
    @app.state.mcp.server.tool(name="get_gone")
    def get_gone() -> str:
        raise ContractError("not_found", "No series 42.")

    @app.state.mcp.server.tool(name="get_crash")
    def get_crash() -> str:
        raise RuntimeError("secret path /srv/comics")

    async with mcp_client(app, Authorization="Bearer " + KEY) as mcp:
        gone = await mcp.call_tool("get_gone", {})
        crash = await mcp.call_tool("get_crash", {})
    assert gone.is_error and gone.structured_content == {
        "code": "not_found",
        "message": "No series 42.",
        "retryable": False,
    }
    assert crash.is_error and crash.structured_content["code"] == "internal"
    assert crash.structured_content["retryable"] is True
    assert "secret" not in crash.content[0].text and "secret" not in str(crash.structured_content)


@pytest.mark.asyncio
async def test_x_api_key_header_also_authenticates(app):
    async with mcp_client(app, **{"X-Api-Key": KEY}) as mcp:
        assert (await mcp.call_tool("list_series", {})).structured_content["total"] == 4


@pytest.mark.asyncio
async def test_disabled_answers_404_before_auth_and_never_the_spa(app):
    app.state.ctx.config.MCP_ENABLED = False
    async with http(app) as client:
        response = await client.post("/mcp", json=INIT, headers=STREAM_HEADERS)
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}
        assert (await client.get("/mcp")).status_code == 404


@pytest.mark.asyncio
async def test_toggling_mcp_enabled_applies_without_restart(app):
    async with http(app, Authorization="Bearer " + KEY) as client:
        assert (await client.post("/mcp", json=INIT, headers=STREAM_HEADERS)).status_code == 200
        app.state.ctx.config.MCP_ENABLED = False
        assert (await client.post("/mcp", json=INIT, headers=STREAM_HEADERS)).status_code == 404
        app.state.ctx.config.MCP_ENABLED = True
        assert (await client.post("/mcp", json=INIT, headers=STREAM_HEADERS)).status_code == 200


@pytest.mark.asyncio
async def test_setup_gate_answers_503_before_first_run_setup(app):
    app.state.ctx.setup_token = "pending"
    async with http(app, Authorization="Bearer " + KEY) as client:
        assert (await client.post("/mcp", json=INIT, headers=STREAM_HEADERS)).status_code == 503


@pytest.mark.asyncio
async def test_bad_key_is_401_and_missing_key_is_401(app):
    async with http(app) as client:
        bad = await client.post("/mcp", json=INIT, headers={**STREAM_HEADERS, "Authorization": "Bearer nope"})
        assert bad.status_code == 401
        bad_x = await client.post("/mcp", json=INIT, headers={**STREAM_HEADERS, "X-Api-Key": "nope"})
        assert bad_x.status_code == 401
        assert (await client.post("/mcp", json=INIT, headers=STREAM_HEADERS)).status_code == 401


@pytest.mark.asyncio
async def test_foreign_origin_is_403_and_own_origin_is_allowed(app):
    async with http(app, Authorization="Bearer " + KEY) as client:
        foreign = await client.post("/mcp", json=INIT, headers={**STREAM_HEADERS, "Origin": "https://evil.example"})
        assert foreign.status_code == 403
        own = await client.post("/mcp", json=INIT, headers={**STREAM_HEADERS, "Origin": "http://testserver"})
        assert own.status_code == 200


@pytest.mark.asyncio
async def test_five_failed_keys_lock_the_ip_out_with_429(app):
    async with http(app) as client:
        for _ in range(5):
            bad = await client.post("/mcp", json=INIT, headers={**STREAM_HEADERS, "Authorization": "Bearer nope"})
            assert bad.status_code == 401
        good = await client.post("/mcp", json=INIT, headers={**STREAM_HEADERS, "Authorization": "Bearer " + KEY})
        assert good.status_code == 429
    assert login_rate_limiter().is_locked_out("127.0.0.1")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_real_uvicorn_streams_through_all_three_middleware_layers(app):
    """The design's owed proof: SSE through SetupGate, CSRF and SecurityHeaders under uvicorn."""

    @asynccontextmanager
    async def lifespan(_app):
        async with app.state.mcp.run():
            yield

    app.router.lifespan_context = lifespan
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            assert time.monotonic() < deadline, "uvicorn did not start"
            time.sleep(0.05)
        url = "http://127.0.0.1:%d/mcp" % port
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + KEY}) as client:
            raw = await client.post(url, json=INIT, headers=STREAM_HEADERS)
            assert raw.status_code == 200
            assert raw.headers["content-type"].startswith("text/event-stream")
            assert raw.headers["x-frame-options"] == "DENY"
            async with Client(streamable_http_client(url, http_client=client)) as mcp:
                result = await mcp.call_tool("list_series", {"limit": 1})
                assert result.structured_content["total"] == 4
    finally:
        server.should_exit = True
        thread.join(10)


@pytest.mark.asyncio
async def test_the_endpoint_serves_again_after_its_lifespan_restarts(app):
    for _ in range(2):
        async with http(app, Authorization="Bearer " + KEY) as client:
            assert (await client.post("/mcp", json=INIT, headers=STREAM_HEADERS)).status_code == 200


def _add_series(**row):
    from comicarr.db import get_engine
    from comicarr.tables import comics

    with get_engine().begin() as conn:
        conn.execute(comics.insert().values(**row))


@pytest.mark.asyncio
async def test_an_accented_name_matches_as_typed_and_case_insensitively_in_ascii(app):
    _add_series(ComicID="1004", ComicName="Éclair", ComicSortName="Eclair", Status="Ended", ContentType="comic")
    async with mcp_client(app, Authorization="Bearer " + KEY) as mcp:
        for typed in ("Éclair", "CLAIR", "clair"):
            page = (await mcp.call_tool("list_series", {"name": typed})).structured_content
            assert [s["series_id"] for s in page["series"]] == ["1004"], typed


@pytest.mark.asyncio
async def test_paging_through_tied_sort_names_returns_every_series_once(app):
    for series_id in ("2003", "2001", "2002"):
        _add_series(ComicID=series_id, ComicName="Annual", ComicSortName="Annual", ContentType="comic")
    seen = []
    async with mcp_client(app, Authorization="Bearer " + KEY) as mcp:
        offset = 0
        while offset is not None:
            page = (
                await mcp.call_tool("list_series", {"name": "Annual", "limit": 1, "offset": offset})
            ).structured_content
            seen += [s["series_id"] for s in page["series"]]
            offset = page["next_offset"]
    assert seen == ["2001", "2002", "2003"]
