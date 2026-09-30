#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""ComicVine as the fallback weekly pull-list source (#919)."""

from unittest.mock import MagicMock, patch

import pytest

import comicarr
from comicarr import weeklypull
from comicarr.app.weekly import cv_source

WALKSOFTLY_DOWN = {
    "status": "failure",
    "retry_after": 120,
    "origin_error": True,
    "cause": "Walksoftly is unreachable. The pull-list source is down upstream.",
}


def _page(results, total, offset=0):
    return {
        "status_code": 1,
        "error": "OK",
        "number_of_total_results": total,
        "offset": offset,
        "results": results,
    }


def _issue(issue_id, volume_id, number, name="Series"):
    return {
        "id": issue_id,
        "issue_number": number,
        "name": None,
        "store_date": "2026-09-30",
        "cover_date": "2026-11-01",
        "volume": {"id": volume_id, "name": name},
    }


@pytest.fixture
def cv_config(monkeypatch):
    config = MagicMock()
    config.COMICVINE_API = "test-key"
    monkeypatch.setattr(comicarr, "CONFIG", config)
    return config


@pytest.fixture
def stored(monkeypatch):
    calls = []
    monkeypatch.setattr(cv_source.locg, "store_week", lambda pull, week, year: calls.append((pull, week, year)))
    return calls


def test_week_bounds_are_sunday_to_saturday():
    assert cv_source.week_bounds("2026-09-30") == ("2026-09-27", "2026-10-03")
    # Across a year boundary.
    assert cv_source.week_bounds("2026-12-30") == ("2026-12-27", "2027-01-02")


def test_pull_week_pages_through_releases_and_stores_walksoftly_shaped_rows(cv_config, stored, monkeypatch):
    requests = []

    def pulldetails(comicid, rtype, offset=0, dateinfo=None, comicidlist=None, **_kwargs):
        requests.append((rtype, offset, dateinfo, comicidlist))
        if rtype == "weekly_releases":
            if offset == 0:
                return _page([_issue(9001, 100, "12", "Absolute Batman"), _issue(9002, 200, "1")], 3)
            return _page([_issue(9003, 300, "4")], 3, offset=2)
        return _page(
            [
                {"id": 100, "name": "Absolute Batman", "start_year": "2024", "publisher": {"name": "DC Comics"}},
                {"id": 200, "name": "Hidden Title", "start_year": "2026", "publisher": {"name": "Ignored Press"}},
                {"id": 300, "name": "No Publisher", "start_year": "2025", "publisher": None},
            ],
            3,
        )

    monkeypatch.setattr(cv_source.cv, "pulldetails", pulldetails)
    monkeypatch.setattr(cv_source, "ignored_publisher_check", lambda publisher: publisher == "Ignored Press")

    result = cv_source.pull_week(39, 2026, "2026-09-30")

    assert result == {"status": "success", "source": "comicvine", "count": 2, "weeknumber": 39, "year": 2026}
    assert [r[:2] for r in requests] == [("weekly_releases", 0), ("weekly_releases", 2), ("weekly_volumes", 0)]
    assert requests[0][2] == {"start_date": "2026-09-27", "end_date": "2026-10-03"}
    assert requests[2][3] == "100|200|300"

    (pull, week, year) = stored[0]
    assert (week, year) == (39, 2026)
    assert pull[0] == {
        "series": "Absolute Batman",
        "alias": None,
        "issue": "12",
        "publisher": "DC Comics",
        "shipdate": "2026-09-30",
        "coverdate": "2026-11-01",
        "comicid": "100",
        "issueid": "9001",
        "weeknumber": "39",
        "annuallink": None,
        "year": "2026",
        "volume": None,
        "seriesyear": "2024",
        "format": None,
    }
    # Ignored publishers are dropped; an unknown publisher is kept.
    assert [row["comicid"] for row in pull] == ["100", "300"]
    assert pull[1]["publisher"] is None


def test_pull_week_looks_up_volumes_a_hundred_at_a_time(cv_config, stored, monkeypatch):
    issues = [_issue(i, 1000 + i, "1") for i in range(150)]
    volume_requests = []

    def pulldetails(comicid, rtype, offset=0, comicidlist=None, **_kwargs):
        if rtype == "weekly_releases":
            return _page(issues[offset : offset + 100], len(issues), offset=offset)
        ids = comicidlist.split("|")
        volume_requests.append(len(ids))
        return _page([{"id": int(v), "name": "S", "start_year": "2026", "publisher": None} for v in ids], len(ids))

    monkeypatch.setattr(cv_source.cv, "pulldetails", pulldetails)

    result = cv_source.pull_week(39, 2026, "2026-09-30")

    assert result["count"] == 150
    assert volume_requests == [100, 50]


def test_pull_week_stores_nothing_when_a_page_fails(cv_config, stored, monkeypatch):
    def pulldetails(comicid, rtype, offset=0, **_kwargs):
        if offset == 0:
            return _page([_issue(1, 10, "1")], 2)
        return None  # ComicVine errored or rate-limited mid-week

    monkeypatch.setattr(cv_source.cv, "pulldetails", pulldetails)

    result = cv_source.pull_week(39, 2026, "2026-09-30")

    assert result["status"] == "failure"
    assert stored == []


def test_pull_week_stores_nothing_when_the_page_cap_cuts_the_week_short(cv_config, stored, monkeypatch):
    # Saving a truncated week would replace a complete saved pull list.
    def pulldetails(comicid, rtype, offset=0, **_kwargs):
        return _page([_issue(offset + 1, 10, "1")], 10_000, offset)

    monkeypatch.setattr(cv_source, "MAX_PAGES", 3)
    monkeypatch.setattr(cv_source.cv, "pulldetails", pulldetails)

    result = cv_source.pull_week(39, 2026, "2026-09-30")

    assert result["status"] == "failure"
    assert stored == []


