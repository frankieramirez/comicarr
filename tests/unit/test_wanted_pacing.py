#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Wanted pacing: how far the RSS watchlist pass is, and when series come up."""

from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.app.search.backlog import PASS_RSS_WANTED
from comicarr.app.series import wanted_pacing
from comicarr.tables import metadata, rss_search_seen

NOW = 1_800_000_000.0


@pytest.fixture
def pacing_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(ENABLE_RSS=True, RSS_CHECKINTERVAL=20, WANTED_SEARCH_PASS_ITEMS=250, SEARCH_TIER_CUTOFF=14),
    )
    monkeypatch.setattr(comicarr, "RSS_STATUS", "Waiting")
    monkeypatch.setattr(comicarr, "SCHED", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _rows():
    # Newest release first is the pass's order: Saga (2026) before Akira (1982).
    rows = [{"IssueID": "akira-%d" % n, "ComicID": "akira", "ReleaseDate": "1982-12-%02d" % n} for n in range(1, 7)]
    rows += [{"IssueID": "saga-%d" % n, "ComicID": "saga", "ReleaseDate": "2026-01-%02d" % n} for n in range(1, 5)]
    return rows


def test_measured_rate_uses_recent_checks_and_falls_back_to_the_configured_ceiling():
    assert wanted_pacing.measured_rate([], now=NOW, interval_minutes=20, configured=750) == (750, False)
    # 100 checks spread over the last two hours: 50 an hour.
    times = [NOW - 7200 + i * 72 for i in range(100)]
    rate, measured = wanted_pacing.measured_rate(times, now=NOW, interval_minutes=20, configured=750)
    assert measured and round(rate) == 50
    # A burst of one pass is spread over at least one interval.
    rate, _ = wanted_pacing.measured_rate([NOW - 60] * 250, now=NOW, interval_minutes=20, configured=750)
    assert round(rate) == 750


def test_pacing_reports_progress_and_orders_series_newest_first(pacing_db):
    with pacing_db.begin() as conn:
        conn.execute(
            insert(rss_search_seen),
            [
                {"pass_kind": PASS_RSS_WANTED, "issue_id": "saga-%d" % n, "checked_at": str(int(NOW - 7200 + n * 1800))}
                for n in range(1, 5)
            ],
        )

    summary, eta = wanted_pacing.pacing(_rows(), config=comicarr.CONFIG, now=NOW)

    assert summary["state"] == "checking"
    assert (summary["total"], summary["checked"], summary["waiting"]) == (10, 4, 6)
    # Four checks across the last 1.5 hours.
    assert summary["per_hour"] == 3
    assert summary["measured"] is True
    assert summary["finishes_in_hours"] == 2.3
    # Saga is fully checked this cycle; Akira's sixth issue is two hours out.
    assert "saga" not in eta
    assert eta["akira"] == pytest.approx(2.25)


def test_pacing_waits_for_the_feed_once_everything_is_checked(pacing_db):
    with pacing_db.begin() as conn:
        conn.execute(
            insert(rss_search_seen),
            [{"pass_kind": PASS_RSS_WANTED, "issue_id": r["IssueID"], "checked_at": str(int(NOW))} for r in _rows()],
        )
    summary, eta = wanted_pacing.pacing(_rows(), config=comicarr.CONFIG, now=NOW)
    assert summary["state"] == "waiting_for_feed"
    assert summary["finishes_in_hours"] is None
    assert eta == {}


def test_pacing_is_off_without_rss(pacing_db):
    config = SimpleNamespace(ENABLE_RSS=False)
    summary, eta = wanted_pacing.pacing(_rows(), config=config, now=NOW)
    assert summary["state"] == "off"
    assert summary["per_hour"] == 0
    assert eta == {}
    assert wanted_pacing.pacing([], config=config, now=NOW)[0]["state"] == "idle"
