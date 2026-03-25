"""
Tests for comicarr.app.metadata domain — Phase 2.

Covers: search routing, comic/issue info lookup, metatag operations.
"""

from unittest.mock import MagicMock, patch

import pytest

from comicarr.app.core.context import AppContext
from comicarr.app.metadata import service as metadata_service


def _make_test_ctx(**overrides):
    """Create a test AppContext for metadata domain tests."""
    config = MagicMock()
    config.MANGADEX_ENABLED = True
    config.CACHE_DIR = "/tmp/test_cache"
    config.HTTP_USERNAME = "admin"
    config.HTTP_PASSWORD = "hash"

    defaults = {
        "config": config,
        "jwt_secret_key": b"test_secret_key_32_bytes_padding!",
        "jwt_generation": 0,
    }
    defaults.update(overrides)
    return AppContext(**defaults)


# =============================================================================
# Search Service Tests
# =============================================================================


class TestSearchComics:
    def test_empty_name_returns_error(self):
        """Search with empty name returns error."""
        ctx = _make_test_ctx()
        result = metadata_service.search_comics(ctx, name="")
        assert "error" in result

    @patch("comicarr.mb")
    def test_comic_search_delegates_to_mb(self, mock_mb):
        """Comic search delegates to mb.findComic."""
        ctx = _make_test_ctx()
        mock_mb.findComic.return_value = [
            {"comicyear": "2020", "issues": 10, "haveit": "No"},
        ]

        result = metadata_service.search_comics(ctx, name="Batman")
        mock_mb.findComic.assert_called_once()
        assert "results" in result
        assert result["results"][0]["in_library"] is False

    @patch("comicarr.mb")
    def test_search_adds_in_library_flag(self, mock_mb):
        """Search adds in_library boolean based on haveit field."""
        ctx = _make_test_ctx()
        mock_mb.findComic.return_value = [
            {"comicyear": "2020", "issues": 5, "haveit": {"id": "123"}},
            {"comicyear": "2021", "issues": 3, "haveit": "No"},
        ]

        result = metadata_service.search_comics(ctx, name="Spider-Man")
        # Results are sorted by (comicyear, issues) descending — 2021 before 2020
        in_lib_flags = [r["in_library"] for r in result["results"]]
        assert True in in_lib_flags
        assert False in in_lib_flags

    @patch("comicarr.mb")
    def test_paginated_results_preserved(self, mock_mb):
        """Paginated results (dict with 'results' key) are preserved."""
        ctx = _make_test_ctx()
        mock_mb.findComic.return_value = {
            "results": [{"comicyear": "2020", "issues": 5, "haveit": "No"}],
            "pagination": {"total": 100, "limit": 10, "offset": 0},
        }

        result = metadata_service.search_comics(ctx, name="X-Men", limit=10, offset=0)
        assert "pagination" in result
        assert result["pagination"]["total"] == 100

    def test_invalid_pagination_returns_error(self):
        """Invalid pagination params return error."""
        ctx = _make_test_ctx()
        result = metadata_service.search_comics(ctx, name="Batman", limit="abc")
        assert "error" in result


class TestSearchManga:
    def test_manga_disabled_returns_error(self):
        """Manga search returns error when MangaDex is disabled."""
        ctx = _make_test_ctx()
        ctx.config.MANGADEX_ENABLED = False

        result = metadata_service.search_manga(ctx, name="One Piece")
        assert "error" in result

    @patch("comicarr.mangadex", create=True)
    def test_manga_search_delegates(self, mock_mangadex):
        """Manga search delegates to mangadex.search_manga."""
        ctx = _make_test_ctx()
        mock_mangadex.search_manga.return_value = {
            "results": [{"title": "One Piece"}],
            "pagination": {"total": 1},
        }

        result = metadata_service.search_manga(ctx, name="One Piece")
        mock_mangadex.search_manga.assert_called_once()


# =============================================================================
# Series Image Tests
# =============================================================================


class TestGetSeriesImage:
    def test_invalid_id_returns_none(self):
        """Non-numeric series ID returns None."""
        ctx = _make_test_ctx()
        result = metadata_service.get_series_image(ctx, "not-a-number")
        assert result is None

    @patch("comicarr.metron", create=True)
    def test_delegates_to_metron(self, mock_metron):
        """Valid series ID delegates to metron.get_series_image."""
        ctx = _make_test_ctx()
        mock_metron.get_series_image.return_value = "https://example.com/cover.jpg"

        result = metadata_service.get_series_image(ctx, "12345")
        assert result == "https://example.com/cover.jpg"


# =============================================================================
# Comic/Issue Info Tests
# =============================================================================


class TestGetComicInfo:
    @patch("comicarr.db")
    def test_returns_comic_data(self, mock_db):
        """get_comic_info returns comic data when found."""
        ctx = _make_test_ctx()
        mock_db.select_all.return_value = [{"ComicID": "123", "ComicName": "Batman"}]

        result = metadata_service.get_comic_info(ctx, "123")
        assert result["ComicName"] == "Batman"

    @patch("comicarr.db")
    def test_returns_none_when_not_found(self, mock_db):
        """get_comic_info returns None when comic not found."""
        ctx = _make_test_ctx()
        mock_db.select_all.return_value = []

        result = metadata_service.get_comic_info(ctx, "nonexistent")
        assert result is None


class TestGetIssueInfo:
    @patch("comicarr.db")
    def test_returns_issue_data(self, mock_db):
        """get_issue_info returns issue data when found."""
        ctx = _make_test_ctx()
        mock_db.select_all.return_value = [{"IssueID": "456", "Issue_Number": "1"}]

        result = metadata_service.get_issue_info(ctx, "456")
        assert result["Issue_Number"] == "1"


# =============================================================================
# Metatag Tests
# =============================================================================


class TestMetatag:
    @patch("comicarr.app.metadata.service._do_manual_metatag")
    def test_manual_metatag_success(self, mock_do_metatag):
        """manual_metatag calls internal _do_manual_metatag."""
        ctx = _make_test_ctx()

        result = metadata_service.manual_metatag(ctx, "issue123", "comic456")
        assert result["success"] is True
        mock_do_metatag.assert_called_once_with("issue123", comicid="comic456")

    @patch("comicarr.app.metadata.service._do_bulk_metatag")
    def test_bulk_metatag_success(self, mock_do_bulk):
        """bulk_metatag calls internal _do_bulk_metatag."""
        ctx = _make_test_ctx()

        issue_ids = ["issue1", "issue2", "issue3"]
        result = metadata_service.bulk_metatag(ctx, "comic456", issue_ids)
        assert result["success"] is True
        assert result["count"] == 3
        mock_do_bulk.assert_called_once_with("comic456", issue_ids)

    @patch("comicarr.app.metadata.service._do_manual_metatag")
    def test_metatag_handles_error(self, mock_do_metatag):
        """Metatag returns error on exception."""
        ctx = _make_test_ctx()
        mock_do_metatag.side_effect = Exception("tagging failed")

        result = metadata_service.manual_metatag(ctx, "issue123")
        assert result["success"] is False
        assert "tagging failed" in result["error"]
