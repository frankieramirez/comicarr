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
from unittest.mock import MagicMock, call, patch

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


def test_update_import_issue_number_persists_file_metadata():
    with patch.object(queries.db, "upsert") as mock_upsert:
        queries.update_import_issue_number("imp-1", "12.5")

    mock_upsert.assert_called_once_with("importresults", {"IssueNumber": "12.5"}, {"impID": "imp-1"})


def test_get_issue_id_for_import_prefers_chapter_number_match():
    with patch.object(queries.db, "select_one", return_value={"IssueID": "chapter-row"}) as mock_select_one:
        result = queries.get_issue_id_for_import("mal-123", "1")

    assert result == "chapter-row"
    assert mock_select_one.call_count == 1


def test_get_issue_id_for_import_falls_back_to_issue_number_match():
    with patch.object(
        queries.db,
        "select_one",
        side_effect=[None, {"IssueID": "issue-row"}],
    ) as mock_select_one:
        result = queries.get_issue_id_for_import("mal-123", "1")

    assert result == "issue-row"
    assert mock_select_one.call_count == 2


def test_get_import_pending_returns_group_and_file_summary_counts():
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    conn.execute.side_effect = [
        MagicMock(scalar=MagicMock(return_value=2)),
        MagicMock(scalar=MagicMock(return_value=4)),
    ]

    group_rows = [
        {
            "GroupKey": "folder:manga-a",
            "ComicName": "Manga A",
            "Volume": None,
            "ComicYear": None,
            "Status": "Unmatched",
            "SRID": None,
            "ComicID": None,
            "SuggestedComicID": None,
            "SuggestedComicName": None,
            "FileCount": 2,
        },
        {
            "GroupKey": "file:root-a",
            "ComicName": "Root A",
            "Volume": None,
            "ComicYear": None,
            "Status": "Unmatched",
            "SRID": None,
            "ComicID": None,
            "SuggestedComicID": None,
            "SuggestedComicName": None,
            "FileCount": 1,
        },
    ]
    file_rows = [
        {
            "impID": "imp-1",
            "ComicFilename": "chapter 1.cbz",
            "ComicLocation": "/imports/Manga A/chapter 1.cbz",
            "IssueNumber": "1",
            "ComicYear": None,
            "Status": "Unmatched",
            "IgnoreFile": 0,
            "MatchConfidence": None,
            "SuggestedComicID": None,
            "SuggestedComicName": None,
            "SuggestedIssueID": None,
            "MatchSource": None,
        }
    ]

    with (
        patch.object(queries.db, "get_engine", return_value=engine),
        patch.object(queries.db, "select_all", side_effect=[group_rows, file_rows, file_rows]),
    ):
        result = queries.get_import_pending(limit=50, offset=0)

    assert result["pagination"]["total"] == 2
    assert result["summary"] == {"group_count": 2, "file_count": 4}
    assert [import_group["DynamicName"] for import_group in result["imports"]] == ["folder:manga-a", "file:root-a"]


def test_clean_import_ids_handles_empty_scalar_and_duplicate_values():
    assert service._clean_import_ids(None) == []
    assert service._clean_import_ids("imp-1") == ["imp-1"]
    assert service._clean_import_ids([" imp-1 ", None, "", "imp-1", "imp-2"]) == ["imp-1", "imp-2"]


def test_update_import_metadata_rejects_blank_issue_number():
    result = service.update_import_metadata(None, "imp-1", " ")
    assert result["success"] is False
    assert "blank" in result["error"]


def test_update_import_metadata_rejects_missing_record():
    with patch.object(service.series_queries, "get_import_row", return_value=None):
        result = service.update_import_metadata(None, "imp-missing", "1")

    assert result["success"] is False
    assert result["not_found"] is True


def test_update_import_metadata_rejects_imported_record():
    with patch.object(service.series_queries, "get_import_row", return_value={"impID": "imp-1", "Status": "Imported"}):
        result = service.update_import_metadata(None, "imp-1", "1")

    assert result["success"] is False
    assert result["imported"] is True


