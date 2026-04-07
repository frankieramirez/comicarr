"""
Unit tests for comicarr/importinbox.py — Import Inbox Scanner.

Tests cover file grouping, auto-matching against library series,
queuing unmatched files for review, and concurrent scan prevention.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_globals():
    """Patch comicarr globals so importinbox can be imported without app init."""
    mock_config = MagicMock()
    mock_config.IMPORT_DIR = "/import"

    with (
        patch("comicarr.CONFIG", mock_config),
        patch("comicarr.importinbox.logger") as mock_log,
        patch("comicarr.importinbox.db") as mock_db,
    ):
        mock_log.fdebug = lambda *a, **kw: None
        mock_log.info = lambda *a, **kw: None
        mock_log.warning = lambda *a, **kw: None
        mock_log.error = lambda *a, **kw: None
        yield {"config": mock_config, "logger": mock_log, "db": mock_db}


@pytest.fixture
def importinbox():
    """Import importinbox fresh for each test and reset globals."""
    from comicarr import importinbox as ib

    ib.INBOX_SCAN_STATUS = None
    ib.INBOX_SCAN_PROGRESS = {
        "total_files": 0,
        "processed_files": 0,
        "auto_imported": 0,
        "queued_for_review": 0,
        "current_group": None,
        "errors": [],
    }
    if ib._SCAN_LOCK.locked():
        ib._SCAN_LOCK.release()
    return ib


class TestCollectFileGroups:
    """Tests for _collect_file_groups directory walking."""

    def test_groups_files_by_parent_directory(self, importinbox):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/import/Batman", [], ["Batman 001.cbz", "Batman 002.cbz"]),
                ("/import/Superman", [], ["Superman 001.cbr"]),
            ]
            result = importinbox._collect_file_groups("/import")

        assert "Batman" in result
        assert len(result["Batman"]) == 2
        assert "Superman" in result
        assert len(result["Superman"]) == 1

    def test_root_files_grouped_individually(self, importinbox):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/import", [], ["Batman 001.cbz", "Superman 001.cbr"]),
            ]
            result = importinbox._collect_file_groups("/import")

        assert "Batman 001" in result
        assert "Superman 001" in result

    def test_skips_non_comic_files(self, importinbox):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/import/Batman", [], ["cover.jpg", "Batman 001.cbz"]),
            ]
            result = importinbox._collect_file_groups("/import")

        assert len(result["Batman"]) == 1

    def test_empty_directory(self, importinbox):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [("/import", [], [])]
            result = importinbox._collect_file_groups("/import")

        assert result == {}


class TestMatchGroup:
    """Tests for _match_group — matching file groups against library."""

    def test_high_confidence_auto_imports(self, importinbox, _mock_globals):
        series_list = [
            {"ComicID": "cv-100", "ComicName": "Batman", "ComicSortName": "Batman", "DynamicName": "batman"},
        ]

        _mock_globals["db"].upsert = MagicMock()

        result = importinbox._match_group(
            "Batman", ["/import/Batman/001.cbz", "/import/Batman/002.cbz"], series_list
        )

        assert result["auto_imported"] == 2
        assert result["queued_for_review"] == 0

    def test_low_confidence_queues_for_review(self, importinbox, _mock_globals):
        series_list = [
            {"ComicID": "cv-100", "ComicName": "Batman", "ComicSortName": "Batman", "DynamicName": "batman"},
        ]

        _mock_globals["db"].upsert = MagicMock()

        result = importinbox._match_group(
            "Completely Unknown Series", ["/import/Unknown/001.cbz"], series_list
        )

        assert result["auto_imported"] == 0
        assert result["queued_for_review"] == 1

    def test_no_series_in_library(self, importinbox, _mock_globals):
        _mock_globals["db"].upsert = MagicMock()

        result = importinbox._match_group(
            "Batman", ["/import/Batman/001.cbz"], []
        )

        assert result["auto_imported"] == 0
        assert result["queued_for_review"] == 1

    def test_multiple_series_takes_highest(self, importinbox, _mock_globals):
        series_list = [
            {"ComicID": "cv-100", "ComicName": "Batman", "ComicSortName": "Batman", "DynamicName": "batman"},
            {"ComicID": "cv-200", "ComicName": "Batman Beyond", "ComicSortName": "Batman Beyond", "DynamicName": "batmanbeyond"},
        ]

        _mock_globals["db"].upsert = MagicMock()

        # Exact match to "Batman" should win
        result = importinbox._match_group(
            "Batman", ["/import/Batman/001.cbz"], series_list
        )

        assert result["auto_imported"] == 1


class TestInboxScan:
    """Tests for the main inboxScan function."""

    def test_happy_path(self, importinbox, _mock_globals):
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value = []
        mock_engine.connect.return_value.__enter__ = lambda s: mock_conn
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        _mock_globals["db"].get_engine.return_value = mock_engine
        _mock_globals["db"].upsert = MagicMock()

        with (
            patch("os.path.isdir", return_value=True),
            patch.object(importinbox, "_collect_file_groups", return_value={
                "Batman": ["/import/Batman/001.cbz"],
                "Unknown": ["/import/Unknown/001.cbz"],
            }),
            patch.object(importinbox, "_match_group", side_effect=[
                {"auto_imported": 1, "queued_for_review": 0},
                {"auto_imported": 0, "queued_for_review": 1},
            ]),
        ):
            result = importinbox.inboxScan()

        assert result["status"] == "completed"
        assert result["auto_imported"] == 1
        assert result["queued_for_review"] == 1

    def test_empty_import_dir(self, importinbox):
        with (
            patch("os.path.isdir", return_value=True),
            patch.object(importinbox, "_collect_file_groups", return_value={}),
        ):
            result = importinbox.inboxScan()

        assert result["status"] == "completed"
        assert result["total_files"] == 0

    def test_import_dir_not_configured(self, importinbox, _mock_globals):
        _mock_globals["config"].IMPORT_DIR = None
        result = importinbox.inboxScan()
        assert result["status"] == "skipped"

    def test_concurrent_scan_rejected(self, importinbox):
        importinbox._SCAN_LOCK.acquire()
        try:
            result = importinbox.inboxScan()
            assert result["status"] == "already_running"
        finally:
            importinbox._SCAN_LOCK.release()

    def test_nonexistent_import_dir(self, importinbox):
        with patch("os.path.isdir", return_value=False):
            result = importinbox.inboxScan()
        assert result["status"] == "error"
        assert result["reason"] == "directory_not_found"


class TestGetScanProgress:
    """Tests for progress polling."""

    def test_returns_current_state(self, importinbox):
        importinbox.INBOX_SCAN_STATUS = "scanning"
        progress = importinbox.get_scan_progress()
        assert progress["status"] == "scanning"
