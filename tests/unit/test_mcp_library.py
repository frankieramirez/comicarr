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
from comicarr.tables import activity_events, annuals, comics, issues
from tests.mcp_harness import KEY, make_app, mcp_client, seed_library, teardown_library

AUTH = {"Authorization": "Bearer " + KEY}


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
    yield
    teardown_library()


@pytest.fixture
def providers(monkeypatch):
    """Fake the mass-add worker: an add writes the series, two Skipped issues and a
    Skipped annual at once, then marks them Wanted when the add carries ``want``."""
    added, wanted, refreshed = [], [], []

    def queue_adds(series):
        with get_engine().begin() as conn:
            for watch in series:
                comic_id = watch["comicid"]
                added.append(comic_id)
                existing = conn.execute(select(comics.c.ComicName).where(comics.c.ComicID == comic_id)).first()
                if existing and not existing[0].startswith("Fetch failed"):
                    continue
                conn.execute(comics.delete().where(comics.c.ComicID == comic_id))
                conn.execute(comics.insert().values(ComicID=comic_id, ComicName="New %s" % comic_id, Status="Active"))
                for n in (1, 2):
                    conn.execute(
                        issues.insert().values(
                            IssueID="%s-%d" % (comic_id, n), ComicID=comic_id, Issue_Number=str(n), Status="Skipped"
                        )
                    )
                conn.execute(
                    annuals.insert().values(
                        IssueID="%s-a1" % comic_id,
                        ComicID=comic_id,
                        Issue_Number="1",
                        Status="Skipped",
                        Deleted=None,  # legacy rows can carry NULL, not the 0 default
                    )
                )
        for watch in series:
            if watch.get("want"):
                wanted.append(watch["comicid"])
                importer.markSeriesWanted(watch["comicid"])

    monkeypatch.setattr(series_add, "queue_series_adds", queue_adds)
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


def _annual_statuses(comic_id):
    with get_engine().connect() as conn:
        rows = conn.execute(select(annuals.c.Status).where(annuals.c.ComicID == comic_id)).fetchall()
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
    assert _annual_statuses("888") == ["Wanted"]


@pytest.mark.asyncio
async def test_a_series_left_by_a_failed_fetch_is_added_again_not_reported_as_in_the_library(providers):
    with get_engine().begin() as conn:
        conn.execute(
            comics.insert().values(ComicID="555", ComicName="Fetch failed, try refreshing. (555)", Status="Active")
        )
    async with mcp_client(_app(), **AUTH) as mcp:
        result = await mcp.call_tool("add_series", {"provider": "comicvine", "provider_id": "555", "kind": "comic"})
    assert result.structured_content == {"series_id": "555", "already_in_library": False, "want_queued": False}
    assert providers["added"] == ["555"]
    assert _series_count("555") == 1


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
    monkeypatch.setattr("comicarr.app.metadata.metron.get_cv_id", lambda _id: None)
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


def test_the_mass_add_worker_marks_a_series_wanted_right_after_an_add_that_carries_want(monkeypatch):
    """The real worker loop runs markSeriesWanted after addComictoDB for an add with ``want``."""
    import queue

    calls = []
    monkeypatch.setattr(importer, "addComictoDB", lambda comicid, **_k: calls.append(("add", comicid)))
    monkeypatch.setattr(importer, "markSeriesWanted", lambda comicid: calls.append(("want", comicid)))
    monkeypatch.setattr(importer, "emit_add_activity", lambda *_a, **_k: None)
    monkeypatch.setattr(importer.time, "sleep", lambda _s: None)
    series_queue, want_queue = queue.Queue(), queue.Queue()
    series_queue.put({"comicid": "4050-1001", "comicname": None, "seriesyear": None, "want": True})
    series_queue.put({"comicid": "1002", "comicname": None, "seriesyear": None})
    importer.addvialist(series_queue, want_queue)
    assert calls == [("add", "4050-1001"), ("want", "1001"), ("add", "1002")]


def test_a_retry_that_fails_again_keeps_the_failed_fetch_marker(monkeypatch):
    """Two failed fetches in a row through the real addComictoDB leave a row that
    the next add still treats as retryable."""
    from types import SimpleNamespace

    import comicarr
    from comicarr.app.series import queries as series_queries

    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(IMP_PATHS=False), raising=False)
    monkeypatch.setattr(importer.cv, "getComic", lambda *_a, **_k: None)
    monkeypatch.setattr(importer.helpers, "ComicSort", lambda *_a, **_k: None)
    for _attempt in range(2):
        assert importer.addComictoDB("4321")["status"] == "incomplete"
        assert series_queries.is_failed_add_placeholder("4321")
