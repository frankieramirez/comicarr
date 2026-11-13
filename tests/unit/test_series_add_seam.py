#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Characterization tests for Series add behind ``app/series/add.py`` (#1209).

They pin what ``importer.addComictoDB``, ``addMangaToDB``, ``addMangaToDB_MAL``
and the worker queues do today when ``comicarr/app/`` calls them through
``comicarr.app.series.add``. ComicVine, MangaDex and MyAnimeList are faked;
nothing touches the network. They describe current behavior, not intended
behavior.
"""

import queue
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select

import comicarr
from comicarr import db, importer
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.series import add as series_add
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, issues, metadata

MD_UUID = "aaaaaaaa-bbbb-cccc-dddd-onepiece01"
MAL_ID = "13"


@pytest.fixture
def library(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///%s" % (tmp_path / "library.db"))
    metadata.create_all(engine)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(comicarr, "COMICSORT", None, raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            COMICVINE_API="test-key",
            CV_VERIFY=True,
            AUTOWANT_ALL=True,
            AUTOWANT_UPCOMING=True,
            CHMOD_DIR="0755",
            ENFORCE_PERMS=False,
            CREATE_FOLDERS=False,
            IMP_PATHS=False,
            ANNUALS_ON=False,
            DESTINATION_DIR=str(tmp_path / "library"),
            MANGA_DIR=str(tmp_path / "manga"),
            FOLDER_FORMAT="$Series",
            REPLACE_SPACES=False,
        ),
        raising=False,
    )
    yield engine
    engine.dispose()


def _row(table, column, value):
    return db.select_one(select(table).where(column == value))


def test_add_series_metadata_only_stores_paused_series_and_skipped_issues(library, tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "CVURL", "https://comicvine.gamespot.com/api/")
    monkeypatch.setattr(comicarr, "CV_RATE_LIMITER", MagicMock())
    session = MagicMock()
    monkeypatch.setattr(comicarr, "CV_SESSION", session)
    volume = {
        "id": 123,
        "name": "Example",
        "start_year": "2020",
        "count_of_issues": 1,
        "publisher": {"name": "Publisher"},
        "site_detail_url": "https://example/123",
    }
    issue = {"id": 456, "volume": {"id": 123}, "issue_number": "1", "cover_date": "2020-01-01"}
    session.get.side_effect = [
        MagicMock(json=lambda: {"status_code": 1, "results": volume}),
        MagicMock(json=lambda: {"status_code": 1, "results": [issue], "number_of_total_results": 1}),
    ]
    monkeypatch.setattr(
        "comicarr.filers.FileHandlers.folder_create",
        lambda self: {"comlocation": str(tmp_path / "library" / "Example (2020)")},
    )
    monkeypatch.setattr("comicarr.filers.FileHandlers.series_folder_collision_detection", lambda *a: None)
    search = MagicMock()
    monkeypatch.setattr("comicarr.search.searchforissue", search)

    result = series_add.add_series("4050-123", metadata_only=True)

    assert result == {"status": "complete", "comicid": "123", "comicname": "Example", "added": True}
    assert _row(comics, comics.c.ComicID, "123")["Status"] == "Paused"
    assert _row(issues, issues.c.IssueID, "456")["Status"] == "Skipped"
    search.assert_not_called()


def test_add_series_provider_failure_leaves_fetch_failed_placeholder(library, monkeypatch):
    get_comic = MagicMock(return_value=None)
    emit = MagicMock()
    monkeypatch.setattr(importer.cv, "getComic", get_comic)
    monkeypatch.setattr(importer.helpers, "ComicSort", lambda **k: None)
    monkeypatch.setattr("comicarr.app.activity.producers.emit_series_activity", emit)

    result = series_add.add_series("999")

    # A failed fetch returns instead of raising, and keeps an Active
    # placeholder row named after the failure; no add activity is narrated.
    assert result == {"status": "incomplete"}
    get_comic.assert_called_once_with("999", "comic", series=True)
    row = _row(comics, comics.c.ComicID, "999")
    assert row["ComicName"] == "Fetch failed, try refreshing. (999)"
    assert row["Status"] == "Active"
    emit.assert_not_called()


@pytest.mark.parametrize(
    ("comic_id", "name", "provider_ids"),
    [
        ("md-" + MD_UUID, "One Piece (MangaDex)", {"MangaDexID": MD_UUID, "MalID": MAL_ID}),
        ("mal-" + MAL_ID, "One Piece (MyAnimeList)", {"MalID": MAL_ID}),
    ],
)
def test_add_manga_adds_series_from_its_provider(library, tmp_path, monkeypatch, comic_id, name, provider_ids):
    import comicarr.mangadex as mangadex
    import comicarr.myanimelist as myanimelist
    from comicarr import config as comicarr_config

    details = {
        "year": 1997,
        "status": "ongoing",
        "author": "Oda",
        "description": "",
        "cover_url": None,
        "alt_titles": [],
    }
    monkeypatch.setattr(
        mangadex,
        "get_manga_details",
        lambda *a, **k: {
            **details,
            "name": "One Piece (MangaDex)",
            "id": "md-" + MD_UUID,
            "url": "https://mangadex.org/title/x",
            "mal_id": MAL_ID,
        },
    )
    monkeypatch.setattr(
        myanimelist,
        "get_manga_details",
        lambda *a, **k: {
            **details,
            "name": "One Piece (MyAnimeList)",
            "url": "https://myanimelist.net/manga/13",
            "last_chapter": None,
        },
    )
    monkeypatch.setattr(mangadex, "find_by_mal_id", lambda *a, **k: None)
    monkeypatch.setattr(importer, "_populate_manga_chapters", lambda *a, **k: 0)
    monkeypatch.setattr(importer.helpers, "getImage", lambda *a, **k: None)
    monkeypatch.setattr(importer.helpers, "ComicSort", lambda **k: None)
    monkeypatch.setattr(comicarr_config, "get_manga_destination", lambda: str(tmp_path / "manga"))

    result = series_add.add_manga(comic_id)

    assert result["status"] == "complete"
    assert result["comicid"] == comic_id
    row = _row(comics, comics.c.ComicID, comic_id)
    assert row["ComicName"] == name
    for column, value in provider_ids.items():
        assert row[column] == value


@pytest.fixture
def acquisition_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    metadata.create_all(get_engine())
    assert ensure_acquisition_schema(get_engine()).ready
    yield RunLedger(get_engine())
    shutdown_engine()


def test_refresh_series_records_run_then_hands_it_to_the_refresh_queue(acquisition_ledger, monkeypatch):
    refresh_queue = queue.Queue()
    start_worker = MagicMock()
    monkeypatch.setattr(importer, "_mass_add_runtime_context", lambda: None)
    monkeypatch.setattr(comicarr, "REFRESH_QUEUE", refresh_queue)
    monkeypatch.setattr(importer, "_start_refresh_worker", start_worker)

    run_id = series_add.refresh_series([{"comicid": 160294, "comicname": "Absolute Batman", "seriesyear": "2024"}])

    assert refresh_queue.get_nowait() == {
        "comicid": "160294",
        "comicname": "Absolute Batman",
        "seriesyear": "2024",
        "run_id": run_id,
    }
    assert refresh_queue.empty()
    assert acquisition_ledger.get_item(run_id, "series", "160294")["state"] == "accepted"
    assert acquisition_ledger.get_run(run_id)["accepted_count"] == 1
    start_worker.assert_called_once_with()
    assert series_add.refresh_series([]) is None


def test_queue_series_adds_and_issue_wants_feed_the_mass_add_worker(monkeypatch):
    add_list = queue.Queue()
    issue_watch_list = queue.Queue()
    running = SimpleNamespace(is_alive=lambda: True)
    monkeypatch.setattr(importer, "_mass_add_runtime_context", lambda: None)
    monkeypatch.setattr(comicarr, "ADD_LIST", add_list)
    monkeypatch.setattr(comicarr, "ISSUE_WATCH_LIST", issue_watch_list)
    monkeypatch.setattr(comicarr, "MASS_ADD", running, raising=False)
    watch = {"comicid": "123", "comicname": None, "seriesyear": None, "location": "/library/Example"}

    series_add.queue_series_adds([watch])
    series_add.queue_issue_wants(["456"])

    assert add_list.get_nowait() == watch
    assert issue_watch_list.get_nowait() == "456"
    assert comicarr.MASS_ADD is running
