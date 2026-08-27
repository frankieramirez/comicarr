#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for the manual import finalization interface."""

import errno
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import call, patch

import pytest
from sqlalchemy import create_engine, insert, select

from comicarr.app.common import placement
from comicarr.app.imports import finalization
from comicarr.app.imports import queries as import_queries
from comicarr.app.series import router as series_router
from comicarr.tables import importresults


def _config(*, move=False, rename=False, file_opts="move"):
    return SimpleNamespace(
        IMP_MOVE=move,
        IMP_RENAME=rename,
        FILE_FORMAT="$Series $Issue",
        # Finalization ignored FILE_OPTS entirely before #342 and always moved,
        # so "move" is the setting under which every pre-existing test here was
        # written. The link and copy modes are new behaviour, covered below.
        FILE_OPTS=file_opts,
        ARC_FILEOPS=file_opts,
        ARC_FILEOPS_SOFTLINK_RELATIVE=False,
    )


def _ctx(*, move=False, rename=False, file_opts="move"):
    return SimpleNamespace(config=_config(move=move, rename=rename, file_opts=file_opts))


def _row(import_id, source_path, *, issue_number=None, filename=None, status="Unmatched"):
    return {
        "impID": import_id,
        "ComicLocation": str(source_path),
        "ComicFilename": filename or source_path.name,
        "IssueNumber": issue_number,
        "Status": status,
    }


@contextmanager
def _environment(rows, target_directory, *, series_id="mal-123", series_name="Berserk"):
    with (
        patch.object(finalization.import_queries, "get_import_rows", return_value=rows),
        patch.object(finalization.import_queries, "get_issue_id", return_value=None),
        patch.object(finalization.import_queries, "mark_imported") as mark_imported,
        patch.object(finalization.series_queries, "get_comic_name", return_value=series_name),
        patch.object(
            finalization.series_queries,
            "get_comic_for_import",
            return_value={"ComicName": series_name, "ComicLocation": str(target_directory)},
        ),
    ):
        yield mark_imported


@pytest.fixture(autouse=True)
def _mock_logger():
    with patch.object(finalization, "logger"):
        yield


def test_preflight_rejects_missing_records_before_adding_manga():
    ctx = SimpleNamespace(config=SimpleNamespace())

    with (
        patch.object(finalization.import_queries, "get_import_rows", return_value=[]),
        patch("comicarr.importer.addMangaToDB_MAL") as add_manga,
    ):
        with pytest.raises(finalization.ImportFinalizationError, match="Missing import record") as exc_info:
            finalization.finalize_manual_match(ctx, ["imp-1"], "mal-123")

    assert exc_info.value.phase == "preflight"
    add_manga.assert_not_called()


def test_scalar_import_id_is_treated_as_one_identifier(tmp_path):
    source = tmp_path / "chapter.cbz"
    target_directory = tmp_path / "library"
    source.write_text("chapter")
    target_directory.mkdir()

    with (
        _environment([_row("imp-1", source)], target_directory),
        patch("comicarr.updater.forceRescan"),
    ):
        result = finalization.finalize_manual_match(_ctx(), "imp-1", "mal-123")

    assert result.matched == 1


def test_unexpected_failure_uses_public_error_type():
    with patch.object(finalization.import_queries, "get_import_rows", side_effect=RuntimeError("database offline")):
        with pytest.raises(finalization.ImportFinalizationError, match="database offline") as exc_info:
            finalization.finalize_manual_match(_ctx(), ["imp-1"], "mal-123")

    assert exc_info.value.phase == "finalization"


