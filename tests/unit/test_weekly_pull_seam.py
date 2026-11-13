#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Characterization tests for the weekly pull seam, ``comicarr.app.weekly.pull`` (#1203).

They pin what the legacy ``weeklypull`` / ``weeklypullit`` bodies do today when
called through the seam: the scheduled job, fetching the pull list, matching a
stored week against the library (one row that marks an issue Wanted, one that
matches nothing), and the future-release check. Providers are faked.
"""

import datetime
from unittest.mock import MagicMock, call

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr import db, weeklypull, weeklypullit
from comicarr.app.weekly import pull
from comicarr.tables import comics, issues, metadata, weekly


@pytest.fixture
def pull_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _seed_library(engine):
    recent = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    with engine.begin() as conn:
        conn.execute(
            insert(comics).values(
                ComicID="160294",
                ComicName="Absolute Batman",
                ComicName_Filesafe="Absolute Batman",
                ComicYear="2024",
                ComicPublisher="DC Comics",
                ComicPublished="October 2024 - Present",
                LatestDate=recent,
                LatestIssue="23",
                Status="Active",
                DynamicComicName="absolutebatman",
                Type="Print",
                ForceContinuing=0,
            )
        )
        conn.execute(
            insert(issues).values(
                IssueID="1194150",
                ComicID="160294",
                ComicName="Absolute Batman",
                Issue_Number="24",
                Int_IssueNumber=24000,
                IssueDate="2026-11-01",
                ReleaseDate="2026-09-23",
                Status="Skipped",
            )
        )


def _seed_pull_row(engine, **row):
    values = {
        "PUBLISHER": "DC Comics",
        "SHIPDATE": "2026-09-23",
        "STATUS": None,
        "weeknumber": "38",
        "year": "2026",
    }
    values.update(row)
    with engine.begin() as conn:
        conn.execute(insert(weekly).values(**values))


def _patch_match(monkeypatch, *, autowant, listed):
    config = MagicMock()
    config.ANNUALS_ON = False
    config.AUTOWANT_UPCOMING = autowant
    config.AUTO_MASS_ADD = False
    monkeypatch.setattr(comicarr, "CONFIG", config)
    monkeypatch.setattr(weeklypull.helpers, "listPull", lambda week, year: listed)
    monkeypatch.setattr(weeklypull.helpers, "checkthepub", lambda comicid: 60)
    monkeypatch.setattr(weeklypull.helpers, "LoadAlternateSearchNames", lambda *_args: None)
    upcoming_update = MagicMock(return_value=None)
    monkeypatch.setattr(weeklypull.updater, "upcoming_update", upcoming_update, raising=False)
    monkeypatch.setattr(weeklypull.updater, "latest_update", MagicMock(), raising=False)
    refresh_thread = MagicMock()
    monkeypatch.setattr(weeklypull.importer, "refresh_thread", refresh_thread, raising=False)
    # new_pullcheck logs and swallows per-row errors; surface them instead.
    swallowed = MagicMock()
    monkeypatch.setattr(weeklypull.helpers, "log_that_exception", swallowed)
    return upcoming_update, refresh_thread, swallowed


def _pull_row(comic):
    return db.select_one(select(weekly).where(weekly.c.COMIC == comic))


def _issue_status():
    return db.select_one(select(issues.c.Status).where(issues.c.IssueID == "1194150"))["Status"]


def test_a_pull_row_for_a_followed_series_marks_its_issue_wanted(pull_db, monkeypatch):
    _seed_library(pull_db)
    _seed_pull_row(
        pull_db,
        COMIC="Absolute Batman",
        ISSUE="24",
        ComicID="160294",
        IssueID="1194150",
        DynamicName="absolutebatman",
    )
    upcoming_update, refresh_thread, swallowed = _patch_match(monkeypatch, autowant=True, listed=["160294"])

    assert pull.match_pull_list(38, "2026") is None

    assert not swallowed.called, swallowed.call_args
    upcoming_update.assert_called_once()
    assert upcoming_update.call_args.kwargs["ComicID"] == "160294"
    assert upcoming_update.call_args.kwargs["IssueNumber"] == "24"
    assert upcoming_update.call_args.kwargs["weekinfo"] == {"weeknumber": 38, "year": "2026"}
    row = _pull_row("Absolute Batman")
    assert (row["ComicID"], row["IssueID"], row["STATUS"]) == ("160294", "1194150", "Wanted")
    assert (row["weeknumber"], row["year"]) == ("38", "2026")
    assert _issue_status() == "Wanted"
    # The issue is already in the library, so no series refresh is queued.
    refresh_thread.assert_not_called()


def test_a_followed_series_without_autowant_is_left_skipped(pull_db, monkeypatch):
    _seed_library(pull_db)
    _seed_pull_row(
        pull_db,
        COMIC="Absolute Batman",
        ISSUE="24",
        ComicID="160294",
        IssueID="1194150",
        DynamicName="absolutebatman",
    )
    _, _, swallowed = _patch_match(monkeypatch, autowant=False, listed=["160294"])

    pull.match_pull_list(38, "2026")

    assert not swallowed.called, swallowed.call_args
    assert _pull_row("Absolute Batman")["STATUS"] == "Skipped"
    assert _issue_status() == "Skipped"


def test_a_pull_row_that_matches_nothing_in_the_library_changes_nothing(pull_db, monkeypatch):
    _seed_library(pull_db)
    _seed_pull_row(
        pull_db,
        COMIC="Some Other Book",
        ISSUE="1",
        ComicID="999999",
        IssueID="888888",
        DynamicName="someotherbook",
    )
    upcoming_update, refresh_thread, swallowed = _patch_match(monkeypatch, autowant=True, listed=[])

    pull.match_pull_list(38, "2026")

    assert not swallowed.called, swallowed.call_args
    upcoming_update.assert_not_called()
    refresh_thread.assert_not_called()
    row = _pull_row("Some Other Book")
    assert (row["ComicID"], row["IssueID"], row["STATUS"]) == ("999999", "888888", None)
    assert _issue_status() == "Skipped"


def test_fetch_pull_list_loads_both_weeks_from_walksoftly_and_matches_each(monkeypatch):
    config = MagicMock()
    config.ALT_PULL = 2
    config.CACHE_DIR = "/tmp"
    monkeypatch.setattr(comicarr, "CONFIG", config)
    monkeypatch.setattr(
        weeklypull.helpers,
        "weekly_info",
        lambda: {"weeknumber": 33, "year": 2026, "prev_weeknumber": 32, "prev_year": 2026},
    )
    locg_calls = []

    def fake_locg(**kwargs):
        locg_calls.append(kwargs)
        return {"status": "success", "count": 3, **kwargs}

    monkeypatch.setattr(weeklypull.locg, "locg", fake_locg)
    monkeypatch.setattr(weeklypull.db, "select_one", lambda _stmt: {"SHIPDATE": "20260813"})
    monkeypatch.setattr(weeklypull.time, "sleep", lambda *_args: None)
    new_pullcheck = MagicMock()
    monkeypatch.setattr(weeklypull, "new_pullcheck", new_pullcheck)

    result = pull.fetch_pull_list()

    assert result == {"status": "success"}
    assert locg_calls == [{"weeknumber": 32, "year": 2026}, {"weeknumber": 33, "year": 2026}]
    assert new_pullcheck.call_args_list == [call(32, 2026), call(33, 2026)]


def test_fetch_pull_list_reports_an_out_of_date_client_as_failure(monkeypatch):
    config = MagicMock()
    config.ALT_PULL = 2
    config.CACHE_DIR = "/tmp"
    monkeypatch.setattr(comicarr, "CONFIG", config)
    monkeypatch.setattr(
        weeklypull.helpers,
        "weekly_info",
        lambda: {"weeknumber": 33, "year": 2026, "prev_weeknumber": 32, "prev_year": 2026},
    )
    monkeypatch.setattr(weeklypull.locg, "locg", lambda **kwargs: {"status": "update_required"})
    monkeypatch.setattr(weeklypull.db, "select_one", lambda _stmt: {"SHIPDATE": "20260813"})
    new_pullcheck = MagicMock()
    monkeypatch.setattr(weeklypull, "new_pullcheck", new_pullcheck)

    assert pull.fetch_pull_list() == {"status": "failure"}
    new_pullcheck.assert_not_called()


def test_check_future_releases_with_no_new_series_searches_nothing(pull_db, monkeypatch):
    find_comic = MagicMock()
    monkeypatch.setattr(weeklypull.mb, "findComic", find_comic)

    assert pull.check_future_releases() is None
    find_comic.assert_not_called()


def test_run_weekly_refresh_fetches_then_checks_future_releases(monkeypatch):
    order = []
    monkeypatch.setattr(weeklypullit.helpers, "job_management", MagicMock())
    monkeypatch.setattr(weeklypullit.helpers, "utctimestamp", lambda: 123.0)
    monkeypatch.setattr(weeklypullit.weeklypull, "pullit", lambda: order.append("pullit") or {"status": "success"})
    monkeypatch.setattr(weeklypullit.weeklypull, "future_check", lambda: order.append("future_check"))
    monkeypatch.setattr(comicarr, "WEEKLY_STATUS", "Queued")
    monkeypatch.setattr(comicarr, "AI_CLIENT", None, raising=False)

    assert pull.run_weekly_refresh() is None

    assert order == ["pullit", "future_check"]
    assert comicarr.WEEKLY_STATUS == "Waiting"


def test_run_weekly_refresh_reraises_a_reported_pull_failure(monkeypatch):
    future_check = MagicMock()
    monkeypatch.setattr(weeklypullit.helpers, "job_management", MagicMock())
    monkeypatch.setattr(weeklypullit.helpers, "utctimestamp", lambda: 123.0)
    monkeypatch.setattr(weeklypullit.weeklypull, "pullit", lambda: {"status": "failure", "cause": "down"})
    monkeypatch.setattr(weeklypullit.weeklypull, "future_check", future_check)
    monkeypatch.setattr(comicarr, "WEEKLY_STATUS", "Queued")

    with pytest.raises(RuntimeError, match="down"):
        pull.run_weekly_refresh()

    future_check.assert_not_called()
    assert comicarr.WEEKLY_STATUS == "Error"
