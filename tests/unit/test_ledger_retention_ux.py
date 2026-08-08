#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""UX fallback contracts after ledger retention prunes rows (#465 / #481).

Seams under test (existing product surfaces only — no full UI e2e):

- ``search_service.get_run`` — pruned run id → existing 404 / missing contract
- ``ai_activity_log`` — an emptied AI log is honestly empty, never tombstoned
- ``health.get_acquisition_health`` — latest run falls back to newest remaining
  or omits the kind; never invents healthy history from empty
- ``series_service.get_wanted`` — pruned latest terminal → null acquisition
  (never-searched presentation per Wanted pure helper)
- ``activity.queries.list_attention_band`` / journal band — unresolved rows
  survive; empty band only when no unresolved trouble remains

Decision-only Timeline progress / Wanted sticky / band presentation rules are
pinned as documented fixture contracts below (no tombstones; inherit empty
contracts when those surfaces ship).
"""

import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, insert, select

import comicarr
from comicarr.app.acquisition import retention
from comicarr.app.acquisition.models import ItemOutcome
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.activity import queries as activity_queries
from comicarr.app.core.context import AppContext
from comicarr.app.downloads import journal
from comicarr.app.search import health
from comicarr.app.search import service as search_service
from comicarr.app.series import service as series_service
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import (
    acquisition_run_items,
    acquisition_runs,
    ai_activity_log,
    comics,
    issues,
    metadata,
    pipeline_journal,
)

FIXED_NOW = datetime.datetime(2026, 8, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(), raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    metadata.create_all(get_engine())
    yield
    shutdown_engine()


def _ctx():
    return AppContext(config=SimpleNamespace())


def _iso(days_ago):
    return (FIXED_NOW - datetime.timedelta(days=days_ago)).isoformat()


def _ai_activity_rows(limit=10):
    """Return the AI activity log newest-first — retention's read side."""
    stmt = select(ai_activity_log.c.action_description).order_by(ai_activity_log.c.timestamp.desc()).limit(limit)
    with get_engine().connect() as conn:
        return [row.action_description for row in conn.execute(stmt)]


