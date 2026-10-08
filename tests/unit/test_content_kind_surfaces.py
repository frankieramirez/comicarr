#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Operator content kind must agree across sync, dashboard, and post-processing."""

import queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr import db, series_kind
from comicarr.app.core.context import AppContext
from comicarr.app.dashboard import queries as dashboard_queries
from comicarr.app.manga.sync import list_active_manga_series
from comicarr.app.series import service as series_service
from comicarr.postprocessor import PostProcessor
from comicarr.series_kind import manga_sql_clause
from comicarr.tables import comics, metadata


@pytest.fixture
def query_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _ctx():
    return AppContext(
        config=SimpleNamespace(
            COMIC_DIR=None,
            MANGA_DIR=None,
            DESTINATION_DIR=None,
            MANGA_DESTINATION_DIR=None,
            MULTIPLE_DEST_DIRS=None,
            NEWCOM_DIR=None,
        )
    )


def _seed_row(**overrides):
    row = {
        "ComicName": "Example",
        "Status": "Active",
        "Have": 1,
        "Total": 1,
    }
    row.update(overrides)
    return row


def _make_pp(comicid):
    mock_queue = MagicMock(spec=queue.Queue)
    mock_apilock = MagicMock()
    mock_apilock.locked.return_value = False
    mock_config = MagicMock()
    mock_config.FILE_OPTS = "move"
    mock_config.IGNORE_SEARCH_WORDS = []
    mock_config.PRE_SCRIPTS = None
    with patch.object(comicarr, "APILOCK", mock_apilock), patch.object(comicarr, "CONFIG", mock_config):
        return PostProcessor(
            nzb_name="Example 001.cbz",
            nzb_folder="/tmp/downloads",
            comicid=comicid,
            issueid="issue-1",
            queue=mock_queue,
            apicall=True,
        )


def _postprocess_uses_manga_branch(row):
    pp = _make_pp(row["ComicID"])
    with (
        patch.object(pp, "_process_manga", return_value=None) as process_manga,
        patch("comicarr.postprocessor.filechecker") as filechecker,
        patch("comicarr.postprocessor.db") as mock_db,
    ):
        mock_db.select_one.return_value = row
        filechecker.FileChecker.return_value.listFiles.return_value = {"comiccount": 0, "comiclist": []}
        try:
            pp.Process()
        except Exception:
            pass
    return process_manga.called


def test_operator_content_kind_agrees_across_surfaces(query_db):
    with query_db.begin() as conn:
        conn.execute(
            insert(comics),
            [
                _seed_row(ComicID="md-a", ComicName="Reclassified", ContentType="manga"),
                _seed_row(ComicID="md-b", ComicName="Kept manga", ContentType="manga"),
                _seed_row(ComicID="4050-1", ComicName="A Comic", ContentType="comic"),
                _seed_row(ComicID="md-c", ComicName="Legacy prefix", ContentType=None),
            ],
        )

    result = series_service.update_content_kind(_ctx(), "md-a", "comic")
    assert result["success"] is True
    assert result["content_type"] == "comic"

    rows = {row["ComicID"]: dict(row) for row in db.select_all(select(comics))}
    expected_manga = {"md-a": False, "md-b": True, "4050-1": False, "md-c": True}

    active_ids = {row["ComicID"] for row in list_active_manga_series()}
    clause_ids = {
        row["ComicID"]
        for row in db.select_all(
            select(comics.c.ComicID).where(manga_sql_clause(comics.c.ComicID, comics.c.ContentType))
        )
    }
    manga_stats = dashboard_queries.get_library_stats("manga")
    comic_stats = dashboard_queries.get_library_stats("comic")

    for comic_id, want_manga in expected_manga.items():
        row = rows[comic_id]
        assert series_kind.is_manga(row) is want_manga
        assert (comic_id in active_ids) is want_manga
        assert (comic_id in clause_ids) is want_manga
        assert _postprocess_uses_manga_branch(row) is want_manga

    assert manga_stats["manga_series"] == 2
    assert comic_stats["comic_series"] == 2
    assert active_ids == {"md-b", "md-c"}
