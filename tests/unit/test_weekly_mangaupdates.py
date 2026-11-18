#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Weekly manga, manhwa and manhua releases from MangaUpdates (#1383)."""

import datetime
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy import insert

from comicarr.app.core import db, runtime, workers
from comicarr.app.core.tables import comics, issues, metadata
from comicarr.app.weekly import mangaupdates
from comicarr.app.weekly import service as weekly_service

# Saturday closing the Sunday-based week of 2026-11-08 to 2026-11-14.
TODAY = datetime.date(2026, 11, 14)
NOW = 1_800_000_000.0


def _release(release_id, series_id, title, chapter, date, volume=None):
    return {
        "record": {"id": release_id, "chapter": chapter, "volume": volume, "release_date": date},
        "metadata": {"series": {"series_id": series_id, "title": title, "url": "https://example.test/%s" % series_id}},
    }


def _series(series_id, title, kind, image="https://cdn.mangaupdates.com/image/thumb/i1.jpg"):
    return {
        "series_id": series_id,
        "title": title,
        "type": kind,
        "year": "2024",
        "url": "https://example.test/%s" % series_id,
        "image": {"url": {"thumb": image, "original": image}},
    }


class FakeApi:
    """Answers MangaUpdates paths from fixtures and records every call."""

    def __init__(self, releases, popular, details=None):
        self.releases = releases
        self.popular = popular
        self.details = details or {}
        self.calls = []

    def __call__(self, method, path, *, params=None, body=None):
        self.calls.append((method, path))
        if path == "/releases/days":
            page = int(params["page"])
            chunk = self.releases[(page - 1) * 2 : page * 2]
            return {"total_hits": len(self.releases), "results": chunk}
        if path == "/series/search":
            if body["page"] > 1:
                return {"results": []}
            return {"results": [{"record": record} for record in self.popular]}
        series_id = path.rsplit("/", 1)[-1]
        if series_id in self.details:
            return self.details[series_id]
        raise mangaupdates.SourceError("HTTP 404")


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(CACHE_DIR=str(tmp_path), MANGADEX_ENABLED=True))
    monkeypatch.setattr(mangaupdates, "_cache", {"path": None, "mtime": None, "data": None})
    monkeypatch.setattr(mangaupdates, "_state", {"thread": None, "last_attempt": 0.0, "last_error": None})
    return tmp_path


def _api():
    return FakeApi(
        releases=[
            _release(1, 10, "Popular Manhwa", "411", "2026-11-11"),
            _release(2, 10, "Popular Manhwa", "412", "2026-11-12"),
            _release(3, 10, "Popular Manhwa", "412", "2026-11-12"),
            _release(4, 20, "Quiet Manga", "75 (end)", "2026-11-12"),
            _release(5, 30, "Volume Manga", None, "2026-11-13", volume="14"),
            _release(6, 40, "Last Week", "9", "2026-11-05"),
        ],
        popular=[_series(10, "Popular Manhwa", "Manhwa")],
        details={"20": _series(20, "Quiet Manga", "Manga"), "30": _series(30, "Volume Manga", "Manhua")},
    )


def test_refresh_pages_releases_and_looks_up_unknown_series(cache_dir, monkeypatch):
    api = _api()
    monkeypatch.setattr(mangaupdates, "_request", api)

    data = mangaupdates.refresh(now=NOW, today=TODAY)

    assert [call for call in api.calls if call[1] == "/releases/days"] == [("GET", "/releases/days")] * 3
    assert data["popular"] == {"10": 1}
    # Popular series come typed from the search; the rest are looked up once.
    assert ("GET", "/series/10") not in api.calls
    assert data["series"]["20"]["type"] == "Manga"
    assert (cache_dir / mangaupdates.CACHE_FILE).exists()


def test_cached_series_are_not_looked_up_again(cache_dir, monkeypatch):
    monkeypatch.setattr(mangaupdates, "_request", _api())
    mangaupdates.refresh(now=NOW, today=TODAY)
    api = _api()
    monkeypatch.setattr(mangaupdates, "_request", api)

    mangaupdates.refresh(now=NOW + 3600, today=TODAY)

    assert not [call for call in api.calls if call[1].startswith("/series/") and call[1] != "/series/search"]


def test_detail_lookups_are_capped_per_refresh(cache_dir, monkeypatch):
    api = _api()
    monkeypatch.setattr(mangaupdates, "_request", api)
    monkeypatch.setattr(mangaupdates, "DETAIL_LOOKUPS_PER_REFRESH", 1)

    data = mangaupdates.refresh(now=NOW, today=TODAY)

    lookups = [call for call in api.calls if call[1].startswith("/series/") and call[1] != "/series/search"]
    assert len(lookups) == 1
    # Newest first: the volume released on the 13th beats the chapter on the 12th.
    assert "30" in data["series"] and "20" not in data["series"]


