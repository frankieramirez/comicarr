#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for the series domain service."""

import datetime
import os
import queue
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

import comicarr
from comicarr.app.core.context import AppContext
from comicarr.app.search import commands as search_commands
from comicarr.app.series import queries as series_queries
from comicarr.app.series import service as series_service


def _state_row(**overrides):
    row = {
        "id": "issue-1",
        "status": None,
        "acquisitionIntent": None,
        "location": None,
        "releaseDate": "2026-01-01",
        "digitalDate": None,
        "issueDate": None,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("row", "series_status", "expected"),
    [
        (
            _state_row(status=None),
            "Active",
            {"fulfillment": "unknown", "displayState": "Unknown", "owned": False, "eligible": True},
        ),
        (
            _state_row(status="Archived"),
            "Active",
            {"fulfillment": "archived", "displayState": "Archived", "owned": True, "eligible": False},
        ),
        (
            _state_row(status="Reserved"),
            "Active",
            {"fulfillment": "reserved", "displayState": "Reserved", "inFlight": True, "eligible": False},
        ),
        (
            _state_row(status="Snatched"),
            "Active",
            {"fulfillment": "snatched", "displayState": "Snatched", "inFlight": True, "eligible": False},
        ),
        (
            _state_row(status="Failed"),
            "Active",
            {"fulfillment": "failed", "displayState": "Failed", "missing": True, "eligible": True},
        ),
        (
            _state_row(status="Skipped", acquisitionIntent="skipped", location="/comics/missing.cbz"),
            "Active",
            {
                "acquisitionIntent": "skipped",
                "fulfillment": "missing",
                "displayState": "Skipped",
                "owned": False,
                "physicalOwned": False,
                "monitored": False,
            },
        ),
        (
            _state_row(status="Skipped", releaseDate="2027-01-01"),
            "Active",
            {"displayState": "Skipped", "eligibilityReason": "future", "future": True, "eligible": False},
        ),
        (
            _state_row(status="Wanted"),
            "Paused",
            {"displayState": "Missing", "eligibilityReason": "paused", "eligible": False},
        ),
        (
            _state_row(status="Wanted"),
            "Ended",
            {"displayState": "Missing", "eligibilityReason": "series_inactive", "eligible": False},
        ),
    ],
)
def test_project_issue_state_is_canonical_and_evidence_backed(row, series_status, expected):
    projected = series_service.project_issue_state(
        row,
        series_status=series_status,
        today=datetime.date(2026, 7, 10),
    )

    for key, value in expected.items():
        assert projected[key] == value
    assert projected["legacyStatus"] == row["status"]


def test_explicit_skip_with_verified_file_keeps_intent_and_reports_owned(tmp_path):
    series_root = tmp_path / "Absolute Batman"
    series_root.mkdir()
    issue_file = series_root / "Absolute Batman 001.cbz"
    issue_file.write_text("comic")

    projected = series_service.project_issue_state(
        _state_row(status="Skipped", acquisitionIntent="skipped", location=issue_file.name),
        series_status="Active",
        series_location=str(series_root),
        today=datetime.date(2026, 7, 10),
    )

    assert projected["acquisitionIntent"] == "skipped"
    assert projected["fulfillment"] == "downloaded"
    assert projected["displayState"] == "Downloaded"
    assert projected["owned"] is True
    assert projected["physicalOwned"] is True


def test_absolute_batman_projection_reconciles_18_owned_2_released_2_future(tmp_path):
    series_root = tmp_path / "Absolute Batman"
    series_root.mkdir()
    for index in range(18):
        (series_root / ("absolute-%s.cbz" % index)).write_text("comic")
    rows = [
        _state_row(id="file-%s" % index, status="Skipped", location="absolute-%s.cbz" % index) for index in range(18)
    ]
    rows.extend(_state_row(id="released-%s" % index, status=None, releaseDate="2026-06-01") for index in range(2))
    rows.extend(_state_row(id="future-%s" % index, status="Skipped", releaseDate="2027-01-01") for index in range(2))

    projected, summary = series_service.project_issue_collection(
        rows,
        series_status="Active",
        today=datetime.date(2026, 7, 10),
        series_location=str(series_root),
    )

    assert len(projected) == 22
    assert summary == {
        "total": 22,
        "issues": 22,
        "annuals": 0,
        "owned": 18,
        "covered": 0,
        "physicalOwned": 18,
        "archived": 0,
        "inFlight": 0,
        "missing": 4,
        "monitored": 22,
        "wanted": 0,
        "skipped": 0,
        "ignored": 0,
        "failed": 0,
        "unknown": 2,
        "future": 2,
        "eligible": 2,
        "deferred": 2,
        "completionPercent": 82,
    }


