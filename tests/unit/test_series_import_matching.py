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

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.schema import CreateTable

from comicarr.app.series import queries, service
from comicarr.tables import importresults


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
            "PageGroup": 0,
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
        patch.object(queries.db, "select_all", side_effect=[group_rows, file_rows]),
    ):
        result = queries.get_import_pending(limit=50, offset=0)

    assert result["pagination"]["total"] == 2
    assert result["summary"] == {"group_count": 2, "file_count": 4}
    assert [group["DynamicName"] for group in result["imports"]] == ["folder:manga-a", "file:root-a"]


@pytest.fixture
def import_engine(monkeypatch):
    engine = create_engine("sqlite://")
    importresults.create(engine)
    monkeypatch.setattr(queries.db, "get_engine", lambda: engine)
    yield engine
    engine.dispose()


def _import_row(imp_id, **values):
    return {
        "impID": imp_id,
        "ComicName": "A",
        "DynamicName": "a",
        "Volume": "1",
        "ComicFilename": imp_id + ".cbz",
        "ComicLocation": "/imports/" + imp_id + ".cbz",
        "IssueNumber": imp_id,
        "ComicYear": "2026",
        "Status": "Unmatched",
        "WatchMatch": None,
        "IgnoreFile": 0,
        "MatchConfidence": None,
        "SuggestedComicID": None,
        "SuggestedComicName": None,
        "SuggestedIssueID": None,
        "MatchSource": None,
        **values,
    }


@pytest.mark.parametrize("include_ignored", [False, True])
def test_import_page_filters_files_before_batching(import_engine, include_ignored):
    rows = [
        _import_row("z", MatchConfidence=90),
        _import_row("a", MatchConfidence=71, IgnoreFile=None),
        _import_row("ignored", IgnoreFile=1),
        _import_row("imported", Status="Imported"),
        _import_row("matched", WatchMatch="Matched"),
        _import_row("null-status", Status=None),
        _import_row("b", ComicName="B", DynamicName="b", WatchMatch="C123"),
        _import_row("c", ComicName="C", DynamicName="c"),
    ]
    with import_engine.begin() as conn:
        conn.execute(importresults.insert(), rows)

    page = queries.get_import_pending(limit=1, include_ignored=include_ignored)
    assert page["summary"] == {"group_count": 3, "file_count": 5 if include_ignored else 4}
    assert page["pagination"] == {"total": 3, "limit": 1, "offset": 0, "has_more": True}
    group = page["imports"][0]
    assert [row["impID"] for row in group["files"]] == (["a", "ignored", "z"] if include_ignored else ["a", "z"])
    assert group["MatchConfidence"] == 80
    assert group["FileCount"] == (3 if include_ignored else 2)
    assert group["files"][0]["IgnoreFile"] == 0
    assert group["files"][0]["ComicLocation"] == "/imports/a.cbz"
    assert "GroupKey" not in group["files"][0]
    second = queries.get_import_pending(limit=1, offset=1)
    assert [row["impID"] for row in second["imports"][0]["files"]] == ["b"]


def test_import_group_fallbacks_and_legacy_null_volumes(import_engine):
    rows = [
        _import_row("a", Volume=None),
        _import_row("b", Volume="None"),
        _import_row("c", Volume="2"),
        _import_row("d", DynamicName="", ComicName="Fallback"),
        _import_row("e", DynamicName=None, ComicName="Fallback"),
        _import_row("f", DynamicName="", ComicName=""),
        _import_row("g", DynamicName=None, ComicName=None),
        _import_row("null-key", impID=None, DynamicName=None, ComicName=None),
    ]
    with import_engine.begin() as conn:
        conn.execute(importresults.insert(), rows)
    result = queries.get_import_pending()
    groups = {(g["DynamicName"], g["Volume"]): g for g in result["imports"]}
    for volume in (None, "None"):
        assert groups[("a", volume)]["FileCount"] == 1
        assert [f["impID"] for f in groups[("a", volume)]["files"]] == ["a", "b"]
    assert [f["impID"] for f in groups[("a", "2")]["files"]] == ["c"]
    assert [f["impID"] for f in groups[("Fallback", "1")]["files"]] == ["d", "e"]
    assert [f["impID"] for f in groups[("f", "1")]["files"]] == ["f"]
    assert [f["impID"] for f in groups[("g", "1")]["files"]] == ["g"]
    assert [f["impID"] for f in groups[(None, "1")]["files"]] == [None]


@pytest.mark.parametrize(("limit", "expected_queries"), [(50, 4), (450, 8)])
def test_import_queries_are_bounded_by_batches_not_groups(import_engine, limit, expected_queries):
    with import_engine.begin() as conn:
        conn.execute(
            importresults.insert(),
            [_import_row(str(i), ComicName=f"Series {i:04d}", Volume=str(i)) for i in range(450)],
        )
    statements = []
    event.listen(import_engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    result = queries.get_import_pending(limit=limit)
    assert len(statements) == expected_queries
    assert len(result["imports"]) == limit
    for i, group in enumerate(result["imports"]):
        assert [f["impID"] for f in group["files"]] == [str(i)]


def test_import_empty_page_does_not_read_files(import_engine):
    statements = []
    event.listen(import_engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    result = queries.get_import_pending(limit=50, offset=10)
    assert result["imports"] == []
    assert result["summary"] == {"group_count": 0, "file_count": 0}
    assert result["pagination"]["has_more"] is False
    assert len(statements) == 3


def test_mysql_collation_keeps_overlapping_legacy_volume_lists(import_engine, monkeypatch):
    # Exercise a case-insensitive volume collation with SQLite so the suite
    # covers the MySQL fallback without requiring an external database.
    importresults.drop(import_engine)
    ddl = str(CreateTable(importresults).compile(import_engine)).replace(
        '"Volume" TEXT', '"Volume" TEXT COLLATE NOCASE'
    )
    with import_engine.begin() as conn:
        conn.exec_driver_sql(ddl)
        conn.execute(importresults.insert(), [_import_row("a", Volume=None), _import_row("b", Volume="none")])
    monkeypatch.setattr(queries.db, "get_dialect", lambda: "mysql")
    result = queries.get_import_pending()
    groups = {group["Volume"]: group for group in result["imports"]}
    assert [f["impID"] for f in groups[None]["files"]] == ["a", "b"]
    assert [f["impID"] for f in groups["none"]["files"]] == ["b"]


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
