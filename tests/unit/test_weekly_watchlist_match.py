#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Characterization tests for the pull-list match (#1461).

They pin what ``upcoming_update`` and ``latest_update`` did in
``comicarr/updater.py`` before the move to ``app/weekly/watchlist_match.py``:
a pulled issue of a watched series becomes Wanted, an issue dated outside the
pull week is reported as an incorrect match, and a pulled issue the series
does not list yet goes to Upcoming. Series refresh and the source re-read are
faked. They describe current behavior, not intended behavior.
"""

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select

import comicarr
from comicarr import helpers
from comicarr.app.series import add, refresh
from comicarr.app.weekly import watchlist_match
from comicarr.tables import comics, issues, metadata, upcoming

WEEK = {"weeknumber": "10", "year": "2024"}


@pytest.fixture
def engine(monkeypatch):
    eng = create_engine("sqlite://")
    metadata.create_all(eng)
    monkeypatch.setattr(comicarr.db, "get_engine", lambda: eng)
    monkeypatch.setattr(comicarr, "PULLBYFILE", False, raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            ALT_PULL=0,
            ANNUALS_ON=False,
            AUTOWANT_UPCOMING=True,
            FAILED_DOWNLOAD_HANDLING=False,
            FAILED_AUTO=False,
        ),
        raising=False,
    )
    monkeypatch.setattr(
        helpers,
        "weekly_info",
        lambda weeknumber, year: {"startweek": "March 03, 2024", "endweek": "March 09, 2024"},
    )
    with eng.begin() as conn:
        conn.execute(
            comics.insert(),
            {
                "ComicID": "100",
                "ComicName": "Absolute Batman",
                "ComicYear": "2024",
                "Status": "Active",
                "LastUpdated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
    return eng


@pytest.fixture
def series_refresh(monkeypatch):
    fake = MagicMock(return_value=None)
    monkeypatch.setattr(refresh, "refresh_series_metadata", fake)
    return fake


def _insert_issue(eng, status, release_date):
    with eng.begin() as conn:
        conn.execute(
            issues.insert(),
            {
                "IssueID": "i5",
                "ComicID": "100",
                "ComicName": "Absolute Batman",
                "Issue_Number": "5",
                "Int_IssueNumber": 5000,
                "IssueDate": release_date,
                "ReleaseDate": release_date,
                "Status": status,
            },
        )


def _status(eng):
    with eng.connect() as conn:
        return conn.execute(select(issues.c.Status).where(issues.c.IssueID == "i5")).scalar_one()


def test_pulled_skipped_issue_becomes_wanted(engine, series_refresh):
    _insert_issue(engine, "Skipped", "2024-03-06")

    result = watchlist_match.upcoming_update("100", "Absolute Batman", "5", "2024-03-06", weekinfo=WEEK)

    assert result == {"Status": "Wanted", "ComicID": "100", "IssueID": "i5"}
    assert _status(engine) == "Wanted"
    series_refresh.assert_called_once_with(["100"], calledfrom="weekly")


def test_downloaded_issue_keeps_its_status(engine, series_refresh):
    _insert_issue(engine, "Downloaded", "2024-03-06")

    result = watchlist_match.upcoming_update("100", "Absolute Batman", "5", "2024-03-06", weekinfo=WEEK)

    assert result == {"Status": "Downloaded", "ComicID": "100", "IssueID": "i5"}
    assert _status(engine) == "Downloaded"


def test_wanted_issue_dated_outside_the_week_is_an_incorrect_match(engine, series_refresh):
    _insert_issue(engine, "Wanted", "2023-01-04")

    result = watchlist_match.upcoming_update("100", "Absolute Batman", "5", "2024-03-06", weekinfo=WEEK)

    assert result == {"Status": "incorrect_match", "ComicID": "100", "IssueID": "i5"}
    assert _status(engine) == "Skipped"
    series_refresh.assert_not_called()


def test_issue_the_series_does_not_list_yet_links_the_pull_entry(engine, series_refresh, monkeypatch):
    reread = MagicMock()
    monkeypatch.setattr(add, "update_issue_data", reread)

    result = watchlist_match.upcoming_update("100", "Absolute Batman", "6", "2024-03-06", weekinfo=WEEK)

    assert result == {"ComicID": "100", "IssueID": None, "Status": None}
    # LastUpdated is recent, so the source is not re-read inside five hours.
    reread.assert_not_called()
    with engine.connect() as conn:
        assert conn.execute(select(upcoming)).first() is None


def test_issue_the_series_does_not_list_yet_rereads_the_source_on_forcecheck(engine, series_refresh, monkeypatch):
    reread = MagicMock()
    monkeypatch.setattr(add, "update_issue_data", reread)

    watchlist_match.upcoming_update("100", "Absolute Batman", "6", "2024-03-06", forcecheck="yes", weekinfo=WEEK)

    reread.assert_called_once_with("100", "Absolute Batman", calledfrom="weeklycheck")


def test_latest_update_records_the_newest_issue_on_the_series(engine):
    watchlist_match.latest_update(ComicID="100", LatestIssue="6", LatestDate="2024-03-06")

    with engine.connect() as conn:
        row = conn.execute(select(comics).where(comics.c.ComicID == "100")).mappings().one()
    assert (row["LatestIssue"], row["intLatestIssue"], row["LatestDate"]) == ("6", 6000, "2024-03-06")