def test_get_comic_detail_returns_backend_summary_for_issues_and_null_deleted_annuals(monkeypatch, tmp_path):
    series_root = tmp_path / "Absolute Batman"
    series_root.mkdir()
    (series_root / "001.cbz").write_text("comic")
    monkeypatch.setattr(
        series_service.series_queries,
        "get_comic",
        lambda _comic_id: [{"ComicID": "160294", "Status": "Active", "ComicLocation": str(series_root)}],
    )
    monkeypatch.setattr(
        series_service.series_queries,
        "get_issues",
        lambda _comic_id: [_state_row(id="owned", status="Downloaded", location="001.cbz")],
    )
    monkeypatch.setattr(
        series_service.series_queries,
        "get_annuals",
        lambda _comic_id: [_state_row(id="annual", status="Archived")],
    )

    result = series_service.get_comic_detail(_make_ctx(ANNUALS_ON=True), "160294")

    assert result["summary"]["total"] == 2
    assert result["summary"]["owned"] == 2
    assert result["summary"]["issues"] == 1
    assert result["summary"]["annuals"] == 1
    assert result["annuals"][0]["annual"] is True
    assert result["providerLinks"] == [
        {
            "provider": "comicvine",
            "label": "ComicVine",
            "url": "https://comicvine.gamespot.com/volume/4050-160294/",
        }
    ]


