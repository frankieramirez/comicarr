#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

"""
Tests for manual import matching behavior.
"""

from types import SimpleNamespace
from unittest.mock import call, patch

import pytest

from comicarr.app.series import queries, service


@pytest.fixture(autouse=True)
def _mock_service_logger():
    with patch.object(service, "logger"):
        yield


def test_match_import_marks_record_imported_with_manual_match_metadata():
    with patch.object(queries.db, "upsert") as mock_upsert:
        queries.match_import("imp-1", "mal-123", "Berserk", issue_id="mal-123-ch1")

    mock_upsert.assert_called_once_with(
        "importresults",
        {
            "ComicID": "mal-123",
            "ComicName": "Berserk",
            "Status": "Imported",
            "SuggestedComicID": "mal-123",
            "SuggestedComicName": "Berserk",
            "MatchSource": "manual",
            "MatchConfidence": 100,
            "WatchMatch": "Cmal-123",
            "IgnoreFile": 0,
            "IssueID": "mal-123-ch1",
            "SuggestedIssueID": "mal-123-ch1",
        },
        {"impID": "imp-1"},
    )


def test_match_import_adds_missing_mal_manga_before_finalizing_rows():
    with (
        patch.object(service.series_queries, "get_comic_name", return_value=None),
        patch(
            "comicarr.importer.addMangaToDB_MAL",
            return_value={"status": "complete", "comicname": "Berserk"},
        ) as mock_add_manga,
        patch.object(
            service.series_queries,
            "get_comic_for_import",
            return_value={"ComicName": "Berserk", "ComicLocation": "/library/Berserk"},
        ),
        patch.object(
            service.series_queries,
            "get_import_rows",
            return_value=[
                {
                    "impID": "imp-1",
                    "ComicLocation": "/import/Berserk/chapter 1.cbz",
                    "ComicFilename": "chapter 1.cbz",
                    "IssueNumber": None,
                }
            ],
        ),
        patch.object(service, "_finalize_import_rows", return_value={"success": True}),
        patch.object(service.series_queries, "match_import") as mock_match,
    ):
        result = service.match_import(None, ["imp-1"], "mal-123", comic_name="Berserk")

    assert result == {
        "success": True,
        "matched": 1,
        "imported": 1,
        "comic_id": "mal-123",
        "comic_name": "Berserk",
        "moved": 0,
        "archived": 0,
    }
    mock_add_manga.assert_called_once_with("mal-123")
    mock_match.assert_called_once_with("imp-1", "mal-123", "Berserk", issue_id=None)


def test_match_import_does_not_finalize_rows_when_manga_add_fails():
    with (
        patch.object(service.series_queries, "get_comic_name", return_value=None),
        patch("comicarr.importer.addMangaToDB", return_value={"status": "incomplete"}),
        patch.object(service.series_queries, "match_import") as mock_match,
    ):
        result = service.match_import(None, ["imp-1"], "md-abc", comic_name="Berserk")

    assert result == {"success": False, "error": "Failed to add manga: md-abc"}
    mock_match.assert_not_called()


def test_match_import_uses_existing_library_name_without_readding_manga():
    with (
        patch.object(service.series_queries, "get_comic_name", return_value="Existing Berserk"),
        patch.object(
            service.series_queries,
            "get_comic_for_import",
            return_value={"ComicName": "Existing Berserk", "ComicLocation": "/library/Berserk"},
        ),
        patch.object(
            service.series_queries,
            "get_import_rows",
            return_value=[
                {
                    "impID": "imp-1",
                    "ComicLocation": "/import/Berserk/chapter 1.cbz",
                    "ComicFilename": "chapter 1.cbz",
                    "IssueNumber": None,
                }
            ],
        ),
        patch.object(service, "_finalize_import_rows", return_value={"success": True}),
        patch.object(service.series_queries, "match_import") as mock_match,
    ):
        result = service.match_import(None, ["imp-1", "", "imp-1"], "mal-123", comic_name="Berserk")

    assert result["success"] is True
    assert result["matched"] == 1
    assert result["comic_name"] == "Existing Berserk"
    mock_match.assert_called_once_with("imp-1", "mal-123", "Existing Berserk", issue_id=None)


def test_match_import_moves_files_before_marking_rows_imported(tmp_path):
    import_dir = tmp_path / "import" / "Berserk"
    target_dir = tmp_path / "library" / "Berserk"
    import_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)
    source_file = import_dir / "chapter 1.cbz"
    source_file.write_text("chapter")

    events = []

    def mark_import(*args, **kwargs):
        events.append("mark")

    def force_rescan(*args, **kwargs):
        events.append("rescan")

    config = SimpleNamespace(IMP_MOVE=True, IMP_RENAME=False, FILE_FORMAT="")

    with (
        patch.object(service.comicarr, "CONFIG", config),
        patch.object(service.series_queries, "get_comic_name", return_value="Berserk"),
        patch.object(
            service.series_queries,
            "get_comic_for_import",
            return_value={"ComicName": "Berserk", "ComicLocation": str(target_dir)},
        ),
        patch.object(
            service.series_queries,
            "get_import_rows",
            return_value=[
                {
                    "impID": "imp-1",
                    "ComicLocation": str(source_file),
                    "ComicFilename": "chapter 1.cbz",
                    "IssueNumber": None,
                }
            ],
        ),
        patch("comicarr.updater.forceRescan", side_effect=force_rescan) as mock_rescan,
        patch.object(service.series_queries, "match_import", side_effect=mark_import) as mock_match,
    ):
        result = service.match_import(None, ["imp-1"], "mal-123", comic_name="Berserk")

    assert result["success"] is True
    assert result["moved"] == 1
    assert result["archived"] == 0
    assert not source_file.exists()
    assert (target_dir / "chapter 1.cbz").exists()
    assert events == ["rescan", "mark"]
    mock_rescan.assert_called_once_with("mal-123")
    mock_match.assert_called_once_with("imp-1", "mal-123", "Berserk", issue_id=None)