def test_move_mode_finalizes_through_one_interface(tmp_path):
    source_directory = tmp_path / "inbox"
    target_directory = tmp_path / "library" / "Berserk"
    source_directory.mkdir()
    target_directory.mkdir(parents=True)
    source = source_directory / "chapter 1.cbz"
    source.write_text("chapter")
    rows = [_row("imp-1", source, issue_number="1")]
    events = []

    with (
        _environment(rows, target_directory),
        patch.object(finalization.import_queries, "get_issue_id", return_value="mal-123-ch1"),
        patch.object(
            finalization.import_queries, "mark_imported", side_effect=lambda *_args, **_kwargs: events.append("commit")
        ) as mark_imported,
        patch("comicarr.updater.forceRescan", side_effect=lambda *_args: events.append("rescan")) as force_rescan,
    ):
        result = finalization.finalize_manual_match(_ctx(move=True), [" imp-1 ", "imp-1"], "mal-123")

    assert result == finalization.ImportFinalizationResult(1, "mal-123", "Berserk", 1, 0)
    assert not source.exists()
    assert (target_directory / source.name).read_text() == "chapter"
    force_rescan.assert_called_once_with("mal-123")
    mark_imported.assert_called_once_with(
        [("imp-1", "mal-123-ch1")], "mal-123", "Berserk", match_source="manual", match_confidence=100
    )
    assert events == ["rescan", "commit"]


def test_missing_manga_is_added_only_after_preflight(tmp_path):
    source = tmp_path / "chapter 1.cbz"
    target_directory = tmp_path / "library" / "Berserk"
    source.write_text("chapter")
    target_directory.mkdir(parents=True)
    rows = [_row("imp-1", source)]

    with (
        _environment(rows, target_directory),
        patch.object(finalization.series_queries, "get_comic_name", return_value=None),
        patch("comicarr.importer.addMangaToDB_MAL", return_value={"status": "complete", "comicname": "Berserk"}) as add,
        patch("comicarr.updater.forceRescan"),
    ):
        result = finalization.finalize_manual_match(_ctx(), ["imp-1"], "mal-123")

    assert result.series_name == "Berserk"
    add.assert_called_once_with("mal-123")


def test_issue_ids_resolve_per_record_with_fallback(tmp_path):
    first = tmp_path / "chapter 1.cbz"
    second = tmp_path / "chapter x.cbz"
    target_directory = tmp_path / "library"
    first.write_text("one")
    second.write_text("two")
    target_directory.mkdir()
    rows = [_row("imp-1", first, issue_number="1"), _row("imp-2", second, issue_number="x")]

    with (
        _environment(rows, target_directory) as mark_imported,
        patch.object(finalization.import_queries, "get_issue_id", side_effect=["chapter-1", None]),
        patch("comicarr.updater.forceRescan"),
    ):
        finalization.finalize_manual_match(
            _ctx(),
            ["imp-1", "imp-2"],
            "mal-123",
            fallback_issue_id="fallback",
        )

    mark_imported.assert_called_once_with(
        [("imp-1", "chapter-1"), ("imp-2", "fallback")],
        "mal-123",
        "Berserk",
        match_source="manual",
        match_confidence=100,
    )


def test_move_preflight_rejects_existing_destination(tmp_path):
    source = tmp_path / "inbox" / "chapter.cbz"
    target_directory = tmp_path / "library"
    source.parent.mkdir()
    target_directory.mkdir()
    source.write_text("new")
    (target_directory / source.name).write_text("existing")

    with (
        _environment([_row("imp-1", source)], target_directory) as mark_imported,
        patch("comicarr.updater.forceRescan") as force_rescan,
    ):
        with pytest.raises(finalization.ImportFinalizationError, match="already exists") as exc_info:
            finalization.finalize_manual_match(_ctx(move=True), ["imp-1"], "mal-123")

    assert exc_info.value.phase == "preflight"
    assert source.read_text() == "new"
    force_rescan.assert_not_called()
    mark_imported.assert_not_called()


