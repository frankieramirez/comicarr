#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The shelf MCP tools: add, change and list print copies without touching search."""

import pytest
from sqlalchemy import select

from comicarr.db import get_engine
from comicarr.tables import issues
from tests.mcp_harness import KEY, make_app, mcp_client, seed_library, teardown_library

AUTH = {"Authorization": "Bearer " + KEY}


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
    yield
    teardown_library()


@pytest.mark.asyncio
async def test_an_agent_adds_two_covers_then_moves_a_wishlist_copy_to_owned():
    async with mcp_client(make_app(writes=True), **AUTH) as mcp:
        standard = await mcp.call_tool(
            "add_shelf_copy",
            {"series_id": "1001", "item_kind": "issue", "item_id": "5002", "paid_cents": 499, "currency": "usd"},
        )
        variant = await mcp.call_tool(
            "add_shelf_copy",
            {
                "series_id": "1001",
                "item_kind": "issue",
                "item_id": "5002",
                "variant_name": "1:25 virgin",
                "state": "wishlist",
            },
        )
        assert not standard.is_error and not variant.is_error
        assert standard.structured_content["currency"] == "USD"
        assert standard.structured_content["item_label"] == "#65"
        assert "Added Saga #65 to the shelf." == standard.content[0].text

        copy_id = variant.structured_content["copy_id"]
        moved = await mcp.call_tool("set_shelf_copy", {"copy_id": copy_id, "state": "owned", "storage": "Box 3"})
        assert moved.structured_content["state"] == "owned"
        assert moved.structured_content["storage"] == "Box 3"

        page = await mcp.call_tool("list_shelf_copies", {"series_id": "1001", "state": "owned"})
        assert page.structured_content["total"] == 2
        assert {c["variant_name"] for c in page.structured_content["copies"]} == {None, "1:25 virgin"}

    with get_engine().connect() as conn:
        assert conn.execute(select(issues.c.Status).where(issues.c.IssueID == "5002")).scalar_one() == "Downloaded"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "arguments", "code", "message"),
    [
        ("add_shelf_copy", {"series_id": "nope", "item_kind": "issue", "item_id": "5002"}, "not_found", "nope"),
        ("add_shelf_copy", {"series_id": "1001", "item_kind": "issue", "item_id": "x"}, "not_found", "1001"),
        (
            "add_shelf_copy",
            {"series_id": "1001", "item_kind": "volume", "volume_number": "1"},
            "invalid_argument",
            "manga",
        ),
        (
            "add_shelf_copy",
            {"series_id": "1001", "item_kind": "issue", "item_id": "5002", "grade": "12"},
            "invalid_argument",
            "grade",
        ),
        ("set_shelf_copy", {"copy_id": "nope", "notes": "x"}, "not_found", "nope"),
        ("set_shelf_copy", {"copy_id": "nope"}, "invalid_argument", "at least one"),
    ],
)
async def test_refusals_use_the_contract_codes(name, arguments, code, message):
    async with mcp_client(make_app(writes=True), **AUTH) as mcp:
        result = await mcp.call_tool(name, arguments)
    assert result.is_error
    assert result.structured_content["code"] == code
    assert message in result.structured_content["message"]


@pytest.mark.asyncio
async def test_a_manga_volume_copy_is_keyed_by_its_normalized_number():
    async with mcp_client(make_app(writes=True), **AUTH) as mcp:
        result = await mcp.call_tool(
            "add_shelf_copy", {"series_id": "md-abc", "item_kind": "volume", "volume_number": "03"}
        )
    out = result.structured_content
    assert (out["volume_number"], out["item_label"], out["format"]) == ("3", "Vol. 3", "tankobon")


@pytest.mark.asyncio
async def test_shelf_writes_are_hidden_while_mcp_writes_are_off():
    async with mcp_client(make_app(), **AUTH) as mcp:
        names = {tool.name for tool in (await mcp.list_tools()).tools}
        refused = await mcp.call_tool("add_shelf_copy", {"series_id": "1001", "item_kind": "issue", "item_id": "5002"})
    assert "list_shelf_copies" in names
    assert not {"add_shelf_copy", "set_shelf_copy"} & names
    assert refused.structured_content["code"] == "writes_disabled"
