#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for the week-by-week industry releases endpoint (#1080)."""

import datetime
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.app.storyarcs import service as storyarcs_service
from comicarr.app.weekly import router
from comicarr.app.weekly import service as weekly_service
from comicarr.tables import comics, issues, metadata, weekly

# Saturday of %U week 41, 2026 (Sunday 2026-10-11 to Saturday 2026-10-17).
TODAY = datetime.date(2026, 10, 17)


@pytest.fixture
def weekly_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(weekly_service, "_FETCH_ATTEMPTS", {})
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _seed_week(engine, rows):
    with engine.begin() as conn:
        conn.execute(insert(weekly), rows)


def _no_fetch(*_args, **_kwargs):
    raise AssertionError("a stored week must not be fetched")


def test_current_week_uses_the_sunday_based_year_at_new_year_boundary():
    """Week zero resolves to the previous Sunday, as My Releases already does."""
    week, year = storyarcs_service.get_current_week(today=datetime.date(2021, 1, 1))

    assert (week, year) == ("52", "2020")


def test_week_window_describes_the_current_week_and_its_neighbours():
    window = weekly_service.week_window(today=TODAY)

    assert window == {
        "week": "41",
        "year": "2026",
        "start": "2026-10-11",
        "end": "2026-10-17",
        "offset": 0,
        "prev": {"week": "40", "year": "2026"},
        "next": {"week": "42", "year": "2026"},
    }


def test_week_window_crosses_the_new_year_with_the_stored_week_key():
    window = weekly_service.week_window("52", "2020", today=datetime.date(2020, 12, 30))

    assert window["start"] == "2020-12-27"
    assert window["next"] == {"week": "1", "year": "2021"}
    assert weekly_service.week_window("1", "2021", today=datetime.date(2020, 12, 30))["prev"] == {
        "week": "52",
        "year": "2020",
    }


def test_week_window_stops_at_the_browsable_edges():
    last = weekly_service.week_window("45", "2026", today=TODAY)

    assert last["offset"] == weekly_service.WEEKS_AHEAD
    assert last["next"] is None
    with pytest.raises(weekly_service.WeekError):
        weekly_service.week_window("46", "2026", today=TODAY)
    with pytest.raises(weekly_service.WeekError):
        weekly_service.week_window("x", "2026", today=TODAY)


def test_a_stored_week_is_read_without_fetching(monkeypatch, weekly_db):
    _seed_week(
        weekly_db,
        [
            {"COMIC": "Current title", "ISSUE": "1", "ComicID": "current", "weeknumber": "41", "year": "2026"},
            {"COMIC": "Last week title", "ISSUE": "1", "ComicID": "old", "weeknumber": "40", "year": "2026"},
        ],
    )
    monkeypatch.setattr(weekly_service, "_fetch_week", _no_fetch)

    result = weekly_service.get_week(today=TODAY)
    previous = weekly_service.get_week("40", "2026", today=TODAY)

    assert result["source"] == "stored"
    assert [row["COMIC"] for row in result["rows"]] == ["Current title"]
    assert [row["COMIC"] for row in previous["rows"]] == ["Last week title"]


def test_early_year_weeks_match_unpadded_stored_rows(monkeypatch, weekly_db):
    _seed_week(
        weekly_db,
        [
            {"COMIC": "Week one title", "ISSUE": "1", "ComicID": "one", "weeknumber": "1", "year": "2026"},
            {"COMIC": "Week two title", "ISSUE": "1", "ComicID": "two", "weeknumber": "2", "year": "2026"},
        ],
    )
    monkeypatch.setattr(weekly_service, "_fetch_week", _no_fetch)

    result = weekly_service.get_week("01", "2026", today=datetime.date(2026, 1, 8))

    assert [row["COMIC"] for row in result["rows"]] == ["Week one title"]


def test_an_unstored_week_is_fetched_once_and_not_retried_straight_away(monkeypatch, weekly_db):
    calls = []

    def fetch(week, year, start):
        calls.append((week, year, start))
        if len(calls) == 1:
            return None
        raise AssertionError("a failed week must wait before it is fetched again")

    monkeypatch.setattr(weekly_service, "_fetch_week", fetch)

    first = weekly_service.get_week("42", "2026", today=TODAY)
    second = weekly_service.get_week("42", "2026", today=TODAY)

    assert calls == [("42", "2026", "2026-10-18")]
    assert first["source"] == second["source"] == "unavailable"
    assert first["rows"] == []


