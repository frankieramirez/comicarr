#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Unit tests for manga RSS / chapter monitoring in comicarr/rsscheck.py.

Tests cover mangaCheck() and mangadexNewChapterCheck() — the two additive
functions for manga series monitoring.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import event

import comicarr
from comicarr.db import get_engine, shutdown_engine
from comicarr.rsscheck import mangaCheck, mangadexNewChapterCheck, nzbdbsearch
from comicarr.tables import comics, metadata, rssdb

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_series(comic_id="md-abc123", name="One Piece", year="1999", status="Active"):
    return {
        "ComicID": comic_id,
        "ComicName": name,
        "ComicYear": year,
        "Status": status,
        "ComicPublisher": "Shueisha",
        "AlternateSearch": None,
        "UseFuzzy": None,
        "ComicVersion": None,
        "ComicName_Filesafe": name,
    }


def _make_chapter(comic_id="md-abc123", issue_id="md-abc123-ch100", ch_num="100", status="Wanted"):
    return {
        "IssueID": issue_id,
        "ComicID": comic_id,
        "ComicName": "One Piece",
        "Issue_Number": ch_num,
        "ChapterNumber": ch_num,
        "Status": status,
        "IssueDate": "2026-01-01",
        "ReleaseDate": "2026-01-01",
        "DigitalDate": "0000-00-00",
        "VolumeNumber": None,
    }


# ---------------------------------------------------------------------------
# mangaCheck tests
# ---------------------------------------------------------------------------


class TestMangaCheck:
    """Tests for mangaCheck() — wanted chapter search triggering."""

    @patch("comicarr.CONFIG", MagicMock(FAILED_DOWNLOAD_HANDLING=False, FAILED_AUTO=False))
    @patch("comicarr.rsscheck.helpers")
    @patch("comicarr.rsscheck.db")
    @patch("comicarr.search.search_init")
    def test_skips_when_no_manga_series(self, mock_search_init, mock_db, mock_helpers):
        mock_db.select_all.return_value = []

        mangaCheck()

        mock_search_init.assert_not_called()

    @patch("comicarr.CONFIG", MagicMock(FAILED_DOWNLOAD_HANDLING=False, FAILED_AUTO=False))
    @patch("comicarr.rsscheck.helpers")
    @patch("comicarr.rsscheck.db")
    @patch("comicarr.search.search_init")
    def test_triggers_search_for_wanted_chapters(self, mock_search_init, mock_db, mock_helpers):
        series = _make_series()
        chapter = _make_chapter()

        mock_db.select_all.side_effect = [
            [series],
            [chapter],
        ]
        mock_helpers.issue_status.return_value = False

        mangaCheck()

        assert mock_search_init.call_count == 1
        call_kwargs = mock_search_init.call_args
        assert call_kwargs[0][0] == "One Piece"
        assert call_kwargs[1]["booktype"] == "manga"

    @patch("comicarr.CONFIG", MagicMock(FAILED_DOWNLOAD_HANDLING=False, FAILED_AUTO=False))
    @patch("comicarr.rsscheck.helpers")
    @patch("comicarr.rsscheck.db")
    @patch("comicarr.search.search_init")
    def test_skips_already_downloaded_chapters(self, mock_search_init, mock_db, mock_helpers):
        series = _make_series()
        chapter = _make_chapter()

        mock_db.select_all.side_effect = [
            [series],
            [chapter],
        ]
        mock_helpers.issue_status.return_value = True

        mangaCheck()

        mock_search_init.assert_not_called()

    @patch("comicarr.CONFIG", MagicMock(FAILED_DOWNLOAD_HANDLING=False, FAILED_AUTO=False))
    @patch("comicarr.rsscheck.helpers")
    @patch("comicarr.rsscheck.db")
    @patch("comicarr.search.search_init")
    def test_handles_search_error_gracefully(self, mock_search_init, mock_db, mock_helpers):
        series = _make_series()
        ch1 = _make_chapter(ch_num="100", issue_id="md-abc123-ch100")
        ch2 = _make_chapter(ch_num="101", issue_id="md-abc123-ch101")

        mock_db.select_all.side_effect = [
            [series],
            [ch1, ch2],
        ]
        mock_helpers.issue_status.return_value = False
        mock_search_init.side_effect = [Exception("provider down"), None]

        mangaCheck()

        assert mock_search_init.call_count == 2

    @patch("comicarr.CONFIG", MagicMock(FAILED_DOWNLOAD_HANDLING=False, FAILED_AUTO=False))
    @patch("comicarr.rsscheck.helpers")
    @patch("comicarr.rsscheck.db")
    @patch("comicarr.search.search_init")
    def test_skips_series_with_no_wanted_chapters(self, mock_search_init, mock_db, mock_helpers):
        series = _make_series()

        mock_db.select_all.side_effect = [
            [series],
            [],
        ]

        mangaCheck()

        mock_search_init.assert_not_called()