def test_move_does_not_overwrite_destination_created_at_transfer_boundary(tmp_path):
    source = tmp_path / "inbox" / "chapter.cbz"
    target_directory = tmp_path / "library"
    destination = target_directory / source.name
    source.parent.mkdir()
    target_directory.mkdir()
    source.write_text("new")
    original_link = os.link
    link_attempted = False

    def link_with_late_destination(source_path, destination_path):
        nonlocal link_attempted
        if destination_path == str(destination) and not link_attempted:
            link_attempted = True
            destination.write_text("external")
        return original_link(source_path, destination_path)

    with (
        _environment([_row("imp-1", source)], target_directory) as mark_imported,
        patch.object(placement.os, "link", side_effect=link_with_late_destination),
        patch("comicarr.updater.forceRescan") as force_rescan,
    ):
        with pytest.raises(finalization.ImportFinalizationError, match="File exists") as exc_info:
            finalization.finalize_manual_match(_ctx(move=True), ["imp-1"], "mal-123")

    assert exc_info.value.phase == "move"
    assert source.read_text() == "new"
    assert destination.read_text() == "external"
    force_rescan.assert_not_called()
    mark_imported.assert_not_called()


def test_no_clobber_move_preserves_cross_filesystem_behavior(tmp_path):
    source = tmp_path / "inbox" / "chapter.cbz"
    destination = tmp_path / "library" / "chapter.cbz"
    source.parent.mkdir()
    destination.parent.mkdir()
    source.write_text("chapter")
    original_link = os.link
    attempts = 0

    def cross_filesystem_once(source_path, destination_path):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError(errno.EXDEV, "cross-device link")
        return original_link(source_path, destination_path)

    with patch.object(placement.os, "link", side_effect=cross_filesystem_once):
        placement.place(
            str(source),
            str(destination),
            placement.Purpose.IMPORT,
            on_existing=placement.OnExisting.REFUSE,
            config=_config(move=True),
        )

    assert not source.exists()
    assert destination.read_text() == "chapter"
    assert list(destination.parent.glob(".comicarr-import-*")) == []


def test_preflight_rejects_missing_source_file(tmp_path):
    source = tmp_path / "missing.cbz"
    target_directory = tmp_path / "library"
    target_directory.mkdir()

    with patch.object(finalization.import_queries, "get_import_rows", return_value=[_row("imp-1", source)]):
        with pytest.raises(finalization.ImportFinalizationError, match="does not exist") as exc_info:
            finalization.finalize_manual_match(_ctx(move=True), ["imp-1"], "mal-123")

    assert exc_info.value.phase == "preflight"


@pytest.mark.parametrize("target_value", [None, "file"])
def test_preflight_rejects_invalid_target_directory(tmp_path, target_value):
    source = tmp_path / "chapter.cbz"
    source.write_text("chapter")
    target = None if target_value is None else tmp_path / "not-a-directory"
    if target is not None:
        target.write_text("file")

    with (
        patch.object(finalization.import_queries, "get_import_rows", return_value=[_row("imp-1", source)]),
        patch.object(finalization.series_queries, "get_comic_name", return_value="Berserk"),
        patch.object(
            finalization.series_queries,
            "get_comic_for_import",
            return_value={"ComicName": "Berserk", "ComicLocation": None if target is None else str(target)},
        ),
    ):
        with pytest.raises(finalization.ImportFinalizationError, match="no library directory|not a directory"):
            finalization.finalize_manual_match(_ctx(), ["imp-1"], "mal-123")


def test_move_preflight_rejects_duplicate_destinations(tmp_path):
    first = tmp_path / "one" / "chapter.cbz"
    second = tmp_path / "two" / "chapter.cbz"
    target_directory = tmp_path / "library"
    first.parent.mkdir()
    second.parent.mkdir()
    target_directory.mkdir()
    first.write_text("one")
    second.write_text("two")
    rows = [_row("imp-1", first), _row("imp-2", second)]

    with _environment(rows, target_directory) as mark_imported:
        with pytest.raises(finalization.ImportFinalizationError, match="same destination"):
            finalization.finalize_manual_match(_ctx(move=True), ["imp-1", "imp-2"], "mal-123")

    assert first.exists() and second.exists()
    mark_imported.assert_not_called()


