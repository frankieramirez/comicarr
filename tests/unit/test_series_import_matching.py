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

from unittest.mock import patch

from comicarr.app.series import queries, service


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
        patch.object(service.series_queries, "match_import") as mock_match,
    ):
        result = service.match_import(None, ["imp-1"], "mal-123", comic_name="Berserk")

    assert result == {
        "success": True,
        "matched": 1,
        "imported": 1,
        "comic_id": "mal-123",
        "comic_name": "Berserk",
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
        patch.object(service.series_queries, "match_import") as mock_match,
    ):
        result = service.match_import(None, ["imp-1", ""], "mal-123", comic_name="Berserk")

    assert result["success"] is True
    assert result["matched"] == 1
    assert result["comic_name"] == "Existing Berserk"
    mock_match.assert_called_once_with("imp-1", "mal-123", "Existing Berserk", issue_id=None)
