#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Needs attention terminal recording through the public module interface."""

from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import OperationalError

import comicarr
from comicarr import db
from comicarr.tables import failed, issues, metadata, pipeline_journal


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def test_actionable_failure_enters_attention_through_record():
    from comicarr.app.attention import Failure, RecordOutcome, read, record

    outcome = record(
        Failure(
            release_key="iss-1|nzbgeek",
            reason="postprocess_error:ValueError",
            issue_id="iss-1",
            provider="nzbgeek",
            nzb_name="Saga.001",
            payload={
                "issueid": "iss-1",
                "comicid": "c-1",
                "comicname": "Saga",
                "issuenumber": "1",
            },
        )
    )

    assert outcome == RecordOutcome(
        transition_won=True,
        base_reason="postprocess_error",
        actionable=True,
        reconciliation="noop",
    )
    view = read()
    assert view.member_total == 1
    assert view.groups[0].members[0].release_key == "iss-1|nzbgeek"


def test_excluded_download_gone_is_blocklisted_rewanted_and_kept_out_of_attention():
    from comicarr.app.attention import Failure, RecordOutcome, read, record

    with db.get_engine().begin() as conn:
        conn.execute(
            insert(issues),
            {
                "IssueID": "iss-9",
                "ComicID": "c-1",
                "ComicName": "Saga",
                "Issue_Number": "1",
                "Status": "Snatched",
            },
        )

    outcome = record(
        Failure(
            release_key="iss-9|ddl",
            reason="download_gone",
            issue_id="iss-9",
            provider="DDL",
            nzb_name="Saga.cbz",
            release_id="ddl-42",
            comic_id="c-1",
            comic_name="Saga",
            issue_number="1",
            payload={"ddl_id": "ddl-42", "filename": "Saga.cbz", "provider": "DDL"},
        )
    )

    assert outcome == RecordOutcome(
        transition_won=True,
        base_reason="download_gone",
        actionable=False,
        reconciliation="blocklisted_and_rewanted",
    )
    assert read().member_total == 0

    issue = db.select_one(select(issues).where(issues.c.IssueID == "iss-9"))
    assert issue["Status"] == "Wanted"
    assert issue["AcquisitionIntent"] == "wanted"

    blocked = db.select_one(
        select(failed).where(
            failed.c.ID == "ddl-42",
            failed.c.Provider == "DDL",
            failed.c.NZBName == "Saga.cbz",
        )
    )
    assert blocked["Status"] == "Failed"
    assert blocked["IssueID"] == "iss-9"


def test_failure_resolved_as_retried_is_recorded_off_the_work_queue():
    from comicarr.app.attention import Failure, read, record

    outcome = record(
        Failure(
            release_key="iss-2|nzbgeek",
            reason="download_failed_researching",
            issue_id="iss-2",
            provider="nzbgeek",
            resolved_as="retried",
        )
    )

    assert outcome.transition_won is True
    assert outcome.base_reason == "download_failed_researching"
    assert outcome.actionable is False
    assert outcome.reconciliation == "none"
    assert read().member_total == 0


def test_manual_review_enters_attention_with_its_stage_actions():
    from comicarr.app.attention import ManualReview, read, record

    outcome = record(
        ManualReview(
            release_key="iss-3|watchdir",
            reason="route_acceptance_missing_identity",
            issue_id="iss-3",
            provider="watchdir",
        )
    )

    assert outcome.transition_won is True
    assert outcome.actionable is True
    view = read()
    member = view.groups[0].members[0]
    assert member.stage == "manual_review"
    assert member.available_actions == ("import", "search_again", "stop_wanting")