def test_a_fetched_week_returns_the_rows_the_source_stored(monkeypatch, weekly_db):
    def fetch(week, year, start):
        _seed_week(weekly_db, [{"COMIC": "Next week", "ISSUE": "3", "weeknumber": week, "year": year}])
        return "walksoftly"

    monkeypatch.setattr(weekly_service, "_fetch_week", fetch)

    result = weekly_service.get_week("42", "2026", today=TODAY)

    assert result["source"] == "fetched"
    assert [row["COMIC"] for row in result["rows"]] == ["Next week"]


def test_fetch_week_falls_back_to_comicvine_on_the_week_midpoint(monkeypatch):
    from comicarr import locg
    from comicarr.app.weekly import cv_source

    pulled = []
    monkeypatch.setattr(locg, "locg", lambda **_kwargs: {"status": "failure"})
    monkeypatch.setattr(cv_source, "is_available", lambda: True)
    monkeypatch.setattr(
        cv_source, "pull_week", lambda week, year, midweek: pulled.append(midweek) or {"status": "success"}
    )

    assert weekly_service._fetch_week("42", "2026", "2026-10-18") == "comicvine"
    assert pulled == ["2026-10-21"]


def test_rows_carry_their_library_state(monkeypatch, weekly_db):
    with weekly_db.begin() as conn:
        conn.execute(
            insert(comics),
            [{"ComicID": "owned", "ComicName": "Owned", "Status": "Active"}],
        )
        conn.execute(
            insert(issues),
            [
                {"IssueID": "owned-5", "ComicID": "owned", "Issue_Number": "5", "Status": "Wanted"},
                {"IssueID": "owned-6", "ComicID": "owned", "Issue_Number": "6", "Status": "Downloaded"},
            ],
        )
    _seed_week(
        weekly_db,
        [
            {"COMIC": "A wanted", "ISSUE": "5", "ComicID": "owned", "IssueID": "owned-5"},
            {"COMIC": "B by number", "ISSUE": "6", "ComicID": "owned", "IssueID": "pull-only-id"},
            {"COMIC": "C not yet listed", "ISSUE": "7", "ComicID": "owned", "IssueID": "owned-7"},
            {"COMIC": "D stranger", "ISSUE": "1", "ComicID": "stranger", "IssueID": "stranger-1"},
        ],
    )
    with weekly_db.begin() as conn:
        conn.execute(weekly.update().values(weeknumber="41", year="2026"))
    monkeypatch.setattr(weekly_service, "_fetch_week", _no_fetch)

    rows = weekly_service.get_week(today=TODAY)["rows"]

    assert [(row["COMIC"], row["state"], row["library_issue_id"], row["in_library"]) for row in rows] == [
        ("A wanted", "wanted", "owned-5", True),
        ("B by number", "downloaded", "owned-6", True),
        ("C not yet listed", "in_library", None, True),
        ("D stranger", "not_in_library", None, False),
    ]


def test_router_rejects_half_a_week_and_weeks_outside_the_window(weekly_db):
    half = router.get_weekly(week=41, year=None, ctx=None)
    far = router.get_weekly(week=10, year=2030, ctx=None)

    assert half.status_code == 400
    assert far.status_code == 400
    assert "weeks ahead" in json.loads(far.body)["detail"]


def _pull_row(engine, **values):
    row = {"COMIC": "New Series", "ISSUE": "1", "ComicID": "4050-77", "IssueID": "900", **values}
    with engine.begin() as conn:
        return conn.execute(insert(weekly).values(**row)).inserted_primary_key[0]


def test_add_from_week_adds_the_series_before_wanting_its_issue(monkeypatch, weekly_db):
    from comicarr import importer
    from comicarr.app.search import service as search_service

    events = []
    monkeypatch.setattr(
        search_service,
        "add_comic",
        lambda ctx, comic_id, folder=None: events.append(("add", comic_id)) or {"success": True, "comicid": comic_id},
    )
    monkeypatch.setattr(importer, "issue_watcher_thread", lambda ids: events.append(("want", ids)))
    rowid = _pull_row(weekly_db)

    result = weekly_service.add_from_week(None, rowid, want=True)

    assert result["success"] is True
    assert result["want_queued"] is True
    assert events == [("add", "4050-77"), ("want", ["900"])]


def test_add_from_week_refuses_rows_it_cannot_add(monkeypatch, weekly_db):
    from comicarr.app.search import service as search_service

    monkeypatch.setattr(search_service, "add_comic", _no_fetch)
    with weekly_db.begin() as conn:
        conn.execute(insert(comics).values(ComicID="4050-77", ComicName="New Series"))
    owned = _pull_row(weekly_db)
    unidentified = _pull_row(weekly_db, ComicID=None, IssueID=None)

    assert weekly_service.add_from_week(None, owned)["status"] == 409
    assert weekly_service.add_from_week(None, unidentified)["status"] == 422
    assert weekly_service.add_from_week(None, 999_999)["status"] == 404