def test_week_rows_collapse_each_series_to_one_row(cache_dir, monkeypatch):
    monkeypatch.setattr(mangaupdates, "_request", _api())
    data = mangaupdates.refresh(now=NOW, today=TODAY)

    rows = {row["COMIC"]: row for row in mangaupdates.week_rows("2026-11-08", "2026-11-14", data)}

    assert set(rows) == {"Popular Manhwa", "Quiet Manga", "Volume Manga"}
    popular = rows["Popular Manhwa"]
    assert (popular["ISSUE"], popular["chapters"], popular["SHIPDATE"]) == ("412", "411–412", "2026-11-12")
    assert popular["format"] == "Manhwa" and popular["popular_rank"] == 1
    assert popular["cover"].startswith("/api/metadata/image-proxy?url=https%3A%2F%2Fcdn.mangaupdates.com")
    assert rows["Quiet Manga"]["ISSUE"] == "75" and rows["Quiet Manga"]["popular_rank"] is None
    assert (rows["Volume Manga"]["ISSUE"], rows["Volume Manga"]["volume"]) == ("", "14")
    # Popular series sort first.
    assert mangaupdates.week_rows("2026-11-08", "2026-11-14", data)[0]["COMIC"] == "Popular Manhwa"


def test_failed_refresh_keeps_the_cache(cache_dir, monkeypatch):
    monkeypatch.setattr(mangaupdates, "_request", _api())
    mangaupdates.refresh(now=NOW, today=TODAY)

    def down(*_args, **_kwargs):
        raise mangaupdates.SourceError("unreachable")

    monkeypatch.setattr(mangaupdates, "_request", down)
    with pytest.raises(mangaupdates.SourceError):
        mangaupdates.refresh(now=NOW + 1, today=TODAY)

    assert len(mangaupdates.load()["releases"]) == 6


def test_ensure_fresh_starts_one_background_refresh(cache_dir, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def slow_refresh():
        started.set()
        release.wait(5)

    monkeypatch.setattr(mangaupdates, "_run_refresh", slow_refresh)
    registry = workers.BackgroundWorkerRegistry()
    monkeypatch.setattr(workers, "_runtime_registry", lambda: registry)

    assert mangaupdates.ensure_fresh(now=NOW) == "refreshing"
    assert started.wait(5)
    assert mangaupdates.ensure_fresh(now=NOW) == "refreshing"
    release.set()
    mangaupdates._state["thread"].join(5)
    # A fresh attempt just ran, so the retry gap holds off another one.
    assert mangaupdates.ensure_fresh(now=NOW + 60) == "ok"
    assert registry.snapshot() == ()


def test_fresh_cache_does_not_refresh(cache_dir, monkeypatch):
    monkeypatch.setattr(mangaupdates, "_request", _api())
    mangaupdates.refresh(now=NOW, today=TODAY)

    def boom():
        raise AssertionError("a fresh cache must not refresh")

    monkeypatch.setattr(mangaupdates, "_run_refresh", boom)

    assert mangaupdates.ensure_fresh(now=NOW + 60) == "ok"


def test_disabled_without_a_manga_provider(monkeypatch):
    assert mangaupdates.is_enabled(SimpleNamespace(MANGADEX_ENABLED=False, MAL_ENABLED=False)) is False
    assert mangaupdates.is_enabled(SimpleNamespace(MANGADEX_ENABLED=False, MAL_ENABLED=True, MAL_CLIENT_ID="x"))


@pytest.fixture
def library_db(cache_dir, monkeypatch):
    monkeypatch.setattr(runtime.current(), "data_dir", str(cache_dir))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def test_manga_rows_match_library_series_and_chapters(library_db, monkeypatch):
    with library_db.begin() as conn:
        conn.execute(
            insert(comics),
            [
                {
                    "ComicID": "md-1",
                    "ComicName": "Popular Manhwa!",
                    "AlternateSearch": None,
                    "ContentType": "manga",
                    "Status": "Active",
                },
                {
                    "ComicID": "mal-2",
                    "ComicName": "Shizuka na Manga",
                    "AlternateSearch": "Quiet Manga##Other",
                    "ContentType": "manga",
                    "Status": "Active",
                },
            ],
        )
        conn.execute(
            insert(issues),
            [{"IssueID": "c-412", "ComicID": "md-1", "Issue_Number": "412.0", "Status": "Wanted"}],
        )
    monkeypatch.setattr(mangaupdates, "_request", _api())
    mangaupdates.refresh(now=NOW, today=TODAY)
    monkeypatch.setattr(mangaupdates, "ensure_fresh", lambda force=False: "ok")
    window = weekly_service.week_window(today=TODAY)

    manga = weekly_service._manga_week(window)

    rows = {row["COMIC"]: row for row in manga["rows"]}
    assert manga["status"] == "ok"
    assert rows["Popular Manhwa"]["state"] == "wanted"
    assert rows["Popular Manhwa"]["ComicID"] == "md-1"
    assert rows["Popular Manhwa"]["library_issue_id"] == "c-412"
    assert rows["Quiet Manga"]["state"] == "in_library"
    assert rows["Volume Manga"]["state"] == "not_in_library"
    assert rows["Volume Manga"]["ComicID"] is None


def test_manga_week_is_disabled_without_a_provider(monkeypatch):
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(MANGADEX_ENABLED=False))

    manga = weekly_service._manga_week(weekly_service.week_window(today=TODAY))

    assert manga["status"] == "disabled" and manga["rows"] == []
