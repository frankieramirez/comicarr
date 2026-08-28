#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Weekly pull-list upstream outage fallback tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db, weeklypull
from comicarr.tables import metadata, weekly


@pytest.fixture
def weekly_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def test_weekly_pull_has_data_runs_the_real_query(weekly_db):
    with weekly_db.begin() as conn:
        conn.execute(
            insert(weekly),
            [
                {
                    "COMIC": "Cached title",
                    "ISSUE": "1",
                    "ComicID": "cached",
                    "IssueID": "cached-1",
                    "SHIPDATE": "20260827",
                    "weeknumber": "33",
                    "year": "2026",
                }
            ],
        )

    assert weeklypull._weekly_pull_has_data(33, 2026) is True
    assert weeklypull._weekly_pull_has_data("33", "2026") is True
    assert weeklypull._weekly_pull_has_data(34, 2026) is False


def test_pullit_uses_cached_week_when_upstream_fails(monkeypatch):
    config = MagicMock()
    config.ALT_PULL = 2
    config.CACHE_DIR = "/tmp"
    monkeypatch.setattr(comicarr, "CONFIG", config)
    monkeypatch.setattr(
        weeklypull.helpers,
        "weekly_info",
        lambda: {"weeknumber": 33, "year": 2026, "prev_weeknumber": 32, "prev_year": 2026},
    )
    monkeypatch.setattr(weeklypull, "_weekly_pull_has_data", lambda week, year: week == 33 and year == 2026)
    monkeypatch.setattr(weeklypull.locg, "locg", lambda **kwargs: {"status": "failure"})
    new_pullcheck = MagicMock()
    monkeypatch.setattr(weeklypull, "new_pullcheck", new_pullcheck)
    monkeypatch.setattr(weeklypull.time, "sleep", lambda *_args: None)

    with patch.object(weeklypull.db, "select_one", return_value={"SHIPDATE": "20260827"}):
        result = weeklypull.pullit()

    assert result == {"status": "success"}
    new_pullcheck.assert_called_once_with(33, 2026)


def test_pullit_still_fails_without_cached_week(monkeypatch):
    config = MagicMock()
    config.ALT_PULL = 2
    config.CACHE_DIR = "/tmp"
    monkeypatch.setattr(comicarr, "CONFIG", config)
    monkeypatch.setattr(
        weeklypull.helpers,
        "weekly_info",
        lambda: {"weeknumber": 33, "year": 2026, "prev_weeknumber": 32, "prev_year": 2026},
    )
    monkeypatch.setattr(weeklypull, "_weekly_pull_has_data", lambda *_args: False)
    monkeypatch.setattr(weeklypull.locg, "locg", lambda **kwargs: {"status": "failure"})
    monkeypatch.setattr(weeklypull, "new_pullcheck", MagicMock())
    monkeypatch.setattr(weeklypull.time, "sleep", lambda *_args: None)

    with patch.object(weeklypull.db, "select_one", return_value={"SHIPDATE": "20260827"}):
        result = weeklypull.pullit()

    assert result == {"status": "failure"}


def test_pullit_surfaces_retry_hint_when_serving_cached_week(monkeypatch):
    config = MagicMock()
    config.ALT_PULL = 2
    config.CACHE_DIR = "/tmp"
    monkeypatch.setattr(comicarr, "CONFIG", config)
    monkeypatch.setattr(
        weeklypull.helpers,
        "weekly_info",
        lambda: {"weeknumber": 33, "year": 2026, "prev_weeknumber": 32, "prev_year": 2026},
    )
    monkeypatch.setattr(weeklypull, "_weekly_pull_has_data", lambda week, year: week == 33 and year == 2026)
    monkeypatch.setattr(weeklypull.locg, "locg", lambda **kwargs: {"status": "failure", "retry_after": 120})
    monkeypatch.setattr(weeklypull, "new_pullcheck", MagicMock())
    monkeypatch.setattr(weeklypull.time, "sleep", lambda *_args: None)

    with patch.object(weeklypull.db, "select_one", return_value={"SHIPDATE": "20260827"}):
        result = weeklypull.pullit()

    assert result == {"status": "success", "retry_after": 120}


def test_pullit_surfaces_retry_hint_on_failure(monkeypatch):
    config = MagicMock()
    config.ALT_PULL = 2
    config.CACHE_DIR = "/tmp"
    monkeypatch.setattr(comicarr, "CONFIG", config)
    monkeypatch.setattr(
        weeklypull.helpers,
        "weekly_info",
        lambda: {"weeknumber": 33, "year": 2026, "prev_weeknumber": 32, "prev_year": 2026},
    )
    monkeypatch.setattr(weeklypull, "_weekly_pull_has_data", lambda *_args: False)
    monkeypatch.setattr(weeklypull.locg, "locg", lambda **kwargs: {"status": "failure", "retry_after": 120})
    monkeypatch.setattr(weeklypull, "new_pullcheck", MagicMock())
    monkeypatch.setattr(weeklypull.time, "sleep", lambda *_args: None)

    with patch.object(weeklypull.db, "select_one", return_value={"SHIPDATE": "20260827"}):
        result = weeklypull.pullit()

    assert result == {"status": "failure", "retry_after": 120}
