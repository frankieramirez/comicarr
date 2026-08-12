#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Activity producers (#484) — journal stages, run brackets, ledger hygiene.

Seams under test:

* ``record_activity`` via journal ``record_transition`` (won-gated)
* ``emit_run_completion`` via ``RunLedger.reconcile`` / ``complete_empty_run``
* ``record_outcome`` / ``record_requeue`` redaction + ``replay`` flag
* ``fail_reason`` token-only at the DDL worker concatenating site
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

import comicarr
from comicarr import db
from comicarr.app.acquisition.models import ItemOutcome
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.downloads import journal
from comicarr.tables import activity_events, comics, issues, metadata


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


def _seed_issue(engine, *, issueid="1001", comicid="C1", name="Saga", number="1"):
    with engine.begin() as conn:
        conn.execute(
            comics.insert(),
            {
                "ComicID": comicid,
                "ComicName": name,
                "ComicYear": "2012",
                "Status": "Active",
            },
        )
        conn.execute(
            issues.insert(),
            {
                "IssueID": issueid,
                "ComicID": comicid,
                "ComicName": name,
                "Issue_Number": number,
                "Status": "Wanted",
            },
        )


def _events(engine):
    with engine.connect() as conn:
        return [
            dict(row._mapping) for row in conn.execute(select(activity_events).order_by(activity_events.c.event_id))
        ]


# ---------------------------------------------------------------------------
# Journal stage → activity (won-gated)
# ---------------------------------------------------------------------------


def test_journal_snatched_emits_grab_succeeded(activity_db, mock_event_bus):
    _seed_issue(activity_db)
    rkey = journal.release_key("1001", "NZBGeek", nzbname="Saga.001")
    won = journal.record_transition(
        rkey,
        journal.SNATCHED,
        issueid="1001",
        provider="NZBGeek",
        nzbname="Saga.001",
    )
    assert won is True
    rows = _events(activity_db)
    assert len(rows) == 1
    assert rows[0]["activity"] == "grab"
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["subject_type"] == "issue"
    assert rows[0]["subject_id"] == "1001"
    assert rows[0]["provider"] == "NZBGeek"
    assert rows[0]["release_key"] == rkey
    mock_event_bus.publish_sync.assert_called()


def test_journal_duplicate_transition_does_not_emit(activity_db, mock_event_bus):
    _seed_issue(activity_db)
    rkey = journal.release_key("1001", "NZBGeek", nzbname="Saga.001")
    assert journal.record_transition(rkey, journal.SNATCHED, issueid="1001", provider="NZBGeek") is True
    assert journal.record_transition(rkey, journal.SNATCHED, issueid="1001", provider="NZBGeek") is False
    assert len(_events(activity_db)) == 1


def test_journal_downloaded_and_post_processed_chain(activity_db, mock_event_bus):
    _seed_issue(activity_db)
    rkey = journal.release_key("1001", "DDL", nzbname="file.cbz")
    assert journal.record_transition(rkey, journal.SNATCHED, issueid="1001", provider="DDL") is True
    assert journal.record_transition(rkey, journal.DOWNLOADED, issueid="1001", provider="DDL") is True
    assert journal.record_transition(rkey, journal.POST_PROCESSING, issueid="1001", provider="DDL") is True
    assert journal.record_transition(rkey, journal.POST_PROCESSED, issueid="1001", provider="DDL") is True
    acts = [(r["activity"], r["status"]) for r in _events(activity_db)]
    assert ("grab", "succeeded") in acts
    assert ("download", "succeeded") in acts
    assert ("import", "started") in acts
    assert ("import", "succeeded") in acts


def test_journal_failed_early_is_download_failed(activity_db, mock_event_bus):
    _seed_issue(activity_db)
    rkey = journal.release_key("1001", "NZBGeek", nzbname="bad")
    journal.record_transition(rkey, journal.SNATCHED, issueid="1001", provider="NZBGeek")
    won = journal.mark_failed(rkey, "download_failed_no_auto_handling", issueid="1001", provider="NZBGeek")
    assert won is True
    fails = [r for r in _events(activity_db) if r["status"] == "failed"]
    assert len(fails) == 1
    assert fails[0]["activity"] == "download"
    assert fails[0]["reason_code"] == "download_failed_no_auto_handling"


def test_journal_failed_after_pp_is_import_failed(activity_db, mock_event_bus):
    _seed_issue(activity_db)
    rkey = journal.release_key("1001", "NZBGeek", nzbname="pp-bad")
    journal.record_transition(rkey, journal.SNATCHED, issueid="1001", provider="NZBGeek")
    journal.record_transition(rkey, journal.DOWNLOADED, issueid="1001", provider="NZBGeek")
    journal.record_transition(rkey, journal.POST_PROCESSING, issueid="1001", provider="NZBGeek")
    won = journal.mark_failed(rkey, "import_failed", issueid="1001", provider="NZBGeek")
    assert won is True
    fails = [r for r in _events(activity_db) if r["status"] == "failed"]
    assert len(fails) == 1
    assert fails[0]["activity"] == "import"


