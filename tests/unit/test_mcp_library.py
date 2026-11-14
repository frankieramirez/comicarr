#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""MCP library writes: add_series and refresh_series (#1309)."""

import pytest
from sqlalchemy import func, select

from comicarr import importer
from comicarr.app.series import add as series_add
from comicarr.app.series import location as series_location
from comicarr.db import get_engine
from comicarr.tables import activity_events, comics, issues
from tests.mcp_harness import KEY, make_app, mcp_client, seed_library, teardown_library

AUTH = {"Authorization": "Bearer " + KEY}


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
    yield
    teardown_library()


@pytest.fixture
def providers(monkeypatch):
    """Fake the mass-add worker: an add writes the series and two Skipped issues at once."""
    added, wanted, refreshed = [], [], []

    def queue_adds(series):
        with get_engine().begin() as conn:
            for watch in series:
                comic_id = watch["comicid"]
                added.append(comic_id)
                if conn.execute(select(comics.c.ComicID).where(comics.c.ComicID == comic_id)).first():
                    continue
                conn.execute(comics.insert().values(ComicID=comic_id, ComicName="New %s" % comic_id, Status="Active"))
                for n in (1, 2):
                    conn.execute(
                        issues.insert().values(
                            IssueID="%s-%d" % (comic_id, n), ComicID=comic_id, Issue_Number=str(n), Status="Skipped"
                        )
                    )

    def queue_wants(comic_ids):
        for comic_id in comic_ids:
            wanted.append(comic_id)
            importer.markSeriesWanted(comic_id)

    monkeypatch.setattr(series_add, "queue_series_adds", queue_adds)
    monkeypatch.setattr(series_add, "queue_series_wants", queue_wants)
    monkeypatch.setattr(series_add, "refresh_series", lambda watch: refreshed.extend(w["comicid"] for w in watch))
    monkeypatch.setattr(series_location, "folder_for_new_series", lambda *_a, **_k: None)
    monkeypatch.setattr("comicarr.app.manga.duplicates.find_existing_manga_series", lambda **_k: None, raising=False)
    return {"added": added, "wanted": wanted, "refreshed": refreshed}


def _app():
    app = make_app(writes=True)
    app.state.ctx.config.MANGADEX_ENABLED = True
    return app


def _statuses(comic_id):
    with get_engine().connect() as conn:
        rows = conn.execute(select(issues.c.Status).where(issues.c.ComicID == comic_id)).fetchall()
    return sorted(row[0] for row in rows)


def _series_count(comic_id):
    with get_engine().connect() as conn:
        return conn.execute(select(func.count()).select_from(comics).where(comics.c.ComicID == comic_id)).scalar()


def _actor_rows(activity):
    with get_engine().connect() as conn:
        rows = conn.execute(
            select(activity_events.c.subject_id, activity_events.c.actor).where(activity_events.c.activity == activity)
        ).fetchall()
    return [tuple(row) for row in rows]


@pytest.mark.asyncio
async def test_add_series_adds_a_comic_and_a_manga_and_get_series_can_read_them(providers):
    async with mcp_client(_app(), **AUTH) as mcp:
        comic = await mcp.call_tool("add_series", {"provider": "comicvine", "provider_id": "4050-777", "kind": "comic"})
        manga = await mcp.call_tool("add_series", {"provider": "mangadex", "provider_id": "abc-123", "kind": "manga"})
    assert not comic.is_error, comic.content[0].text
    assert not manga.is_error, manga.content[0].text
    assert comic.structured_content == {"series_id": "777", "already_in_library": False, "want_queued": False}
    assert manga.structured_content["series_id"] == "md-abc-123"
    assert providers["added"] == ["777", "md-abc-123"]
    assert _series_count("777") == 1 and _series_count("md-abc-123") == 1
    assert _statuses("777") == ["Skipped", "Skipped"]
    assert sorted(_actor_rows("add")) == [("777", "mcp"), ("md-abc-123", "mcp")]


@pytest.mark.asyncio
async def test_add_series_with_want_marks_its_issues_wanted(providers):
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool(
            "add_series", {"provider": "comicvine", "provider_id": "888", "kind": "comic", "want": True}
        )
    assert result.structured_content["want_queued"] is True
    assert providers["wanted"] == ["888"]
    assert _statuses("888") == ["Wanted", "Wanted"]


@pytest.mark.asyncio
async def test_adding_the_same_series_twice_returns_it_and_creates_no_duplicate(providers):
    arguments = {"provider": "comicvine", "provider_id": "999", "kind": "comic"}
    async with mcp_client(_app(), **AUTH) as mcp:
        first = await mcp.call_tool("add_series", arguments)
        second = await mcp.call_tool("add_series", arguments)
        library = await mcp.call_tool("add_series", {"provider": "comicvine", "provider_id": "1001", "kind": "comic"})
    assert first.structured_content["series_id"] == second.structured_content["series_id"] == "999"
    assert second.structured_content["already_in_library"] is True
    assert "already in the library" in second.content[0].text
    assert library.structured_content == {"series_id": "1001", "already_in_library": True, "want_queued": False}
    assert providers["added"] == ["999"]
    assert _series_count("999") == 1


@pytest.mark.asyncio
async def test_a_kind_that_does_not_match_the_provider_is_invalid_argument(providers):
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool("add_series", {"provider": "mangadex", "provider_id": "x", "kind": "comic"})
    assert result.is_error and result.structured_content["code"] == "invalid_argument"
    assert providers["added"] == []


@pytest.mark.asyncio
async def test_an_unreachable_or_disabled_provider_is_provider_unavailable(providers, monkeypatch):
    monkeypatch.setattr("comicarr.metron.get_cv_id", lambda _id: None)
    app = make_app(writes=True)
    async with mcp_client(app, **AUTH) as mcp:
        metron = await mcp.call_tool("add_series", {"provider": "metron", "provider_id": "55", "kind": "comic"})
        manga = await mcp.call_tool("add_series", {"provider": "mangadex", "provider_id": "y", "kind": "manga"})
    for result, retryable in ((metron, True), (manga, False)):
        assert result.is_error
        assert result.structured_content["code"] == "provider_unavailable"
        # Metron may answer next time; a switched-off integration will not.
        assert result.structured_content["retryable"] is retryable
    assert providers["added"] == []


@pytest.mark.asyncio
async def test_refresh_series_queues_a_known_series_and_refuses_an_unknown_one(providers):
    async with mcp_client(_app(), **AUTH) as mcp:
        known = await mcp.call_tool("refresh_series", {"series_id": "1001"})
        unknown = await mcp.call_tool("refresh_series", {"series_id": "nope"})
    assert not known.is_error, known.content[0].text
    assert known.structured_content == {"series_id": "1001", "already_queued": False}
    assert providers["refreshed"] == ["1001"]
    assert _actor_rows("refresh") == [("1001", "mcp")]
    assert unknown.is_error and unknown.structured_content["code"] == "not_found"


def test_the_mass_add_worker_marks_a_queued_series_wanted_after_its_adds(monkeypatch):
    """The real worker loop routes a ``{"series": id}`` want to markSeriesWanted."""
    import queue

    calls = []
    monkeypatch.setattr(importer, "markSeriesWanted", calls.append)
    monkeypatch.setattr(importer.time, "sleep", lambda _s: None)
    series_queue, want_queue = queue.Queue(), queue.Queue()
    want_queue.put({"series": "1001"})
    importer.addvialist(series_queue, want_queue)
    assert calls == ["1001"]