class TestMangaCheckRssdb:
    """mangaCheck() against a real rssdb: per-series skip and the pass-scoped lookup memo."""

    PROVIDERS = ("nzb.one", "nzb.two", "nzb.three")
    ALT_NAMES = ("op", "wan pisu")

    @pytest.fixture
    def rss_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(
            comicarr, "CONFIG", SimpleNamespace(FAILED_DOWNLOAD_HANDLING=False, FAILED_AUTO=False), raising=False
        )
        monkeypatch.delenv("DATABASE_URL", raising=False)
        shutdown_engine()
        engine = get_engine()
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(comics.insert().values(ComicID="md-hit", ComicName="One Piece", AlternateSearch=None))
            conn.execute(comics.insert().values(ComicID="md-miss", ComicName="Dandadan", AlternateSearch=None))
        queries = []

        def count_rssdb(_conn, _cursor, statement, _params, _context, _many):
            if "FROM rssdb" in statement and "LIMIT" not in statement:
                queries.append(statement)

        event.listen(engine, "before_cursor_execute", count_rssdb)
        yield SimpleNamespace(engine=engine, rssdb_queries=queries)
        event.remove(engine, "before_cursor_execute", count_rssdb)
        shutdown_engine()

    @staticmethod
    def _add_rss_row(engine, title, site):
        with engine.begin() as conn:
            conn.execute(
                rssdb.insert().values(Title=title, Link="https://example/" + title, Pubdate="now", Site=site, Size="1")
            )

    def _run(self, mock_db, series_rows, chapters_by_series, search_init):
        mock_db.get_engine = get_engine
        mock_db.select_all.side_effect = [series_rows] + [chapters_by_series[row["ComicID"]] for row in series_rows]
        with patch("comicarr.rsscheck.helpers") as mock_helpers, patch("comicarr.search.search_init", search_init):
            mock_helpers.issue_status.return_value = False
            mangaCheck()

    def _series(self):
        return [
            _make_series(comic_id="md-hit", name="One Piece"),
            _make_series(comic_id="md-miss", name="Dandadan"),
        ]

    def _chapters(self):
        return {
            "md-hit": [
                _make_chapter(comic_id="md-hit", issue_id="md-hit-ch%s" % n, ch_num=str(n)) for n in (100, 101, 102)
            ],
            "md-miss": [_make_chapter(comic_id="md-miss", issue_id="md-miss-ch1", ch_num="1")],
        }

    def _lookup_every_provider_and_alt(self, results):
        def fake_search_init(*args, **kwargs):
            comic_id = kwargs["ComicID"]
            for provider in self.PROVIDERS:
                for alt in (args[0],) + self.ALT_NAMES:
                    results.append((comic_id, nzbdbsearch(alt, args[1], comic_id, provider, args[2], None, False)))

        return MagicMock(side_effect=fake_search_init)

    @patch("comicarr.rsscheck.db")
    def test_series_with_no_rss_rows_is_skipped(self, mock_db, rss_db):
        self._add_rss_row(rss_db.engine, "One Piece 100 (2026)", "nzb.one")
        search_init = MagicMock()

        self._run(mock_db, self._series(), self._chapters(), search_init)

        searched = [call.kwargs["ComicID"] for call in search_init.call_args_list]
        assert searched.count("md-miss") == 0
        assert searched.count("md-hit") == 3

    @patch("comicarr.rsscheck.db")
    def test_alternate_name_or_ddl_match_keeps_the_series(self, mock_db, rss_db):
        with rss_db.engine.begin() as conn:
            conn.execute(comics.update().where(comics.c.ComicID == "md-miss").values(AlternateSearch="Dan Da Dan"))
        self._add_rss_row(rss_db.engine, "Dan Da Dan 001", "nzb.one")
        with rss_db.engine.begin() as conn:
            conn.execute(rssdb.insert().values(Title="GC post", Link="l", Site="DDL(GetComics)", ComicName="One Piece"))
        series = self._series()
        series[1]["AlternateSearch"] = "Dan Da Dan"
        search_init = MagicMock()

        self._run(mock_db, series, self._chapters(), search_init)

        assert {call.kwargs["ComicID"] for call in search_init.call_args_list} == {"md-hit", "md-miss"}

    @patch("comicarr.rsscheck.db")
    def test_repeat_lookups_in_one_pass_hit_rssdb_once_per_provider(self, mock_db, rss_db):
        for provider in self.PROVIDERS:
            self._add_rss_row(rss_db.engine, "One Piece 100 [%s]" % provider, provider)
        results = []

        self._run(mock_db, self._series(), self._chapters(), self._lookup_every_provider_and_alt(results))

        assert len(results) == 3 * len(self.PROVIDERS) * (1 + len(self.ALT_NAMES))
        assert len(rss_db.rssdb_queries) == len(self.PROVIDERS)
        assert all(len(found["entries"]) == 1 for _comic_id, found in results)

    @patch("comicarr.rsscheck.db")
    def test_memo_is_dropped_between_passes(self, mock_db, rss_db):
        self._add_rss_row(rss_db.engine, "One Piece 100 [one]", "nzb.one")
        first = []
        self._run(mock_db, self._series(), self._chapters(), self._lookup_every_provider_and_alt(first))
        assert {comic_id for comic_id, _found in first} == {"md-hit"}

        self._add_rss_row(rss_db.engine, "One Piece 101 [one]", "nzb.one")
        self._add_rss_row(rss_db.engine, "Dandadan 001 [one]", "nzb.one")
        second = []
        self._run(mock_db, self._series(), self._chapters(), self._lookup_every_provider_and_alt(second))

        hit_titles = {
            entry["title"]
            for comic_id, found in second
            if comic_id == "md-hit" and found != "no results"
            for entry in found["entries"]
        }
        assert hit_titles == {"One Piece 100 [one]", "One Piece 101 [one]"}
        assert "md-miss" in {comic_id for comic_id, _found in second}

    def test_lookups_outside_a_pass_are_not_memoised(self, rss_db):
        self._add_rss_row(rss_db.engine, "One Piece 100 [one]", "nzb.one")

        nzbdbsearch("One Piece", "100", "md-hit", "nzb.one", "1999", None, False)
        nzbdbsearch("One Piece", "101", "md-hit", "nzb.one", "1999", None, False)

        assert len(rss_db.rssdb_queries) == 2


