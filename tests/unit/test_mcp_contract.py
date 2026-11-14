#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""The MCP tool contract: names, and the ``tools/list`` snapshot (#1303).

``tests/contract/mcp_tools.json`` records every tool, writes included, by name, title,
description, input and output schemas and annotations. Any change to
``tools/list`` fails here until the snapshot changes in the same pull request.
After an intended change, regenerate it and review the diff::

    UPDATE_MCP_SNAPSHOT=1 pytest tests/unit/test_mcp_contract.py

``tests/contract/mcp_tool_names.txt`` lists every name ``tools/list`` has
published (#1312). Regenerating only adds to it, so a name that disappears
without an MCP tool entry in the deprecation registry fails here even after
the snapshot is updated. Delete a line by hand only when its registry entry's
window has run out and the entry goes too.
"""

import json
import os
from pathlib import Path

import pytest
from mcp import Client

from comicarr.app.mcp.contracts import VERBS
from comicarr.app.system.deprecations import REGISTRY
from tests.mcp_harness import make_app

SNAPSHOT = Path(__file__).resolve().parents[1] / "contract" / "mcp_tools.json"
PUBLISHED_NAMES = SNAPSHOT.with_name("mcp_tool_names.txt")


def vanished_names(published, listed, registered):
    """Published names no longer listed and not covered by a registry entry."""
    return sorted(set(published) - set(listed) - set(registered))


def _registered_tool_names(registry=REGISTRY):
    return {entry.mcp_tool for entry in registry if entry.mcp_tool}


def _read_published():
    return [line.strip() for line in PUBLISHED_NAMES.read_text(encoding="utf-8").splitlines() if line.strip()]


def verb_problems(names):
    """Names that break ``verb_noun``: no noun, not snake_case, or a verb outside VERBS."""
    problems = []
    for name in names:
        verb, _, noun = name.partition("_")
        if not noun or name != name.lower() or not name.replace("_", "").isalnum():
            problems.append("%s: not verb_noun snake_case" % name)
        elif verb not in VERBS:
            problems.append("%s: verb %r is not in contracts.VERBS" % (name, verb))
    return problems


async def _listed_tools():
    app = make_app(writes=True)
    async with Client(app.state.mcp.server) as client:
        tools = (await client.list_tools()).tools
    return sorted(
        (
            tool.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
                include={"name", "title", "description", "input_schema", "output_schema", "annotations"},
            )
            for tool in tools
        ),
        key=lambda tool: tool["name"],
    )


def _render(tools):
    return json.dumps(tools, indent=2, sort_keys=True) + "\n"


@pytest.mark.asyncio
async def test_tools_list_matches_the_snapshot():
    rendered = _render(await _listed_tools())
    if os.environ.get("UPDATE_MCP_SNAPSHOT"):
        SNAPSHOT.write_text(rendered, encoding="utf-8")
    assert SNAPSHOT.read_text(encoding="utf-8") == rendered, (
        "tools/list changed. If intended, run UPDATE_MCP_SNAPSHOT=1 pytest tests/unit/test_mcp_contract.py "
        "and commit tests/contract/mcp_tools.json in this pull request."
    )


@pytest.mark.asyncio
async def test_no_published_tool_name_disappears_without_a_registry_entry():
    listed = [tool["name"] for tool in await _listed_tools()]
    if os.environ.get("UPDATE_MCP_SNAPSHOT"):
        names = sorted(set(_read_published()) | set(listed))
        PUBLISHED_NAMES.write_text("".join(name + "\n" for name in names), encoding="utf-8")
    published = _read_published()
    assert vanished_names(published, listed, _registered_tool_names()) == [], (
        "These MCP tool names left tools/list. Keep each as an alias "
        "(deprecations.mcp_tool_rename in comicarr/app/system/deprecations.py) for the ADR-0006 window."
    )
    assert sorted(set(listed) - set(published)) == [], (
        "New tool names are missing from tests/contract/mcp_tool_names.txt. "
        "Run UPDATE_MCP_SNAPSHOT=1 pytest tests/unit/test_mcp_contract.py."
    )


def test_the_vanished_check_fails_a_removed_name_and_passes_a_registered_one():
    assert vanished_names(["list_series", "get_series"], ["list_series"], set()) == ["get_series"]
    assert vanished_names(["list_series", "get_series"], ["list_series"], {"get_series"}) == []


@pytest.mark.asyncio
async def test_every_tool_is_named_verb_noun_with_an_allowed_verb():
    assert verb_problems(tool["name"] for tool in await _listed_tools()) == []


def test_the_name_check_rejects_an_unlisted_verb_and_a_bad_shape():
    assert verb_problems(["list_series", "get_issue_story"]) == []
    assert verb_problems(["fetch_series", "series", "List_series", "list-series"]) == [
        "fetch_series: verb 'fetch' is not in contracts.VERBS",
        "series: not verb_noun snake_case",
        "List_series: not verb_noun snake_case",
        "list-series: not verb_noun snake_case",
    ]


@pytest.mark.asyncio
async def test_every_tool_publishes_an_output_schema_a_title_and_annotations():
    for tool in await _listed_tools():
        assert tool.get("title"), tool["name"]
        assert tool.get("outputSchema"), tool["name"]
        assert tool.get("annotations"), tool["name"]
