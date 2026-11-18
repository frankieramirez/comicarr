#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Wanted page live-sticky acquisition annotations (#490).

Pins:
- annotation comes from the latest search ``acquisition_run_items`` row only
- sticky after the run closes until a newer run supersedes it
- membership filter stays ``Status == 'Wanted'`` (Snatched never annotates in)
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import insert, update

import comicarr
from comicarr.app.acquisition.models import ItemOutcome
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.core import db, runtime
from comicarr.app.core.tables import comics, issues, metadata
from comicarr.app.series import queries as series_queries
from comicarr.app.series import service as series_service


@pytest.fixture
def wanted_db(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "data_dir", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _seed_wanted_issues(engine, issue_ids):
    with engine.begin() as conn:
        conn.execute(
            insert(comics),
            {
                "ComicID": "comic-1",
                "ComicName": "Batman",
                "ComicSortName": "Batman",
                "ComicPublisher": "DC",
                "Status": "Active",
                "Have": 0,
                "Total": len(issue_ids),
                "ContentType": "comic",
            },
        )
        conn.execute(
            insert(issues),
            [
                {
                    "IssueID": issue_id,
                    "ComicID": "comic-1",
                    "Issue_Number": str(index + 1),
                    "Status": "Wanted",
                    "DateAdded": f"2026-01-{index + 1:02d}",
                }
                for index, issue_id in enumerate(issue_ids)
            ],
        )


def test_never_searched_rows_carry_null_acquisition(wanted_db):
    _seed_wanted_issues(wanted_db, ["issue-a", "issue-b"])

    result = series_service.get_wanted(SimpleNamespace(config=None), limit=50, offset=0)

    assert result["pagination"]["total"] == 2
    assert all(row["Status"] == "Wanted" for row in result["issues"])
    assert all(row["acquisition"] is None for row in result["issues"])


def test_latest_search_item_annotates_wanted_row(wanted_db):
    _seed_wanted_issues(wanted_db, ["issue-12", "issue-13"])
    ledger = RunLedger(wanted_db)
    ledger.create_run("run-1", command_kind="search", trigger="manual")
    ledger.accept_item("run-1", entity_type="issue", entity_id="issue-12")
    assert ledger.claim_item("run-1", "issue", "issue-12") is True
    ledger.record_outcome("run-1", "issue", "issue-12", ItemOutcome.NO_MATCH, reason="providers empty")

    result = series_service.get_wanted(SimpleNamespace(config=None), limit=50, offset=0)
    by_id = {row["IssueID"]: row for row in result["issues"]}

    annotation = by_id["issue-12"]["acquisition"]
    assert annotation is not None
    assert annotation["state"] == ItemOutcome.NO_MATCH.value
    assert annotation["attempt_count"] == 1
    assert annotation["reason"] == "providers empty"
    assert annotation["run_id"] == "run-1"
    assert annotation["entity_type"] == "issue"
    assert annotation["completed_at"] is not None

    assert by_id["issue-13"]["acquisition"] is None


def test_annotation_is_sticky_after_run_closes_until_newer_run_supersedes(wanted_db):
    _seed_wanted_issues(wanted_db, ["issue-sticky"])
    ledger = RunLedger(wanted_db)

    ledger.create_run("run-old", command_kind="search", trigger="scheduler")
    ledger.accept_item("run-old", entity_type="issue", entity_id="issue-sticky")
    assert ledger.claim_item("run-old", "issue", "issue-sticky") is True
    ledger.record_outcome("run-old", "issue", "issue-sticky", ItemOutcome.NO_MATCH)
    old_run = ledger.get_run("run-old")
    # Terminal no_match closes the run; annotation must still stick on Wanted.
    assert old_run["completion_state"] == "completed"
    assert old_run["completed_at"] is not None

    after_close = series_service.get_wanted(SimpleNamespace(config=None), limit=10, offset=0)
    sticky = after_close["issues"][0]["acquisition"]
    assert sticky["run_id"] == "run-old"
    assert sticky["state"] == ItemOutcome.NO_MATCH.value
    assert sticky["attempt_count"] == 1

    ledger.create_run("run-new", command_kind="search", trigger="manual")
    ledger.accept_item("run-new", entity_type="issue", entity_id="issue-sticky")
    # Live searching annotation from the newer run must supersede the sticky no_match.
    live = series_service.get_wanted(SimpleNamespace(config=None), limit=10, offset=0)
    annotation = live["issues"][0]["acquisition"]
    assert annotation["run_id"] == "run-new"
    assert annotation["state"] == ItemOutcome.ACCEPTED.value
    assert annotation["attempt_count"] == 0

    assert ledger.claim_item("run-new", "issue", "issue-sticky") is True
    ledger.record_outcome("run-new", "issue", "issue-sticky", ItemOutcome.NO_MATCH)
    after_new_close = series_service.get_wanted(SimpleNamespace(config=None), limit=10, offset=0)
    superseded = after_new_close["issues"][0]["acquisition"]
    assert superseded["run_id"] == "run-new"
    assert superseded["state"] == ItemOutcome.NO_MATCH.value
    assert superseded["attempt_count"] == 1


def test_refresh_run_items_do_not_annotate_wanted_issues(wanted_db):
    _seed_wanted_issues(wanted_db, ["issue-refresh"])
    ledger = RunLedger(wanted_db)
    ledger.create_run("refresh-run", command_kind="refresh", trigger="manual")
    ledger.accept_item("refresh-run", entity_type="series", entity_id="issue-refresh")

    result = series_service.get_wanted(SimpleNamespace(config=None), limit=10, offset=0)
    assert result["issues"][0]["acquisition"] is None


def test_membership_filter_unchanged_snatched_not_returned(wanted_db):
    _seed_wanted_issues(wanted_db, ["issue-wanted", "issue-snatched"])
    with wanted_db.begin() as conn:
        conn.execute(update(issues).where(issues.c.IssueID == "issue-snatched").values(Status="Snatched"))

    ledger = RunLedger(wanted_db)
    ledger.create_run("run-snatch", command_kind="search", trigger="manual")
    ledger.accept_item("run-snatch", entity_type="issue", entity_id="issue-snatched")
    assert ledger.claim_item("run-snatch", "issue", "issue-snatched") is True
    ledger.record_outcome("run-snatch", "issue", "issue-snatched", ItemOutcome.SUCCEEDED)

    result = series_service.get_wanted(SimpleNamespace(config=None), limit=50, offset=0)
    assert result["pagination"]["total"] == 1
    assert [row["IssueID"] for row in result["issues"]] == ["issue-wanted"]


def test_latest_item_selection_prefers_most_recently_updated(wanted_db):
    _seed_wanted_issues(wanted_db, ["issue-order"])
    ledger = RunLedger(wanted_db)
    ledger.create_run("run-a", command_kind="search", trigger="manual")
    ledger.accept_item("run-a", entity_type="issue", entity_id="issue-order")
    assert ledger.claim_item("run-a", "issue", "issue-order") is True
    ledger.record_outcome("run-a", "issue", "issue-order", ItemOutcome.FAILED, reason="old")

    ledger.create_run("run-b", command_kind="search", trigger="manual")
    ledger.accept_item("run-b", entity_type="issue", entity_id="issue-order")
    assert ledger.claim_item("run-b", "issue", "issue-order") is True
    ledger.record_outcome("run-b", "issue", "issue-order", ItemOutcome.NO_MATCH, reason="new")

    latest = series_queries.get_latest_search_items_by_entity_ids(["issue-order"])
    assert latest["issue-order"]["run_id"] == "run-b"
    assert latest["issue-order"]["state"] == ItemOutcome.NO_MATCH.value
    assert latest["issue-order"]["reason"] == "new"


def test_live_searching_state_while_accepted_or_running(wanted_db):
    _seed_wanted_issues(wanted_db, ["issue-live"])
    ledger = RunLedger(wanted_db)
    ledger.create_run("run-live", command_kind="search", trigger="manual")
    ledger.accept_item("run-live", entity_type="issue", entity_id="issue-live")

    accepted = series_service.get_wanted(SimpleNamespace(config=None), limit=10, offset=0)
    assert accepted["issues"][0]["acquisition"]["state"] == ItemOutcome.ACCEPTED.value

    assert ledger.claim_item("run-live", "issue", "issue-live") is True
    running = series_service.get_wanted(SimpleNamespace(config=None), limit=10, offset=0)
    assert running["issues"][0]["acquisition"]["state"] == ItemOutcome.RUNNING.value
    assert running["issues"][0]["acquisition"]["attempt_count"] == 1


def test_get_latest_search_items_empty_input():
    assert series_queries.get_latest_search_items_by_entity_ids([]) == {}
    assert series_queries.get_latest_search_items_by_entity_ids(None) == {}
