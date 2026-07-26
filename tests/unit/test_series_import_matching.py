#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for Import Inbox behavior that remains in the Series domain."""

from unittest.mock import MagicMock, patch

from comicarr.app.series import queries, service


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
    assert [group["DynamicName"] for group in result["imports"]] == ["folder:manga-a", "file:root-a"]


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
            service.series_queries,
            "get_import_row",
            return_value={"impID": "imp-1", "Status": "Not Imported"},
        ),
        patch.object(service.series_queries, "update_import_issue_number") as update_issue_number,
    ):
        result = service.update_import_metadata(None, " imp-1 ", " 2.5 ")

    assert result == {"success": True, "imp_id": "imp-1", "issue_number": "2.5"}
    update_issue_number.assert_called_once_with("imp-1", "2.5")
