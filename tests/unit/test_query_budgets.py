#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Query-count budgets for the main read endpoints.

Each endpoint runs against a small seeded library and must stay at or under
the statement budget in ``tests/query_budgets.py``. It runs again against a
library twice the size, and the count must not change: a count that grows
with the library is an N+1. Section 7 of
``docs/architecture/foundations-plan.md`` explains why this, and not
wall-clock time, gates pull requests.
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, text

import comicarr
from comicarr import db
from comicarr.tables import (
    acquisition_run_items,
    activity_events,
    comics,
    issues,
    metadata,
    pipeline_journal,
    weekly,
)
from tests.query_budgets import BUDGETS
from tests.query_count import count_statements

SMALL = {"series": 20, "issues_per_series": 15}
LARGE = {"series": 40, "issues_per_series": 30}

# The series every detail read asks for; it exists at both sizes.
DETAIL_SERIES = "s0000"

ENDPOINTS = {
    "library_list": "/api/series",
    "series_detail": "/api/series/%s" % DETAIL_SERIES,
    "wanted_by_series": "/api/wanted/series",
    "wanted_issues": "/api/wanted?comic_id=%s&limit=50" % DETAIL_SERIES,
    "dashboard_library": "/api/dashboard/library",
    "dashboard_activity": "/api/dashboard/activity",
    "dashboard_upcoming": "/api/dashboard/upcoming",
}

STATUSES = ("Downloaded", "Wanted", "Downloaded", "Skipped", "Snatched", "Archived")


def seed_library(engine, series, issues_per_series):
    """Seed comics, issues, search state, activity and this week's pull."""
    from comicarr.app.storyarcs.service import get_current_week

    week, year = get_current_week()
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    comic_rows, issue_rows, run_items, events, pull, journal = [], [], [], [], [], []
    for s in range(series):
        comic_id = "s%04d" % s
        manga = s % 5 == 0
        comic_rows.append(
            {
                "ComicID": comic_id,
                "ComicName": "Series %d" % s,
                "ComicSortName": "Series %d" % s,
                "ComicYear": "2020",
                "ComicPublisher": "Publisher %d" % (s % 4),
                "Status": "Active",
                "ContentType": "manga" if manga else "comic",
                "Have": issues_per_series // 2,
                "Total": issues_per_series,
                "ComicLocation": "/library/Series %d" % s,
                "LatestIssue": str(issues_per_series),
                "LatestDate": "2026-11-01",
            }
        )
        for n in range(1, issues_per_series + 1):
            issue_id = "%s-%03d" % (comic_id, n)
            status = STATUSES[n % len(STATUSES)]
            issue_rows.append(
                {
                    "IssueID": issue_id,
                    "ComicID": comic_id,
                    "ComicName": "Series %d" % s,
                    "Issue_Number": str(n),
                    "Int_IssueNumber": n * 1000,
                    "IssueDate": "2026-%02d-01" % (n % 12 + 1),
                    "ReleaseDate": "2026-%02d-01" % (n % 12 + 1),
                    "Status": status,
                    "Location": "Series %d %03d.cbz" % (s, n) if status == "Downloaded" else None,
                }
            )
            if status == "Wanted" and n % 4 == 1:
                run_items.append(
                    {
                        "run_id": "run-%s" % comic_id,
                        "command_kind": "search",
                        "entity_type": "issue",
                        "entity_id": issue_id,
                        "state": "no_match",
                        "attempt_count": 2,
                        "created_at": stamp,
                        "updated_at": stamp,
                    }
                )
            if n <= 2:
                events.append(
                    {
                        "created_at": (now - timedelta(hours=s * 2 + n)).strftime("%Y-%m-%d %H:%M:%S"),
                        "activity": "download",
                        "status": "succeeded",
                        "subject_type": "issue",
                        "subject_id": issue_id,
                        "subject_label": "Series %d #%d" % (s, n),
                        "parent_series_id": comic_id,
                    }
                )
        # This week's pull holds one wanted, one snatched or one downloaded issue per series.
        pulled = (1, 4, 2)[s % 3]
        pull.append(
            {
                "SHIPDATE": now.date().isoformat(),
                "PUBLISHER": "Publisher %d" % (s % 4),
                "ISSUE": str(pulled),
                "COMIC": "Series %d" % s,
                "STATUS": "Wanted",
                "ComicID": comic_id,
                "IssueID": "%s-%03d" % (comic_id, pulled),
                "weeknumber": week,
                "year": year,
            }
        )

        if pulled == 1:
            # A failed download behind the wanted pull issue, so Needs attention has members.
            journal.append(
                {
                    "release_key": "rk-%s" % comic_id,
                    "issueid": "%s-001" % comic_id,
                    "provider": "DDL",
                    "stage": "failed",
                    "stage_rank": 60,
                    "updated_date": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "fail_reason": "submission_rejected",
                    "payload_json": json.dumps({"comicid": comic_id, "comicname": "Series %d" % s}),
                }
            )

    with engine.begin() as conn:
        conn.execute(insert(comics), comic_rows)
        conn.execute(insert(issues), issue_rows)
        if run_items:
            conn.execute(insert(acquisition_run_items), run_items)
        conn.execute(insert(activity_events), events)
        conn.execute(insert(weekly), pull)
        conn.execute(insert(pipeline_journal), journal)


