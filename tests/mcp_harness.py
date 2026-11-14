#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Shared harness for the MCP endpoint tests: a small library and an app serving /mcp."""

import types
from contextlib import asynccontextmanager

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

import comicarr
from comicarr.app.main import create_app
from comicarr.app.system.service import login_rate_limiter
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, metadata

KEY = "mcp-test-key-0123456789abcdef"
CLIENT_IP = "127.0.0.1"
LEGACY = "2025-11-25"
MODERN = "2026-07-28"
STREAM_HEADERS = {"Accept": "application/json, text/event-stream"}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": LEGACY, "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}

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


def seed_library(tmp_path, monkeypatch):
    """Point Comicarr at a fresh SQLite DB holding :data:`SERIES`; clear the lockout counter."""
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    engine = get_engine()
    metadata.create_all(engine)
    with engine.begin() as conn:
        for row in SERIES:
            conn.execute(comics.insert().values(**row))
    login_rate_limiter().record_success(CLIENT_IP)


def teardown_library():
    login_rate_limiter().record_success(CLIENT_IP)
    shutdown_engine()


def make_app():
    app = create_app()
    app.state.ctx = types.SimpleNamespace(
        config=types.SimpleNamespace(MCP_ENABLED=True, MCP_WRITE_ENABLED=False, API_KEY=KEY, ENABLE_HTTPS=False),
        setup_token=None,
    )
    return app


@asynccontextmanager
async def http(app, **headers):
    """An httpx2 client wired to ``app`` in-process, with the MCP session manager running."""
    async with app.state.mcp.run():
        transport = httpx2.ASGITransport(app=app, client=(CLIENT_IP, 5000))
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver", headers=headers) as client:
            yield client


@asynccontextmanager
async def mcp_client(app, mode="auto", **headers):
    """The SDK's own client, talking Streamable HTTP to ``app``."""
    async with http(app, **headers) as client:
        transport = streamable_http_client("http://testserver/mcp", http_client=client)
        async with Client(transport, mode=mode) as mcp:
            yield mcp