def test_record_uses_caller_transaction_for_transition_and_reconciliation(monkeypatch):
    from comicarr.app.attention import Failure, record

    with db.get_engine().begin() as conn:
        conn.execute(
            insert(issues),
            {
                "IssueID": "iss-tx",
                "ComicID": "c-tx",
                "ComicName": "Saga",
                "Issue_Number": "9",
                "Status": "Snatched",
            },
        )

    def reject_standalone_write(*_args, **_kwargs):
        raise AssertionError("reconciliation escaped the caller transaction")

    monkeypatch.setattr(db, "upsert", reject_standalone_write)

    with pytest.raises(RuntimeError, match="rollback transaction"):
        with db.get_engine().begin() as conn:
            outcome = record(
                Failure(
                    release_key="iss-tx|ddl",
                    reason="download_gone",
                    issue_id="iss-tx",
                    provider="DDL",
                    nzb_name="Saga.009.cbz",
                    release_id="ddl-tx",
                ),
                conn=conn,
            )
            assert outcome.reconciliation == "blocklisted_and_rewanted"
            assert (
                conn.execute(
                    select(pipeline_journal.c.stage).where(pipeline_journal.c.release_key == "iss-tx|ddl")
                ).scalar_one()
                == "failed"
            )
            assert conn.execute(select(issues.c.Status).where(issues.c.IssueID == "iss-tx")).scalar_one() == "Wanted"
            assert conn.execute(select(failed.c.Status).where(failed.c.ID == "ddl-tx")).scalar_one() == "Failed"
            raise RuntimeError("rollback transaction")

    assert db.select_one(select(pipeline_journal).where(pipeline_journal.c.release_key == "iss-tx|ddl")) is None
    assert db.select_one(select(issues).where(issues.c.IssueID == "iss-tx"))["Status"] == "Snatched"
    assert db.select_one(select(failed).where(failed.c.ID == "ddl-tx")) is None


def test_record_opens_one_transaction_when_caller_does_not_supply_one(monkeypatch):
    from comicarr.app.attention import Failure, record

    with db.get_engine().begin() as conn:
        conn.execute(
            insert(issues),
            {
                "IssueID": "iss-owned-tx",
                "ComicID": "c-owned-tx",
                "ComicName": "Saga",
                "Issue_Number": "10",
                "Status": "Snatched",
            },
        )

    def reject_standalone_write(*_args, **_kwargs):
        raise AssertionError("record split one operation across transactions")

    monkeypatch.setattr(db, "upsert", reject_standalone_write)

    outcome = record(
        Failure(
            release_key="iss-owned-tx|ddl",
            reason="download_gone",
            issue_id="iss-owned-tx",
            provider="DDL",
            nzb_name="Saga.010.cbz",
            release_id="ddl-owned-tx",
        )
    )

    assert outcome.reconciliation == "blocklisted_and_rewanted"
    assert (
        db.select_one(select(pipeline_journal).where(pipeline_journal.c.release_key == "iss-owned-tx|ddl"))["stage"]
        == "failed"
    )
    assert db.select_one(select(issues).where(issues.c.IssueID == "iss-owned-tx"))["Status"] == "Wanted"
    assert db.select_one(select(failed).where(failed.c.ID == "ddl-owned-tx"))["Status"] == "Failed"


def test_record_rolls_back_terminal_transition_when_reconciliation_fails(monkeypatch):
    from comicarr.app.attention import Failure, record

    with db.get_engine().begin() as conn:
        conn.execute(
            insert(issues),
            {
                "IssueID": "iss-failed-tx",
                "ComicID": "c-failed-tx",
                "ComicName": "Saga",
                "Issue_Number": "11",
                "Status": "Snatched",
            },
        )

    original_upsert_conn = db.upsert_conn

    def fail_rewant(conn, table_name, values, controls):
        if table_name == "issues":
            raise RuntimeError("rewant persistence failed")
        return original_upsert_conn(conn, table_name, values, controls)

    monkeypatch.setattr(db, "upsert_conn", fail_rewant)

    with pytest.raises(RuntimeError, match="rewant persistence failed"):
        record(
            Failure(
                release_key="iss-failed-tx|ddl",
                reason="download_gone",
                issue_id="iss-failed-tx",
                provider="DDL",
                nzb_name="Saga.011.cbz",
                release_id="ddl-failed-tx",
            )
        )

    assert db.select_one(select(pipeline_journal).where(pipeline_journal.c.release_key == "iss-failed-tx|ddl")) is None
    assert db.select_one(select(issues).where(issues.c.IssueID == "iss-failed-tx"))["Status"] == "Snatched"
    assert db.select_one(select(failed).where(failed.c.ID == "ddl-failed-tx")) is None


