#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Activity event write facade (#479).

Seams under test (public facade only):

* ``record_activity`` — durable insert; co-commit when ``conn`` is supplied
* ``publish_activity`` — best-effort ``activity`` SSE after commit
* journal ``won`` gate — no write / no publish when the transition lost
* legal-cell rejection and ``reason_code`` invariant
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

import comicarr
from comicarr.app.core import db
from comicarr.app.core.tables import activity_events, metadata


@pytest.fixture
def activity_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


@pytest.fixture
def mock_event_bus(monkeypatch):
    bus = MagicMock(name="event_bus")
    bus.publish_sync.return_value = True
    runtime = SimpleNamespace(event_bus=bus, disposed=False)
    monkeypatch.setattr(
        "comicarr.app.activity.events.get_runtime_if_initialized",
        lambda: runtime,
    )
    return bus


def _count_events(engine):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(activity_events)).scalar_one()


def _all_events(engine):
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(select(activity_events)).all()]


# ---------------------------------------------------------------------------
# Own-transaction write + post-commit publish
# ---------------------------------------------------------------------------


def test_record_activity_owns_transaction_and_publishes_after_commit(activity_db, mock_event_bus):
    from comicarr.app.activity.events import record_activity

    row = record_activity(
        activity="import",
        status="succeeded",
        subject_type="issue",
        subject_id="iss-1",
        subject_label="Saga #1",
        release_key="iss-1|ddl",
        parent_series_id="series-1",
        provider="DDL",
    )

    assert row is not None
    assert row["event_id"] is not None
    assert row["activity"] == "import"
    assert row["status"] == "succeeded"
    assert row["subject_type"] == "issue"
    assert row["subject_id"] == "iss-1"
    assert row["subject_label"] == "Saga #1"
    assert row["release_key"] == "iss-1|ddl"
    assert row["parent_series_id"] == "series-1"
    assert row["provider"] == "DDL"
    assert "created_at" in row and row["created_at"]

    assert _count_events(activity_db) == 1
    mock_event_bus.publish_sync.assert_called_once_with("activity", row)


def test_record_activity_does_not_publish_when_insert_would_not_be_durable(activity_db, mock_event_bus, monkeypatch):
    """Publish must not fire if the owned write fails (invert ai log_activity bug)."""
    from comicarr.app.activity import events

    def boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(events, "_insert_row", boom)

    row = events.record_activity(
        activity="add",
        status="succeeded",
        subject_type="series",
        subject_id="s-1",
        subject_label="Saga",
    )

    assert row is None
    assert _count_events(activity_db) == 0
    mock_event_bus.publish_sync.assert_not_called()


# ---------------------------------------------------------------------------
# Co-commit with caller transaction
# ---------------------------------------------------------------------------


def test_record_activity_co_commits_on_caller_conn_without_publishing(activity_db, mock_event_bus):
    from comicarr.app.activity.events import publish_activity, record_activity

    with activity_db.begin() as conn:
        row = record_activity(
            activity="import",
            status="started",
            subject_type="issue",
            subject_id="iss-2",
            subject_label="Saga #2",
            release_key="iss-2|nzb",
            conn=conn,
        )
        # Still open: publish must wait for the caller's commit.
        mock_event_bus.publish_sync.assert_not_called()
        assert row is not None
        assert row["event_id"] is not None

    # After commit the row is durable; caller publishes.
    assert _count_events(activity_db) == 1
    publish_activity(row)
    mock_event_bus.publish_sync.assert_called_once_with("activity", row)


def test_record_activity_rolls_back_with_caller_transaction(activity_db, mock_event_bus):
    from comicarr.app.activity.events import record_activity

    try:
        with activity_db.begin() as conn:
            record_activity(
                activity="grab",
                status="succeeded",
                subject_type="issue",
                subject_id="iss-3",
                subject_label="Saga #3",
                provider="NZBGeek",
                conn=conn,
            )
            raise RuntimeError("caller aborted")
    except RuntimeError:
        pass

    assert _count_events(activity_db) == 0
    mock_event_bus.publish_sync.assert_not_called()


def test_record_activity_propagates_insert_failure_on_caller_conn(activity_db, mock_event_bus, monkeypatch):
    """Co-commit insert failures must reach the caller, not be swallowed.

    The caller owns the transaction; a masked failure would poison it and
    resurface as an unrelated error at their next statement or commit().
    """
    from comicarr.app.activity import events

    def _boom(conn, values):
        raise RuntimeError("insert exploded")

    monkeypatch.setattr(events, "_insert_row", _boom)

    with activity_db.begin() as conn:
        with pytest.raises(RuntimeError, match="insert exploded"):
            events.record_activity(
                activity="grab",
                status="succeeded",
                subject_type="issue",
                subject_id="iss-9",
                subject_label="Saga #9",
                provider="NZBGeek",
                conn=conn,
            )

    assert _count_events(activity_db) == 0
    mock_event_bus.publish_sync.assert_not_called()


