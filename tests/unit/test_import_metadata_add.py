#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select

import comicarr
from comicarr import db, importer
from comicarr.tables import comics, issues


@pytest.fixture
def metadata_environment(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///%s" % (tmp_path / "library.db"))
    comics.create(engine)
    issues.create(engine)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            COMICVINE_API="test-key",
            CV_VERIFY=True,
            AUTOWANT_ALL=True,
            CHMOD_DIR="0755",
            ENFORCE_PERMS=False,
            AUTOWANT_UPCOMING=True,
            DESTINATION_DIR=str(tmp_path / "library"),
        ),
    )
    monkeypatch.setattr(comicarr, "CVURL", "https://comicvine.gamespot.com/api/")
    monkeypatch.setattr(comicarr, "CV_RATE_LIMITER", MagicMock())
    session = MagicMock()
    monkeypatch.setattr(comicarr, "CV_SESSION", session)
    volume = {
        "id": 123,
        "name": "Example",
        "start_year": "2020",
        "count_of_issues": 1,
        "publisher": {"name": "Publisher"},
        "site_detail_url": "https://example/123",
    }
    issue = {"id": 456, "volume": {"id": 123}, "issue_number": "1", "cover_date": "2020-01-01"}
    session.get.side_effect = [
        MagicMock(json=lambda: {"status_code": 1, "results": volume}),
        MagicMock(json=lambda: {"status_code": 1, "results": [issue], "number_of_total_results": 1}),
    ]
    monkeypatch.setattr(
        "comicarr.filers.FileHandlers.folder_create",
        lambda self: {"comlocation": str(tmp_path / "library" / "Example (2020)")},
    )
    monkeypatch.setattr("comicarr.filers.FileHandlers.series_folder_collision_detection", lambda *a: None)
    yield engine, session, volume, issue
    engine.dispose()


def test_metadata_only_add_is_unmonitored_and_never_acquires_or_places_files(metadata_environment, monkeypatch):
    engine, session, _, _ = metadata_environment
    search = MagicMock()
    rescan = MagicMock()
    move = MagicMock()
    monkeypatch.setattr("comicarr.search.searchforissue", search)
    monkeypatch.setattr("comicarr.updater.forceRescan", rescan)
    monkeypatch.setattr("comicarr.moveit.movefiles", move)

    result = importer.addComictoDB("4050-123", metadata_only=True)

    assert result == {"status": "complete", "comicid": "123", "comicname": "Example", "added": True}
    assert db.select_one(select(comics).where(comics.c.ComicID == "123"))["Status"] == "Paused"
    assert db.select_one(select(issues).where(issues.c.IssueID == "456"))["Status"] == "Skipped"
    search.assert_not_called()
    rescan.assert_not_called()
    move.assert_not_called()
    assert session.get.call_count == 2


def test_provider_failure_writes_nothing_and_retry_succeeds(metadata_environment):
    _, session, volume, issue = metadata_environment
    session.get.side_effect = [
        MagicMock(json=lambda: {"status_code": 1, "results": volume}),
        RuntimeError("provider unavailable"),
    ]
    with pytest.raises(RuntimeError, match="provider unavailable"):
        importer.addComictoDB("123", metadata_only=True)
    assert db.select_all(select(comics)) == []
    assert db.select_all(select(issues)) == []
    session.get.side_effect = [
        MagicMock(json=lambda: {"status_code": 1, "results": volume}),
        MagicMock(json=lambda: {"status_code": 1, "results": [issue], "number_of_total_results": 1}),
    ]
    assert importer.addComictoDB("123", metadata_only=True)["status"] == "complete"


def test_partial_metadata_commit_failure_rolls_back_and_can_retry(metadata_environment, monkeypatch):
    _, session, volume, issue = metadata_environment
    write = db.upsert_conn

    def fail_series_write(conn, table, values, keys):
        if table == "comics":
            raise RuntimeError("database full")
        write(conn, table, values, keys)

    monkeypatch.setattr(db, "upsert_conn", fail_series_write)
    with pytest.raises(RuntimeError, match="database full"):
        importer.addComictoDB("123", metadata_only=True)
    assert db.select_all(select(comics)) == []
    assert db.select_all(select(issues)) == []
    monkeypatch.setattr(db, "upsert_conn", write)
    session.get.side_effect = [
        MagicMock(json=lambda: {"status_code": 1, "results": volume}),
        MagicMock(json=lambda: {"status_code": 1, "results": [issue], "number_of_total_results": 1}),
    ]
    assert importer.addComictoDB("123", metadata_only=True)["status"] == "complete"