def test_rename_failure_keeps_original_filename(tmp_path):
    source = tmp_path / "chapter.cbz"
    target_directory = tmp_path / "library"
    source.write_text("chapter")
    target_directory.mkdir()

    with (
        _environment([_row("imp-1", source, issue_number="1")], target_directory),
        patch("comicarr.helpers.rename_param", side_effect=ValueError("bad format")),
        patch("comicarr.updater.forceRescan"),
    ):
        finalization.finalize_manual_match(_ctx(move=True, rename=True), ["imp-1"], "mal-123")

    assert (target_directory / "chapter.cbz").exists()


def test_second_move_failure_rolls_back_first_move(tmp_path):
    first = tmp_path / "inbox" / "one.cbz"
    second = tmp_path / "inbox" / "two.cbz"
    target_directory = tmp_path / "library"
    first.parent.mkdir()
    target_directory.mkdir()
    first.write_text("one")
    second.write_text("two")
    rows = [_row("imp-1", first), _row("imp-2", second)]
    original_place = placement.place

    def fail_second_move(source_path, destination_path, purpose, **kwargs):
        if source_path == str(second):
            raise placement.PlacementError("disk full")
        return original_place(source_path, destination_path, purpose, **kwargs)

    with (
        _environment(rows, target_directory) as mark_imported,
        patch.object(placement, "place", side_effect=fail_second_move),
    ):
        with pytest.raises(finalization.ImportFinalizationError, match="disk full") as exc_info:
            finalization.finalize_manual_match(_ctx(move=True), ["imp-1", "imp-2"], "mal-123")

    assert exc_info.value.rollback_failed is False
    assert first.read_text() == "one" and second.read_text() == "two"
    mark_imported.assert_not_called()


def test_rescan_failure_rolls_back_and_reconciles(tmp_path):
    source = tmp_path / "chapter.cbz"
    target_directory = tmp_path / "library"
    source.write_text("chapter")
    target_directory.mkdir()

    with (
        _environment([_row("imp-1", source)], target_directory) as mark_imported,
        patch("comicarr.updater.forceRescan", side_effect=[RuntimeError("scan failed"), None]) as force_rescan,
    ):
        with pytest.raises(finalization.ImportFinalizationError, match="scan failed") as exc_info:
            finalization.finalize_manual_match(_ctx(move=True), ["imp-1"], "mal-123")

    assert exc_info.value.phase == "rescan"
    assert exc_info.value.rollback_failed is False
    assert source.exists()
    assert force_rescan.call_args_list == [call("mal-123"), call("mal-123")]
    mark_imported.assert_not_called()


def test_database_failure_after_move_restores_files_and_reconciles(tmp_path):
    source = tmp_path / "chapter.cbz"
    target_directory = tmp_path / "library"
    source.write_text("chapter")
    target_directory.mkdir()

    with (
        _environment([_row("imp-1", source)], target_directory),
        patch.object(finalization.import_queries, "mark_imported", side_effect=RuntimeError("database unavailable")),
        patch("comicarr.updater.forceRescan") as force_rescan,
    ):
        with pytest.raises(finalization.ImportFinalizationError, match="database unavailable") as exc_info:
            finalization.finalize_manual_match(_ctx(move=True), ["imp-1"], "mal-123")

    assert exc_info.value.phase == "commit"
    assert exc_info.value.rollback_failed is False
    assert source.exists()
    assert not (target_directory / source.name).exists()
    assert force_rescan.call_args_list == [call("mal-123"), call("mal-123")]


def test_database_failure_surfaces_incomplete_rollback(tmp_path):
    source = tmp_path / "chapter.cbz"
    target_directory = tmp_path / "library"
    source.write_text("chapter")
    target_directory.mkdir()

    def fail_reverse_move(destination_path, source_path):
        raise OSError("permission denied")

    with (
        _environment([_row("imp-1", source)], target_directory),
        patch.object(finalization.import_queries, "mark_imported", side_effect=RuntimeError("database unavailable")),
        patch.object(placement, "restore_moved_file", side_effect=fail_reverse_move),
        patch("comicarr.updater.forceRescan"),
    ):
        with pytest.raises(finalization.ImportFinalizationError, match="rollback incomplete") as exc_info:
            finalization.finalize_manual_match(_ctx(move=True), ["imp-1"], "mal-123")

    assert exc_info.value.rollback_failed is True
    assert (target_directory / source.name).exists()


