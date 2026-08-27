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

        batman_key = "folder:%s" % importinbox._filepath_to_impid("/import/Batman")
        superman_key = "folder:%s" % importinbox._filepath_to_impid("/import/Superman")
        assert result[batman_key]["group_name"] == "Batman"
        assert len(result[batman_key]["files"]) == 2
        assert result[superman_key]["group_name"] == "Superman"
        assert len(result[superman_key]["files"]) == 1

    def test_issue_186_nested_manga_folders_stay_separate(self, importinbox):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/import/Manga A", [], ["chapter 1.cbz", "chapter 2.cbz"]),
                ("/import/Manga B", [], ["chapter 1.cbz", "chapter 2.cbz"]),
            ]
            result = importinbox._collect_file_groups("/import")

        manga_a_key = "folder:%s" % importinbox._filepath_to_impid("/import/Manga A")
        manga_b_key = "folder:%s" % importinbox._filepath_to_impid("/import/Manga B")
        assert set(result.keys()) == {manga_a_key, manga_b_key}
        assert result[manga_a_key]["group_name"] == "Manga A"
        assert len(result[manga_a_key]["files"]) == 2
        assert result[manga_b_key]["group_name"] == "Manga B"
        assert len(result[manga_b_key]["files"]) == 2

    def test_folder_group_keys_do_not_collapse_similar_normalized_names(self, importinbox):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/import/Batman", [], ["001.cbz"]),
                ("/import/Batman - Year One", [], ["001.cbz"]),
            ]
            result = importinbox._collect_file_groups("/import")

        assert len(result) == 2
        assert sorted(group["group_name"] for group in result.values()) == [
            "Batman",
            "Batman - Year One",
        ]
        assert all(key.startswith("folder:") for key in result)

    def test_root_files_grouped_individually(self, importinbox):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/import", [], ["Batman 001.cbz", "Superman 001.cbr"]),
            ]
            result = importinbox._collect_file_groups("/import")

        assert len(result) == 2
        assert sorted(group["group_name"] for group in result.values()) == ["Batman", "Superman"]
        assert all(key.startswith("file:") for key in result)

    def test_skips_non_comic_files(self, importinbox):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [
                ("/import/Batman", [], ["cover.jpg", "Batman 001.cbz"]),
            ]
            result = importinbox._collect_file_groups("/import")

        batman_key = "folder:%s" % importinbox._filepath_to_impid("/import/Batman")
        assert len(result[batman_key]["files"]) == 1

    def test_empty_directory(self, importinbox):
        with patch("os.walk") as mock_walk:
            mock_walk.return_value = [("/import", [], [])]
            result = importinbox._collect_file_groups("/import")

        assert result == {}


class TestLoadLibrarySeries:
    """Tests for loading the library fields used by inbox matching."""

    def test_uses_dynamic_comic_name_as_dynamic_name(self, importinbox, _mock_globals):
        mock_row = MagicMock()
        mock_row._mapping = {
            "ComicID": "mal-100",
            "ComicName": "One Piece",
            "ComicSortName": "One Piece",
            "DynamicName": "one piece",
        }
        mock_conn = MagicMock()
        mock_conn.execute.return_value = [mock_row]
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = lambda _context: mock_conn
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        _mock_globals["db"].get_engine.return_value = mock_engine

        result = importinbox._load_library_series()

        assert result == [dict(mock_row._mapping)]
        stmt = mock_conn.execute.call_args.args[0]
        assert stmt.selected_columns.DynamicName.element.name == "DynamicComicName"