def test_pull_week_without_an_api_key_never_calls_comicvine(cv_config, stored, monkeypatch):
    cv_config.COMICVINE_API = None
    pulldetails = MagicMock()
    monkeypatch.setattr(cv_source.cv, "pulldetails", pulldetails)

    result = cv_source.pull_week(39, 2026, "2026-09-30")

    assert result["status"] == "failure"
    pulldetails.assert_not_called()
    assert stored == []


# --- pullit() choosing the fallback ------------------------------------------


@pytest.fixture
def walksoftly_down(cv_config, monkeypatch):
    cv_config.ALT_PULL = 2
    cv_config.CACHE_DIR = "/tmp"

    def weekly_info(week=None, year=None):
        info = {"weeknumber": 39, "year": 2026, "prev_weeknumber": 38, "prev_year": 2026}
        if week is not None:
            info["midweek"] = {38: "2026-09-23", 39: "2026-09-30"}[int(week)]
        return info

    monkeypatch.setattr(weeklypull.helpers, "weekly_info", weekly_info)
    monkeypatch.setattr(weeklypull.locg, "locg", lambda **kwargs: dict(WALKSOFTLY_DOWN))
    monkeypatch.setattr(weeklypull.time, "sleep", lambda *_args: None)
    new_pullcheck = MagicMock()
    monkeypatch.setattr(weeklypull, "new_pullcheck", new_pullcheck)
    return new_pullcheck


def _run_pullit():
    with patch.object(weeklypull.db, "select_one", return_value={"SHIPDATE": "20260930"}):
        return weeklypull.pullit()


def test_current_week_is_filled_from_comicvine_when_walksoftly_is_down(walksoftly_down, monkeypatch):
    # Previous week already saved; current week has nothing saved.
    monkeypatch.setattr(weeklypull, "_weekly_pull_has_data", lambda week, year: int(week) == 38)
    pulled = []

    def pull_week(week, year, midweek):
        pulled.append((week, year, midweek))
        return {"status": "success", "source": "comicvine", "count": 42, "weeknumber": week, "year": year}

    monkeypatch.setattr(cv_source, "pull_week", pull_week)

    result = _run_pullit()

    # The settled previous week keeps its saved rows; only the current week asks ComicVine.
    assert pulled == [(39, 2026, "2026-09-30")]
    assert [c.args for c in walksoftly_down.call_args_list] == [(38, 2026), (39, 2026)]
    assert result["status"] == "success"
    assert result["source"] == "comicvine"
    # Walksoftly's outage and retry hint still travel, so the job retries it.
    assert result["origin_error"] is True
    assert result["retry_after"] == 120
    assert "Walksoftly" in result["cause"]


def test_previous_week_without_saved_rows_also_uses_comicvine(walksoftly_down, monkeypatch):
    monkeypatch.setattr(weeklypull, "_weekly_pull_has_data", lambda *_args: False)
    pulled = []
    monkeypatch.setattr(
        cv_source,
        "pull_week",
        lambda week, year, midweek: pulled.append(week) or {"status": "success", "source": "comicvine", "count": 1},
    )

    result = _run_pullit()

    assert pulled == [38, 39]
    assert result["status"] == "success"


def test_saved_rows_still_serve_the_week_when_comicvine_also_fails(walksoftly_down, monkeypatch):
    monkeypatch.setattr(weeklypull, "_weekly_pull_has_data", lambda *_args: True)
    monkeypatch.setattr(
        cv_source, "pull_week", lambda *_args: {"status": "failure", "source": "comicvine", "cause": "down"}
    )

    result = _run_pullit()

    assert result["status"] == "success"
    assert "source" not in result
    assert [c.args for c in walksoftly_down.call_args_list] == [(38, 2026), (39, 2026)]


def test_the_run_fails_when_neither_source_nor_saved_rows_have_the_week(walksoftly_down, monkeypatch):
    monkeypatch.setattr(weeklypull, "_weekly_pull_has_data", lambda *_args: False)
    monkeypatch.setattr(cv_source, "pull_week", lambda *_args: {"status": "failure", "cause": "down"})

    result = _run_pullit()

    assert result["status"] == "failure"
    assert "Walksoftly" in result["cause"]
    walksoftly_down.assert_not_called()


def test_an_exception_in_the_fallback_does_not_escape_pullit(walksoftly_down, monkeypatch):
    monkeypatch.setattr(weeklypull, "_weekly_pull_has_data", lambda *_args: True)

    def explode(*_args):
        raise ValueError("unexpected ComicVine payload")

    monkeypatch.setattr(cv_source, "pull_week", explode)

    result = _run_pullit()

    assert result["status"] == "success"  # served from the saved rows instead


def test_current_week_answers_expire_before_the_next_pull_run(cv_config):
    """A cached Sunday answer must not hide store dates ComicVine adds by Wednesday."""
    from comicarr import cv

    cv_config.CV_CACHE_TTL_SEARCH = 86400
    cv_config.CV_CACHE_TTL_METADATA = 604800
    assert cv.get_cache_ttl_for_rtype("weekly_releases") < 4 * 3600
    # Publishers don't change week to week, so series lookups keep the long cache.
    assert cv.get_cache_ttl_for_rtype("weekly_volumes") == 604800
    # An operator who shortened the search cache further is still honoured.
    cv_config.CV_CACHE_TTL_SEARCH = 600
    assert cv.get_cache_ttl_for_rtype("weekly_releases") == 600