def test_database_failure_does_not_overwrite_recreated_source_during_rollback(tmp_path):
    source = tmp_path / "inbox" / "chapter.cbz"
    target_directory = tmp_path / "library"
    source.parent.mkdir()
    target_directory.mkdir()
    source.write_text("chapter")

    def recreate_source(*_args, **_kwargs):
        source.write_text("external")
        raise RuntimeError("database unavailable")

    with (
        _environment([_row("imp-1", source)], target_directory),
        patch.object(finalization.import_queries, "mark_imported", side_effect=recreate_source),
        patch("comicarr.updater.forceRescan"),
    ):
        with pytest.raises(finalization.ImportFinalizationError, match="rollback incomplete") as exc_info:
            finalization.finalize_manual_match(_ctx(move=True), ["imp-1"], "mal-123")

    assert exc_info.value.rollback_failed is True
    assert source.read_text() == "external"
    assert (target_directory / source.name).read_text() == "chapter"


def test_database_failure_surfaces_missing_source_and_destination_during_rollback(tmp_path):
    source = tmp_path / "chapter.cbz"
    target_directory = tmp_path / "library"
    source.write_text("chapter")
    target_directory.mkdir()

    def delete_moved_file(*_args, **_kwargs):
        (target_directory / source.name).unlink()
        raise RuntimeError("database unavailable")

    with (
        _environment([_row("imp-1", source)], target_directory),
        patch.object(finalization.import_queries, "mark_imported", side_effect=delete_moved_file),
        patch("comicarr.updater.forceRescan"),
    ):
        with pytest.raises(
            finalization.ImportFinalizationError, match="source and destination are missing"
        ) as exc_info:
            finalization.finalize_manual_match(_ctx(move=True), ["imp-1"], "mal-123")

    assert exc_info.value.rollback_failed is True


def test_archive_mode_deduplicates_directories_and_is_retryable_after_commit_failure(tmp_path):
    source_directory = tmp_path / "inbox"
    target_directory = tmp_path / "library"
    source_directory.mkdir()
    target_directory.mkdir()
    first = source_directory / "one.cbz"
    second = source_directory / "two.cbz"
    first.write_text("one")
    second.write_text("two")
    rows = [_row("imp-1", first), _row("imp-2", second)]

    with (
        _environment(rows, target_directory),
        patch.object(finalization.import_queries, "mark_imported", side_effect=RuntimeError("database unavailable")),
        patch("comicarr.updater.forceRescan") as force_rescan,
    ):
        with pytest.raises(finalization.ImportFinalizationError) as exc_info:
            finalization.finalize_manual_match(_ctx(), ["imp-1", "imp-2"], "mal-123")

    assert exc_info.value.phase == "commit"
    assert exc_info.value.rollback_failed is False
    assert first.exists() and second.exists()
    assert force_rescan.call_args_list == [
        call("mal-123", archive=str(source_directory)),
        call("mal-123"),
    ]


def test_process_lock_prevents_finalizations_from_interleaving(tmp_path):
    source = tmp_path / "chapter.cbz"
    target_directory = tmp_path / "library"
    source.write_text("chapter")
    target_directory.mkdir()
    row = _row("imp-1", source)
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def load_rows(_ids):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.05)
        with state_lock:
            active -= 1
        return [row]

    with (
        patch.object(finalization.import_queries, "get_import_rows", side_effect=load_rows),
        patch.object(finalization.import_queries, "get_issue_id", return_value=None),
        patch.object(finalization.import_queries, "mark_imported"),
        patch.object(finalization.series_queries, "get_comic_name", return_value="Berserk"),
        patch.object(
            finalization.series_queries,
            "get_comic_for_import",
            return_value={"ComicName": "Berserk", "ComicLocation": str(target_directory)},
        ),
        patch("comicarr.updater.forceRescan"),
    ):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(finalization.finalize_manual_match, _ctx(), ["imp-1"], "mal-123") for _ in range(2)
            ]
            for future in futures:
                future.result()

    assert maximum_active == 1