def test_update_import_metadata_updates_pending_record():
    with (
        patch.object(
            service.series_queries, "get_import_row", return_value={"impID": "imp-1", "Status": "Not Imported"}
        ),
        patch.object(service.series_queries, "update_import_issue_number") as mock_update,
    ):
        result = service.update_import_metadata(None, " imp-1 ", " 2.5 ")

    assert result == {"success": True, "imp_id": "imp-1", "issue_number": "2.5"}
    mock_update.assert_called_once_with("imp-1", "2.5")


def test_match_import_empty_ids_does_not_add_or_finalize_manga():
    with (
        patch.object(service, "_ensure_import_series") as mock_ensure_series,
        patch.object(service.series_queries, "get_comic_name", return_value="Existing Berserk"),
        patch.object(service.series_queries, "get_comic_for_import") as mock_get_comic,
        patch.object(service.series_queries, "get_import_rows") as mock_get_rows,
        patch.object(service.series_queries, "match_import") as mock_match,
    ):
        result = service.match_import(None, None, "mal-123", comic_name="Berserk")

    assert result == {
        "success": True,
        "matched": 0,
        "imported": 0,
        "comic_id": "mal-123",
        "comic_name": "Existing Berserk",
        "moved": 0,
        "archived": 0,
    }
    mock_ensure_series.assert_not_called()
    mock_get_comic.assert_not_called()
    mock_get_rows.assert_not_called()
    mock_match.assert_not_called()


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


def test_match_import_resolves_issue_id_per_import_row():
    import_rows_seen = []

    def finalize(rows, *args, **kwargs):
        import_rows_seen.extend(rows)
        return {"success": True}

    with (
        patch.object(service.series_queries, "get_comic_name", return_value="Berserk"),
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
                    "IssueNumber": "1",
                },
                {
                    "impID": "imp-2",
                    "ComicLocation": "/import/Berserk/chapter 2.cbz",
                    "ComicFilename": "chapter 2.cbz",
                    "IssueNumber": "2",
                },
            ],
        ),
        patch.object(
            service.series_queries, "get_issue_id_for_import", side_effect=["mal-123-ch1", "mal-123-ch2"]
        ) as mock_get_issue,
        patch.object(service, "_finalize_import_rows", side_effect=finalize),
        patch.object(service.series_queries, "match_import") as mock_match,
    ):
        result = service.match_import(None, ["imp-1", "imp-2"], "mal-123", comic_name="Berserk")

    assert result["success"] is True
    assert [row["_ResolvedIssueID"] for row in import_rows_seen] == ["mal-123-ch1", "mal-123-ch2"]
    mock_get_issue.assert_has_calls([call("mal-123", "1"), call("mal-123", "2")])
    mock_match.assert_has_calls(
        [
            call("imp-1", "mal-123", "Berserk", issue_id="mal-123-ch1"),
            call("imp-2", "mal-123", "Berserk", issue_id="mal-123-ch2"),
        ]
    )


def test_match_import_uses_request_issue_id_as_fallback():
    with (
        patch.object(service.series_queries, "get_comic_name", return_value="Berserk"),
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
                    "ComicLocation": "/import/Berserk/chapter x.cbz",
                    "ComicFilename": "chapter x.cbz",
                    "IssueNumber": "x",
                }
            ],
        ),
        patch.object(service.series_queries, "get_issue_id_for_import", return_value=None),
        patch.object(service, "_finalize_import_rows", return_value={"success": True}),
        patch.object(service.series_queries, "match_import") as mock_match,
    ):
        result = service.match_import(None, ["imp-1"], "mal-123", comic_name="Berserk", issue_id="fallback-ch")

    assert result["success"] is True
    mock_match.assert_called_once_with("imp-1", "mal-123", "Berserk", issue_id="fallback-ch")


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


