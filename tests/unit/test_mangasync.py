"""
Unit tests for comicarr/mangasync.py — Manga Library Scanner.

Tests cover the scan-then-select flow: existing series get chapters
auto-updated, new series are collected for user selection.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_globals():
    """Patch comicarr globals so mangasync can be imported without app init."""
    mock_config = MagicMock()
    mock_config.MANGA_DIR = "/manga"
    mock_config.MAL_ENABLED = False
    mock_config.MAL_CLIENT_ID = None
    mock_config.MANGADEX_ENABLED = True

    with (
        patch("comicarr.CONFIG", mock_config),
        patch("comicarr.mangasync.logger") as mock_log,
        patch("comicarr.mangasync.db") as mock_db,
    ):
        mock_log.fdebug = lambda *a, **kw: None
        mock_log.info = lambda *a, **kw: None
        mock_log.warning = lambda *a, **kw: None
        mock_log.error = lambda *a, **kw: None
        yield {"config": mock_config, "logger": mock_log, "db": mock_db}


@pytest.fixture
def mangasync():
    """Import mangasync fresh for each test and reset globals."""
    from comicarr import mangasync as ms

    ms.MANGA_SCAN_STATUS = None
    ms.MANGA_SCAN_PROGRESS = {
        "total_files": 0,
        "processed_files": 0,
        "series_found": 0,
        "series_matched": 0,
        "series_imported": 0,
        "current_series": None,
        "errors": [],
    }
    ms.MANGA_SCAN_RESULTS = None
    ms.MANGA_SCAN_ID = None
    if ms._SCAN_LOCK.locked():
        ms._SCAN_LOCK.release()
    return ms


def _mock_db_engine(mock_globals, rows=None):
    """Helper to set up a mock DB engine returning given rows."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value = rows or []
    mock_engine.connect.return_value.__enter__ = lambda s: mock_conn
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    mock_globals["db"].get_engine.return_value = mock_engine
    return mock_conn


class TestCheckExistingSeries:
    """Tests for _check_existing_series — auto-updating library series."""

    def test_existing_series_returns_result(self, mangasync, _mock_globals):
        mock_row = MagicMock()
        mock_row._mapping = {"ComicID": "md-123", "ComicName": "Bleach", "ContentType": "manga"}
        mock_conn = _mock_db_engine(_mock_globals, rows=[mock_row])

        with patch.object(mangasync, "_mark_chapters_downloaded", return_value=5):
            result = mangasync._check_existing_series("Bleach", [])

        assert result is not None
        assert result["chapters_downloaded"] == 5
        assert result["comic_id"] == "md-123"

    def test_new_series_returns_none(self, mangasync, _mock_globals):
        _mock_db_engine(_mock_globals, rows=[])

        result = mangasync._check_existing_series("NewSeries", [])
        assert result is None


class TestMatchSeries:
    """Tests for _match_series — matching new series against providers."""

    def test_mangadex_match(self, mangasync, _mock_globals):
        mangadex_results = {
            "results": [
                {
                    "name": "One Piece",
                    "comicid": "md-456",
                    "comicyear": "1997",
                    "comicthumb": "http://example.com/thumb.jpg",
                    "comicimage": "http://example.com/image.jpg",
                    "alt_titles": [],
                },
            ],
        }

        with patch("comicarr.mangadex.search_manga", return_value=mangadex_results):
            result = mangasync._match_series("One Piece", [("/manga/One Piece/v01.cbz", None)])

        assert result["matched"] is True
        assert result["match"]["comicid"] == "md-456"
        assert result["match"]["source"] == "mangadex"
        assert result["match"]["confidence"] == 100

    def test_no_match_found(self, mangasync, _mock_globals):
        with patch("comicarr.mangadex.search_manga", return_value={"results": []}):
            result = mangasync._match_series("Unknown Manga", [])

        assert result["matched"] is False
        assert result["match"] is None

    def test_mangadex_unreachable(self, mangasync, _mock_globals):
        with patch("comicarr.mangadex.search_manga", return_value=None):
            result = mangasync._match_series("Some Manga", [])

        assert result["matched"] is False