def test_record_activity_swallows_insert_failure_on_owned_transaction(activity_db, mock_event_bus, monkeypatch):
    """Owned-transaction path stays best-effort: it rolls back and returns None."""
    from comicarr.app.activity import events

    def _boom(conn, values):
        raise RuntimeError("insert exploded")

    monkeypatch.setattr(events, "_insert_row", _boom)

    row = events.record_activity(
        activity="grab",
        status="succeeded",
        subject_type="issue",
        subject_id="iss-10",
        subject_label="Saga #10",
        provider="NZBGeek",
    )

    assert row is None
    assert _count_events(activity_db) == 0
    mock_event_bus.publish_sync.assert_not_called()


# ---------------------------------------------------------------------------
# Journal won gate
# ---------------------------------------------------------------------------


def test_record_activity_noops_when_journal_won_is_false(activity_db, mock_event_bus):
    from comicarr.app.activity.events import record_activity

    row = record_activity(
        activity="import",
        status="succeeded",
        subject_type="issue",
        subject_id="iss-4",
        subject_label="Saga #4",
        release_key="iss-4|ddl",
        won=False,
    )

    assert row is None
    assert _count_events(activity_db) == 0
    mock_event_bus.publish_sync.assert_not_called()


def test_record_activity_writes_when_won_is_true(activity_db, mock_event_bus):
    from comicarr.app.activity.events import record_activity

    row = record_activity(
        activity="download",
        status="succeeded",
        subject_type="issue",
        subject_id="iss-5",
        subject_label="Saga #5",
        release_key="iss-5|ddl",
        won=True,
    )

    assert row is not None
    assert _count_events(activity_db) == 1
    mock_event_bus.publish_sync.assert_called_once()


# ---------------------------------------------------------------------------
# Legal cells
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "activity,status,subject_type",
    [
        ("search", "no_match", "issue"),  # dropped per #427
        ("search", "blocked", "run"),  # dropped per ADR
        ("search", "retrying", "issue"),  # retrying withdrawn
        ("download", "started", "issue"),  # no download.started
        ("grab", "started", "issue"),
        ("system", "succeeded", "series"),  # no system activity
        ("tag", "succeeded", "run"),  # tag only @ issue|series
        ("import", "succeeded", "series"),  # import is issue/annual
    ],
)
def test_record_activity_rejects_illegal_cells(activity_db, mock_event_bus, activity, status, subject_type):
    from comicarr.app.activity.events import record_activity

    kwargs = {
        "activity": activity,
        "status": status,
        "subject_type": subject_type,
        "subject_id": "x-1",
        "subject_label": "X",
    }
    if activity in ("download", "import"):
        kwargs["release_key"] = "x-1|p"
    if status in ("failed", "blocked", "needs_attention", "retrying"):
        kwargs["reason_code"] = "test_reason"

    row = record_activity(**kwargs)

    assert row is None
    assert _count_events(activity_db) == 0
    mock_event_bus.publish_sync.assert_not_called()


@pytest.mark.parametrize(
    "activity,status,subject_type,extra",
    [
        ("search", "succeeded", "run", {"run_id": "run-1", "scope_type": "series", "scope_id": "s-1"}),
        ("grab", "cancelled", "series", {"provider": "DDL", "reason_code": None}),
        ("tag", "needs_attention", "issue", {"reason_code": "corrupt_archive"}),
        ("refresh", "succeeded", "arc", {}),
        ("download", "cancelled", "issue", {"release_key": "iss|p", "reason_code": "ignored_by_operator"}),
        ("import", "cancelled", "issue", {"release_key": "iss|p", "reason_code": "ignored_by_operator"}),
    ],
)
def test_record_activity_accepts_blessed_cells(activity_db, mock_event_bus, activity, status, subject_type, extra):
    from comicarr.app.activity.events import record_activity

    row = record_activity(
        activity=activity,
        status=status,
        subject_type=subject_type,
        subject_id="id-1",
        subject_label="Label",
        **extra,
    )

    assert row is not None
    assert row["activity"] == activity
    assert row["status"] == status
    assert row["subject_type"] == subject_type
    mock_event_bus.publish_sync.assert_called_once()


# ---------------------------------------------------------------------------
# reason_code invariant (severity pure function of status)
# ---------------------------------------------------------------------------


def test_reason_code_required_when_severity_not_normal(activity_db, mock_event_bus):
    from comicarr.app.activity.events import record_activity, severity_for

    assert severity_for("failed") == "action_required"
    assert severity_for("succeeded") == "normal"

    row = record_activity(
        activity="import",
        status="failed",
        subject_type="issue",
        subject_id="iss-f",
        subject_label="Saga #F",
        release_key="iss-f|ddl",
        # reason_code omitted
    )

    assert row is None
    assert _count_events(activity_db) == 0
    mock_event_bus.publish_sync.assert_not_called()