# ---------------------------------------------------------------------------
# mangadexNewChapterCheck tests
# ---------------------------------------------------------------------------


@patch("comicarr.CONFIG", MagicMock())
class TestMangadexNewChapterCheck:
    """Tests for mangadexNewChapterCheck() — MangaDex polling for new chapters."""

    @patch("comicarr.rsscheck.db")
    @patch("comicarr.mangadex.get_all_chapters")
    def test_skips_when_no_manga_series(self, mock_get_chapters, mock_db):
        mock_db.select_all.return_value = []

        mangadexNewChapterCheck()

        mock_get_chapters.assert_not_called()

    @patch("comicarr.rsscheck.db")
    @patch("comicarr.mangadex.get_all_chapters")
    def test_adds_new_chapters_as_wanted(self, mock_get_chapters, mock_db):
        series = _make_series()

        mock_db.select_all.side_effect = [
            [series],
            [],
        ]
        mock_get_chapters.return_value = [
            {
                "id": "ch-uuid-1",
                "chapter": "1",
                "volume": "1",
                "title": "Romance Dawn",
                "publish_at": "1999-07-22T00:00:00+00:00",
            },
            {
                "id": "ch-uuid-2",
                "chapter": "2",
                "volume": "1",
                "title": "They Call Him Straw Hat Luffy",
                "publish_at": "1999-07-29T00:00:00+00:00",
            },
        ]

        mangadexNewChapterCheck()

        assert mock_db.upsert.call_count == 2

        first_call = mock_db.upsert.call_args_list[0]
        assert first_call[0][0] == "issues"
        value_dict = first_call[0][1]
        assert value_dict["ComicName"] == "One Piece"
        assert value_dict["ChapterNumber"] == "1"
        assert value_dict["Status"] == "Wanted"
        assert value_dict["VolumeNumber"] == "1"
        key_dict = first_call[0][2]
        assert key_dict["IssueID"] == "md-abc123-ch1"

    @patch("comicarr.rsscheck.db")
    @patch("comicarr.mangadex.get_all_chapters")
    def test_skips_existing_chapters(self, mock_get_chapters, mock_db):
        series = _make_series()

        mock_db.select_all.side_effect = [
            [series],
            [{"IssueID": "md-abc123-ch1", "ChapterNumber": "1"}],
        ]
        mock_get_chapters.return_value = [
            {"id": "ch-uuid-1", "chapter": "1", "volume": None, "title": "Ch 1"},
            {"id": "ch-uuid-2", "chapter": "2", "volume": None, "title": "Ch 2"},
        ]

        mangadexNewChapterCheck()

        assert mock_db.upsert.call_count == 1
        value_dict = mock_db.upsert.call_args_list[0][0][1]
        assert value_dict["ChapterNumber"] == "2"

    @patch("comicarr.rsscheck.db")
    @patch("comicarr.mangadex.get_all_chapters")
    def test_handles_api_error_gracefully(self, mock_get_chapters, mock_db):
        series = _make_series()

        mock_db.select_all.side_effect = [
            [series],
            [],
        ]
        mock_get_chapters.side_effect = Exception("API timeout")

        mangadexNewChapterCheck()

        mock_db.upsert.assert_not_called()

    @patch("comicarr.rsscheck.db")
    @patch("comicarr.mangadex.get_all_chapters")
    def test_skips_chapters_with_no_number(self, mock_get_chapters, mock_db):
        series = _make_series()

        mock_db.select_all.side_effect = [
            [series],
            [],
        ]
        mock_get_chapters.return_value = [
            {"id": "ch-uuid-1", "chapter": None, "volume": "1", "title": "Oneshot"},
        ]

        mangadexNewChapterCheck()

        mock_db.upsert.assert_not_called()

    @patch("comicarr.rsscheck.db")
    @patch("comicarr.mangadex.get_all_chapters")
    def test_handles_none_from_api(self, mock_get_chapters, mock_db):
        series = _make_series()

        mock_db.select_all.side_effect = [
            [series],
            [],
        ]
        mock_get_chapters.return_value = None

        mangadexNewChapterCheck()

        mock_db.upsert.assert_not_called()

    @patch("comicarr.rsscheck.db")
    @patch("comicarr.mangadex.get_all_chapters")
    def test_volume_number_none_when_not_provided(self, mock_get_chapters, mock_db):
        series = _make_series()

        mock_db.select_all.side_effect = [
            [series],
            [],
        ]
        mock_get_chapters.return_value = [
            {"id": "ch-uuid-1", "chapter": "5", "volume": None, "title": "Ch 5"},
        ]

        mangadexNewChapterCheck()

        value_dict = mock_db.upsert.call_args_list[0][0][1]
        assert value_dict["VolumeNumber"] is None