# ---------------------------------------------------------------------------
# Run completion brackets (not in-flight)
# ---------------------------------------------------------------------------


def test_empty_run_narrates_nothing_to_search(activity_db, mock_event_bus):
    ledger = RunLedger(activity_db)
    ledger.create_run("empty-1", command_kind="search", trigger="manual_wanted_scan")
    ledger.complete_empty_run("empty-1")
    rows = _events(activity_db)
    assert len(rows) == 1
    assert rows[0]["activity"] == "search"
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["subject_type"] == "run"
    assert rows[0]["reason_code"] == "nothing_to_search"
    assert "accepted" in (rows[0]["reason_detail"] or "")


def test_reconcile_completion_narrates_once_with_counts(activity_db, mock_event_bus):
    ledger = RunLedger(activity_db)
    ledger.create_run("run-1", command_kind="search", trigger="manual")
    ledger.accept_item("run-1", "issue", "a")
    ledger.accept_item("run-1", "issue", "b")
    # Still open — no completion narrative.
    assert _events(activity_db) == []
    ledger.record_outcome("run-1", "issue", "a", ItemOutcome.SUCCEEDED)
    assert _events(activity_db) == []  # still running
    ledger.record_outcome("run-1", "issue", "b", ItemOutcome.NO_MATCH)
    rows = _events(activity_db)
    assert len(rows) == 1
    assert rows[0]["activity"] == "search"
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["subject_type"] == "run"
    detail = rows[0]["reason_detail"] or ""
    assert '"accepted":2' in detail
    assert '"grabbed":1' in detail
    assert '"no_match":1' in detail
    # Re-reconcile must not double-emit.
    ledger.reconcile("run-1")
    assert len(_events(activity_db)) == 1


# ---------------------------------------------------------------------------
# Ledger hygiene
# ---------------------------------------------------------------------------


def test_record_outcome_redacts_sensitive_reason(activity_db):
    ledger = RunLedger(activity_db)
    ledger.create_run("r-redact", command_kind="refresh", trigger="t")
    ledger.accept_item(
        "r-redact",
        "series",
        "S1",
        payload={"comicid": "S1", "comicname": "X", "seriesyear": "2020"},
    )
    ledger.claim_item("r-redact", "series", "S1")
    ledger.record_outcome(
        "r-redact",
        "series",
        "S1",
        ItemOutcome.FAILED,
        reason="boom apikey=supersecretvalue123 Authorization: Bearer tokensecret99",
    )
    item = ledger.get_item("r-redact", "series", "S1")
    assert item["reason"] is not None
    assert "supersecretvalue123" not in item["reason"]
    assert "tokensecret99" not in item["reason"]
    assert "[redacted]" in item["reason"]


def test_record_requeue_accepts_replay_flag(activity_db):
    from comicarr.app.acquisition.runs import is_retry_pending

    ledger = RunLedger(activity_db)
    ledger.create_run("r-replay", command_kind="search", trigger="t")
    ledger.accept_item("r-replay", "issue", "i1")
    assert ledger.claim_item("r-replay", "issue", "i1") is True
    item = ledger.record_requeue("r-replay", "issue", "i1", reason="worker restart", replay=True)
    assert item["state"] == ItemOutcome.ACCEPTED.value
    assert item["attempt_count"] == 1  # discriminator: accepted + attempt_count > 0
    assert item.get("replay") is True
    assert is_retry_pending(item) is True


def test_ddl_fail_detail_survives_payload_sanitizer(activity_db, mock_event_bus):
    """fail_detail must remain available for narrative reason_detail (#430 A5)."""
    _seed_issue(activity_db)
    rkey = journal.release_key("1001", "DDL", nzbname="x.cbz", discriminant="d1")
    journal.record_transition(rkey, journal.SNATCHED, issueid="1001", provider="DDL")
    from comicarr.app.common.redaction import redact_sensitive_text

    detail = redact_sensitive_text("boom apikey=supersecretvalue123")
    won = journal.mark_failed(
        rkey,
        "ddl-worker-rejected",
        payload={"issueid": "1001", "provider": "DDL", "fail_detail": detail},
        issueid="1001",
        provider="DDL",
    )
    assert won is True
    fails = [r for r in _events(activity_db) if r["status"] == "failed"]
    assert len(fails) == 1
    assert fails[0]["reason_code"] == "ddl-worker-rejected"
    assert fails[0]["reason_detail"] is not None
    assert "supersecretvalue123" not in fails[0]["reason_detail"]
    assert "[redacted]" in fails[0]["reason_detail"]


# ---------------------------------------------------------------------------
# fail_reason token-only
# ---------------------------------------------------------------------------


def test_ddl_worker_fail_reason_is_token_only():
    """The concatenating site must not embed exception text in fail_reason."""
    import inspect

    from comicarr.app.downloads import service as downloads_service

    src = inspect.getsource(downloads_service)
    assert 'reason="ddl-worker-rejected"' in src
    assert 'fail_reason="ddl-worker-rejected: %s"' not in src
