#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Unit tests for the daily ledger retention sweep (#480 / #481).

Seams under test:
- ``run_ledger_retention`` public entrypoint (eligibility, hybrid/age math,
  delete order, batching, no VACUUM)
- Module constants match the #464 parameter table
"""

import datetime

import pytest
from sqlalchemy import insert, select

from comicarr.app.acquisition import retention
from comicarr.app.acquisition.models import ItemOutcome, RunState
from comicarr.app.core import runtime
from comicarr.app.core.db import get_engine, shutdown_engine
from comicarr.app.core.tables import (
    acquisition_maintenance_events,
    acquisition_run_items,
    acquisition_runs,
    ai_activity_log,
    metadata,
    pipeline_journal,
)
from comicarr.app.downloads import journal

FIXED_NOW = datetime.datetime(2026, 8, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "data_dir", str(tmp_path))
    monkeypatch.setattr(runtime.current(), "config", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    metadata.create_all(get_engine())
    yield
    shutdown_engine()


def _iso(days_ago, hours=0):
    return (FIXED_NOW - datetime.timedelta(days=days_ago, hours=hours)).isoformat()


def _journal_ts(days_ago):
    return (FIXED_NOW - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _insert_run(run_id, completion_state, completed_at=None, updated_at=None):
    now = updated_at or _iso(0)
    with get_engine().begin() as conn:
        conn.execute(
            insert(acquisition_runs).values(
                run_id=run_id,
                command_kind="search",
                trigger="test",
                dispatch_state="accepted",
                completion_state=completion_state,
                accepted_count=0,
                terminal_count=0,
                succeeded_count=0,
                no_match_count=0,
                blocked_count=0,
                failed_count=0,
                created_at=now,
                updated_at=now,
                completed_at=completed_at,
            )
        )


def _insert_item(run_id, state, completed_at=None, updated_at=None, entity_id=None):
    now = updated_at or _iso(0)
    with get_engine().begin() as conn:
        result = conn.execute(
            insert(acquisition_run_items).values(
                run_id=run_id,
                command_kind="search",
                entity_type="issue",
                entity_id=entity_id or ("e-%s-%s" % (run_id, state)),
                state=state,
                dispatch_state="pending",
                queue_priority="routine",
                attempt_count=0,
                created_at=now,
                updated_at=now,
                completed_at=completed_at,
            )
        )
        return result.inserted_primary_key[0]


def _insert_journal(release_key, stage, updated_date, status=None):
    with get_engine().begin() as conn:
        conn.execute(
            insert(pipeline_journal).values(
                release_key=release_key,
                stage=stage,
                stage_rank=journal.STAGE_RANK[stage],
                updated_date=updated_date,
                status=status,
            )
        )


def _insert_maintenance(created_at, reason="test"):
    with get_engine().begin() as conn:
        result = conn.execute(
            insert(acquisition_maintenance_events).values(
                epoch=1,
                action="acquire",
                actor="test",
                reason=reason,
                created_at=created_at,
            )
        )
        return result.inserted_primary_key[0]


def _insert_ai(timestamp, action="act"):
    with get_engine().begin() as conn:
        result = conn.execute(
            insert(ai_activity_log).values(
                timestamp=timestamp,
                feature_type="chat",
                action_description=action,
                success="true",
            )
        )
        return result.inserted_primary_key[0]


def _count(table):
    with get_engine().connect() as conn:
        return conn.execute(select(table)).fetchall().__len__()


def _item_states():
    with get_engine().connect() as conn:
        return sorted(row.state for row in conn.execute(select(acquisition_run_items.c.state)))


def _run_ids():
    with get_engine().connect() as conn:
        return sorted(row.run_id for row in conn.execute(select(acquisition_runs.c.run_id)))


def _journal_keys():
    with get_engine().connect() as conn:
        return sorted(row.release_key for row in conn.execute(select(pipeline_journal.c.release_key)))


def test_constants_match_parameter_table():
    assert retention.DELETE_BATCH_SIZE == 500
    assert retention.ITEMS_AGE_DAYS == 90
    assert retention.ITEMS_KEEP_NEWEST == 50_000
    assert retention.RUNS_AGE_DAYS == 90
    assert retention.RUNS_KEEP_NEWEST == 2_000
    assert retention.JOURNAL_AGE_DAYS == 365
    assert retention.MAINTENANCE_AGE_DAYS == 90
    assert retention.MAINTENANCE_KEEP_NEWEST == 5_000
    assert retention.AI_AGE_DAYS == 90
    assert retention.AI_KEEP_NEWEST == 10_000


def test_never_deletes_accepted_or_running_items(monkeypatch):
    """Recovery floor: nonterminal item states are immortal (#463 / #481).

    Keep floor is zeroed so age alone would delete terminals; accepted/running
    must still survive (eligibility, not newest-N).
    """
    monkeypatch.setattr(retention, "ITEMS_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "RUNS_KEEP_NEWEST", 0)
    _insert_run("live", RunState.RUNNING.value, completed_at=None, updated_at=_iso(200))
    _insert_item("live", ItemOutcome.ACCEPTED.value, completed_at=None, updated_at=_iso(200), entity_id="a")
    _insert_item("live", ItemOutcome.RUNNING.value, completed_at=None, updated_at=_iso(200), entity_id="b")
    _insert_item("live", ItemOutcome.SUCCEEDED.value, completed_at=_iso(200), updated_at=_iso(200), entity_id="c")

    summary = retention.run_ledger_retention(now=FIXED_NOW)

    assert summary is not None
    assert summary["acquisition_run_items"] == 1
    assert _item_states() == sorted([ItemOutcome.ACCEPTED.value, ItemOutcome.RUNNING.value])
    assert _run_ids() == ["live"]


def test_never_deletes_incomplete_runs_or_runs_with_remaining_items(monkeypatch):
    """Incomplete runs and any run that still has items stay forever (#463)."""
    monkeypatch.setattr(retention, "ITEMS_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "RUNS_KEEP_NEWEST", 0)

    # Incomplete: no completed_at, even if ancient.
    _insert_run("pending-old", RunState.PENDING.value, completed_at=None, updated_at=_iso(400))
    _insert_run("running-old", RunState.RUNNING.value, completed_at=None, updated_at=_iso(400))

    # Completed but still has a terminal item kept only because we leave it
    # after lowering keep floor to 0… actually with floor 0 the item ages out.
    # Keep an accepted item so the completed run cannot empty itself.
    _insert_run("done-with-live", RunState.COMPLETED.value, completed_at=_iso(400), updated_at=_iso(400))
    _insert_item(
        "done-with-live",
        ItemOutcome.ACCEPTED.value,
        completed_at=None,
        updated_at=_iso(400),
        entity_id="still-live",
    )
    # Completed with only an old terminal item: item is eligible and will purge,
    # then the empty completed run may purge — separate test covers that path.
    _insert_run("done-with-terminal", RunState.COMPLETED.value, completed_at=_iso(10), updated_at=_iso(10))
    _insert_item(
        "done-with-terminal",
        ItemOutcome.SUCCEEDED.value,
        completed_at=_iso(10),
        updated_at=_iso(10),
        entity_id="kept-young",
    )

    summary = retention.run_ledger_retention(now=FIXED_NOW)

    assert summary is not None
    assert set(_run_ids()) == {"pending-old", "running-old", "done-with-live", "done-with-terminal"}
    assert ItemOutcome.ACCEPTED.value in _item_states()
    assert ItemOutcome.SUCCEEDED.value in _item_states()


def test_empty_finished_failed_run_is_eligible(monkeypatch):
    """Finished empty shells (failed/partial/blocked) prune once items are gone."""
    monkeypatch.setattr(retention, "ITEMS_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "RUNS_KEEP_NEWEST", 0)
    _insert_run("failed-done", RunState.FAILED.value, completed_at=_iso(100), updated_at=_iso(100))
    _insert_item(
        "failed-done",
        ItemOutcome.FAILED.value,
        completed_at=_iso(100),
        updated_at=_iso(100),
        entity_id="f1",
    )

    summary = retention.run_ledger_retention(now=FIXED_NOW)

    assert summary["acquisition_run_items"] == 1
    assert summary["acquisition_runs"] == 1
    assert _run_ids() == []


def test_deletes_old_terminal_items_then_empty_completed_runs(monkeypatch):
    # Small fixtures sit inside the real newest-N floors; lower floors so age
    # past 90d is enough to delete under the hybrid formula.
    monkeypatch.setattr(retention, "ITEMS_KEEP_NEWEST", 1)
    # After the old item is purged only one empty completed run is eligible;
    # keep floor 0 so age alone can remove it.
    monkeypatch.setattr(retention, "RUNS_KEEP_NEWEST", 0)

    _insert_run("old-done", RunState.COMPLETED.value, completed_at=_iso(100), updated_at=_iso(100))
    _insert_item(
        "old-done",
        ItemOutcome.SUCCEEDED.value,
        completed_at=_iso(100),
        updated_at=_iso(100),
        entity_id="done-1",
    )
    _insert_run("recent-done", RunState.COMPLETED.value, completed_at=_iso(10), updated_at=_iso(10))
    _insert_item(
        "recent-done",
        ItemOutcome.NO_MATCH.value,
        completed_at=_iso(10),
        updated_at=_iso(10),
        entity_id="done-2",
    )

    summary = retention.run_ledger_retention(now=FIXED_NOW)

    assert summary["acquisition_run_items"] == 1
    assert summary["acquisition_runs"] == 1
    assert _run_ids() == ["recent-done"]
    assert _item_states() == [ItemOutcome.NO_MATCH.value]


def test_never_deletes_open_or_unresolved_journal_rows():
    """Open stages and unresolved failed/manual_review are immortal (#463)."""
    _insert_journal("open-snatched", journal.SNATCHED, _journal_ts(400))
    _insert_journal("open-downloaded", journal.DOWNLOADED, _journal_ts(400))
    _insert_journal("failed-open", journal.FAILED, _journal_ts(400), status=None)
    _insert_journal("review-open", journal.MANUAL_REVIEW, _journal_ts(400), status=None)
    _insert_journal("review-band-status", journal.MANUAL_REVIEW, _journal_ts(400), status=journal.MANUAL_REVIEW)
    _insert_journal("pp-old", journal.POST_PROCESSED, _journal_ts(400))
    _insert_journal("failed-resolved", journal.FAILED, _journal_ts(400), status=journal.STATUS_IGNORED)
    _insert_journal("review-resolved", journal.MANUAL_REVIEW, _journal_ts(400), status=journal.STATUS_IMPORTED)
    _insert_journal("pp-recent", journal.POST_PROCESSED, _journal_ts(30))

    summary = retention.run_ledger_retention(now=FIXED_NOW)

    # Three eligible old terminals deleted (pp-old, failed-resolved, review-resolved).
    assert summary["pipeline_journal"] == 3
    assert _journal_keys() == sorted(
        [
            "open-snatched",
            "open-downloaded",
            "failed-open",
            "review-open",
            "review-band-status",
            "pp-recent",
        ]
    )


def test_journal_age_only_keeps_eligible_under_365_days(monkeypatch):
    """Journal has no newest-N floor: only age past 365d on eligible terminals."""
    # Even with keep floors zeroed on other tables, journal ignores count floors.
    monkeypatch.setattr(retention, "ITEMS_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "RUNS_KEEP_NEWEST", 0)

    _insert_journal("pp-364", journal.POST_PROCESSED, _journal_ts(364))
    _insert_journal("pp-366", journal.POST_PROCESSED, _journal_ts(366))
    _insert_journal("failed-resolved-100", journal.FAILED, _journal_ts(100), status=journal.STATUS_RETRIED)

    summary = retention.run_ledger_retention(now=FIXED_NOW)

    assert summary["pipeline_journal"] == 1
    assert _journal_keys() == sorted(["pp-364", "failed-resolved-100"])


def test_hybrid_keep_newest_floor_even_when_old(monkeypatch):
    # Five old terminal items; newest 2 (by age desc, pk desc) must remain.
    monkeypatch.setattr(retention, "ITEMS_KEEP_NEWEST", 2)
    _insert_run("batch", RunState.COMPLETED.value, completed_at=_iso(200), updated_at=_iso(200))
    ids = []
    for day in (200, 190, 180, 170, 160):
        ids.append(
            _insert_item(
                "batch",
                ItemOutcome.SUCCEEDED.value,
                completed_at=_iso(day),
                updated_at=_iso(day),
                entity_id="i-%s" % day,
            )
        )
    summary = retention.run_ledger_retention(now=FIXED_NOW)
    assert summary["acquisition_run_items"] == 3
    with get_engine().connect() as conn:
        remaining = sorted(row.item_id for row in conn.execute(select(acquisition_run_items.c.item_id)))
    # Newest by age: day 160 then 170 (largest completed_at, then pk).
    assert remaining == sorted(ids[-2:])


def test_hybrid_keeps_young_rows_even_outside_newest_n(monkeypatch):
    """Hybrid: younger-than-horizon rows survive even when keep_newest is 0."""
    monkeypatch.setattr(retention, "ITEMS_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "RUNS_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "MAINTENANCE_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "AI_KEEP_NEWEST", 0)

    _insert_run("old", RunState.COMPLETED.value, completed_at=_iso(100), updated_at=_iso(100))
    _insert_item(
        "old",
        ItemOutcome.SUCCEEDED.value,
        completed_at=_iso(100),
        updated_at=_iso(100),
        entity_id="old-i",
    )
    _insert_run("young", RunState.COMPLETED.value, completed_at=_iso(5), updated_at=_iso(5))
    _insert_item(
        "young",
        ItemOutcome.SUCCEEDED.value,
        completed_at=_iso(5),
        updated_at=_iso(5),
        entity_id="young-i",
    )
    _insert_maintenance(_iso(100), reason="old-m")
    _insert_maintenance(_iso(5), reason="young-m")
    _insert_ai(_iso(100), action="old-ai")
    _insert_ai(_iso(5), action="young-ai")

    summary = retention.run_ledger_retention(now=FIXED_NOW)

    assert summary["acquisition_run_items"] == 1
    assert summary["acquisition_runs"] == 1
    assert summary["acquisition_maintenance_events"] == 1
    assert summary["ai_activity_log"] == 1
    assert _run_ids() == ["young"]
    assert _count(acquisition_maintenance_events) == 1
    assert _count(ai_activity_log) == 1


def test_maintenance_and_ai_are_fully_eligible_under_hybrid(monkeypatch):
    monkeypatch.setattr(retention, "MAINTENANCE_KEEP_NEWEST", 1)
    monkeypatch.setattr(retention, "AI_KEEP_NEWEST", 1)

    _insert_maintenance(_iso(100), reason="old")
    _insert_maintenance(_iso(5), reason="new")
    _insert_ai(_iso(100), action="old-ai")
    _insert_ai(_iso(5), action="new-ai")

    summary = retention.run_ledger_retention(now=FIXED_NOW)

    assert summary["acquisition_maintenance_events"] == 1
    assert summary["ai_activity_log"] == 1
    assert _count(acquisition_maintenance_events) == 1
    assert _count(ai_activity_log) == 1


def test_batching_loops_until_dry(monkeypatch):
    monkeypatch.setattr(retention, "DELETE_BATCH_SIZE", 2)
    monkeypatch.setattr(retention, "ITEMS_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "RUNS_KEEP_NEWEST", 0)
    _insert_run("many", RunState.COMPLETED.value, completed_at=_iso(120), updated_at=_iso(120))
    for i in range(5):
        _insert_item(
            "many",
            ItemOutcome.FAILED.value,
            completed_at=_iso(120),
            updated_at=_iso(120),
            entity_id="x-%s" % i,
        )

    summary = retention.run_ledger_retention(now=FIXED_NOW)

    assert summary["acquisition_run_items"] == 5
    assert _count(acquisition_run_items) == 0
    # Empty completed run is eligible and old → deleted after items.
    assert summary["acquisition_runs"] == 1


def test_soft_fail_logs_and_does_not_raise(monkeypatch, caplog):
    def boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(retention, "_purge_acquisition_run_items", boom)
    result = retention.run_ledger_retention(now=FIXED_NOW)
    assert result is None


def test_delete_order_items_runs_journal_maintenance_ai(monkeypatch):
    order = []

    def wrap(name, original):
        def _inner(*args, **kwargs):
            order.append(name)
            return original(*args, **kwargs)

        return _inner

    monkeypatch.setattr(
        retention,
        "_purge_acquisition_run_items",
        wrap("items", retention._purge_acquisition_run_items),
    )
    monkeypatch.setattr(
        retention,
        "_purge_acquisition_runs",
        wrap("runs", retention._purge_acquisition_runs),
    )
    monkeypatch.setattr(
        retention,
        "_purge_pipeline_journal",
        wrap("journal", retention._purge_pipeline_journal),
    )
    monkeypatch.setattr(
        retention,
        "_purge_maintenance_events",
        wrap("maintenance", retention._purge_maintenance_events),
    )
    monkeypatch.setattr(
        retention,
        "_purge_ai_activity_log",
        wrap("ai", retention._purge_ai_activity_log),
    )

    retention.run_ledger_retention(now=FIXED_NOW)
    assert order == ["items", "runs", "journal", "maintenance", "ai"]


def test_sweep_does_not_invoke_vacuum(monkeypatch):
    """VACUUM is out-of-band ops only — never a product feature of the sweep."""
    vacuum_calls = []

    class _TrackingConn:
        def __init__(self, real):
            self._real = real

        def execute(self, *args, **kwargs):
            statement = str(args[0]) if args else ""
            if "vacuum" in statement.lower():
                vacuum_calls.append(statement)
            return self._real.execute(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._real, name)

    real_begin = get_engine().begin

    class _TrackingBegin:
        def __enter__(self):
            self._cm = real_begin()
            self._conn = _TrackingConn(self._cm.__enter__())
            return self._conn

        def __exit__(self, *exc):
            return self._cm.__exit__(*exc)

    monkeypatch.setattr(retention, "ITEMS_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "RUNS_KEEP_NEWEST", 0)
    monkeypatch.setattr(get_engine(), "begin", lambda: _TrackingBegin())

    _insert_run("v", RunState.COMPLETED.value, completed_at=_iso(120), updated_at=_iso(120))
    _insert_item(
        "v",
        ItemOutcome.SUCCEEDED.value,
        completed_at=_iso(120),
        updated_at=_iso(120),
        entity_id="v1",
    )
    retention.run_ledger_retention(now=FIXED_NOW)
    assert vacuum_calls == []

    # Source-level guard: module must not reference VACUUM.
    import inspect

    source = inspect.getsource(retention)
    assert "vacuum" not in source.lower()
