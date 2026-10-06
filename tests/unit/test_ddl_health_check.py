#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Stuck DDL health check: orphan reconciliation and active-item notify (#959)."""

import datetime
import json
import queue
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr import db
from comicarr.app.downloads import journal, service
from comicarr.app.downloads.ddl_commands import DDLCommand
from comicarr.tables import ddl_info, issues, metadata, nzblog, pipeline_journal


def _ago(minutes):
    return (datetime.datetime.now() - datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")


def _ddl_payload(**overrides):
    payload = {
        "id": "ddl-1",
        "link": "https://downloads.invalid/issue.cbz",
        "site": "DDL(GetComics)",
        "series": "Saga",
        "year": "2026",
        "size": "10 MB",
        "comicid": "comic-1",
        "issueid": "issue-1",
        "oneoff": False,
        "link_type": "GC-Main",
        "filename": "Saga 001.cbz",
        "mainlink": "https://getcomics.invalid/saga",
        "comicinfo": [{"pack": False, "IssueID": "issue-1"}],
        "packinfo": None,
        "remote_filesize": 10_485_760,
        "resume": None,
        "issues": "1",
        "pack": False,
    }
    payload.update(overrides)
    return payload


def _health_config(**overrides):
    cfg = {
        "ENABLE_DDL": True,
        "DDL_STUCK_NOTIFY": True,
        "DDL_STUCK_THRESHOLD": 30,
        "FAILED_DOWNLOAD_HANDLING": True,
    }
    cfg.update(overrides)
    return SimpleNamespace(**cfg)


@pytest.fixture
def health_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    monkeypatch.setattr(comicarr, "CONFIG", _health_config(), raising=False)
    monkeypatch.setattr(comicarr, "DDL_QUEUE", queue.Queue(), raising=False)
    monkeypatch.setattr(comicarr, "DDL_QUEUED", set(), raising=False)
    monkeypatch.setattr(comicarr, "DDL_STUCK_NOTIFIED", set(), raising=False)
    monkeypatch.setitem(service._ACTIVE_DDL_ITEM, "id", None)
    notified = []
    monkeypatch.setattr(
        "comicarr.app.system.service.notify_ddl_stuck",
        lambda item, age: notified.append((item["ID"], age)),
    )
    yield notified
    db.shutdown_engine()


@pytest.fixture
def link(monkeypatch):
    """Injected source-link probe: set ``link.alive`` to True, False, or None."""

    state = SimpleNamespace(alive=True, calls=0)

    def probe(_url):
        state.calls += 1
        return state.alive

    monkeypatch.setattr("comicarr.app.downloads.recovery_classify._ddl_link_alive", probe)
    return state


def _insert_downloading(age_minutes=45, **overrides):
    command = DDLCommand.from_mapping(_ddl_payload(**overrides))
    values = command.to_persisted_values(status="Downloading")
    values["updated_date"] = _ago(age_minutes)
    db.upsert("ddl_info", values, {"ID": command.id})
    return command.id


def _release_key(ddl_id="ddl-1"):
    return journal.release_key("issue-1", "DDL", nzbname="Saga 001.cbz", hash=None, discriminant=ddl_id)


def _insert_journal(stage, ddl_id="ddl-1", fail_reason=None):
    payload = _ddl_payload(id=ddl_id)
    payload.update({"provider": "DDL", "ddl": True})
    with db.get_engine().begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            {
                "release_key": _release_key(ddl_id),
                "issueid": "issue-1",
                "provider": "DDL",
                "downloader_type": "ddl",
                "nzbname": "Saga 001.cbz",
                "stage": stage,
                "stage_rank": journal.stage_rank(stage),
                "payload_json": json.dumps(payload),
                "fail_reason": fail_reason,
                "updated_date": "2026-10-06 12:00:00",
            },
        )
        # A live snatch keeps its nzblog row; its absence reads as "already imported".
        conn.execute(insert(nzblog), {"IssueID": "issue-1", "PROVIDER": "DDL"})


def _insert_issue(status="Snatched"):
    with db.get_engine().begin() as conn:
        conn.execute(
            insert(issues),
            {"IssueID": "issue-1", "ComicID": "comic-1", "ComicName": "Saga", "Issue_Number": "1", "Status": status},
        )


def _ddl_status(item_id="ddl-1"):
    return db.select_one(select(ddl_info).where(ddl_info.c.ID == item_id))["status"]


def _journal_rows():
    return db.select_all(select(pipeline_journal).where(pipeline_journal.c.issueid == "issue-1")) or []


def _issue_status():
    return db.select_one(select(issues).where(issues.c.IssueID == "issue-1"))["Status"]


def test_unanchored_orphan_goes_to_manual_review(health_db, link):
    _insert_downloading()

    service.ddl_health_check()

    assert _ddl_status() == "Manual Review"
    [row] = _journal_rows()
    assert row["stage"] == journal.MANUAL_REVIEW
    assert row["fail_reason"] == "legacy_downloading_without_correlation"
    assert link.calls == 0
    assert health_db == []


def test_anchored_orphan_with_dead_link_fails_as_download_gone(health_db, link):
    link.alive = False
    _insert_issue()
    _insert_downloading()
    _insert_journal(journal.SNATCHED)

    service.ddl_health_check()

    assert _ddl_status() == "Failed"
    [row] = _journal_rows()
    assert row["stage"] == journal.FAILED
    assert row["fail_reason"] == "download_gone"
    assert health_db == []


