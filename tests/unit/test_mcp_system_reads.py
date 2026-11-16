#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""MCP releases, health and discovery reads (#1306)."""

import datetime
import json
import types

import pytest
from sqlalchemy import insert

from comicarr import mb
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.weekly import service as weekly_service
from comicarr.db import get_engine
from comicarr.tables import jobhistory, weekly
from tests.mcp_harness import KEY, LEGACY, MODERN, make_app, mcp_client, seed_library, teardown_library

AUTH = "Bearer " + KEY

SECRETS = {
    "COMICVINE_API": "cv-secret-4f1e9a",
    "SAB_APIKEY": "sab-secret-77c2d0",
    "SAB_PASSWORD": "sab-password-19aa",
    "QBITTORRENT_PASSWORD": "qbit-password-a51b",
    "METRON_PASSWORD": "metron-password-c3d4",
}


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
    assert ensure_acquisition_schema(get_engine()).ready
    yield
    teardown_library()


async def _call(name, arguments, app=None):
    async with mcp_client(app or make_app(), Authorization=AUTH) as mcp:
        return await mcp.call_tool(name, arguments)


def _seed_this_week():
    window = weekly_service.week_window()
    with get_engine().begin() as conn:
        for comic, issue, comic_id in (("Saga", "66", "1001"), ("Absolute Batman", "14", "158000")):
            conn.execute(
                insert(weekly).values(
                    COMIC=comic,
                    ISSUE=issue,
                    PUBLISHER="Image" if comic == "Saga" else "DC",
                    SHIPDATE=window["start"],
                    STATUS="Skipped",
                    ComicID=comic_id,
                    weeknumber=window["week"],
                    year=window["year"],
                )
            )
    return window


@pytest.mark.asyncio
async def test_get_weekly_releases_marks_followed_series():
    window = _seed_this_week()
    page = (await _call("get_weekly_releases", {})).structured_content
    assert (page["week"], page["year"], page["source"]) == (window["week"], window["year"], "stored")
    assert (page["total"], page["followed"]) == (2, 1)
    by_name = {r["series_name"]: r for r in page["releases"]}
    saga, batman = by_name["Saga"], by_name["Absolute Batman"]
    assert (saga["series_id"], saga["issue_id"], saga["state"]) == ("1001", "5001", "in_library")
    assert (batman["series_id"], batman["comicvine_id"], batman["state"]) == (None, "158000", "not_in_library")

    followed = (await _call("get_weekly_releases", {"followed_only": True})).structured_content
    assert [r["series_name"] for r in followed["releases"]] == ["Saga"]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [{"week": 10}, {"week": 1, "year": 1990}])
async def test_get_weekly_releases_rejects_a_bad_week(arguments):
    result = await _call("get_weekly_releases", arguments)
    assert result.is_error and result.structured_content["code"] == "invalid_argument"


@pytest.mark.asyncio
async def test_get_system_health_reports_jobs_and_routes_without_any_secret(monkeypatch):
    app = make_app()
    config = app.state.ctx.config
    for key, value in SECRETS.items():
        setattr(config, key, value)
    config.SAB_HOST = "http://sab.local:8080"
    config.NZB_DOWNLOADER = 0
    with get_engine().begin() as conn:
        conn.execute(
            insert(jobhistory).values(
                JobName="RSS Feeds",
                status="Waiting",
                prev_run_timestamp=1_763_100_000.0,
                last_failure_timestamp=1_763_100_000.0,
                last_error="GET https://indexer.example/api?apikey=%s failed" % SECRETS["SAB_APIKEY"],
            )
        )
    job = types.SimpleNamespace(
        id="rss",
        name="RSS Feeds",
        next_run_time=datetime.datetime(2026, 11, 14, 20, 0, tzinfo=datetime.timezone.utc),
        trigger="interval[0:20:00]",
    )
    app.state.ctx.scheduler = types.SimpleNamespace(get_jobs=lambda: [job])

    result = await _call("get_system_health", {}, app=app)
    assert not result.is_error, result.content
    health = result.structured_content
    assert [route["route"] for route in health["routes"]] == ["ddl", "nzb", "torrent"]
    assert health["can_search"] in (True, False)
    [rss] = health["jobs"]
    assert (rss["job_id"], rss["status"], rss["next_run"]) == ("rss", "Waiting", "2026-11-14 20:00:00+00:00")
    assert rss["last_failure"].startswith("2025-11-14")
    assert any(c["key"] == "comicvine" for c in health["connections"])

    rendered = json.dumps(health) + "".join(block.text for block in result.content)
    for secret in SECRETS.values():
        assert secret not in rendered, secret
    assert "sab.local" not in rendered


