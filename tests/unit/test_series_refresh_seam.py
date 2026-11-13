#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Characterization tests for series refresh behind ``app/series/refresh.py`` (#1207).

They pin what ``updater.dbUpdate`` does today when ``comicarr/app/`` calls it,
with the metadata provider (``importer.addComictoDB``) and the file rescan
faked. They describe current behavior, not intended behavior.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select

import comicarr
from comicarr import importer, updater
from comicarr.app.downloads import service as downloads_service
from comicarr.app.series import refresh as series_refresh
from comicarr.tables import annuals, comics, issues, metadata


def _config(**overrides):
    values = {
        "CV_ONLY": True,
        "CV_ONETIMER": 1,
        "ANNUALS_ON": False,
        "AUTOWANT_ALL": False,
        "AUTOWANT_UPCOMING": True,
        "SERIES_METADATA_LOCAL": False,
        "UPDATE_ENDED": False,
        "REFRESH_CACHE": 7,
        "DBUPDATE_INTERVAL": 1440,
        "DUPECONSTRAINT": "filesize",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def engine(monkeypatch):
    eng = create_engine("sqlite://")
    metadata.create_all(eng)
    monkeypatch.setattr(comicarr.db, "get_engine", lambda: eng)
    monkeypatch.setattr(comicarr, "IMPORTLOCK", False, raising=False)
    monkeypatch.setattr(comicarr, "CONFIG", _config(), raising=False)
    return eng


@pytest.fixture
def fakes(monkeypatch):
    add = MagicMock()
    rescan = MagicMock()
    emit = MagicMock(return_value={"event_id": 1})
    monkeypatch.setattr(importer, "addComictoDB", add)
    monkeypatch.setattr(updater, "forceRescan", rescan)
    monkeypatch.setattr("comicarr.app.activity.producers.emit_series_activity", emit)
    return SimpleNamespace(add=add, rescan=rescan, emit=emit)


def _issue_data(comic_id, issue_id, number, release_date):
    return {
        "ComicID": comic_id,
        "ComicName": "Absolute Batman",
        "IssueID": issue_id,
        "IssueName": None,
        "Issue_Number": number,
        "IssueDate": release_date,
        "ReleaseDate": release_date,
        "DigitalDate": "0000-00-00",
        "Int_IssueNumber": int(number) * 1000,
        "AltIssueNumber": None,
        "ImageURL": None,
        "ImageURL_ALT": None,
    }


def _insert_comic(eng, **row):
    values = {
        "ComicID": "100",
        "ComicName": "Absolute Batman",
        "ComicYear": "2024",
        "ContentType": "comic",
        "Status": "Active",
        "LastUpdated": "2024-01-01 00:00:00",
        "Have": 1,
        "Total": 1,
    }
    values.update(row)
    with eng.begin() as conn:
        conn.execute(comics.insert(), values)


def _issues_by_id(eng, comic_id):
    with eng.connect() as conn:
        rows = conn.execute(select(issues).where(issues.c.ComicID == comic_id)).mappings().all()
    return {row["IssueID"]: dict(row) for row in rows}


def test_seam_delegates_to_db_update(monkeypatch):
    db_update = MagicMock()
    monkeypatch.setattr(updater, "dbUpdate", db_update)

    assert series_refresh.refresh_series_metadata(("100",), calledfrom="dupechk") is None

    db_update.assert_called_once_with(ComicIDList=["100"], calledfrom="dupechk")


def test_comic_refresh_adds_new_issues_and_restores_existing_status(engine, fakes):
    _insert_comic(engine)
    with engine.begin() as conn:
        conn.execute(
            issues.insert(),
            {
                "IssueID": "i1",
                "ComicID": "100",
                "ComicName": "Absolute Batman",
                "Issue_Number": "1",
                "IssueDate": "2023-10-01",
                "ReleaseDate": "2023-10-01",
                "Status": "Downloaded",
                "Location": "Absolute Batman 001.cbz",
                "ComicSize": "1234",
            },
        )
    fakes.add.return_value = {
        "status": "complete",
        "issuedata": [
            _issue_data("100", "i1", "1", "2023-10-01"),
            # Released before LastUpdated: Skipped.
            _issue_data("100", "i2", "2", "2023-11-01"),
            # Released after LastUpdated, in the past: Wanted (AUTOWANT_UPCOMING).
            _issue_data("100", "i3", "3", "2024-06-01"),
            # Future release: Wanted.
            _issue_data("100", "i4", "4", "2099-01-01"),
        ],
        "anndata": None,
    }

    series_refresh.refresh_series_metadata(["100"], calledfrom="dupechk")

    fakes.add.assert_called_once_with("100", "no", calledfrom="dbupdate", annload=[], csyear=None, fixed_type=None)
    rows = _issues_by_id(engine, "100")
    assert set(rows) == {"i1", "i2", "i3", "i4"}
    assert rows["i1"]["Status"] == "Downloaded"
    assert rows["i1"]["Location"] == "Absolute Batman 001.cbz"
    assert rows["i1"]["ComicSize"] == "1234"
    assert rows["i2"]["Status"] == "Skipped"
    assert rows["i3"]["Status"] == "Wanted"
    assert rows["i4"]["Status"] == "Wanted"
    fakes.rescan.assert_called_once_with("100")
    # Only calledfrom="refresh" narrates; the dupecheck caller emits nothing.
    fakes.emit.assert_not_called()


def test_comic_refresh_failure_keeps_issue_rows_and_emits_failed(engine, fakes):
    _insert_comic(engine)
    with engine.begin() as conn:
        conn.execute(issues.insert(), {"IssueID": "i1", "ComicID": "100", "Status": "Downloaded"})
    fakes.add.return_value = {"status": "incomplete"}

    series_refresh.refresh_series_metadata(["100"], calledfrom="dupechk")

    assert set(_issues_by_id(engine, "100")) == {"i1"}
    fakes.rescan.assert_not_called()
    assert fakes.emit.call_args.args[:2] == ("refresh", "failed")
    assert fakes.emit.call_args.kwargs["reason_code"] == "refresh_failed"


def test_out_of_whack_series_is_re_added_without_reconciliation(engine, fakes):
    _insert_comic(engine, Have=5, Total=2)
    with engine.begin() as conn:
        conn.execute(issues.insert(), {"IssueID": "i1", "ComicID": "100", "Status": "Downloaded"})
    fakes.add.return_value = {"status": "complete"}

    series_refresh.refresh_series_metadata(["100"], calledfrom="dupechk")

    fakes.add.assert_called_once_with("100", "no", annload=[], csyear=None)
    assert set(_issues_by_id(engine, "100")) == {"i1"}
    fakes.rescan.assert_not_called()


def test_manga_refresh_goes_through_manga_importer_and_rescans(engine, fakes):
    _insert_comic(engine, ComicID="mal-1", ComicName="Test Manga", ContentType="manga")
    with engine.begin() as conn:
        conn.execute(issues.insert(), {"IssueID": "c1", "ComicID": "mal-1", "Status": "Downloaded"})
    fakes.add.return_value = {"status": "complete", "comicid": "mal-1", "content_type": "manga"}

    series_refresh.refresh_series_metadata(["mal-1"], calledfrom="dupechk")

    fakes.add.assert_called_once_with("mal-1", "no")
    fakes.rescan.assert_called_once_with("mal-1")
    # The CV delete-and-reload path is skipped, so chapter rows are untouched.
    assert _issues_by_id(engine, "mal-1")["c1"]["Status"] == "Downloaded"
    fakes.emit.assert_not_called()


def test_refresh_is_skipped_while_an_import_holds_the_lock(engine, fakes, monkeypatch):
    _insert_comic(engine)
    monkeypatch.setattr(comicarr, "IMPORTLOCK", True)

    series_refresh.refresh_series_metadata(["100"], calledfrom="dupechk")

    fakes.add.assert_not_called()


def test_several_ids_with_refresh_tag_stop_after_the_first(engine, fakes):
    # Surprise, pinned as-is: with calledfrom="refresh" the loop breaks after
    # the first series, so later ids in the same call are never refreshed.
    _insert_comic(engine, ComicID="mal-1", ContentType="manga")
    _insert_comic(engine, ComicID="mal-2", ContentType="manga")
    fakes.add.return_value = {"status": "complete"}

    series_refresh.refresh_series_metadata(["mal-1", "mal-2"], calledfrom="refresh")

    assert fakes.add.call_count == 1
    assert fakes.emit.call_args.args[:2] == ("refresh", "succeeded")


def test_dupecheck_refreshes_series_when_have_exceeds_total(engine, tmp_path, monkeypatch):
    _insert_comic(engine, Have=3, Total=2, ComicLocation=str(tmp_path))
    with engine.begin() as conn:
        conn.execute(
            issues.insert(),
            {"IssueID": "i1", "ComicID": "100", "Status": "Downloaded", "Location": "a.cbz", "ComicSize": None},
        )
    incoming = tmp_path / "incoming.cbz"
    incoming.write_bytes(b"x" * 10)

    calls = []

    def fake_refresh(comic_ids, calledfrom=None):
        calls.append((list(comic_ids), calledfrom))
        with engine.begin() as conn:
            conn.execute(comics.update().where(comics.c.ComicID == "100").values(Have=2))

    monkeypatch.setattr(series_refresh, "refresh_series_metadata", fake_refresh)
    rescan = MagicMock()
    monkeypatch.setattr(updater, "forceRescan", rescan)

    result = downloads_service.duplicate_filecheck(str(incoming), ComicID="100", IssueID="i1")

    assert calls == [(["100"], "dupechk")]
    rescan.assert_called_once_with("100")
    assert result == {"action": "dont_dupe"}


def test_new_annual_status_is_written_against_the_last_new_issue(engine, fakes, monkeypatch):
    # Bug, pinned as-is: the new-annual status loop reads ``iss`` (the last new
    # issue) instead of ``ann``, so the annual keeps Status None and a stray
    # annuals row appears under the issue's IssueID.
    monkeypatch.setattr(comicarr, "CONFIG", _config(ANNUALS_ON=True))
    _insert_comic(engine)
    with engine.begin() as conn:
        conn.execute(issues.insert(), {"IssueID": "i1", "ComicID": "100", "Status": "Skipped"})

    def fake_manual_annual(annchk):
        with engine.begin() as conn:
            conn.execute(annuals.insert(), {"IssueID": "a1", "ComicID": "100", "ReleaseDate": "2099-01-01"})

    monkeypatch.setattr(importer, "manualAnnual", fake_manual_annual)
    fakes.add.return_value = {
        "status": "complete",
        "issuedata": [_issue_data("100", "i2", "2", "2023-11-01")],
        "anndata": [{"placeholder": True}],
    }

    series_refresh.refresh_series_metadata(["100"], calledfrom="dupechk")

    with engine.connect() as conn:
        ann_rows = {r["IssueID"]: r["Status"] for r in conn.execute(select(annuals)).mappings()}
    assert ann_rows == {"a1": None, "i2": "Skipped"}
    assert _issues_by_id(engine, "100")["i2"]["Status"] == "Skipped"
