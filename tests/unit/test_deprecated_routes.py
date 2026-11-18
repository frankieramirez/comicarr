#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Duplicate REST routes stay as deprecated aliases until 1.0.0 (#1501, ADR-0006)."""

import json
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from comicarr.app.ai import router as ai_router
from comicarr.app.core import db
from comicarr.app.core.tables import mcp_tool_calls
from comicarr.app.main import create_app
from comicarr.app.metadata import router as metadata_router
from comicarr.app.search import router as search_router
from comicarr.app.search import service as search_service
from comicarr.app.system import deprecated_routes, deprecations
from tests.mcp_harness import seed_library, teardown_library

ROUTE_ENTRIES = {
    "api-metadata-search": ("/api/metadata/search", "/api/search/comics"),
    "api-metadata-search-manga": ("/api/metadata/search/manga", "/api/search/manga"),
    "api-ai-chat-stream": ("/api/ai/chat/stream", "/api/ai/chat/turns/stream"),
}


@pytest.fixture(autouse=True)
def library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
    monkeypatch.setattr(deprecated_routes, "_calls", deprecated_routes.ToolCallRecorder())
    monkeypatch.setattr(deprecated_routes, "_warned", set())
    yield
    teardown_library()


@pytest.fixture
def warnings(monkeypatch):
    lines = []
    monkeypatch.setattr(deprecated_routes.logger, "warn", lambda message: lines.append(message))
    return lines


def _ctx():
    return SimpleNamespace(config=SimpleNamespace(MAL_ENABLED=False, MANGADEX_ENABLED=True))


def _last_called(entry_id):
    name = deprecations.route_usage_key(entry_id)
    row = db.select_one(select(mcp_tool_calls.c.last_called_at).where(mcp_tool_calls.c.tool_name == name))
    return row["last_called_at"] if row else None


def _body(response):
    return json.loads(response.body)


def test_metadata_search_answers_exactly_like_search_comics(monkeypatch, warnings):
    found = {"results": [{"comicid": "4050-1", "in_library": False}], "pagination": {"total": 1}}
    monkeypatch.setattr(search_service, "find_comic", lambda ctx, **kw: found)
    body = {"name": "Saga", "limit": 20}

    old = metadata_router.search_comics(body, ctx=_ctx())

    assert _body(old) == search_router.search_comics(body, ctx=_ctx()) == found
    assert old.headers["Deprecation"] == deprecated_routes.DEPRECATED_SINCE
    assert old.headers["Link"] == '<https://comicarr.com/docs/deprecations#api-metadata-search>; rel="deprecation"'


def test_metadata_search_manga_now_uses_the_manga_search_and_its_errors(monkeypatch, warnings):
    monkeypatch.setattr(search_service, "find_manga", lambda ctx, **kw: {"error": "Manga integration is not enabled"})

    old = metadata_router.search_manga({"name": "Dandadan"}, ctx=_ctx())
    new = search_router.search_manga({"name": "Dandadan"}, ctx=_ctx())

    assert old.status_code == new.status_code == 400
    assert _body(old) == _body(new)
    assert "deprecations#api-metadata-search-manga" in old.headers["Link"]


def test_a_missing_name_is_still_a_400_with_the_notice(warnings):
    old = metadata_router.search_comics({}, ctx=_ctx())

    assert old.status_code == 400
    assert _body(old) == {"detail": "Missing search name"}
    assert "Deprecation" in old.headers


def test_a_call_is_recorded_and_warned_about_once_per_process(monkeypatch, warnings):
    monkeypatch.setattr(search_service, "find_comic", lambda ctx, **kw: {"results": []})
    entry = deprecations.entry("api-metadata-search")
    assert entry.in_use() is False

    for _ in range(3):
        metadata_router.search_comics({"name": "Saga"}, ctx=_ctx())

    assert _last_called("api-metadata-search") is not None
    assert entry.in_use() is True
    assert len(warnings) == 1
    assert "POST /api/metadata/search was called" in warnings[0]
    assert "POST /api/search/comics" in warnings[0]


def test_an_alias_unused_for_30_days_drops_off_health():
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 31 * 86400))
    db.upsert("mcp_tool_calls", {"last_called_at": stamp}, {"tool_name": "route:api-metadata-search"})

    assert deprecations.entry("api-metadata-search").in_use() is False


@pytest.mark.asyncio
async def test_the_old_chat_stream_carries_the_notice(monkeypatch, warnings):
    async def fake_stream(messages, ctx):
        yield {"type": "text", "content": "hi"}
        yield {"type": "done"}

    monkeypatch.setattr(ai_router, "stream_chat_response", fake_stream)

    class FakeRequest:
        async def json(self):
            return {"messages": [{"role": "user", "content": "hello"}]}

    response = await ai_router.chat_stream(FakeRequest(), ctx=_ctx())

    assert response.media_type == "text/event-stream"
    assert "deprecations#api-ai-chat-stream" in response.headers["Link"]
    assert deprecations.entry("api-ai-chat-stream").in_use() is True


def test_each_alias_has_a_registry_entry_naming_its_replacement():
    for entry_id, (old, new) in ROUTE_ENTRIES.items():
        entry = deprecations.entry(entry_id)
        assert old in entry.name
        assert new in entry.replacement
        assert entry.removable_from == "1.0.0"
        assert entry.docs_url.endswith("#" + entry_id)


def test_openapi_marks_only_the_aliases_deprecated():
    paths = create_app().openapi()["paths"]

    for old, new in ROUTE_ENTRIES.values():
        assert paths[old]["post"]["deprecated"] is True
        assert "deprecated" not in paths[new]["post"]


def test_an_unknown_entry_id_fails_loudly():
    with pytest.raises(KeyError):
        deprecated_routes.headers("no-such-route")