def test_repeat_add_reuses_metadata_and_does_not_change_monitoring(metadata_environment):
    _, session, _, _ = metadata_environment
    importer.addComictoDB("123", metadata_only=True)
    db.upsert("comics", {"Status": "Active"}, {"ComicID": "123"})
    result = importer.addComictoDB("4050-123", metadata_only=True)
    assert result["added"] is False
    assert result["comicid"] == "123"
    assert session.get.call_count == 2
    assert db.select_one(select(comics))["Status"] == "Active"


@pytest.mark.parametrize("mapped", [None, "4050-123"])
def test_metron_mapping_is_canonical_or_refused_before_writes(metadata_environment, monkeypatch, mapped):
    _, session, _, _ = metadata_environment
    monkeypatch.setattr("comicarr.metron.get_cv_id", lambda _: mapped)
    if mapped:
        result = importer.addComictoDB("metron-789", metadata_only=True)
        assert result["comicid"] == "123"
        assert db.select_one(select(issues))["ComicID"] == "123"
    else:
        with pytest.raises(ValueError, match="no ComicVine mapping"):
            importer.addComictoDB("metron-789", metadata_only=True)
        session.get.assert_not_called()
        assert db.select_all(select(comics)) == []


@pytest.mark.parametrize("problem", ["page_failure", "different_series", "duplicate", "over_limit"])
def test_incomplete_or_incorrect_provider_roster_is_refused(metadata_environment, problem):
    _, session, volume, issue = metadata_environment
    if problem == "over_limit":
        volume["count_of_issues"] = 2001
    if problem == "different_series":
        issue["volume"] = {"id": 999}
    if problem == "duplicate":
        volume["count_of_issues"] = 2
    session.get.side_effect = [
        MagicMock(json=lambda: {"status_code": 1, "results": volume}),
        MagicMock(
            json=lambda: {
                "status_code": 1,
                "results": [] if problem == "page_failure" else [issue, issue] if problem == "duplicate" else [issue],
                "number_of_total_results": volume["count_of_issues"],
            }
        ),
    ]
    with pytest.raises(ValueError):
        importer.addComictoDB("123", metadata_only=True)
    assert db.select_all(select(comics)) == []
    assert db.select_all(select(issues)) == []


def test_issue_owned_by_another_series_is_never_repointed(metadata_environment):
    db.upsert("issues", {"ComicID": "other", "Status": "Downloaded", "Location": "existing.cbz"}, {"IssueID": "456"})
    with pytest.raises(ValueError, match="another series"):
        importer.addComictoDB("123", metadata_only=True)
    assert db.select_one(select(issues))["ComicID"] == "other"
    assert db.select_one(select(issues))["Location"] == "existing.cbz"
    assert db.select_all(select(comics)) == []


def test_active_failed_placeholder_is_retried(metadata_environment):
    db.upsert("comics", {"ComicName": "Fetch failed, try refreshing. (123)", "Status": "Active"}, {"ComicID": "123"})
    result = importer.addComictoDB("123", metadata_only=True)
    assert result["status"] == "complete"
    assert db.select_one(select(comics))["Status"] == "Paused"


def test_rate_limiter_wait_is_bounded_without_consuming_a_token():
    from comicarr.rate_limiter import ComicVineRateLimiter

    limiter = ComicVineRateLimiter(calls_per_second=0.01)
    limiter.tokens = 0
    with pytest.raises(TimeoutError, match="deadline"):
        limiter.acquire(timeout=0.001)
    assert limiter.tokens < 0.01
    assert not limiter.lock.locked()


def test_rate_limiter_lock_wait_is_bounded():
    from comicarr.rate_limiter import ComicVineRateLimiter

    limiter = ComicVineRateLimiter()
    limiter.lock.acquire()
    try:
        with pytest.raises(TimeoutError, match="busy"):
            limiter.acquire(timeout=0.001)
    finally:
        limiter.lock.release()