def test_reason_code_accepted_for_action_required(activity_db, mock_event_bus):
    from comicarr.app.activity.events import record_activity

    row = record_activity(
        activity="import",
        status="failed",
        subject_type="issue",
        subject_id="iss-f2",
        subject_label="Saga #F2",
        release_key="iss-f2|ddl",
        reason_code="import_failed",
        reason_detail="permission denied",
    )

    assert row is not None
    assert row["reason_code"] == "import_failed"
    assert row["reason_detail"] == "permission denied"
    mock_event_bus.publish_sync.assert_called_once()


def test_reason_code_optional_for_normal_severity(activity_db, mock_event_bus):
    from comicarr.app.activity.events import record_activity

    row = record_activity(
        activity="add",
        status="succeeded",
        subject_type="series",
        subject_id="s-9",
        subject_label="Saga",
    )

    assert row is not None
    assert row.get("reason_code") is None


# ---------------------------------------------------------------------------
# Field contract extras
# ---------------------------------------------------------------------------


def test_download_and_import_require_release_key(activity_db, mock_event_bus):
    from comicarr.app.activity.events import record_activity

    assert (
        record_activity(
            activity="download",
            status="succeeded",
            subject_type="issue",
            subject_id="iss-r",
            subject_label="Saga #R",
        )
        is None
    )
    assert (
        record_activity(
            activity="import",
            status="started",
            subject_type="issue",
            subject_id="iss-r",
            subject_label="Saga #R",
        )
        is None
    )
    assert _count_events(activity_db) == 0
    mock_event_bus.publish_sync.assert_not_called()


def test_run_id_only_valid_for_search(activity_db, mock_event_bus):
    from comicarr.app.activity.events import record_activity

    assert (
        record_activity(
            activity="grab",
            status="succeeded",
            subject_type="issue",
            subject_id="iss-1",
            subject_label="Saga #1",
            provider="NZBGeek",
            run_id="run-should-not-apply",
        )
        is None
    )
    assert _count_events(activity_db) == 0


def test_grab_requires_provider(activity_db, mock_event_bus):
    from comicarr.app.activity.events import record_activity

    assert (
        record_activity(
            activity="grab",
            status="succeeded",
            subject_type="issue",
            subject_id="iss-1",
            subject_label="Saga #1",
        )
        is None
    )
    assert _count_events(activity_db) == 0


def test_scope_fields_only_on_run_subjects(activity_db, mock_event_bus):
    from comicarr.app.activity.events import record_activity

    assert (
        record_activity(
            activity="add",
            status="succeeded",
            subject_type="series",
            subject_id="s-1",
            subject_label="Saga",
            scope_type="series",
            scope_id="s-1",
        )
        is None
    )
    assert _count_events(activity_db) == 0


def test_publish_activity_is_best_effort_without_runtime(activity_db, monkeypatch):
    from comicarr.app.activity.events import publish_activity, record_activity

    monkeypatch.setattr(
        "comicarr.app.activity.events.get_runtime_if_initialized",
        lambda: None,
    )

    row = record_activity(
        activity="add",
        status="succeeded",
        subject_type="arc",
        subject_id="arc-1",
        subject_label="Infinity Gauntlet",
        # own-txn path will try publish after insert; runtime missing → swallow
    )
    # When runtime is missing during record_activity own-txn publish, row still
    # persists (best-effort publish never undoes durability).
    assert row is not None
    assert _count_events(activity_db) == 1

    # Explicit publish with no bus is also a quiet no-op.
    assert publish_activity(row) is False


def test_publish_activity_never_announces_empty_payload(mock_event_bus):
    from comicarr.app.activity.events import publish_activity

    assert publish_activity(None) is False
    assert publish_activity({}) is False
    mock_event_bus.publish_sync.assert_not_called()


def test_persists_denorm_and_conditional_fields(activity_db, mock_event_bus):
    from comicarr.app.activity.events import record_activity

    row = record_activity(
        activity="search",
        status="succeeded",
        subject_type="run",
        subject_id="run-42",
        subject_label="Wanted search",
        run_id="run-42",
        scope_type="series",
        scope_id="series-9",
        parent_series_id="series-9",
        provider=None,
    )

    stored = _all_events(activity_db)[0]
    assert stored["run_id"] == "run-42"
    assert stored["scope_type"] == "series"
    assert stored["scope_id"] == "series-9"
    assert stored["parent_series_id"] == "series-9"
    assert stored["subject_label"] == "Wanted search"
    assert row["event_id"] == stored["event_id"]