def test_match_import_archive_mode_rescans_source_directory_before_marking_rows_imported(tmp_path):
    import_dir = tmp_path / "import" / "Berserk"
    target_dir = tmp_path / "library" / "Berserk"
    import_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)
    source_file = import_dir / "chapter 1.cbz"
    source_file.write_text("chapter")

    events = []

    def mark_import(*args, **kwargs):
        events.append("mark")

    def force_rescan(*args, **kwargs):
        events.append("rescan")

    config = SimpleNamespace(IMP_MOVE=False, IMP_RENAME=False, FILE_FORMAT="")

    with (
        patch.object(service.comicarr, "CONFIG", config),
        patch.object(service.series_queries, "get_comic_name", return_value="Berserk"),
        patch.object(
            service.series_queries,
            "get_comic_for_import",
            return_value={"ComicName": "Berserk", "ComicLocation": str(target_dir)},
        ),
        patch.object(
            service.series_queries,
            "get_import_rows",
            return_value=[
                {
                    "impID": "imp-1",
                    "ComicLocation": str(source_file),
                    "ComicFilename": "chapter 1.cbz",
                    "IssueNumber": None,
                }
            ],
        ),
        patch("comicarr.updater.forceRescan", side_effect=force_rescan) as mock_rescan,
        patch.object(service.series_queries, "match_import", side_effect=mark_import) as mock_match,
    ):
        result = service.match_import(None, ["imp-1"], "mal-123", comic_name="Berserk")

    assert result["success"] is True
    assert result["moved"] == 0
    assert result["archived"] == 1
    assert source_file.exists()
    assert events == ["rescan", "rescan", "mark"]
    mock_rescan.assert_has_calls(
        [
            call("mal-123", archive=str(import_dir)),
            call("mal-123"),
        ]
    )
    mock_match.assert_called_once_with("imp-1", "mal-123", "Berserk", issue_id=None)


def test_match_import_missing_source_file_does_not_mark_row_imported(tmp_path):
    target_dir = tmp_path / "library" / "Berserk"
    target_dir.mkdir(parents=True)
    missing_file = tmp_path / "import" / "Berserk" / "missing.cbz"
    config = SimpleNamespace(IMP_MOVE=True, IMP_RENAME=False, FILE_FORMAT="")

    with (
        patch.object(service.comicarr, "CONFIG", config),
        patch.object(service.series_queries, "get_comic_name", return_value="Berserk"),
        patch.object(
            service.series_queries,
            "get_comic_for_import",
            return_value={"ComicName": "Berserk", "ComicLocation": str(target_dir)},
        ),
        patch.object(
            service.series_queries,
            "get_import_rows",
            return_value=[
                {
                    "impID": "imp-1",
                    "ComicLocation": str(missing_file),
                    "ComicFilename": "missing.cbz",
                    "IssueNumber": None,
                }
            ],
        ),
        patch("comicarr.updater.forceRescan") as mock_rescan,
        patch.object(service.series_queries, "match_import") as mock_match,
    ):
        result = service.match_import(None, ["imp-1"], "mal-123", comic_name="Berserk")

    assert result["success"] is False
    assert "does not exist" in result["error"]
    mock_rescan.assert_not_called()
    mock_match.assert_not_called()


def test_match_import_missing_target_location_does_not_mark_row_imported(tmp_path):
    import_dir = tmp_path / "import" / "Berserk"
    import_dir.mkdir(parents=True)
    source_file = import_dir / "chapter 1.cbz"
    source_file.write_text("chapter")
    config = SimpleNamespace(IMP_MOVE=True, IMP_RENAME=False, FILE_FORMAT="")

    with (
        patch.object(service.comicarr, "CONFIG", config),
        patch.object(service.series_queries, "get_comic_name", return_value="Berserk"),
        patch.object(
            service.series_queries,
            "get_comic_for_import",
            return_value={"ComicName": "Berserk", "ComicLocation": None},
        ),
        patch.object(
            service.series_queries,
            "get_import_rows",
            return_value=[
                {
                    "impID": "imp-1",
                    "ComicLocation": str(source_file),
                    "ComicFilename": "chapter 1.cbz",
                    "IssueNumber": None,
                }
            ],
        ),
        patch("comicarr.updater.forceRescan") as mock_rescan,
        patch.object(service.series_queries, "match_import") as mock_match,
    ):
        result = service.match_import(None, ["imp-1"], "mal-123", comic_name="Berserk")

    assert result["success"] is False
    assert "no library directory" in result["error"]
    assert source_file.exists()
    mock_rescan.assert_not_called()
    mock_match.assert_not_called()