def test_match_import_move_mode_fails_when_destination_exists_without_marking_imported(tmp_path):
    import_dir = tmp_path / "import" / "Berserk"
    target_dir = tmp_path / "library" / "Berserk"
    import_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)
    source_file = import_dir / "chapter 1.cbz"
    destination_file = target_dir / "chapter 1.cbz"
    source_file.write_text("new chapter")
    destination_file.write_text("existing chapter")
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
        patch("comicarr.updater.forceRescan") as mock_rescan,
        patch.object(service.series_queries, "match_import") as mock_match,
    ):
        result = service.match_import(None, ["imp-1"], "mal-123", comic_name="Berserk")

    assert result["success"] is False
    assert "already exists" in result["error"]
    assert source_file.read_text() == "new chapter"
    assert destination_file.read_text() == "existing chapter"
    mock_rescan.assert_not_called()
    mock_match.assert_not_called()


def test_match_import_move_failure_rolls_back_prior_moves_without_marking_imported(tmp_path):
    import_dir = tmp_path / "import" / "Berserk"
    target_dir = tmp_path / "library" / "Berserk"
    import_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)
    first_source = import_dir / "chapter 1.cbz"
    second_source = import_dir / "chapter 2.cbz"
    first_source.write_text("chapter one")
    second_source.write_text("chapter two")
    config = SimpleNamespace(IMP_MOVE=True, IMP_RENAME=False, FILE_FORMAT="")
    original_move = service.shutil.move

    def move_with_second_failure(source_path, destination_path):
        if source_path == str(second_source):
            raise OSError("disk full")
        return original_move(source_path, destination_path)

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
                    "ComicLocation": str(first_source),
                    "ComicFilename": "chapter 1.cbz",
                    "IssueNumber": None,
                },
                {
                    "impID": "imp-2",
                    "ComicLocation": str(second_source),
                    "ComicFilename": "chapter 2.cbz",
                    "IssueNumber": None,
                },
            ],
        ),
        patch("comicarr.updater.forceRescan") as mock_rescan,
        patch.object(service.shutil, "move", side_effect=move_with_second_failure),
        patch.object(service.series_queries, "match_import") as mock_match,
    ):
        result = service.match_import(None, ["imp-1", "imp-2"], "mal-123", comic_name="Berserk")

    assert result["success"] is False
    assert "Failed to move import file" in result["error"]
    assert first_source.read_text() == "chapter one"
    assert second_source.read_text() == "chapter two"
    assert not (target_dir / "chapter 1.cbz").exists()
    assert not (target_dir / "chapter 2.cbz").exists()
    mock_rescan.assert_not_called()
    mock_match.assert_not_called()


def test_match_import_rescan_failure_rolls_back_move_without_marking_imported(tmp_path):
    import_dir = tmp_path / "import" / "Berserk"
    target_dir = tmp_path / "library" / "Berserk"
    import_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)
    source_file = import_dir / "chapter 1.cbz"
    source_file.write_text("chapter")
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
        patch("comicarr.updater.forceRescan", side_effect=RuntimeError("scan failed")) as mock_rescan,
        patch.object(service.series_queries, "match_import") as mock_match,
    ):
        result = service.match_import(None, ["imp-1"], "mal-123", comic_name="Berserk")

    assert result["success"] is False
    assert "Failed to rescan" in result["error"]
    assert source_file.read_text() == "chapter"
    assert not (target_dir / "chapter 1.cbz").exists()
    mock_rescan.assert_called_once_with("mal-123")
    mock_match.assert_not_called()


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


def test_match_import_target_file_location_does_not_mark_row_imported(tmp_path):
    import_dir = tmp_path / "import" / "Berserk"
    library_dir = tmp_path / "library"
    import_dir.mkdir(parents=True)
    library_dir.mkdir(parents=True)
    source_file = import_dir / "chapter 1.cbz"
    target_file = library_dir / "Berserk"
    source_file.write_text("chapter")
    target_file.write_text("not a directory")
    config = SimpleNamespace(IMP_MOVE=False, IMP_RENAME=False, FILE_FORMAT="")

    with (
        patch.object(service.comicarr, "CONFIG", config),
        patch.object(service.series_queries, "get_comic_name", return_value="Berserk"),
        patch.object(
            service.series_queries,
            "get_comic_for_import",
            return_value={"ComicName": "Berserk", "ComicLocation": str(target_file)},
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
    assert "not a directory" in result["error"]
    assert source_file.exists()
    assert target_file.is_file()
    mock_rescan.assert_not_called()
    mock_match.assert_not_called()