@pytest.fixture
def library_db(tmp_path, monkeypatch):
    """Yield a function that builds a fresh seeded library database."""
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(COMIC_DIR="", MANGA_DIR="", ANNUALS_ON=False))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    built = []

    def build(size):
        folder = tmp_path / ("lib%d" % len(built))
        folder.mkdir()
        monkeypatch.setattr(comicarr, "DATA_DIR", str(folder))
        db.shutdown_engine()
        engine = db.get_engine()
        metadata.create_all(engine)
        seed_library(engine, **size)
        built.append(engine)
        return engine

    yield build
    db.shutdown_engine()


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from comicarr.app.core.context import AppContext, get_context
    from comicarr.app.core.security import require_session
    from comicarr.app.dashboard.router import router as dashboard_router
    from comicarr.app.series.router import router as series_router

    app = FastAPI()
    app.include_router(series_router)
    app.include_router(dashboard_router)
    app.dependency_overrides[require_session] = lambda: "operator"
    app.dependency_overrides[get_context] = lambda: AppContext(config=comicarr.CONFIG)
    return TestClient(app)


def measure(engine):
    """Return each endpoint's statement count against ``engine``."""
    counts = {}
    with _client() as client:
        for name, path in ENDPOINTS.items():
            # One unmeasured call first, so a lazily built cache costs nothing.
            assert client.get(path).status_code == 200, name
            with count_statements(engine) as counter:
                response = client.get(path)
            assert response.status_code == 200, "%s returned %s" % (name, response.status_code)
            counts[name] = counter.count
    return counts


def test_counter_counts_each_statement_once(tmp_path):
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///%s" % (tmp_path / "count.db"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (n INTEGER)"))
    with count_statements(engine) as counter:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO t VALUES (1)"))
            conn.execute(text("INSERT INTO t VALUES (:n)"), [{"n": 2}, {"n": 3}])
            conn.execute(text("SELECT n FROM t")).all()
    # The executemany batch is one round trip; BEGIN and COMMIT are not statements.
    assert counter.count == 3
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    assert counter.count == 3, "counting stops when the block exits"


def test_every_endpoint_has_a_budget():
    assert set(BUDGETS) == set(ENDPOINTS)


def test_endpoints_stay_within_budget_and_flat_with_library_size(library_db):
    small = measure(library_db(SMALL))
    large = measure(library_db(LARGE))

    over = [
        "over budget: %s ran %d statements, budget %d" % (name, count, BUDGETS[name])
        for name, count in small.items()
        if count > BUDGETS[name]
    ]
    grew = [
        "grows with library size (an N+1): %s ran %d statements at %d series and %d at %d series"
        % (name, small[name], SMALL["series"], large[name], LARGE["series"])
        for name in ENDPOINTS
        if large[name] != small[name]
    ]
    problems = over + grew
    assert not problems, "\n".join(problems)