class TestMatchGroup:
    """Tests for _match_group — matching file groups against library."""

    def test_high_confidence_auto_imports(self, importinbox, _mock_globals):
        from unittest.mock import ANY

        series_list = [
            {"ComicID": "cv-100", "ComicName": "Batman", "ComicSortName": "Batman", "DynamicName": "batman"},
        ]
        files = ["/import/Batman/001.cbz", "/import/Batman/002.cbz"]

        _mock_globals["db"].upsert = MagicMock()

        with (
            patch("comicarr.app.imports.queries.get_import_rows", return_value=[]),
            patch("comicarr.app.imports.finalization.finalize_manual_match") as finalize,
        ):
            result = importinbox._match_group(
                "folder:batman",
                {"group_name": "Batman", "files": files},
                series_list,
            )

        assert result["auto_imported"] == 2
        assert result["queued_for_review"] == 0
        assert _mock_globals["db"].upsert.call_count == 2
        pending = _mock_globals["db"].upsert.call_args_list[0].args[1]
        assert pending["Status"] == "Not Imported"
        assert pending["MatchSource"] == "inbox-auto"
        finalize.assert_called_once_with(
            ANY,
            [importinbox._filepath_to_impid(filepath) for filepath in files],
            "cv-100",
            series_name="Batman",
            match_source="inbox-auto",
            match_confidence=100,
        )

    def test_finalization_failure_queues_group_for_review(self, importinbox, _mock_globals):
        from comicarr.app.imports.finalization import ImportFinalizationError

        series_list = [
            {"ComicID": "cv-100", "ComicName": "Batman", "ComicSortName": "Batman", "DynamicName": "batman"},
        ]
        files = ["/import/Batman/001.cbz", "/import/Batman/002.cbz"]

        _mock_globals["db"].upsert = MagicMock()

        with (
            patch("comicarr.app.imports.queries.get_import_rows", return_value=[]),
            patch(
                "comicarr.app.imports.finalization.finalize_manual_match",
                side_effect=ImportFinalizationError("destination exists", phase="preflight"),
            ),
        ):
            result = importinbox._match_group(
                "folder:batman",
                {"group_name": "Batman", "files": files},
                series_list,
            )

        assert result["auto_imported"] == 0
        assert result["queued_for_review"] == 2
        assert _mock_globals["db"].upsert.call_count == 2

    def test_rescan_skips_already_imported_files(self, importinbox, _mock_globals):
        series_list = [
            {"ComicID": "cv-100", "ComicName": "Batman", "ComicSortName": "Batman", "DynamicName": "batman"},
        ]
        files = ["/import/Batman/001.cbz", "/import/Batman/002.cbz"]
        imported_row = {"impID": importinbox._filepath_to_impid(files[0]), "Status": "Imported"}

        _mock_globals["db"].upsert = MagicMock()

        with (
            patch("comicarr.app.imports.queries.get_import_rows", return_value=[imported_row]),
            patch("comicarr.app.imports.finalization.finalize_manual_match") as finalize,
        ):
            result = importinbox._match_group(
                "folder:batman",
                {"group_name": "Batman", "files": files},
                series_list,
            )

        assert result["auto_imported"] == 1
        assert result["queued_for_review"] == 0
        assert _mock_globals["db"].upsert.call_count == 1
        finalize.assert_called_once()
        assert finalize.call_args.args[1] == [importinbox._filepath_to_impid(files[1])]

    def test_rescan_with_whole_group_already_imported_is_a_noop(self, importinbox, _mock_globals):
        series_list = [
            {"ComicID": "cv-100", "ComicName": "Batman", "ComicSortName": "Batman", "DynamicName": "batman"},
        ]
        files = ["/import/Batman/001.cbz"]
        imported_row = {"impID": importinbox._filepath_to_impid(files[0]), "Status": "Imported"}

        _mock_globals["db"].upsert = MagicMock()

        with (
            patch("comicarr.app.imports.queries.get_import_rows", return_value=[imported_row]),
            patch("comicarr.app.imports.finalization.finalize_manual_match") as finalize,
        ):
            result = importinbox._match_group(
                "folder:batman",
                {"group_name": "Batman", "files": files},
                series_list,
            )

        assert result["auto_imported"] == 0
        assert result["queued_for_review"] == 0
        _mock_globals["db"].upsert.assert_not_called()
        finalize.assert_not_called()

    def test_low_confidence_queues_for_review(self, importinbox, _mock_globals):
        series_list = [
            {"ComicID": "cv-100", "ComicName": "Batman", "ComicSortName": "Batman", "DynamicName": "batman"},
        ]

        _mock_globals["db"].upsert = MagicMock()

        result = importinbox._match_group(
            "folder:unknown",
            {"group_name": "Completely Unknown Series", "files": ["/import/Unknown/001.cbz"]},
            series_list,
        )

        assert result["auto_imported"] == 0
        assert result["queued_for_review"] == 1

    def test_no_series_in_library(self, importinbox, _mock_globals):
        _mock_globals["db"].upsert = MagicMock()

        result = importinbox._match_group(
            "folder:batman",
            {"group_name": "Batman", "files": ["/import/Batman/chapter 1.cbz"]},
            [],
        )

        assert result["auto_imported"] == 0
        assert result["queued_for_review"] == 1
        _mock_globals["db"].upsert.assert_called_once()
        queued_values = _mock_globals["db"].upsert.call_args.args[1]
        assert queued_values["DynamicName"] == "folder:batman"
        assert queued_values["ComicName"] == "Batman"
        assert queued_values["IssueNumber"] == "1"

    def test_multiple_series_takes_highest(self, importinbox, _mock_globals):
        series_list = [
            {"ComicID": "cv-100", "ComicName": "Batman", "ComicSortName": "Batman", "DynamicName": "batman"},
            {
                "ComicID": "cv-200",
                "ComicName": "Batman Beyond",
                "ComicSortName": "Batman Beyond",
                "DynamicName": "batmanbeyond",
            },
        ]

        _mock_globals["db"].upsert = MagicMock()

        # Exact match to "Batman" should win
        with (
            patch("comicarr.app.imports.queries.get_import_rows", return_value=[]),
            patch.object(importinbox, "_finalize_auto_import_group", return_value=True),
        ):
            result = importinbox._match_group(
                "folder:batman",
                {"group_name": "Batman", "files": ["/import/Batman/001.cbz"]},
                series_list,
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
            patch.object(
                importinbox,
                "_collect_file_groups",
                return_value={
                    "folder:batman": {"group_name": "Batman", "files": ["/import/Batman/001.cbz"]},
                    "folder:unknown": {"group_name": "Unknown", "files": ["/import/Unknown/001.cbz"]},
                },
            ),
            patch.object(
                importinbox,
                "_match_group",
                side_effect=[
                    {"auto_imported": 1, "queued_for_review": 0},
                    {"auto_imported": 0, "queued_for_review": 1},
                ],
            ),
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
