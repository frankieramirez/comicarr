"""
Unit tests for comicarr/comicsync.py — Comic Library Scanner.

Tests cover directory walking, series matching against ComicVine,
scan-then-select flow, and concurrent scan prevention.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_globals():
    """Patch comicarr globals so comicsync can be imported without app init."""
    mock_config = MagicMock()
    mock_config.COMIC_DIR = "/comics"
    mock_config.COMICVINE_API = "test-api-key"

    with (
        patch("comicarr.CONFIG", mock_config),
        patch("comicarr.comicsync.logger") as mock_log,
        patch("comicarr.comicsync.db") as mock_db,
    ):
        mock_log.fdebug = lambda *a, **kw: None
        mock_log.info = lambda *a, **kw: None
        mock_log.warning = lambda *a, **kw: None
        mock_log.error = lambda *a, **kw: None
        yield {"config": mock_config, "logger": mock_log, "db": mock_db}


@pytest.fixture
def comicsync():
    """Import comicsync fresh for each test and reset globals."""
    from comicarr import comicsync as cs

    # Reset module-level state
    cs.COMIC_SCAN_STATUS = None
    cs.COMIC_SCAN_PROGRESS = {
        "total_files": 0,
        "processed_files": 0,
        "series_found": 0,
        "series_matched": 0,
        "current_series": None,
        "errors": [],
    }
    cs.COMIC_SCAN_RESULTS = None
    cs.COMIC_SCAN_ID = None
    # Ensure lock is released
    if cs._SCAN_LOCK.locked():
        cs._SCAN_LOCK.release()
    return cs


class TestCollectSeriesFiles:
    """Tests for _collect_series_files directory walking."""

    def test_groups_files_by_parent_directory(self, comicsync):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/comics/Batman", [], ["Batman 001.cbz", "Batman 002.cbz"]),
                ("/comics/Spider-Man", [], ["Spider-Man 001.cbr"]),
            ]
            result = comicsync._collect_series_files("/comics")

        assert "Batman" in result
        assert len(result["Batman"]) == 2
        assert "Spider-Man" in result
        assert len(result["Spider-Man"]) == 1

    def test_skips_non_comic_files(self, comicsync):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/comics/Batman", [], ["Batman 001.cbz", "cover.jpg", "metadata.xml"]),
            ]
            result = comicsync._collect_series_files("/comics")

        assert len(result["Batman"]) == 1

    def test_empty_directory_returns_empty(self, comicsync):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/comics", [], []),
            ]
            result = comicsync._collect_series_files("/comics")

        assert result == {}

    def test_files_in_root_use_filename_guess(self, comicsync):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/comics", [], ["Batman 001.cbz"]),
            ]
            result = comicsync._collect_series_files("/comics")

        assert "Batman" in result

    def test_series_folder_with_no_comics_skipped(self, comicsync):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/comics/EmptySeries", [], ["readme.txt"]),
            ]
            result = comicsync._collect_series_files("/comics")

        assert result == {}


class TestGuessSeriesFromFilename:
    """Tests for _guess_series_from_filename."""

    def test_strips_issue_number(self, comicsync):
        assert comicsync._guess_series_from_filename("Batman 001.cbz") == "Batman"

    def test_strips_year_in_parens(self, comicsync):
        assert comicsync._guess_series_from_filename("Batman (2016) 001.cbz") == "Batman"

    def test_strips_hash_issue(self, comicsync):
        assert comicsync._guess_series_from_filename("Batman #42.cbr") == "Batman"

    def test_returns_none_for_empty(self, comicsync):
        assert comicsync._guess_series_from_filename(".cbz") is None


class TestNameSimilarity:
    """Tests for fuzzy name matching (via scanutil)."""

    def test_exact_match(self):
        from comicarr.scanutil import name_similarity

        assert name_similarity("Batman", "Batman") == 1.0

    def test_case_insensitive(self):
        from comicarr.scanutil import name_similarity

        assert name_similarity("batman", "BATMAN") == 1.0

    def test_partial_match(self):
        from comicarr.scanutil import name_similarity

        score = name_similarity("Batman", "Batman: Year One")
        assert score > 0.5

    def test_no_match(self):
        from comicarr.scanutil import name_similarity

        score = name_similarity("Batman", "Naruto")
        assert score < 0.5

    def test_empty_string(self):
        from comicarr.scanutil import name_similarity

        assert name_similarity("", "Batman") == 0.0


class TestComicScan:
    """Tests for the main comicScan function."""

    def test_happy_path_matches_series(self, comicsync, _mock_globals):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value = []
        mock_engine.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        _mock_globals["db"].get_engine.return_value = mock_engine

        cv_results = {
            "results": [
                {
                    "name": "Batman",
                    "comicid": "12345",
                    "comicyear": "2016",
                    "publisher": "DC Comics",
                    "issues": "100",
                    "comicthumb": "http://example.com/thumb.jpg",
                    "comicimage": "http://example.com/image.jpg",
                },
            ],
            "pagination": {"total": 1, "limit": 5, "offset": 0, "returned": 1},
        }

        with (
            patch("os.path.isdir", return_value=True),
            patch.object(comicsync, "_collect_series_files", return_value={
                "Batman": ["/comics/Batman/001.cbz", "/comics/Batman/002.cbz"],
            }),
            patch("comicarr.mb.findComic", return_value=cv_results),
        ):
            result = comicsync.comicScan("/comics")

        assert result["status"] == "completed"
        assert result["series_found"] == 1
        assert result["series_matched"] == 1
        assert len(result["scan_results"]) == 1
        assert result["scan_results"][0]["match"]["comicid"] == "12345"
        assert comicsync.COMIC_SCAN_ID is not None

    def test_empty_directory(self, comicsync):
        with (
            patch("os.path.isdir", return_value=True),
            patch.object(comicsync, "_collect_series_files", return_value={}),
        ):
            result = comicsync.comicScan("/comics")

        assert result["status"] == "completed"
        assert result["series_found"] == 0
        assert result["scan_results"] == []

    def test_comicvine_unreachable(self, comicsync, _mock_globals):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value = []
        mock_engine.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        _mock_globals["db"].get_engine.return_value = mock_engine

        with (
            patch("os.path.isdir", return_value=True),
            patch.object(comicsync, "_collect_series_files", return_value={
                "Batman": ["/comics/Batman/001.cbz"],
            }),
            patch("comicarr.mb.findComic", side_effect=Exception("API unreachable")),
        ):
            result = comicsync.comicScan("/comics")

        assert result["status"] == "completed"
        assert result["series_found"] == 1
        assert result["series_matched"] == 0
        assert len(result["errors"]) == 0  # Error captured in scan_results, not fatal
        assert result["scan_results"][0]["error"] is not None

    def test_concurrent_scan_rejected(self, comicsync):
        comicsync._SCAN_LOCK.acquire()
        try:
            result = comicsync.comicScan("/comics")
            assert result["status"] == "already_running"
        finally:
            comicsync._SCAN_LOCK.release()

    def test_no_comic_dir_configured(self, comicsync, _mock_globals):
        _mock_globals["config"].COMIC_DIR = None
        result = comicsync.comicScan()
        assert result["status"] == "skipped"


class TestImportSelectedSeries:
    """Tests for the confirm/import flow."""

    def test_import_selected(self, comicsync):
        comicsync.COMIC_SCAN_ID = "12345"
        comicsync.COMIC_SCAN_RESULTS = [
            {"series_name": "Batman", "matched": True, "match": {"comicid": "cv-100"}},
            {"series_name": "Superman", "matched": True, "match": {"comicid": "cv-200"}},
        ]

        with patch("comicarr.importer.addComictoDB") as mock_import:
            result = comicsync.import_selected_series(["cv-100", "cv-200"], "12345")

        assert result["success"] is True
        assert result["imported"] == 2
        assert mock_import.call_count == 2

    def test_skips_unselected(self, comicsync):
        comicsync.COMIC_SCAN_ID = "12345"
        comicsync.COMIC_SCAN_RESULTS = [
            {"series_name": "Batman", "matched": True, "match": {"comicid": "cv-100"}},
            {"series_name": "Superman", "matched": True, "match": {"comicid": "cv-200"}},
        ]

        with patch("comicarr.importer.addComictoDB") as mock_import:
            result = comicsync.import_selected_series(["cv-100"], "12345")

        assert result["imported"] == 1
        mock_import.assert_called_once_with("cv-100")

    def test_stale_scan_id_rejected(self, comicsync):
        comicsync.COMIC_SCAN_ID = "99999"
        comicsync.COMIC_SCAN_RESULTS = [{"series_name": "Batman"}]

        result = comicsync.import_selected_series(["cv-100"], "12345")
        assert result["success"] is False
        assert result["stale"] is True

    def test_empty_selection_rejected(self, comicsync):
        comicsync.COMIC_SCAN_ID = "12345"
        comicsync.COMIC_SCAN_RESULTS = [{"series_name": "Batman"}]

        result = comicsync.import_selected_series([], "12345")
        assert result["success"] is False

    def test_results_cleared_after_import(self, comicsync):
        comicsync.COMIC_SCAN_ID = "12345"
        comicsync.COMIC_SCAN_RESULTS = [
            {"series_name": "Batman", "matched": True, "match": {"comicid": "cv-100"}},
        ]

        with patch("comicarr.importer.addComictoDB"):
            comicsync.import_selected_series(["cv-100"], "12345")

        assert comicsync.COMIC_SCAN_RESULTS is None
        assert comicsync.COMIC_SCAN_ID is None


class TestGetScanProgress:
    """Tests for progress polling."""

    def test_returns_current_state(self, comicsync):
        comicsync.COMIC_SCAN_STATUS = "scanning"
        comicsync.COMIC_SCAN_ID = "12345"

        progress = comicsync.get_scan_progress()
        assert progress["status"] == "scanning"
        assert progress["scan_id"] == "12345"
