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

import sys
from unittest.mock import MagicMock, patch

import pytest

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
    }


@pytest.fixture(autouse=True)
def _isolate_module():
    """Remove rsscheck from the module cache so each test gets a fresh import
    with its own patches applied."""
    mods_to_remove = [k for k in sys.modules if k.startswith("comicarr.rsscheck")]
    for m in mods_to_remove:
        del sys.modules[m]
    yield
    mods_to_remove = [k for k in sys.modules if k.startswith("comicarr.rsscheck")]
    for m in mods_to_remove:
        del sys.modules[m]


# ---------------------------------------------------------------------------
# mangaCheck tests
# ---------------------------------------------------------------------------


class TestMangaCheck:
    """Tests for mangaCheck() — wanted chapter search triggering."""

    @patch("comicarr.rsscheck.helpers")
    @patch("comicarr.rsscheck.db")
    @patch("comicarr.search.search_init")
    def test_skips_when_no_manga_series(self, mock_search_init, mock_db, mock_helpers):
        mock_db.select_all.return_value = []

        from comicarr.rsscheck import mangaCheck

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
            [series],   # first call: manga series query
            [chapter],  # second call: wanted chapters query
        ]
        mock_helpers.issue_status.return_value = False  # not already downloaded

        from comicarr.rsscheck import mangaCheck

        mangaCheck()

        assert mock_search_init.call_count == 1
        call_kwargs = mock_search_init.call_args
        # First positional arg is comic name
        assert call_kwargs[0][0] == "One Piece"
        # Check booktype kwarg
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
        mock_helpers.issue_status.return_value = True  # already downloaded

        from comicarr.rsscheck import mangaCheck

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

        from comicarr.rsscheck import mangaCheck

        # Should not raise even though first search fails
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
            [],  # no wanted chapters
        ]

        from comicarr.rsscheck import mangaCheck

        mangaCheck()

        mock_search_init.assert_not_called()


# ---------------------------------------------------------------------------
# mangadexNewChapterCheck tests
# ---------------------------------------------------------------------------


class TestMangadexNewChapterCheck:
    """Tests for mangadexNewChapterCheck() — MangaDex polling for new chapters."""

    @patch("comicarr.rsscheck.db")
    @patch("comicarr.mangadex.get_all_chapters")
    def test_skips_when_no_manga_series(self, mock_get_chapters, mock_db):
        mock_db.select_all.return_value = []

        from comicarr.rsscheck import mangadexNewChapterCheck

        mangadexNewChapterCheck()

        mock_get_chapters.assert_not_called()

    @patch("comicarr.rsscheck.db")
    @patch("comicarr.mangadex.get_all_chapters")
    def test_adds_new_chapters_as_wanted(self, mock_get_chapters, mock_db):
        series = _make_series()

        # First call: manga series; second call: existing issues
        mock_db.select_all.side_effect = [
            [series],
            [],  # no existing issues
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

        from comicarr.rsscheck import mangadexNewChapterCheck

        mangadexNewChapterCheck()

        assert mock_db.upsert.call_count == 2

        # Verify first upsert call
        first_call = mock_db.upsert.call_args_list[0]
        assert first_call[0][0] == "issues"  # table name
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
            [{"IssueID": "md-abc123-ch1", "ChapterNumber": "1"}],  # ch 1 exists
        ]
        mock_get_chapters.return_value = [
            {"id": "ch-uuid-1", "chapter": "1", "volume": None, "title": "Ch 1"},
            {"id": "ch-uuid-2", "chapter": "2", "volume": None, "title": "Ch 2"},
        ]

        from comicarr.rsscheck import mangadexNewChapterCheck

        mangadexNewChapterCheck()

        # Only chapter 2 should be inserted (chapter 1 already exists)
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

        from comicarr.rsscheck import mangadexNewChapterCheck

        # Should not raise
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

        from comicarr.rsscheck import mangadexNewChapterCheck

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

        from comicarr.rsscheck import mangadexNewChapterCheck

        # Should not raise
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

        from comicarr.rsscheck import mangadexNewChapterCheck

        mangadexNewChapterCheck()

        value_dict = mock_db.upsert.call_args_list[0][0][1]
        assert value_dict["VolumeNumber"] is None
