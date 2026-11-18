#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Metron as a backup weekly pull-list source."""

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import comicarr
from comicarr.app.core import runtime
from comicarr.app.weekly import metron_source


def _issue(name, number, year_began, store_date="2026-10-21"):
    return SimpleNamespace(
        number=number,
        store_date=datetime.date.fromisoformat(store_date),
        cover_date=datetime.date(2026, 12, 1),
        series=SimpleNamespace(name=name, volume=1, year_began=year_began),
    )


@pytest.fixture
def metron(monkeypatch):
    monkeypatch.setattr(
        comicarr, "CONFIG", SimpleNamespace(METRON_USERNAME="reader", METRON_PASSWORD="secret"), raising=False
    )
    api = MagicMock()
    monkeypatch.setattr(runtime.current(), "metron_api", api, raising=False)
    stored = []
    monkeypatch.setattr(metron_source.locg, "store_week", lambda pull, week, year: stored.append((pull, week, year)))
    monkeypatch.setattr(
        metron_source.weekly_queries,
        "get_library_comics",
        lambda: [
            {"ComicID": "4050-1", "ComicName": "Night Watch", "DynamicComicName": None, "ComicYear": "2024"},
            {"ComicID": "4050-2", "ComicName": "Night Watch", "DynamicComicName": None, "ComicYear": "1999"},
            {"ComicID": "4050-3", "ComicName": "Sky Riders", "DynamicComicName": None, "ComicYear": "2020"},
        ],
    )
    return api, stored


def test_is_available_needs_both_login_fields(monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(METRON_USERNAME="reader", METRON_PASSWORD=""))
    assert metron_source.is_available() is False
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(METRON_USERNAME="reader", METRON_PASSWORD="pw"))
    assert metron_source.is_available() is True
    monkeypatch.setattr(comicarr, "CONFIG", MagicMock())
    assert metron_source.is_available() is False


def test_pull_week_asks_for_the_week_by_store_date_and_matches_library_series(metron):
    api, stored = metron
    api.issues_list.return_value = [
        _issue("Night Watch", "7", 2024),
        _issue("Sky Riders", "12", 2020),
        _issue("Stranger Things Happen", "1", 2026),
    ]

    result = metron_source.pull_week(42, 2026, "2026-10-21")

    api.issues_list.assert_called_once_with(
        {"store_date_range_after": "2026-10-18", "store_date_range_before": "2026-10-24"}
    )
    assert result == {"status": "success", "source": "metron", "count": 3, "weeknumber": 42, "year": 2026}
    pull, week, year = stored[0]
    assert (week, year) == (42, 2026)
    by_series = {row["series"]: row for row in pull}
    # Two library series share the name; the start year picks the right one.
    assert by_series["Night Watch"]["comicid"] == "4050-1"
    assert by_series["Sky Riders"]["comicid"] == "4050-3"
    assert by_series["Stranger Things Happen"]["comicid"] is None
    assert by_series["Night Watch"]["shipdate"] == "2026-10-21"
    assert by_series["Night Watch"]["issue"] == "7"


def test_an_ambiguous_name_without_a_year_is_left_unmatched(metron):
    api, stored = metron
    api.issues_list.return_value = [_issue("Night Watch", "7", None)]

    metron_source.pull_week(42, 2026, "2026-10-21")

    assert stored[0][0][0]["comicid"] is None


def test_an_empty_week_stores_nothing(metron):
    api, stored = metron
    api.issues_list.return_value = []

    result = metron_source.pull_week(42, 2026, "2026-10-21")

    assert result["status"] == "failure"
    assert result["reason"] == "no_releases"
    assert stored == []


def test_a_metron_error_stores_nothing(metron):
    api, stored = metron
    api.issues_list.side_effect = RuntimeError("503")

    result = metron_source.pull_week(42, 2026, "2026-10-21")

    assert result["reason"] == "failed"
    assert stored == []