def test_anchored_orphan_with_live_link_fails_as_stalled_and_is_rewanted(health_db, link):
    link.alive = True
    _insert_issue()
    _insert_downloading()
    _insert_journal(journal.SNATCHED)

    service.ddl_health_check()

    assert _ddl_status() == "Failed"
    [row] = _journal_rows()
    assert row["stage"] == journal.FAILED
    assert row["fail_reason"] == "ddl_stalled"
    assert _issue_status() == "Wanted"
    assert comicarr.DDL_QUEUE.empty()
    assert health_db == []


def test_unreachable_link_stays_downloading_notifies_once_and_retries(health_db, link):
    link.alive = None
    _insert_issue()
    _insert_downloading()
    _insert_journal(journal.SNATCHED)

    service.ddl_health_check()
    service.ddl_health_check()

    assert _ddl_status() == "Downloading"
    assert [row["stage"] for row in _journal_rows()] == [journal.SNATCHED]
    assert [item_id for item_id, _age in health_db] == ["ddl-1"]

    link.alive = False
    service.ddl_health_check()

    assert _ddl_status() == "Failed"
    assert link.calls == 3


def test_row_anchored_only_to_failed_journal_is_failed_without_rewant(health_db, link):
    _insert_issue(status="Skipped")
    _insert_downloading()
    _insert_journal(journal.FAILED, fail_reason="ddl-worker-rejected")

    service.ddl_health_check()

    assert _ddl_status() == "Failed"
    [row] = _journal_rows()
    assert row["fail_reason"] == "ddl-worker-rejected"
    assert _issue_status() == "Skipped"
    assert link.calls == 0


def test_row_anchored_only_to_manual_review_journal_matches_it(health_db, link):
    _insert_downloading()
    _insert_journal(journal.MANUAL_REVIEW, fail_reason="ambiguous_ddl_acceptance_after_restart")

    service.ddl_health_check()

    assert _ddl_status() == "Manual Review"
    assert link.calls == 0


def test_active_item_is_never_changed_and_notified_once(health_db, link):
    _insert_downloading(age_minutes=5000)
    _insert_journal(journal.SNATCHED)
    service._ACTIVE_DDL_ITEM["id"] = "ddl-1"

    service.ddl_health_check()
    service.ddl_health_check()

    assert _ddl_status() == "Downloading"
    assert [row["stage"] for row in _journal_rows()] == [journal.SNATCHED]
    assert [item_id for item_id, _age in health_db] == ["ddl-1"]
    assert link.calls == 0


def test_item_queued_for_this_worker_is_left_alone(health_db, link):
    _insert_downloading()
    comicarr.DDL_QUEUED.add("ddl-1")

    service.ddl_health_check()

    assert _ddl_status() == "Downloading"
    assert _journal_rows() == []


def test_row_inside_threshold_is_untouched(health_db, link):
    _insert_downloading(age_minutes=10)

    service.ddl_health_check()

    assert _ddl_status() == "Downloading"
    assert _journal_rows() == []
    assert health_db == []


def test_notify_off_still_reconciles_orphans(health_db, link, monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", _health_config(DDL_STUCK_NOTIFY=False))
    _insert_downloading()
    _insert_downloading(id="ddl-2")
    service._ACTIVE_DDL_ITEM["id"] = "ddl-2"

    service.ddl_health_check()

    assert _ddl_status("ddl-1") == "Manual Review"
    assert _ddl_status("ddl-2") == "Downloading"
    assert health_db == []


def test_restart_does_not_renotify_a_reconciled_row(health_db, link):
    link.alive = True
    _insert_issue()
    _insert_downloading()
    _insert_journal(journal.SNATCHED)

    service.ddl_health_check()
    comicarr.DDL_STUCK_NOTIFIED.clear()
    service.ddl_health_check()

    assert _ddl_status() == "Failed"
    assert health_db == []


def test_attention_write_failure_leaves_row_downloading_for_retry(health_db, link, monkeypatch):
    link.alive = True
    _insert_issue()
    _insert_downloading()
    _insert_journal(journal.SNATCHED)

    failing = {"on": True}
    real_record = service.record

    def flaky_record(entry):
        if failing["on"]:
            raise RuntimeError("database is locked")
        return real_record(entry)

    monkeypatch.setattr(service, "record", flaky_record)
    service.ddl_health_check()

    assert _ddl_status() == "Downloading"
    assert [row["stage"] for row in _journal_rows()] == [journal.SNATCHED]

    failing["on"] = False
    service.ddl_health_check()

    assert _ddl_status() == "Failed"


def test_worker_clears_active_item_on_every_exit(monkeypatch):
    calls = []

    def loop(_queue, _failures, active_item):
        service._ACTIVE_DDL_ITEM["id"] = "ddl-1"
        active_item["value"] = None
        calls.append(service.active_ddl_item_id())
        if len(calls) == 1:
            raise RuntimeError("poison item")
        return None

    monkeypatch.setattr(service, "_ddl_downloader_loop", loop)
    monkeypatch.setitem(service._ACTIVE_DDL_ITEM, "id", None)

    service.ddl_downloader(queue.Queue())

    assert calls == ["ddl-1", "ddl-1"]
    assert service.active_ddl_item_id() is None