class TestMangaScan:
    """Tests for the main mangaScan function."""

    def test_existing_series_auto_updated_new_series_in_results(self, mangasync, _mock_globals):
        """Scan with 1 existing series and 1 new one.

        Existing series should be auto-updated (chapters marked downloaded).
        New series should appear in scan_results for user selection.
        """
        series_map = {
            "Bleach": [("/manga/Bleach/v01.cbz", None)],
            "NewManga": [("/manga/NewManga/v01.cbz", None)],
        }

        def mock_check_existing(name, files):
            if name == "Bleach":
                return {"chapters_downloaded": 3, "comic_id": "md-existing"}
            return None

        with (
            patch("os.path.isdir", return_value=True),
            patch.object(mangasync, "_collect_series_files", return_value=series_map),
            patch.object(mangasync, "_check_existing_series", side_effect=mock_check_existing),
            patch.object(mangasync, "_match_series", return_value={
                "series_name": "NewManga",
                "file_count": 1,
                "matched": True,
                "match": {"comicid": "md-new", "name": "NewManga", "confidence": 85, "source": "mangadex"},
            }),
        ):
            result = mangasync.mangaScan("/manga")

        assert result["status"] == "completed"
        assert result["existing_updated"] == 1
        assert result["chapters_marked_downloaded"] == 3
        assert result["series_matched"] == 1
        assert len(result["scan_results"]) == 1
        assert result["scan_results"][0]["match"]["comicid"] == "md-new"

    def test_all_existing_series_empty_results(self, mangasync, _mock_globals):
        mock_row = MagicMock()
        mock_row._mapping = {"ComicID": "md-1", "ComicName": "Bleach", "ContentType": "manga"}
        _mock_db_engine(_mock_globals, rows=[mock_row])

        with (
            patch("os.path.isdir", return_value=True),
            patch.object(mangasync, "_collect_series_files", return_value={
                "Bleach": [("/manga/Bleach/v01.cbz", None)],
            }),
            patch.object(mangasync, "_mark_chapters_downloaded", return_value=2),
        ):
            result = mangasync.mangaScan("/manga")

        assert result["scan_results"] == []
        assert result["existing_updated"] == 1

    def test_concurrent_scan_rejected(self, mangasync):
        mangasync._SCAN_LOCK.acquire()
        try:
            result = mangasync.mangaScan("/manga")
            assert result["status"] == "already_running"
        finally:
            mangasync._SCAN_LOCK.release()


class TestImportSelectedManga:
    """Tests for the confirm/import flow."""

    def test_import_selected(self, mangasync):
        mangasync.MANGA_SCAN_ID = "12345"
        mangasync.MANGA_SCAN_RESULTS = [
            {"series_name": "One Piece", "match": {"comicid": "md-100"}},
        ]

        with patch("comicarr.importer.addMangaToDB") as mock_import:
            result = mangasync.import_selected_manga(["md-100"], "12345")

        assert result["success"] is True
        assert result["imported"] == 1
        mock_import.assert_called_once_with("md-100")

    def test_import_mal_series(self, mangasync):
        mangasync.MANGA_SCAN_ID = "12345"
        mangasync.MANGA_SCAN_RESULTS = [
            {"series_name": "Bleach", "match": {"comicid": "mal-200"}},
        ]

        with patch("comicarr.importer.addMangaToDB_MAL") as mock_import:
            result = mangasync.import_selected_manga(["mal-200"], "12345")

        assert result["success"] is True
        mock_import.assert_called_once_with("mal-200")

    def test_stale_scan_id_rejected(self, mangasync):
        mangasync.MANGA_SCAN_ID = "99999"
        mangasync.MANGA_SCAN_RESULTS = [{"series_name": "Test"}]

        result = mangasync.import_selected_manga(["md-100"], "12345")
        assert result["success"] is False
        assert result["stale"] is True

    def test_empty_selection_rejected(self, mangasync):
        mangasync.MANGA_SCAN_ID = "12345"
        mangasync.MANGA_SCAN_RESULTS = [{"series_name": "Test"}]

        result = mangasync.import_selected_manga([], "12345")
        assert result["success"] is False

    def test_results_cleared_after_import(self, mangasync):
        mangasync.MANGA_SCAN_ID = "12345"
        mangasync.MANGA_SCAN_RESULTS = [{"series_name": "Test"}]

        with patch("comicarr.importer.addMangaToDB"):
            mangasync.import_selected_manga(["md-100"], "12345")

        assert mangasync.MANGA_SCAN_RESULTS is None
        assert mangasync.MANGA_SCAN_ID is None


class TestGetScanProgress:
    """Tests for progress polling."""

    def test_returns_scan_id_and_results(self, mangasync):
        mangasync.MANGA_SCAN_STATUS = "completed"
        mangasync.MANGA_SCAN_ID = "12345"
        mangasync.MANGA_SCAN_RESULTS = [{"series_name": "Test"}]

        progress = mangasync.get_scan_progress()
        assert progress["status"] == "completed"
        assert progress["scan_id"] == "12345"
        assert progress["results"] == [{"series_name": "Test"}]