def _comicvine_and_metron_results(*_args, **_kwargs):
    return [
        {
            "name": "Saga",
            "comicyear": "2012",
            "comicid": "1001",
            "url": "https://comicvine.gamespot.com/saga/4050-1001/",
            "issues": "66",
            "publisher": "Image",
            "haveit": "1001",
        },
        {
            "name": "Saga of the Swamp Thing",
            "comicyear": "1982",
            "comicid": "metron-2211",
            "url": "https://metron.cloud/series/2211/",
            "issues": "45",
            "publisher": "DC",
            "haveit": "No",
        },
    ]


@pytest.mark.asyncio
async def test_find_series_returns_ids_in_add_series_terms(monkeypatch):
    monkeypatch.setattr(mb, "findComic", _comicvine_and_metron_results)
    page = (await _call("find_series", {"name": "Saga"})).structured_content
    assert [(r["provider"], r["provider_id"], r["kind"], r["in_library"]) for r in page["results"]] == [
        ("comicvine", "1001", "comic", True),
        ("metron", "2211", "comic", False),
    ]
    assert page["total"] == 2


@pytest.mark.asyncio
async def test_find_series_finds_manga_on_mangadex(monkeypatch):
    from comicarr.app.manga import mangadex

    monkeypatch.setattr(
        mangadex,
        "search_manga",
        lambda *_a, **_k: {
            "results": [{"name": "Dandadan", "comicyear": "2021", "comicid": "md-abc", "haveit": "md-abc"}],
            "pagination": {"total": 1},
        },
    )
    app = make_app()
    app.state.ctx.config.MANGADEX_ENABLED = True
    page = (await _call("find_series", {"name": "Dandadan", "kind": "manga"}, app=app)).structured_content
    assert [(r["provider"], r["provider_id"], r["in_library"]) for r in page["results"]] == [("mangadex", "abc", True)]


@pytest.mark.asyncio
async def test_find_series_turns_a_provider_failure_into_provider_unavailable(monkeypatch):
    def outage(*_args, **_kwargs):
        raise ConnectionError("comicvine.gamespot.com timed out")

    monkeypatch.setattr(mb, "findComic", outage)
    result = await _call("find_series", {"name": "Saga"})
    assert result.is_error
    assert result.structured_content["code"] == "provider_unavailable"
    assert result.structured_content["retryable"] is True


@pytest.mark.asyncio
async def test_find_series_says_when_manga_is_turned_off():
    result = await _call("find_series", {"name": "Dandadan", "kind": "manga"})
    assert result.is_error and result.structured_content["code"] == "provider_unavailable"
    assert result.structured_content["retryable"] is False


@pytest.mark.asyncio
async def test_find_series_with_no_match_is_an_empty_page(monkeypatch):
    monkeypatch.setattr(mb, "findComic", lambda *_a, **_k: [])
    page = (await _call("find_series", {"name": "Nothing Like This"})).structured_content
    assert (page["results"], page["total"]) == ([], 0)


@pytest.mark.asyncio
async def test_find_series_treats_a_returned_provider_error_as_retryable(monkeypatch):
    from comicarr.app.search import service as search_service

    monkeypatch.setattr(
        search_service,
        "find_comic",
        lambda *_a, **_k: {"error": "Metron could not look up this series. Check the connection and try again."},
    )
    result = await _call("find_series", {"name": "https://metron.cloud/series/2211/"})
    assert result.is_error
    assert (result.structured_content["code"], result.structured_content["retryable"]) == (
        "provider_unavailable",
        True,
    )


@pytest.mark.asyncio
async def test_find_series_keeps_the_provider_total_past_the_last_page(monkeypatch):
    from comicarr.app.manga import mangadex

    monkeypatch.setattr(mangadex, "search_manga", lambda *_a, **_k: {"results": [], "pagination": {"total": 10}})
    app = make_app()
    app.state.ctx.config.MANGADEX_ENABLED = True
    page = (await _call("find_series", {"name": "Dandadan", "kind": "manga", "offset": 25}, app=app)).structured_content
    assert (page["results"], page["total"], page["next_offset"]) == ([], 10, None)


def test_health_hides_a_bearer_token_and_a_folder_path():
    from comicarr.app.mcp.tools.system import _connection_result
    from comicarr.app.search.health import _sanitize

    assert "s3cret" not in _sanitize("401 with Authorization: Bearer s3cret-token")
    assert "s3cret" not in _sanitize("Authorization=Basic s3cret")
    assert _connection_result("Folder not found: /srv/private/ddl") == "Folder not found"
    assert _connection_result("Comicarr can't write to /srv/private/ddl") == "Comicarr can't write to the folder"
    assert _connection_result("Connected") == "Connected"


@pytest.mark.asyncio
async def test_health_reports_an_unwritable_folder_without_its_path(monkeypatch):
    from comicarr.app.system import connections

    row = {"key": "ddl_folder", "label": "Direct-download folder", "kind": "folder", "ok": False}
    row["result"] = "Comicarr can't write to /srv/private/ddl"
    monkeypatch.setattr(connections, "snapshot", lambda *_a, **_k: [row])
    health = (await _call("get_system_health", {})).structured_content
    [folder] = [c for c in health["connections"] if c["key"] == "ddl_folder"]
    assert (folder["ok"], folder["result"]) == (False, "Comicarr can't write to the folder")
    assert "/srv/private" not in json.dumps(health)