def test_get_annuals_keeps_legacy_null_deleted_rows(monkeypatch):
    select_all = MagicMock(return_value=[])
    monkeypatch.setattr(series_queries.db, "select_all", select_all)

    series_queries.get_annuals("160294")

    sql = str(select_all.call_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert 'annuals."Deleted" IS NULL' in sql
    assert 'annuals."Deleted" != 1' in sql


def _make_ctx(**config_overrides):
    config_values = {
        "COMIC_DIR": None,
        "MANGA_DIR": None,
        "DESTINATION_DIR": None,
        "MANGA_DESTINATION_DIR": None,
        "MULTIPLE_DEST_DIRS": None,
        "NEWCOM_DIR": None,
    }
    config_values.update(config_overrides)
    return AppContext(config=SimpleNamespace(**config_values))


def _comic(location):
    return {
        "ComicName": "Example Series",
        "ComicYear": "2026",
        "ComicLocation": str(location),
    }


def _delete(ctx, location, delete_side_effect=None):
    with (
        patch.object(series_service.series_queries, "get_comic_for_delete", return_value=_comic(location)),
        patch.object(series_service.series_queries, "delete_comic") as delete_from_db,
    ):
        delete_from_db.side_effect = delete_side_effect
        result = series_service.delete_comic(ctx, "123", delete_directory=True)
    return result, delete_from_db


def test_refresh_comic_includes_canonical_series_year(monkeypatch):
    refresh_thread = MagicMock()
    monkeypatch.setattr(comicarr, "REFRESH_QUEUE", SimpleNamespace(queue=[]))
    monkeypatch.setattr(comicarr, "importer", SimpleNamespace(refresh_thread=refresh_thread))
    monkeypatch.setattr(
        series_service.series_queries,
        "get_comic_for_refresh",
        lambda _comic_id: {"ComicName": "Absolute Batman", "ComicYear": "2024"},
    )

    result = series_service.refresh_comic(_make_ctx(), "160294")

    assert result["success"] is True
    refresh_thread.assert_called_once_with(
        [{"comicid": "160294", "comicname": "Absolute Batman", "seriesyear": "2024"}]
    )


def test_refresh_comic_coalesces_existing_mapping_command(monkeypatch):
    refresh_thread = MagicMock()
    refresh_queue = queue.Queue()
    refresh_queue.put({"comicid": "160294", "comicname": "Absolute Batman", "seriesyear": "2024"})
    monkeypatch.setattr(comicarr, "REFRESH_QUEUE", refresh_queue)
    monkeypatch.setattr(comicarr, "importer", SimpleNamespace(refresh_thread=refresh_thread))
    monkeypatch.setattr(
        series_service.series_queries,
        "get_comic_for_refresh",
        lambda _comic_id: {"ComicName": "Absolute Batman", "ComicYear": "2024"},
    )

    result = series_service.refresh_comic(_make_ctx(), "160294")

    assert result == {"success": True, "message": "Already queued for refresh"}
    refresh_thread.assert_not_called()


def test_queue_issue_persists_search_before_async_handoff(monkeypatch):
    mark_wanted = MagicMock()
    enqueue = MagicMock(return_value=SimpleNamespace(run_id="search-run"))
    monkeypatch.setattr(series_service.series_queries, "queue_issue", mark_wanted)
    monkeypatch.setattr(search_commands, "enqueue_search_command", enqueue)

    result = series_service.queue_issue(_make_ctx(), "issue-1", audit_identity="frankie")

    mark_wanted.assert_called_once_with("issue-1", "frankie")
    enqueue.assert_called_once_with({"issueid": "issue-1"}, trigger="issue_wanted")
    assert result == {"success": True, "run_id": "search-run"}


def test_explicit_issue_actions_dual_write_canonical_intent(monkeypatch):
    upsert = MagicMock()
    monkeypatch.setattr(series_queries.db, "upsert", upsert)

    series_queries.queue_issue("issue-1", "frankie")
    series_queries.unqueue_issue("issue-2", "frankie")

    assert upsert.call_args_list == [
        call(
            "issues",
            {"AcquisitionIntent": "wanted", "Status": "Wanted"},
            {"IssueID": "issue-1"},
        ),
        call(
            "issues",
            {"AcquisitionIntent": "skipped", "Status": "Skipped"},
            {"IssueID": "issue-2"},
        ),
    ]


def test_update_search_settings_stores_flag_columns_in_search_readable_form(monkeypatch):
    """AllowPacks is read as == 1 / == "1" by search.py; IgnoreType via bool()."""
    upsert = MagicMock()
    rows = iter(
        [
            {"ComicID": "160294", "AllowPacks": None, "IgnoreType": None},
            {"ComicID": "160294", "AllowPacks": "1", "IgnoreType": 0},
        ]
    )
    monkeypatch.setattr(series_service.series_queries, "get_comic_search_settings", lambda _comic_id: next(rows))
    monkeypatch.setattr(series_service.series_queries, "update_comic_search_settings", upsert)

    result = series_service.update_search_settings(_make_ctx(), "160294", allow_packs=True, ignore_type=False)

    upsert.assert_called_once_with("160294", {"AllowPacks": "1", "IgnoreType": 0})
    assert result == {"success": True, "settings": {"allow_packs": True, "ignore_type": False}}


def test_update_search_settings_is_partial_and_rejects_unknown_series(monkeypatch):
    upsert = MagicMock()
    monkeypatch.setattr(
        series_service.series_queries,
        "get_comic_search_settings",
        lambda comic_id: {"ComicID": "160294", "AllowPacks": "0", "IgnoreType": 1} if comic_id == "160294" else None,
    )
    monkeypatch.setattr(series_service.series_queries, "update_comic_search_settings", upsert)

    missing = series_service.update_search_settings(_make_ctx(), "999999", allow_packs=True)
    assert missing["success"] is False
    upsert.assert_not_called()

    empty = series_service.update_search_settings(_make_ctx(), "160294")
    assert empty["success"] is False
    upsert.assert_not_called()

    partial = series_service.update_search_settings(_make_ctx(), "160294", ignore_type=False)
    assert partial["success"] is True
    upsert.assert_called_once_with("160294", {"IgnoreType": 0})


def test_search_settings_query_upserts_lowercase_comics_table(monkeypatch):
    upsert = MagicMock()
    monkeypatch.setattr(series_queries.db, "upsert", upsert)

    series_queries.update_comic_search_settings("160294", {"AllowPacks": "1", "IgnoreType": 1})

    upsert.assert_called_once_with("comics", {"AllowPacks": "1", "IgnoreType": 1}, {"ComicID": "160294"})


@pytest.mark.parametrize("content_type", ["comic", "manga"])
def test_update_content_kind_persists_and_returns_canonical_value(monkeypatch, content_type):
    update = MagicMock()
    rows = iter(
        [
            {"ComicID": "160294", "ContentType": "comic"},
            {"ComicID": "160294", "ContentType": content_type},
        ]
    )
    monkeypatch.setattr(series_service.series_queries, "get_comic_content_kind", lambda _comic_id: next(rows))
    monkeypatch.setattr(series_service.series_queries, "update_comic_content_kind", update)

    result = series_service.update_content_kind(_make_ctx(), "160294", content_type)

    update.assert_called_once_with("160294", content_type)
    assert result == {"success": True, "content_type": content_type}


def test_update_content_kind_rejects_unknown_series_without_writing(monkeypatch):
    update = MagicMock()
    monkeypatch.setattr(series_service.series_queries, "get_comic_content_kind", lambda _comic_id: None)
    monkeypatch.setattr(series_service.series_queries, "update_comic_content_kind", update)

    result = series_service.update_content_kind(_make_ctx(), "missing", "manga")

    assert result == {"success": False, "error": "ComicID missing not found in watchlist"}
    update.assert_not_called()


def test_content_kind_query_updates_only_content_type(monkeypatch):
    upsert = MagicMock()
    monkeypatch.setattr(series_queries.db, "upsert", upsert)

    series_queries.update_comic_content_kind("160294", "manga")

    upsert.assert_called_once_with("comics", {"ContentType": "manga"}, {"ComicID": "160294"})


def test_preview_search_all_missing_excludes_owned_future_and_skipped(monkeypatch):
    projected = [
        series_service.project_issue_state(row, series_status="Active")
        for row in (
            _state_row(id="owned", status="Downloaded", location="/library/1.cbz"),
            _state_row(id="released", status=None, releaseDate="2026-01-01"),
            _state_row(id="future", status=None, releaseDate="2099-01-01"),
            _state_row(id="skipped", status="Skipped", acquisitionIntent="skipped", releaseDate="2026-01-01"),
        )
    ]
    projected[0].update(
        {
            "fulfillment": "downloaded",
            "displayState": "Downloaded",
            "owned": True,
            "physicalOwned": True,
            "missing": False,
            "eligible": False,
            "eligibilityReason": "owned",
        }
    )
    monkeypatch.setattr(
        series_service,
        "get_comic_detail",
        lambda _ctx, _comic_id: {
            "comic": [{"ComicID": "160294", "Status": "Active"}],
            "issues": projected,
            "annuals": [],
            "summary": {"total": 4},
        },
    )

    import comicarr.app.search.health as search_health

    monkeypatch.setattr(
        search_health,
        "get_search_health",
        lambda *_args, **_kwargs: {
            "viable_route": True,
            "routes": {
                "ddl": {"ready": True, "reason": "ready"},
                "nzb": {"ready": False, "reason": "disabled"},
                "torrent": {"ready": False, "reason": "disabled"},
            },
        },
    )

    preview = series_service.preview_search_all_missing(_make_ctx(), "160294")

    assert preview["success"] is True
    assert preview["eligibleCount"] == 1
    assert preview["eligible"][0]["issueId"] == "released"
    reasons = {item["issueId"]: item["reason"] for item in preview["excluded"]}
    assert reasons["owned"] == "owned"
    assert reasons["future"] == "future"
    assert reasons["skipped"] == "explicit_skip"
    assert preview["canSearch"] is True


def test_search_all_missing_reports_one_durable_confirmed_run(monkeypatch):
    selection = [{"entity_type": "issue", "entity_id": "a", "source": {}}]
    preview = {
        "success": True,
        "eligible": [{"issueId": "a"}],
        "excludedCount": 3,
        "route": {"viable": True},
    }
    monkeypatch.setattr(series_service, "_search_missing_preview_state", lambda *_args: (selection, preview))
    import comicarr.app.search.bulk as bulk

    confirm = MagicMock(
        return_value={"run_id": "search-run", "accepted": 1, "idempotent": True, "dispatch_error": None}
    )
    monkeypatch.setattr(bulk, "confirm_preview", confirm)
    monkeypatch.setattr(
        bulk,
        "read_preview",
        lambda *_args, **_kwargs: {"series_id": "160294", "state": "previewed", "run_id": None},
    )
    monkeypatch.setattr(series_service.db, "get_engine", MagicMock(return_value=object()))

    result = series_service.search_all_missing(
        _make_ctx(),
        "160294",
        "frankie",
        confirm=True,
        preview_token="token",
        fingerprint="fingerprint",
        session_id="session",
    )

    assert result["success"] is True
    assert result["accepted"] == 1
    assert result["run_id"] == "search-run"
    assert result["idempotent"] is True
    confirm.assert_called_once()


def test_search_all_missing_requires_confirm_and_reports_blocked_route(monkeypatch):
    monkeypatch.setattr(
        series_service,
        "_search_missing_preview_state",
        lambda *_args, **_kwargs: (
            [{"entity_id": "a"}],
            {
                "success": True,
                "eligible": [{"issueId": "a"}],
                "excludedCount": 0,
                "route": {"viable": False, "reason": "no_viable_acquisition_route"},
            },
        ),
    )
    import comicarr.app.search.bulk as bulk

    monkeypatch.setattr(
        bulk,
        "read_preview",
        lambda *_args, **_kwargs: {"series_id": "160294", "state": "previewed", "run_id": None},
    )
    monkeypatch.setattr(series_service.db, "get_engine", MagicMock(return_value=object()))

    denied = series_service.search_all_missing(_make_ctx(), "160294", "frankie", confirm=False)
    blocked = series_service.search_all_missing(
        _make_ctx(),
        "160294",
        "frankie",
        confirm=True,
        preview_token="token",
        fingerprint="fingerprint",
        session_id="session",
    )

    assert denied["success"] is False
    assert blocked["status"] == "blocked"
    assert blocked["error"] == "no_viable_acquisition_route"


class TestDeleteComicDirectory:
    def test_rejects_directory_when_no_library_root_is_configured(self, tmp_path):
        series_directory = tmp_path / "series"
        series_directory.mkdir()

        result, delete_from_db = _delete(_make_ctx(), series_directory)

        assert result["success"] is False
        assert series_directory.is_dir()
        delete_from_db.assert_not_called()

    def test_rejects_directory_outside_configured_library_roots(self, tmp_path):
        library_root = tmp_path / "library"
        outside_series = tmp_path / "outside" / "series"
        library_root.mkdir()
        outside_series.mkdir(parents=True)

        result, delete_from_db = _delete(
            _make_ctx(DESTINATION_DIR=str(library_root)),
            outside_series,
        )

        assert result["success"] is False
        assert outside_series.is_dir()
        delete_from_db.assert_not_called()

    def test_rejects_path_prefix_sibling_of_library_root(self, tmp_path):
        """A path that shares a string prefix with the root must not authorize deletion."""
        library_root = tmp_path / "library"
        evil_series = tmp_path / "library-evil" / "series"
        library_root.mkdir()
        evil_series.mkdir(parents=True)

        result, delete_from_db = _delete(
            _make_ctx(DESTINATION_DIR=str(library_root)),
            evil_series,
        )

        assert result["success"] is False
        assert evil_series.is_dir()
        delete_from_db.assert_not_called()

    @pytest.mark.parametrize(
        "root_value",
        ["None", "none", "  ", 42],
    )
    def test_rejects_when_configured_roots_are_empty_or_invalid(self, tmp_path, root_value):
        series_directory = tmp_path / "series"
        series_directory.mkdir()

        result, delete_from_db = _delete(
            _make_ctx(DESTINATION_DIR=root_value),
            series_directory,
        )

        assert result["success"] is False
        assert series_directory.is_dir()
        delete_from_db.assert_not_called()

    def test_rejects_configured_library_root_itself(self, tmp_path):
        library_root = tmp_path / "library"
        library_root.mkdir()

        result, delete_from_db = _delete(
            _make_ctx(DESTINATION_DIR=str(library_root)),
            library_root,
        )

        assert result["success"] is False
        assert library_root.is_dir()
        delete_from_db.assert_not_called()

    def test_rejects_symlink_that_escapes_library_root(self, tmp_path):
        library_root = tmp_path / "library"
        outside_series = tmp_path / "outside" / "series"
        library_root.mkdir()
        outside_series.mkdir(parents=True)
        linked_series = library_root / "linked-series"
        linked_series.symlink_to(outside_series, target_is_directory=True)

        result, delete_from_db = _delete(
            _make_ctx(DESTINATION_DIR=str(library_root)),
            linked_series,
        )

        assert result["success"] is False
        assert linked_series.is_symlink()
        assert outside_series.is_dir()
        delete_from_db.assert_not_called()

    def test_unlinks_in_library_symlink_without_removing_target(self, tmp_path):
        library_root = tmp_path / "library"
        real_series = library_root / "real-series"
        real_series.mkdir(parents=True)
        (real_series / "issue.cbz").write_text("x")
        linked_series = library_root / "linked-series"
        linked_series.symlink_to(real_series, target_is_directory=True)

        result, delete_from_db = _delete(
            _make_ctx(DESTINATION_DIR=str(library_root)),
            linked_series,
        )

        assert result["success"] is True
        assert not linked_series.exists()
        assert real_series.is_dir()
        assert (real_series / "issue.cbz").is_file()
        delete_from_db.assert_called_once_with("123")

    def test_unlinks_regular_file_comic_location(self, tmp_path):
        library_root = tmp_path / "library"
        library_root.mkdir()
        series_file = library_root / "series.cbz"
        series_file.write_text("comic-data")

        result, delete_from_db = _delete(
            _make_ctx(DESTINATION_DIR=str(library_root)),
            series_file,
        )

        assert result["success"] is True
        assert not series_file.exists()
        delete_from_db.assert_called_once_with("123")

    def test_rejects_filesystem_root_as_configured_library_root(self, tmp_path):
        series_directory = tmp_path / "series"
        series_directory.mkdir()

        result, delete_from_db = _delete(
            _make_ctx(DESTINATION_DIR=os.sep),
            series_directory,
        )

        assert result["success"] is False
        assert series_directory.is_dir()
        delete_from_db.assert_not_called()

    def test_filesystem_failure_does_not_delete_database_rows(self, tmp_path):
        library_root = tmp_path / "library"
        series_directory = library_root / "series"
        series_directory.mkdir(parents=True)

        with (
            patch.object(
                series_service.series_queries,
                "get_comic_for_delete",
                return_value=_comic(series_directory),
            ),
            patch.object(series_service.shutil, "rmtree", side_effect=OSError("permission denied")),
            patch.object(series_service.series_queries, "delete_comic") as delete_from_db,
        ):
            result = series_service.delete_comic(
                _make_ctx(DESTINATION_DIR=str(library_root)),
                "123",
                delete_directory=True,
            )

        assert result["success"] is False
        assert series_directory.is_dir()
        delete_from_db.assert_not_called()

    @pytest.mark.parametrize(
        "root_key",
        [
            "DESTINATION_DIR",
            "MANGA_DESTINATION_DIR",
            "COMIC_DIR",
            "MANGA_DIR",
            "MULTIPLE_DEST_DIRS",
            "NEWCOM_DIR",
        ],
    )
    def test_valid_strict_descendant_is_removed_before_database_rows(self, tmp_path, root_key):
        library_root = tmp_path / "library"
        series_directory = library_root / "series"
        series_directory.mkdir(parents=True)

        def assert_directory_was_removed(_comic_id):
            assert not series_directory.exists()

        result, delete_from_db = _delete(
            _make_ctx(**{root_key: str(library_root)}),
            series_directory,
            delete_side_effect=assert_directory_was_removed,
        )

        assert result["success"] is True
        assert not series_directory.exists()
        delete_from_db.assert_called_once_with("123")

    def test_missing_valid_directory_still_deletes_database_rows(self, tmp_path):
        library_root = tmp_path / "library"
        missing_series = library_root / "missing-series"
        library_root.mkdir()

        result, delete_from_db = _delete(
            _make_ctx(DESTINATION_DIR=str(library_root)),
            missing_series,
        )

        assert result["success"] is True
        delete_from_db.assert_called_once_with("123")

    def test_database_only_deletion_does_not_validate_or_remove_directory(self, tmp_path):
        outside_series = tmp_path / "outside" / "series"
        outside_series.mkdir(parents=True)
        ctx = _make_ctx()

        with (
            patch.object(
                series_service.series_queries,
                "get_comic_for_delete",
                return_value=_comic(outside_series),
            ),
            patch.object(series_service.series_queries, "delete_comic") as delete_from_db,
        ):
            result = series_service.delete_comic(ctx, "123", delete_directory=False)

        assert result["success"] is True
        assert outside_series.is_dir()
        delete_from_db.assert_called_once_with("123")