def test_mark_imported_rolls_back_all_updates_when_one_record_is_no_longer_pending():
    engine = create_engine("sqlite://")
    importresults.create(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(importresults),
            [
                {"impID": "imp-1", "Status": "Unmatched"},
                {"impID": "imp-2", "Status": "Imported"},
            ],
        )

    with patch.object(import_queries.db, "get_engine", return_value=engine):
        with pytest.raises(import_queries.ImportRecordChangedError, match="imp-2"):
            import_queries.mark_imported(
                [("imp-1", "issue-1"), ("imp-2", "issue-2")],
                "mal-123",
                "Berserk",
            )

    with engine.connect() as conn:
        rows = {row.impID: row.Status for row in conn.execute(select(importresults.c.impID, importresults.c.Status))}
    assert rows == {"imp-1": "Unmatched", "imp-2": "Imported"}


def test_mark_imported_treats_imported_status_case_insensitively():
    engine = create_engine("sqlite://")
    importresults.create(engine)
    with engine.begin() as conn:
        conn.execute(insert(importresults), {"impID": "imp-1", "Status": "imported"})

    with patch.object(import_queries.db, "get_engine", return_value=engine):
        with pytest.raises(import_queries.ImportRecordChangedError, match="imp-1"):
            import_queries.mark_imported([("imp-1", None)], "mal-123", "Berserk")


def test_mark_imported_does_not_recreate_a_deleted_record():
    engine = create_engine("sqlite://")
    importresults.create(engine)

    with patch.object(import_queries.db, "get_engine", return_value=engine):
        with pytest.raises(import_queries.ImportRecordChangedError, match="imp-missing"):
            import_queries.mark_imported([("imp-missing", None)], "mal-123", "Berserk")

    with engine.connect() as conn:
        assert conn.execute(select(importresults.c.impID)).all() == []


def test_get_issue_id_prefers_chapter_number_then_falls_back_to_issue_number():
    with patch.object(import_queries.db, "select_one", side_effect=[None, {"IssueID": "issue-row"}]) as select_one:
        result = import_queries.get_issue_id("mal-123", "1")

    assert result == "issue-row"
    assert select_one.call_count == 2

    with patch.object(import_queries.db, "select_one", return_value={"IssueID": "chapter-row"}) as select_one:
        result = import_queries.get_issue_id("mal-123", "1")

    assert result == "chapter-row"
    assert select_one.call_count == 1


def test_router_preserves_success_response_shape():
    expected = finalization.ImportFinalizationResult(2, "mal-123", "Berserk", 2, 0)
    with patch.object(series_router.import_finalization, "finalize_manual_match", return_value=expected):
        response = series_router.match_import(
            {"imp_ids": ["imp-1", "imp-2"], "comic_id": "mal-123"},
            ctx=_ctx(),
        )

    assert response == {
        "success": True,
        "matched": 2,
        "imported": 2,
        "comic_id": "mal-123",
        "comic_name": "Berserk",
        "moved": 2,
        "archived": 0,
    }


