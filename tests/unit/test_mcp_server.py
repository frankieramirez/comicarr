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
import types
from contextlib import asynccontextmanager

import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

import comicarr
from comicarr.app.main import create_app
from comicarr.app.system.service import login_rate_limiter
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, metadata

KEY = "mcp-test-key-0123456789abcdef"
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}
STREAM_HEADERS = {"Accept": "application/json, text/event-stream"}

SERIES = [
    {
        "ComicID": "1001",
        "ComicName": "Saga",
        "ComicSortName": "Saga",
        "ComicYear": "2012",
        "Status": "Active",
        "ComicPublisher": "Image",
        "Have": 60,
        "Total": 66,
        "LatestIssue": "66",
        "ContentType": "comic",
    },
    {
        "ComicID": "md-abc",
        "ComicName": "Dandadan",
        "ComicSortName": "Dandadan",
        "ComicYear": "2021",
        "Status": "Active",
        "Have": 10,
        "Total": 150,
        "ContentType": "manga",
    },
    {
        "ComicID": "1002",
        "ComicName": "Paper Girls",
        "ComicSortName": "Paper Girls",
        "ComicYear": "2015",
        "Status": "Paused",
        "Have": 30,
        "Total": 30,
        "ContentType": "comic",
    },
    {
        "ComicID": "1003",
        "ComicName": "Wired",
        "ComicSortName": "Wired",
        "ComicYear": "1993",
        "Status": "Active",
        "Have": 1,
        "Total": 5,
        "ContentType": "magazine",
    },
]


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    engine = get_engine()
    metadata.create_all(engine)
    with engine.begin() as conn:
        for row in SERIES:
            conn.execute(comics.insert().values(**row))
    login_rate_limiter().record_success("127.0.0.1")
    login_rate_limiter().record_success("testclient")
    yield
    login_rate_limiter().record_success("127.0.0.1")
    login_rate_limiter().record_success("testclient")
    shutdown_engine()


@pytest.fixture
def app():
    app = create_app()
    app.state.ctx = types.SimpleNamespace(
        config=types.SimpleNamespace(MCP_ENABLED=True, MCP_WRITE_ENABLED=False, API_KEY=KEY, ENABLE_HTTPS=False),
        setup_token=None,
    )
    return app


@asynccontextmanager
async def http(app, **headers):
    async with app.state.mcp.run():
        transport = httpx2.ASGITransport(app=app, client=("127.0.0.1", 5000))
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver", headers=headers) as client:
            yield client


@asynccontextmanager
async def mcp_client(app, **headers):
    async with http(app, **headers) as client:
        async with Client(streamable_http_client("http://testserver/mcp", http_client=client)) as mcp:
            yield mcp


@pytest.mark.asyncio
async def test_tools_list_and_list_series_through_the_sdk_client(app):
    async with mcp_client(app, Authorization="Bearer " + KEY) as mcp:
        tools = (await mcp.list_tools()).tools
        assert [t.name for t in tools] == ["list_series"]
        tool = tools[0]
        assert tool.title == "List series"
        assert tool.annotations.read_only_hint is True
        assert tool.output_schema["required"] == ["series", "total", "next_offset"]

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

        too_big = await mcp.call_tool("list_series", {"limit": 101})
        assert too_big.is_error


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
