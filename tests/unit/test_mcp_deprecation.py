#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Renamed MCP tools keep working through the ADR-0006 deprecation window (#1312)."""

import time

import pytest
from mcp import Client
from sqlalchemy import select

from comicarr.app.core import db
from comicarr.app.core.tables import mcp_tool_calls
from comicarr.app.mcp import usage
from comicarr.app.mcp.server import register_aliases
from comicarr.app.system.deprecations import REGISTRY, mcp_tool_called_recently, mcp_tool_rename
from tests.mcp_harness import make_app, seed_library, teardown_library


@pytest.fixture(autouse=True)
def library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
    yield
    teardown_library()


def _last_called(name):
    row = db.select_one(select(mcp_tool_calls.c.last_called_at).where(mcp_tool_calls.c.tool_name == name))
    return row["last_called_at"] if row else None


def _set_last_called(name, seconds_ago):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))
    db.upsert("mcp_tool_calls", {"last_called_at": stamp}, {"tool_name": name})


@pytest.mark.asyncio
async def test_an_alias_returns_the_new_tools_result_and_is_listed_as_deprecated():
    app = make_app()
    server = app.state.mcp.server
    server.alias("list_comics", "list_series")

    async with Client(server) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        new = await client.call_tool("list_series", {"kind": "manga"})
        old = await client.call_tool("list_comics", {"kind": "manga"})

    assert not old.is_error
    assert old.structured_content == new.structured_content
    assert [s["series_id"] for s in old.structured_content["series"]] == ["md-abc"]
    alias = tools["list_comics"]
    assert alias.title == "List series (deprecated)"
    assert alias.description.startswith("Deprecated: renamed to list_series, use that instead.")
    assert alias.input_schema == tools["list_series"].input_schema
    assert alias.output_schema == tools["list_series"].output_schema


@pytest.mark.asyncio
async def test_an_alias_of_a_write_tool_follows_the_write_switch():
    app = make_app(writes=False)
    server = app.state.mcp.server
    server.alias("set_series_paused", "pause_series")

    async with Client(server) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        result = await client.call_tool("set_series_paused", {"series_id": "1001"})

    assert "set_series_paused" not in names
    assert result.is_error
    assert result.structured_content["code"] == "writes_disabled"


def test_an_alias_needs_a_known_target_and_a_free_name():
    server = make_app().state.mcp.server
    with pytest.raises(ValueError):
        server.alias("list_comics", "no_such_tool")
    with pytest.raises(ValueError):
        server.alias("pause_series", "list_series")


@pytest.mark.asyncio
async def test_ten_calls_within_an_hour_write_the_last_call_row_once(monkeypatch):
    writes = []
    real_upsert = usage.db.upsert

    def spy(table, values, keys):
        writes.append((table, keys))
        real_upsert(table, values, keys)

    monkeypatch.setattr(usage.db, "upsert", spy)
    app = make_app()

    async with Client(app.state.mcp.server) as client:
        for _ in range(10):
            await client.call_tool("list_series", {})

    assert writes == [("mcp_tool_calls", {"tool_name": "list_series"})]
    assert _last_called("list_series") is not None


def test_the_recorder_writes_again_once_the_hour_is_up(monkeypatch):
    writes = []
    monkeypatch.setattr(usage.db, "upsert", lambda table, values, keys: writes.append(keys["tool_name"]))
    now = [1000.0]
    recorder = usage.ToolCallRecorder(clock=lambda: now[0])

    recorder.record("list_series")
    now[0] += usage.WRITE_EVERY_SECONDS - 1
    recorder.record("list_series")
    recorder.record("pause_series")
    now[0] += 1
    recorder.record("list_series")

    assert writes == ["list_series", "pause_series", "list_series"]


def test_a_failed_write_never_fails_the_call(monkeypatch):
    def broken(*args):
        raise RuntimeError("database is gone")

    monkeypatch.setattr(usage.db, "upsert", broken)
    usage.ToolCallRecorder().record("list_series")


@pytest.mark.asyncio
async def test_unknown_names_are_not_recorded():
    app = make_app()
    async with Client(app.state.mcp.server) as client:
        await client.call_tool("no_such_tool", {})
    assert _last_called("no_such_tool") is None


@pytest.mark.asyncio
async def test_in_use_is_true_after_a_call_and_false_once_the_row_is_older_than_30_days():
    entry = mcp_tool_rename("list_comics", "list_series", announced_in="0.53.0", removable_from="1.0.0")
    app = make_app()
    register_aliases(app.state.mcp.server, [entry])

    assert entry.in_use() is False
    async with Client(app.state.mcp.server) as client:
        await client.call_tool("list_comics", {})
    assert entry.in_use() is True
    # The new name's calls are its own; only the old name keeps the entry in use.
    assert _last_called("list_series") is None

    _set_last_called("list_comics", 29 * 86400)
    assert entry.in_use() is True
    _set_last_called("list_comics", 31 * 86400)
    assert entry.in_use() is False


def test_an_unreadable_timestamp_is_not_in_use():
    db.upsert("mcp_tool_calls", {"last_called_at": "yesterday"}, {"tool_name": "list_comics"})
    assert mcp_tool_called_recently("list_comics") is False


def test_a_rename_entry_names_both_tools_and_links_its_docs_section():
    entry = mcp_tool_rename("list_comics", "list_series", announced_in="0.53.0", removable_from="1.0.0")
    assert entry.id == "mcp-tool-list-comics"
    assert entry.name == "The MCP tool list_comics"
    assert "list_series" in entry.replacement
    assert entry.docs_url.endswith("#mcp-tool-list-comics")


def test_the_live_server_declares_an_alias_for_every_mcp_registry_entry():
    server = make_app().state.mcp.server
    expected = {entry.mcp_tool: entry.mcp_replacement for entry in REGISTRY if entry.mcp_tool}
    assert server.aliases == expected