@pytest.mark.parametrize(
    ("imp_ids", "stored_name", "request_name", "expected_name"),
    [
        ([""], "Stored Series", "Request Series", "Stored Series"),
        (",,", None, "Request Series", "Request Series"),
    ],
)
def test_router_preserves_normalized_empty_success_response(
    imp_ids,
    stored_name,
    request_name,
    expected_name,
):
    with (
        patch.object(series_router.series_queries, "get_comic_name", return_value=stored_name),
        patch.object(series_router.import_finalization, "finalize_manual_match") as finalize,
    ):
        response = series_router.match_import(
            {
                "imp_ids": imp_ids,
                "comic_id": "mal-123",
                "comic_name": request_name,
            },
            ctx=_ctx(),
        )

    assert response == {
        "success": True,
        "matched": 0,
        "imported": 0,
        "comic_id": "mal-123",
        "comic_name": expected_name,
        "moved": 0,
        "archived": 0,
    }
    finalize.assert_not_called()


def test_router_preserves_error_response_shape():
    error = finalization.ImportFinalizationError("disk full", phase="move")
    with patch.object(series_router.import_finalization, "finalize_manual_match", side_effect=error):
        response = series_router.match_import(
            {"imp_ids": ["imp-1"], "comic_id": "mal-123"},
            ctx=_ctx(),
        )

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": "disk full"}


class TestFinalizationHonoursFileOpts:
    """Finalization always moved, whatever FILE_OPTS said.

    The link and copy modes exist precisely so the download folder survives, so
    an operator running one of them lost their source file on every manual
    import. These are new behaviour -- there is no prior art to characterize.
    """

    @staticmethod
    def _finalize(tmp_path, file_opts):
        source = tmp_path / "inbox" / "chapter.cbz"
        target_directory = tmp_path / "library"
        source.parent.mkdir()
        target_directory.mkdir()
        source.write_text("chapter")

        with (
            _environment([_row("imp-1", source)], target_directory) as mark_imported,
            patch("comicarr.updater.forceRescan"),
        ):
            result = finalization.finalize_manual_match(_ctx(move=True, file_opts=file_opts), ["imp-1"], "mal-123")

        return source, target_directory / source.name, result, mark_imported

    @pytest.mark.parametrize("file_opts", ("copy", "hardlink", "softlink"))
    def test_source_preserving_modes_leave_the_operators_file_alone(self, tmp_path, file_opts):
        source, destination, result, mark_imported = self._finalize(tmp_path, file_opts)

        assert source.exists(), "%s must not consume the import source" % file_opts
        assert not source.is_symlink(), "an import must not replace the inbox file with a link"
        assert source.read_text() == "chapter"
        assert destination.exists()
        assert result.moved == 1
        mark_imported.assert_called_once()

    def test_move_still_consumes_the_source(self, tmp_path):
        source, destination, _result, _mark = self._finalize(tmp_path, "move")

        assert not source.exists()
        assert destination.read_text() == "chapter"

    def test_hardlink_publishes_one_inode_under_two_names(self, tmp_path):
        source, destination, _result, _mark = self._finalize(tmp_path, "hardlink")

        assert os.path.samefile(source, destination)

    def test_softlink_points_the_library_at_the_inbox_file(self, tmp_path):
        source, destination, _result, _mark = self._finalize(tmp_path, "softlink")

        assert destination.is_symlink()
        assert os.path.realpath(destination) == os.path.realpath(source)

    @pytest.mark.parametrize("file_opts", ("copy", "hardlink", "softlink"))
    def test_an_existing_destination_is_still_refused(self, tmp_path, file_opts):
        source = tmp_path / "inbox" / "chapter.cbz"
        target_directory = tmp_path / "library"
        source.parent.mkdir()
        target_directory.mkdir()
        source.write_text("new")
        (target_directory / source.name).write_text("the operator's file")

        with (
            _environment([_row("imp-1", source)], target_directory) as mark_imported,
            patch("comicarr.updater.forceRescan"),
        ):
            with pytest.raises(finalization.ImportFinalizationError, match="already exists"):
                finalization.finalize_manual_match(_ctx(move=True, file_opts=file_opts), ["imp-1"], "mal-123")

        assert (target_directory / source.name).read_text() == "the operator's file"
        assert source.read_text() == "new"
        mark_imported.assert_not_called()


