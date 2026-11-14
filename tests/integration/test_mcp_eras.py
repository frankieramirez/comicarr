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

import pytest

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
}


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
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
            assert not result.is_error, (name, result.content)
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
