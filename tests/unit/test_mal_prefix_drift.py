#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""MangaDex-added and MyAnimeList-added series must be treated alike.

Three places knew about "md-" and not "mal-", each of them a copy of the same
decision made somewhere else:

  * post-processing sent every MAL download down the ComicVine path,
  * the chapter poll skipped MAL series entirely,
  * and the MangaDex add path never recorded MangaDexID, so a series added that
    way was invisible to every lookup keyed on it.

The rule itself now lives in ``comicarr.series_kind`` and is tested against that
interface in ``test_series_kind.py``. What remains here is the integration
coverage: that each of these three call sites actually asks it.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select

import comicarr
from comicarr import rsscheck
from comicarr.postprocessor import PostProcessor
from comicarr.tables import comics, metadata


def _make_pp(comicid):
    lock = MagicMock()
    lock.locked.return_value = False
    config = MagicMock()
    config.FILE_OPTS = "move"
    config.IGNORE_SEARCH_WORDS = []
    config.PRE_SCRIPTS = None
    with patch.object(comicarr, "APILOCK", lock), patch.object(comicarr, "CONFIG", config):
        return PostProcessor(
            nzb_name="Chapter 1.cbz",
            nzb_folder="/tmp/downloads",
            comicid=comicid,
            queue=MagicMock(),
            apicall=True,
        )


class TestPostProcessingRoutesBothProviders:
    @pytest.mark.parametrize("comicid", ("md-abc123", "mal-161890"))
    def test_manga_ids_reach_the_manga_path(self, comicid):
        pp = _make_pp(comicid)

        with patch.object(pp, "_process_manga", return_value=None) as process_manga:
            pp.Process()

        process_manga.assert_called_once()

    def test_a_comicvine_id_still_does_not(self):
        pp = _make_pp("12345")

        with (
            patch.object(pp, "_process_manga") as process_manga,
            patch("comicarr.postprocessor.filechecker") as filechecker,
            patch("comicarr.postprocessor.db") as mock_db,
        ):
            mock_db.select_one.return_value = {"ComicID": "12345"}
            filechecker.FileChecker.return_value.listFiles.return_value = {"comiccount": 0, "comiclist": []}
            try:
                pp.Process()
            except Exception:
                pass

        process_manga.assert_not_called()


def _seed(engine, rows):
    with engine.begin() as conn:
        for row in rows:
            conn.execute(comics.insert(), row)


class TestChapterPollCoversBothProviders:
    def _run(self, monkeypatch, rows):
        engine = create_engine("sqlite://")
        metadata.create_all(engine)
        _seed(engine, rows)
        monkeypatch.setattr(rsscheck.db, "get_engine", lambda: engine)
        monkeypatch.setattr(rsscheck.db, "select_all", lambda stmt: _select_all(engine, stmt))

        polled = []
        import comicarr.mangadex as mangadex

        monkeypatch.setattr(
            mangadex,
            "get_all_chapters",
            lambda manga_id, *a, **k: polled.append(manga_id) or [],
        )
        rsscheck.mangadexNewChapterCheck()
        return polled

    def test_both_providers_are_polled_with_a_mangadex_id(self, monkeypatch):
        polled = self._run(
            monkeypatch,
            [
                {
                    "ComicID": "md-uuid-1",
                    "ComicName": "Chainsaw Man",
                    "ContentType": "manga",
                    "Status": "Active",
                },
                {
                    "ComicID": "mal-161890",
                    "ComicName": "Bleach",
                    "ContentType": "manga",
                    "Status": "Active",
                    "MangaDexID": "uuid-2",
                },
            ],
        )

        # Both providers resolve to a bare MangaDex uuid: md- series carry it in
        # the ComicID, mal- series in MangaDexID. The query has no ORDER BY, so
        # compare without depending on row order.
        assert sorted(polled) == ["uuid-1", "uuid-2"]

    def test_a_mal_series_without_a_resolved_uuid_is_skipped(self, monkeypatch):
        polled = self._run(
            monkeypatch,
            [
                {
                    "ComicID": "mal-999",
                    "ComicName": "Unresolved",
                    "ContentType": "manga",
                    "Status": "Active",
                }
            ],
        )

        assert polled == []

    def test_paused_series_are_left_alone(self, monkeypatch):
        polled = self._run(
            monkeypatch,
            [
                {
                    "ComicID": "md-uuid-3",
                    "ComicName": "Paused",
                    "ContentType": "manga",
                    "Status": "Paused",
                }
            ],
        )

        assert polled == []


def _select_all(engine, stmt):
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings()]


class TestMangaDexAddRecordsItsId:
    def test_mangadex_add_writes_mangadexid(self, monkeypatch, tmp_path):
        """The MAL path always recorded MangaDexID; the MangaDex path did not."""
        from comicarr import importer

        engine = create_engine("sqlite://")
        metadata.create_all(engine)
        monkeypatch.setattr(importer.db, "get_engine", lambda: engine)
        monkeypatch.setattr(comicarr, "COMICSORT", None, raising=False)
        monkeypatch.setattr(
            comicarr,
            "CONFIG",
            SimpleNamespace(
                MANGA_DIR=str(tmp_path),
                FOLDER_FORMAT="$Series",
                REPLACE_SPACES=False,
                CREATE_FOLDERS=False,
                ENFORCE_PERMS=False,
            ),
            raising=False,
        )
        import comicarr.mangadex as mangadex
        from comicarr import config as comicarr_config

        monkeypatch.setattr(
            mangadex,
            "get_manga_details",
            lambda *a, **k: {
                "id": "uuid-42",
                "title": "Chainsaw Man",
                "year": 2018,
                "status": "ongoing",
                "author": "Fujimoto",
                "description": "",
                "cover_url": None,
                "url": "https://mangadex.org/title/uuid-42",
                "alt_titles": [],
            },
        )
        monkeypatch.setattr(importer, "_populate_manga_chapters", lambda *a, **k: 0)
        monkeypatch.setattr(importer.helpers, "getImage", lambda *a, **k: None)
        monkeypatch.setattr(importer.helpers, "ComicSort", lambda **k: None)
        monkeypatch.setattr(comicarr_config, "get_manga_destination", lambda: str(tmp_path))

        importer.addMangaToDB("md-uuid-42")

        with engine.connect() as conn:
            row = conn.execute(select(comics).where(comics.c.ComicID == "md-uuid-42")).mappings().fetchone()

        assert row["MangaDexID"] == "uuid-42"