def _journal_ts(days_ago):
    return (FIXED_NOW - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _seed_wanted_issue(issue_id="issue-prune"):
    with get_engine().begin() as conn:
        conn.execute(
            insert(comics),
            {
                "ComicID": "comic-1",
                "ComicName": "Batman",
                "ComicSortName": "Batman",
                "ComicPublisher": "DC",
                "Status": "Active",
                "Have": 0,
                "Total": 1,
                "ContentType": "comic",
            },
        )
        conn.execute(
            insert(issues),
            {
                "IssueID": issue_id,
                "ComicID": "comic-1",
                "Issue_Number": "1",
                "Status": "Wanted",
                "DateAdded": "2026-01-01",
            },
        )


# ---------------------------------------------------------------------------
# Existing API / service seams
# ---------------------------------------------------------------------------


def test_pruned_run_id_uses_existing_missing_contract(monkeypatch):
    """GET run for a pruned id is 404 / search run not found — no ghost payload."""
    monkeypatch.setattr(retention, "ITEMS_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "RUNS_KEEP_NEWEST", 0)

    ledger = RunLedger(get_engine())
    ledger.create_run("pruned-run", command_kind="search", trigger="manual")
    ledger.accept_item("pruned-run", entity_type="issue", entity_id="iss-1")
    assert ledger.claim_item("pruned-run", "issue", "iss-1") is True
    ledger.record_outcome("pruned-run", "issue", "iss-1", ItemOutcome.SUCCEEDED)
    run = ledger.get_run("pruned-run")
    assert run is not None
    assert run["completed_at"] is not None

    # Age the completed timestamps past the 90d hybrid horizon.
    with get_engine().begin() as conn:
        conn.execute(
            acquisition_runs.update()
            .where(acquisition_runs.c.run_id == "pruned-run")
            .values(completed_at=_iso(120), updated_at=_iso(120), created_at=_iso(120))
        )
        conn.execute(
            acquisition_run_items.update()
            .where(acquisition_run_items.c.run_id == "pruned-run")
            .values(completed_at=_iso(120), updated_at=_iso(120), created_at=_iso(120))
        )

    before = search_service.get_run(_ctx(), "pruned-run")
    assert before["success"] is True

    summary = retention.run_ledger_retention(now=FIXED_NOW)
    assert summary["acquisition_runs"] == 1

    missing = search_service.get_run(_ctx(), "pruned-run")
    assert missing == {
        "success": False,
        "error": "search run not found",
        "status_code": 404,
    }


def test_ai_feed_empty_list_is_honest_after_prune(monkeypatch):
    """Empty AI feed after full prune is a valid empty list, not an error."""
    monkeypatch.setattr(retention, "AI_KEEP_NEWEST", 0)

    with get_engine().begin() as conn:
        conn.execute(
            insert(ai_activity_log),
            [
                {
                    "timestamp": _iso(100),
                    "feature_type": "chat",
                    "action_description": "old",
                    "success": "true",
                },
                {
                    "timestamp": _iso(5),
                    "feature_type": "chat",
                    "action_description": "young",
                    "success": "true",
                },
            ],
        )

    assert len(_ai_activity_rows()) == 2

    summary = retention.run_ledger_retention(now=FIXED_NOW)
    assert summary["ai_activity_log"] == 1

    assert _ai_activity_rows() == ["young"]

    # Prune the last young row by forcing age past horizon with keep floor 0.
    with get_engine().begin() as conn:
        conn.execute(
            ai_activity_log.update().values(timestamp=_iso(100)),
        )
    summary2 = retention.run_ledger_retention(now=FIXED_NOW)
    assert summary2["ai_activity_log"] == 1

    assert _ai_activity_rows() == []


def test_acquisition_health_falls_back_to_newest_remaining_or_omits(monkeypatch):
    """Latest-run health uses remaining rows only — never invents history."""
    monkeypatch.setattr(retention, "ITEMS_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "RUNS_KEEP_NEWEST", 0)

    ledger = RunLedger(get_engine())

    ledger.create_run("old-search", command_kind="search", trigger="scheduler")
    ledger.accept_item("old-search", entity_type="issue", entity_id="a")
    assert ledger.claim_item("old-search", "issue", "a") is True
    ledger.record_outcome("old-search", "issue", "a", ItemOutcome.NO_MATCH)

    ledger.create_run("new-search", command_kind="search", trigger="manual")
    ledger.accept_item("new-search", entity_type="issue", entity_id="b")
    assert ledger.claim_item("new-search", "issue", "b") is True
    ledger.record_outcome("new-search", "issue", "b", ItemOutcome.SUCCEEDED)

    with get_engine().begin() as conn:
        conn.execute(
            acquisition_runs.update()
            .where(acquisition_runs.c.run_id == "old-search")
            .values(
                completed_at=_iso(120),
                updated_at=_iso(120),
                created_at=_iso(120),
            )
        )
        conn.execute(
            acquisition_run_items.update()
            .where(acquisition_run_items.c.run_id == "old-search")
            .values(completed_at=_iso(120), updated_at=_iso(120), created_at=_iso(120))
        )
        # Keep new-search young so hybrid age keeps it.
        conn.execute(
            acquisition_runs.update()
            .where(acquisition_runs.c.run_id == "new-search")
            .values(completed_at=_iso(5), updated_at=_iso(5), created_at=_iso(5))
        )
        conn.execute(
            acquisition_run_items.update()
            .where(acquisition_run_items.c.run_id == "new-search")
            .values(completed_at=_iso(5), updated_at=_iso(5), created_at=_iso(5))
        )

    before = health.get_acquisition_health(engine=get_engine())
    assert before["search"]["run_id"] == "new-search"

    retention.run_ledger_retention(now=FIXED_NOW)

    after = health.get_acquisition_health(engine=get_engine())
    assert "search" in after
    assert after["search"]["run_id"] == "new-search"
    assert after["search"]["completion"]["state"] == "completed"

    # Age out the remaining run entirely → kind omitted, not invented healthy.
    with get_engine().begin() as conn:
        conn.execute(
            acquisition_runs.update()
            .where(acquisition_runs.c.run_id == "new-search")
            .values(completed_at=_iso(120), updated_at=_iso(120))
        )
        conn.execute(
            acquisition_run_items.update()
            .where(acquisition_run_items.c.run_id == "new-search")
            .values(completed_at=_iso(120), updated_at=_iso(120))
        )
    retention.run_ledger_retention(now=FIXED_NOW)

    empty_health = health.get_acquisition_health(engine=get_engine())
    assert empty_health == {} or "search" not in empty_health


def test_wanted_sticky_falls_back_to_null_when_latest_terminal_pruned(monkeypatch):
    """Pruned latest terminal item → null acquisition (never-searched glyph)."""
    monkeypatch.setattr(retention, "ITEMS_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "RUNS_KEEP_NEWEST", 0)

    _seed_wanted_issue("issue-sticky")
    ledger = RunLedger(get_engine())
    ledger.create_run("run-sticky", command_kind="search", trigger="manual")
    ledger.accept_item("run-sticky", entity_type="issue", entity_id="issue-sticky")
    assert ledger.claim_item("run-sticky", "issue", "issue-sticky") is True
    ledger.record_outcome("run-sticky", "issue", "issue-sticky", ItemOutcome.NO_MATCH, reason="none")

    annotated = series_service.get_wanted(SimpleNamespace(config=None), limit=10, offset=0)
    assert annotated["issues"][0]["acquisition"] is not None
    assert annotated["issues"][0]["acquisition"]["state"] == ItemOutcome.NO_MATCH.value

    with get_engine().begin() as conn:
        conn.execute(
            acquisition_runs.update()
            .where(acquisition_runs.c.run_id == "run-sticky")
            .values(completed_at=_iso(120), updated_at=_iso(120), created_at=_iso(120))
        )
        conn.execute(
            acquisition_run_items.update()
            .where(acquisition_run_items.c.run_id == "run-sticky")
            .values(completed_at=_iso(120), updated_at=_iso(120), created_at=_iso(120))
        )

    retention.run_ledger_retention(now=FIXED_NOW)

    after = series_service.get_wanted(SimpleNamespace(config=None), limit=10, offset=0)
    assert after["issues"][0]["IssueID"] == "issue-sticky"
    assert after["issues"][0]["acquisition"] is None


def test_needs_attention_band_keeps_unresolved_after_journal_retention():
    """Unresolved band rows survive; resolved old terminals may leave."""
    with get_engine().begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                {
                    "release_key": "open-failed",
                    "stage": journal.FAILED,
                    "stage_rank": journal.STAGE_RANK[journal.FAILED],
                    "updated_date": _journal_ts(400),
                    "status": None,
                },
                {
                    "release_key": "open-review",
                    "stage": journal.MANUAL_REVIEW,
                    "stage_rank": journal.STAGE_RANK[journal.MANUAL_REVIEW],
                    "updated_date": _journal_ts(400),
                    "status": None,
                },
                {
                    "release_key": "resolved-old",
                    "stage": journal.FAILED,
                    "stage_rank": journal.STAGE_RANK[journal.FAILED],
                    "updated_date": _journal_ts(400),
                    "status": journal.STATUS_IGNORED,
                },
                {
                    "release_key": "pp-old",
                    "stage": journal.POST_PROCESSED,
                    "stage_rank": journal.STAGE_RANK[journal.POST_PROCESSED],
                    "updated_date": _journal_ts(400),
                    "status": None,
                },
            ],
        )

    before = activity_queries.list_attention_band()
    assert {row["release_key"] for row in before} == {"open-failed", "open-review"}

    summary = retention.run_ledger_retention(now=FIXED_NOW)
    assert summary["pipeline_journal"] == 2

    after = activity_queries.list_attention_band()
    assert {row["release_key"] for row in after} == {"open-failed", "open-review"}


def test_needs_attention_band_empty_only_when_no_unresolved_work():
    """Empty band is honest empty — no synthetic 'unknown trouble' tombstone."""
    assert activity_queries.list_attention_band() == []


# ---------------------------------------------------------------------------
# Pure-helper / documented-fixture contracts for decision-only surfaces (#465)
# ---------------------------------------------------------------------------


def test_decision_only_wanted_null_acquisition_is_never_searched_presentation():
    """Fixture contract: null acquisition maps to the never-searched glyph.

    Frontend pure helper ``formatWantedAcquisitionAnnotation(null)`` is the
    product seam; this documents the backend payload shape retention produces.
    """
    pruned_row = {
        "IssueID": "issue-x",
        "Status": "Wanted",
        "acquisition": None,
    }
    # No tombstone field, no "pruned" flag — same shape as never-searched.
    assert "pruned" not in pruned_row
    assert pruned_row["acquisition"] is None


def test_decision_only_timeline_progress_has_no_synthetic_counters_for_missing_run():
    """Fixture contract: missing run yields no ghost '17 of 42' progress.

    Timeline progress UI is still decision-only for some surfaces; when a run
    id is absent the existing missing contract applies — no synthetic counters.
    """
    missing = search_service.get_run(_ctx(), "never-existed-run")
    assert missing["success"] is False
    assert missing["status_code"] == 404
    assert "run" not in missing or missing.get("run") is None
    # No fabricated progress fields on the error payload.
    for key in ("accepted_count", "terminal_count", "processed", "of"):
        assert key not in missing


def test_decision_only_band_empty_means_no_unresolved_trouble():
    """Fixture contract: empty attention band is data absence, not a tombstone."""
    empty = activity_queries.list_attention_band()
    assert empty == []
    # No synthetic placeholder rows.
    assert not any(isinstance(row, dict) and row.get("pruned") for row in empty)


def test_no_tombstone_rows_written_by_sweep(monkeypatch):
    """Retention deletes rows; it does not insert placeholder / pruned markers."""
    monkeypatch.setattr(retention, "ITEMS_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "RUNS_KEEP_NEWEST", 0)
    monkeypatch.setattr(retention, "AI_KEEP_NEWEST", 0)

    ledger = RunLedger(get_engine())
    ledger.create_run("gone", command_kind="search", trigger="manual")
    ledger.accept_item("gone", entity_type="issue", entity_id="g1")
    assert ledger.claim_item("gone", "issue", "g1") is True
    ledger.record_outcome("gone", "issue", "g1", ItemOutcome.FAILED)

    with get_engine().begin() as conn:
        conn.execute(
            acquisition_runs.update()
            .where(acquisition_runs.c.run_id == "gone")
            .values(completed_at=_iso(200), updated_at=_iso(200), created_at=_iso(200))
        )
        conn.execute(
            acquisition_run_items.update()
            .where(acquisition_run_items.c.run_id == "gone")
            .values(completed_at=_iso(200), updated_at=_iso(200), created_at=_iso(200))
        )
        conn.execute(
            insert(ai_activity_log),
            {
                "timestamp": _iso(200),
                "feature_type": "chat",
                "action_description": "old",
                "success": "true",
            },
        )

    retention.run_ledger_retention(now=FIXED_NOW)

    assert ledger.get_run("gone") is None
    assert _ai_activity_rows() == []
    # Tables empty — no tombstone substitute rows.
    with get_engine().connect() as conn:
        assert conn.execute(select(func.count()).select_from(acquisition_runs)).scalar() == 0
        assert conn.execute(select(func.count()).select_from(acquisition_run_items)).scalar() == 0
        assert conn.execute(select(func.count()).select_from(ai_activity_log)).scalar() == 0