def test_mangadex_metadata_add_is_unmonitored_without_placeholder_issues(metadata_environment, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "comicarr.mangadex.get_manga_details",
        lambda _: {
            "id": "md-abc",
            "name": "Example Manga",
            "year": "2020",
            "author": "Author",
        },
    )
    monkeypatch.setattr(
        "comicarr.mangadex.get_manga_chapters",
        lambda *a, **kw: {
            "chapters": [{"chapter": "1", "title": "First", "release_date": "2020-01-01"}],
            "pagination": {"total": 1},
        },
    )
    monkeypatch.setattr("comicarr.config.get_manga_destination", lambda: str(tmp_path / "library"))
    comicarr.CONFIG.FOLDER_FORMAT = "$Series ($Year)"
    result = importer.addComictoDB("md-abc", metadata_only=True)
    assert result["comicid"] == "md-abc"
    assert db.select_one(select(comics))["Status"] == "Paused"
    assert db.select_one(select(issues))["IssueID"] == "md-abc-ch1"
    assert db.select_one(select(issues))["Status"] == "Skipped"


def test_mal_metadata_requires_exact_chapter_source(metadata_environment, monkeypatch):
    monkeypatch.setattr(
        "comicarr.myanimelist.get_manga_details",
        lambda _: {
            "name": "Example Manga",
            "year": "2020",
            "author": "Author",
        },
    )
    resolve = MagicMock(return_value=None)
    monkeypatch.setattr("comicarr.mangadex.find_by_mal_id", resolve)
    with pytest.raises(ValueError, match="verified MangaDex"):
        importer.addComictoDB("mal-13", metadata_only=True)
    assert resolve.call_args.kwargs["allow_title_match"] is False
    assert db.select_all(select(comics)) == []


@pytest.fixture
def pending_import(metadata_environment, tmp_path, monkeypatch):
    from comicarr.app.imports import finalization
    from comicarr.tables import importresults

    engine, session, volume, issue = metadata_environment
    importresults.create(engine)
    source = tmp_path / "Example 001.cbz"
    source.write_bytes(b"book")
    db.upsert(
        "importresults",
        {
            "ComicLocation": str(source),
            "ComicFilename": source.name,
            "IssueNumber": "1",
            "Status": "Not Imported",
        },
        {"impID": "pending"},
    )
    config = SimpleNamespace(IMP_MOVE=True, IMP_RENAME=False, IMP_METADATA=False, FILE_OPTS="move")
    ctx = SimpleNamespace(config=config)
    monkeypatch.setattr("comicarr.updater.forceRescan", MagicMock())
    return finalization, ctx, source, session, importresults


def test_confirmed_missing_comic_adds_then_imports_using_canonical_issue_ids(pending_import):
    finalization, ctx, source, session, importresults = pending_import
    result = finalization.finalize_manual_match(ctx, ["pending"], "4050-123", series_name="Example", add_missing=True)
    assert result.series_id == "123"
    assert result.matched == result.moved == 1
    row = db.select_one(select(importresults))
    assert row["Status"] == "Imported"
    assert row["ComicID"] == "123"
    assert row["IssueID"] == "456"
    assert not source.exists()
    assert (source.parent / "library" / "Example (2020)" / source.name).read_bytes() == b"book"
    assert session.get.call_count == 2


def test_missing_series_requires_confirmation_and_auto_never_adds(pending_import):
    finalization, ctx, source, session, importresults = pending_import
    for arguments in ({}, {"add_missing": True, "match_source": "inbox-auto"}):
        with pytest.raises(finalization.ImportFinalizationError, match="Confirm Add series"):
            finalization.finalize_manual_match(ctx, ["pending"], "123", series_name="Example", **arguments)
    assert source.read_bytes() == b"book"
    assert db.select_one(select(importresults))["Status"] == "Not Imported"
    session.get.assert_not_called()


@pytest.mark.parametrize("result", [None, {"status": "incomplete"}, {"status": "complete", "comicid": "999"}])
def test_failed_metadata_completion_leaves_files_pending(pending_import, monkeypatch, result):
    finalization, ctx, source, _, importresults = pending_import
    monkeypatch.setattr(importer, "addComictoDB", lambda *args, **kwargs: result)
    with pytest.raises(finalization.ImportFinalizationError, match="Example") as error:
        finalization.finalize_manual_match(ctx, ["pending"], "123", series_name="Example", add_missing=True)
    assert error.value.phase == "series"
    assert source.read_bytes() == b"book"
    assert db.select_one(select(importresults))["Status"] == "Not Imported"