def test_owned_record_publishes_activity_only_after_commit(monkeypatch):
    from comicarr.app.activity import events
    from comicarr.app.attention import Failure, record

    observed = []

    def observe_publish(payload):
        persisted = db.select_one(select(pipeline_journal).where(pipeline_journal.c.release_key == "iss-event|nzbgeek"))
        observed.append((payload, persisted["stage"]))
        return True

    monkeypatch.setattr(events, "publish_activity", observe_publish)

    record(
        Failure(
            release_key="iss-event|nzbgeek",
            reason="submission_rejected",
            issue_id="iss-event",
            provider="nzbgeek",
        )
    )

    assert len(observed) == 1
    assert observed[0][0]["release_key"] == "iss-event|nzbgeek"
    assert observed[0][1] == "failed"


def test_owned_record_retries_sqlite_lock_contention(monkeypatch):
    from comicarr.app.attention import Failure, _recording, record

    real_engine = db.get_engine()
    attempts = 0

    class FlakyEngine:
        def begin(self):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise OperationalError("database is locked", None, None)
            return real_engine.begin()

    monkeypatch.setattr(db, "get_engine", lambda: FlakyEngine())
    monkeypatch.setattr(_recording.time, "sleep", lambda _seconds: None)

    outcome = record(
        Failure(
            release_key="iss-lock|nzbgeek",
            reason="submission_rejected",
            issue_id="iss-lock",
            provider="nzbgeek",
        )
    )

    assert attempts == 3
    assert outcome.transition_won is True
    with real_engine.connect() as conn:
        assert (
            conn.execute(
                select(pipeline_journal.c.stage).where(pipeline_journal.c.release_key == "iss-lock|nzbgeek")
            ).scalar_one()
            == "failed"
        )


def test_torrent_monitor_not_found_survives_a_raising_record(monkeypatch):
    """A recording failure must not kill the torrent-monitor worker thread.

    ``worker_main`` catches only ``MaintenanceBlocked``, so anything else that
    escapes ``_handle_torrent_monitor_result`` takes the monitor down until the
    process restarts. ``record`` now runs strict reconciliation as well as the
    journal transition, so it can raise for reasons the old journal-only write
    never could.
    """
    from comicarr.app.downloads import service

    def exploding_record(_entry, **_kwargs):
        raise RuntimeError("attention persistence failed")

    monkeypatch.setattr(service, "record", exploding_record)

    service._handle_torrent_monitor_result(
        {
            "issueid": "iss-torrent",
            "comicid": "c-torrent",
            "hash": "deadbeef",
            "provider": "torrent-provider",
            "nzbname": "Saga.002",
        },
        {"snatch_status": "NOT FOUND"},
    )


def test_torrent_monitor_persistence_quarantine_survives_a_raising_record(monkeypatch):
    """Same containment for the quarantine written after a journal write fails."""
    from comicarr.app.downloads import journal, service

    def exploding_record(_entry, **_kwargs):
        raise RuntimeError("attention persistence failed")

    def exploding_transition(*_args, **_kwargs):
        raise RuntimeError("journal write failed")

    monkeypatch.setattr(service, "record", exploding_record)
    monkeypatch.setattr(journal, "record_transition", exploding_transition)

    service._handle_torrent_monitor_result(
        {
            "issueid": "iss-torrent-2",
            "comicid": "c-torrent-2",
            "hash": "cafebabe",
            "provider": "torrent-provider",
            "nzbname": "Saga.003",
        },
        {"snatch_status": "MONITOR COMPLETE", "copied_filepath": "/tmp/Saga.003.cbz"},
    )