class TestRollbackUnderSourcePreservingModes:
    """Rolling back a copy or a link means removing the destination.

    Moving it back would be wrong: the source never left. Under hardlink the two
    paths are one inode, so a naive move-back would destroy the only name.
    """

    @pytest.mark.parametrize("file_opts", ("copy", "hardlink", "softlink"))
    def test_a_later_failure_removes_the_placed_file_and_keeps_both_sources(self, tmp_path, file_opts):
        first = tmp_path / "inbox" / "one.cbz"
        second = tmp_path / "inbox" / "two.cbz"
        target_directory = tmp_path / "library"
        first.parent.mkdir()
        target_directory.mkdir()
        first.write_text("one")
        second.write_text("two")
        original_place = placement.place

        def fail_second(source_path, destination_path, purpose, **kwargs):
            if source_path == str(second):
                raise placement.PlacementError("disk full")
            return original_place(source_path, destination_path, purpose, **kwargs)

        with (
            _environment([_row("imp-1", first), _row("imp-2", second)], target_directory) as mark_imported,
            patch.object(placement, "place", side_effect=fail_second),
        ):
            with pytest.raises(finalization.ImportFinalizationError, match="disk full") as exc_info:
                finalization.finalize_manual_match(_ctx(move=True, file_opts=file_opts), ["imp-1", "imp-2"], "mal-123")

        assert exc_info.value.rollback_failed is False
        assert first.read_text() == "one", "the first source must survive its rollback"
        assert second.read_text() == "two"
        assert not (target_directory / first.name).exists(), "the placed file must be removed, not moved back"
        mark_imported.assert_not_called()

    @pytest.mark.parametrize("file_opts", ("copy", "hardlink", "softlink"))
    def test_a_database_failure_removes_the_placed_file(self, tmp_path, file_opts):
        source = tmp_path / "inbox" / "chapter.cbz"
        target_directory = tmp_path / "library"
        source.parent.mkdir()
        target_directory.mkdir()
        source.write_text("chapter")

        with (
            _environment([_row("imp-1", source)], target_directory),
            patch.object(
                finalization.import_queries, "mark_imported", side_effect=RuntimeError("database unavailable")
            ),
            patch("comicarr.updater.forceRescan"),
        ):
            with pytest.raises(finalization.ImportFinalizationError, match="database unavailable"):
                finalization.finalize_manual_match(_ctx(move=True, file_opts=file_opts), ["imp-1"], "mal-123")

        assert source.read_text() == "chapter"
        assert not (target_directory / source.name).exists()

    def test_rollback_reads_what_happened_not_what_was_configured(self, tmp_path):
        """A hardlink that hit EXDEV ran as a copy. Rollback must follow the
        result, not FILE_OPTS -- otherwise the mode it reads is a lie."""
        source = tmp_path / "inbox" / "chapter.cbz"
        target_directory = tmp_path / "library"
        source.parent.mkdir()
        target_directory.mkdir()
        source.write_text("chapter")
        real_link = os.link
        seen = []

        def exdev_on_the_first_publish(source_path, destination_path, *args, **kwargs):
            seen.append(destination_path)
            if len(seen) == 1:
                raise OSError(errno.EXDEV, "cross-device link")
            return real_link(source_path, destination_path, *args, **kwargs)

        with (
            _environment([_row("imp-1", source)], target_directory),
            patch.object(placement.os, "link", side_effect=exdev_on_the_first_publish),
            patch.object(
                finalization.import_queries, "mark_imported", side_effect=RuntimeError("database unavailable")
            ),
            patch("comicarr.updater.forceRescan"),
        ):
            with pytest.raises(finalization.ImportFinalizationError) as exc_info:
                finalization.finalize_manual_match(_ctx(move=True, file_opts="hardlink"), ["imp-1"], "mal-123")

        assert exc_info.value.rollback_failed is False, "rollback must not have tried to move a copy back"
        assert source.read_text() == "chapter"
        assert not (target_directory / source.name).exists()