@pytest.mark.asyncio
async def test_get_search_run_reports_progress():
    ledger = RunLedger()
    ledger.create_run("run-42", "search", "manual", scope_type="series", scope_id="1001")
    ledger.accept_item("run-42", "issue", "5001")
    run = (await _call("get_search_run", {"run_id": "run-42"})).structured_content
    assert (run["run_id"], run["scope_id"], run["accepted"], run["items_total"]) == ("run-42", "1001", 1, 1)
    assert [(i["entity_id"], i["status"]) for i in run["items"]] == [("5001", "queued")]


@pytest.mark.asyncio
async def test_get_search_run_on_an_unknown_run_is_not_found():
    result = await _call("get_search_run", {"run_id": "no-such-run"})
    assert result.is_error and result.structured_content["code"] == "not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, version", [("legacy", LEGACY), (MODERN, MODERN)], ids=[LEGACY, MODERN])
async def test_each_tool_answers_with_faked_providers_in_each_protocol_era(monkeypatch, mode, version):
    monkeypatch.setattr(mb, "findComic", _comicvine_and_metron_results)
    _seed_this_week()
    RunLedger().create_run("run-1", "search", "manual")
    calls = {
        "get_weekly_releases": ({}, lambda out: out["followed"] == 1),
        "get_system_health": ({}, lambda out: len(out["routes"]) == 3),
        "find_series": ({"name": "Saga"}, lambda out: out["total"] == 2),
        "get_search_run": ({"run_id": "run-1"}, lambda out: out["run_id"] == "run-1"),
    }
    async with mcp_client(make_app(), mode=mode, Authorization=AUTH) as mcp:
        assert mcp.session.protocol_version == version
        for name, (arguments, check) in calls.items():
            result = await mcp.call_tool(name, arguments)
            assert not result.is_error, (name, result.content)
            assert check(result.structured_content), (name, result.structured_content)


def _mangadex_answers(monkeypatch, response):
    """Drive the real mangadex.search_manga with ``response`` from its HTTP layer."""
    from comicarr.app.manga import mangadex

    monkeypatch.setattr(mangadex, "_make_request", lambda *_a, **_k: response)
    monkeypatch.setattr(mangadex, "listLibrary", lambda: {})
    monkeypatch.setattr(
        mangadex.comicarr, "CONFIG", types.SimpleNamespace(MANGADEX_ENABLED=True, MANGADEX_CONTENT_RATING=None)
    )
    app = make_app()
    app.state.ctx.config.MANGADEX_ENABLED = True
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, {"result": "error", "errors": [{"status": 503}]}])
async def test_find_series_reports_a_failed_mangadex_search_as_retryable(monkeypatch, response):
    # #1329: a failed MangaDex request is not "No manga series matched".
    app = _mangadex_answers(monkeypatch, response)
    result = await _call("find_series", {"name": "Dandadan", "kind": "manga"}, app=app)
    assert result.is_error
    assert (result.structured_content["code"], result.structured_content["retryable"]) == (
        "provider_unavailable",
        True,
    )


@pytest.mark.asyncio
async def test_find_series_keeps_a_genuine_mangadex_no_match_an_empty_page(monkeypatch):
    app = _mangadex_answers(monkeypatch, {"result": "ok", "data": [], "total": 0})
    page = (await _call("find_series", {"name": "Nothing Like This", "kind": "manga"}, app=app)).structured_content
    assert (page["results"], page["total"]) == ([], 0)


def test_manga_search_surfaces_a_mangadex_failure_after_a_myanimelist_error(monkeypatch):
    from comicarr.app.manga import mangadex, myanimelist
    from comicarr.app.search import service as search_service

    def mal_down(*_a, **_k):
        raise ConnectionError("myanimelist.net timed out")

    monkeypatch.setattr(myanimelist, "search_manga", mal_down)
    monkeypatch.setattr(mangadex, "_make_request", lambda *_a, **_k: None)
    monkeypatch.setattr(mangadex, "listLibrary", lambda: {})
    monkeypatch.setattr(
        mangadex.comicarr, "CONFIG", types.SimpleNamespace(MANGADEX_ENABLED=True, MANGADEX_CONTENT_RATING=None)
    )
    ctx = types.SimpleNamespace(
        config=types.SimpleNamespace(MAL_ENABLED=True, MAL_CLIENT_ID="client", MANGADEX_ENABLED=True)
    )

    assert search_service.find_manga(ctx, "Dandadan") == {"error": mangadex.SEARCH_FAILED_ERROR}
    assert search_service.find_comic(ctx, "Dandadan", content_type="manga") == {"error": mangadex.SEARCH_FAILED_ERROR}