def test_unresolved_issue_keeps_metadata_and_files_pending_then_retries(pending_import):
    finalization, ctx, source, session, importresults = pending_import
    db.upsert("importresults", {"IssueNumber": "99"}, {"impID": "pending"})
    with pytest.raises(finalization.ImportFinalizationError, match="series remains") as error:
        finalization.finalize_manual_match(ctx, ["pending"], "123", add_missing=True)
    assert error.value.phase == "issues"
    assert source.read_bytes() == b"book"
    assert db.select_one(select(importresults))["Status"] == "Not Imported"
    assert db.select_one(select(comics))["Status"] == "Paused"
    assert not (source.parent / "library").exists()
    db.upsert("importresults", {"IssueNumber": "1"}, {"impID": "pending"})
    assert finalization.finalize_manual_match(ctx, ["pending"], "123", add_missing=True).matched == 1
    assert session.get.call_count == 2


def test_metron_finalization_propagates_canonical_id_to_imports(pending_import, monkeypatch):
    finalization, ctx, _, _, importresults = pending_import
    mapping = MagicMock(return_value="4050-123")
    monkeypatch.setattr("comicarr.metron.get_cv_id", mapping)
    result = finalization.finalize_manual_match(ctx, ["pending"], "metron-789", add_missing=True)
    assert result.series_id == "123"
    assert db.select_one(select(importresults))["ComicID"] == "123"
    mapping.assert_called_once()


def test_concurrent_repeated_submission_places_once(pending_import):
    from concurrent.futures import ThreadPoolExecutor

    finalization, ctx, source, session, importresults = pending_import

    def submit():
        try:
            return finalization.finalize_manual_match(ctx, ["pending"], "123", add_missing=True).matched
        except finalization.ImportFinalizationError as error:
            return error.phase

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))
    assert sorted(results, key=str) == [1, "preflight"]
    assert session.get.call_count == 2
    assert db.select_one(select(importresults))["Status"] == "Imported"
    assert not source.exists()


def test_retry_does_not_repoint_an_existing_library_file(pending_import):
    finalization, ctx, source, _, importresults = pending_import
    importer.addComictoDB("123", metadata_only=True)
    series = db.select_one(select(comics))
    from pathlib import Path

    library = Path(series["ComicLocation"])
    library.mkdir(parents=True)
    existing_file = library / "owned.cbz"
    existing_file.write_bytes(b"original")
    db.upsert("issues", {"Location": "owned.cbz", "Status": "Downloaded"}, {"IssueID": "456"})
    with pytest.raises(finalization.ImportFinalizationError) as error:
        finalization.finalize_manual_match(ctx, ["pending"], "123", add_missing=True)
    assert error.value.phase == "issues"
    assert source.read_bytes() == b"book"
    assert existing_file.read_bytes() == b"original"
    assert db.select_one(select(issues))["Location"] == "owned.cbz"
    assert db.select_one(select(importresults))["Status"] == "Not Imported"


def test_existing_series_without_refresh_timestamp_keeps_legacy_match_behavior(pending_import):
    finalization, ctx, source, session, importresults = pending_import
    library = source.parent / "library" / "Existing"
    library.mkdir(parents=True)
    db.upsert(
        "comics", {"ComicName": "Existing", "ComicLocation": str(library), "Status": "Active"}, {"ComicID": "123"}
    )
    db.upsert("issues", {"ComicID": "123", "Issue_Number": "1", "Status": "Skipped"}, {"IssueID": "456"})
    result = finalization.finalize_manual_match(ctx, ["pending"], "123")
    assert result.series_name == "Existing"
    assert db.select_one(select(importresults))["Status"] == "Imported"
    assert db.select_one(select(comics))["Status"] == "Active"
    session.get.assert_not_called()


def test_provider_failure_does_not_return_credential_bearing_urls(pending_import):
    import requests

    finalization, ctx, source, session, _ = pending_import
    session.get.side_effect = requests.HTTPError("403 https://provider/volume/?api_key=test-key")
    with pytest.raises(finalization.ImportFinalizationError) as error:
        finalization.finalize_manual_match(ctx, ["pending"], "123", add_missing=True)
    assert "test-key" not in str(error.value)
    assert "ComicVine request failed" in str(error.value)
    assert source.read_bytes() == b"book"
