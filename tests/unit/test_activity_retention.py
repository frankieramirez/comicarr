#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Activity narrative table 90-day retention (#489)."""

import datetime

import pytest
from sqlalchemy import insert, select

from comicarr.app.activity.retention import (
    JOB_ID,
    JOB_NAME,
    RETENTION_DAYS,
    purge_expired_activity_events,
)
from comicarr.app.core import runtime
from comicarr.app.core.db import get_engine, shutdown_engine
from comicarr.app.core.tables import activity_events, metadata
from comicarr.app.system import service as system_service


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "data_dir", str(tmp_path))
    monkeypatch.setattr(runtime.current(), "config", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    metadata.create_all(get_engine())
    yield
    shutdown_engine()


def _iso(days_ago, *, now):
    return (now - datetime.timedelta(days=days_ago)).isoformat()


def _insert_event(created_at, *, subject_id="sub-1"):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            insert(activity_events).values(
                created_at=created_at,
                activity="search",
                status="succeeded",
                subject_type="series",
                subject_id=subject_id,
                subject_label="Test Series",
            )
        )


def _remaining_subject_ids():
    with get_engine().connect() as conn:
        rows = conn.execute(select(activity_events.c.subject_id)).all()
    return {row.subject_id for row in rows}


def test_purge_deletes_rows_older_than_retention_window():
    now = datetime.datetime(2026, 8, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    _insert_event(_iso(91, now=now), subject_id="old-91")
    _insert_event(_iso(100, now=now), subject_id="old-100")
    _insert_event(_iso(1, now=now), subject_id="recent-1")

    deleted = purge_expired_activity_events(now=now)

    assert deleted == 2
    assert _remaining_subject_ids() == {"recent-1"}


def test_purge_keeps_recent_and_exact_cutoff_rows():
    """Age predicate is strict less-than: created_at == cutoff is kept."""
    now = datetime.datetime(2026, 8, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    cutoff = (now - datetime.timedelta(days=RETENTION_DAYS)).isoformat()
    _insert_event(cutoff, subject_id="exactly-90")
    _insert_event(_iso(89, now=now), subject_id="recent-89")
    _insert_event(_iso(0, now=now), subject_id="today")
    _insert_event(_iso(91, now=now), subject_id="old-91")

    deleted = purge_expired_activity_events(now=now)

    assert deleted == 1
    assert _remaining_subject_ids() == {"exactly-90", "recent-89", "today"}


def test_purge_does_not_touch_empty_table():
    deleted = purge_expired_activity_events(now=datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc))
    assert deleted == 0
    assert _remaining_subject_ids() == set()


def test_scheduler_job_name_matches_retention_module():
    assert JOB_ID == "activity_retention"
    assert system_service.SCHEDULER_JOB_NAMES[JOB_ID] == JOB_NAME
