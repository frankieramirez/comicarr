#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Stuck DDL health check: resume, fail, expiry, and restart notify (#959)."""

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
from comicarr.tables import ddl_info, failed, issues, metadata, pipeline_journal


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
        "DDL_STUCK_EXPIRY": 1440,
        "DDL_AUTORESUME": True,
        "FAILED_DOWNLOAD_HANDLING": False,
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
    work = queue.Queue()
    monkeypatch.setattr(comicarr, "DDL_QUEUE", work, raising=False)
    monkeypatch.setattr(comicarr, "DDL_QUEUED", set(), raising=False)
    monkeypatch.setattr(comicarr, "DDL_STUCK_NOTIFIED", set(), raising=False)
    notified = []
    monkeypatch.setattr(
        "comicarr.app.system.service.notify_ddl_stuck",
        lambda item, age: notified.append((item["ID"], age)),
    )
    yield engine, work, notified
    db.shutdown_engine()


def _insert_downloading(age_minutes=45, **overrides):
    command = DDLCommand.from_mapping(_ddl_payload(**overrides))
    values = command.to_persisted_values(status="Downloading")
    values["updated_date"] = _ago(age_minutes)
    db.upsert("ddl_info", values, {"ID": command.id})
    return command.id


def _insert_issue(issue_id="issue-1"):
    with db.get_engine().begin() as conn:
        conn.execute(
            insert(issues),
            {
                "IssueID": issue_id,
                "ComicID": "comic-1",
                "ComicName": "Saga",
                "Issue_Number": "1",
                "Status": "Snatched",
            },
        )


def _ddl_row(item_id="ddl-1"):
    return db.select_one(select(ddl_info).where(ddl_info.c.ID == item_id))


def test_stuck_resume_enqueues_when_autoresume_and_link_valid(health_db, monkeypatch):
    _engine, work, notified = health_db
    monkeypatch.setattr(comicarr, "CONFIG", _health_config())
    monkeypatch.setattr("comicarr.app.downloads.recovery_classify._ddl_link_alive", lambda link: True)
    _insert_downloading()

    service.ddl_health_check()

    row = _ddl_row()
    assert row["status"] == "Queued"
    queued = work.get_nowait()
    assert queued["id"] == "ddl-1"
    assert queued["link"] == "https://downloads.invalid/issue.cbz"
    assert notified[0][0] == "ddl-1"


def test_stuck_fail_rewants_when_failed_handling_enabled(health_db, monkeypatch):
    _engine, _work, notified = health_db
    monkeypatch.setattr(comicarr, "CONFIG", _health_config(DDL_AUTORESUME=False, FAILED_DOWNLOAD_HANDLING=True))
    _insert_issue()
    _insert_downloading()

    service.ddl_health_check()

    row = _ddl_row()
    assert row["status"] == "Failed"
    issue = db.select_one(select(issues).where(issues.c.IssueID == "issue-1"))
    assert issue["Status"] == "Wanted"
    journal_row = db.select_one(select(pipeline_journal))
    assert journal_row["fail_reason"] == service.FAIL_REASON_DDL_STUCK
    assert journal_row["stage"] == journal.FAILED
    assert notified[0][0] == "ddl-1"


def test_stuck_fail_without_handling_does_not_rewant(health_db, monkeypatch):
    _engine, _work, _notified = health_db
    monkeypatch.setattr(comicarr, "CONFIG", _health_config(DDL_AUTORESUME=False, FAILED_DOWNLOAD_HANDLING=False))
    _insert_issue()
    _insert_downloading()

    service.ddl_health_check()

    assert _ddl_row()["status"] == "Failed"
    issue = db.select_one(select(issues).where(issues.c.IssueID == "issue-1"))
    assert issue["Status"] == "Snatched"
    journal_row = db.select_one(select(pipeline_journal))
    assert journal_row["fail_reason"] == "download_failed_no_auto_handling"


def test_hard_expiry_fails_even_when_autoresume_and_link_valid(health_db, monkeypatch):
    _engine, work, _notified = health_db
    monkeypatch.setattr(comicarr, "CONFIG", _health_config())
    monkeypatch.setattr("comicarr.app.downloads.recovery_classify._ddl_link_alive", lambda link: True)
    _insert_downloading(age_minutes=1500)

    service.ddl_health_check()

    assert _ddl_row()["status"] == "Failed"
    assert work.empty()


def test_owned_download_is_left_until_expiry(health_db, monkeypatch):
    _engine, _work, notified = health_db
    monkeypatch.setattr(comicarr, "CONFIG", _health_config())
    monkeypatch.setattr(comicarr, "DDL_QUEUED", {"ddl-1"}, raising=False)
    _insert_downloading(age_minutes=45)

    service.ddl_health_check()

    assert _ddl_row()["status"] == "Downloading"
    assert notified == []


def test_owned_download_fails_after_hard_expiry(health_db, monkeypatch):
    _engine, _work, _notified = health_db
    monkeypatch.setattr(comicarr, "CONFIG", _health_config(FAILED_DOWNLOAD_HANDLING=False))
    monkeypatch.setattr(comicarr, "DDL_QUEUED", {"ddl-1"}, raising=False)
    _insert_downloading(age_minutes=1500)

    service.ddl_health_check()

    assert _ddl_row()["status"] == "Failed"
    assert "ddl-1" not in comicarr.DDL_QUEUED


def test_dead_link_fails_as_gone_and_blocklists(health_db, monkeypatch):
    _engine, _work, _notified = health_db
    monkeypatch.setattr(comicarr, "CONFIG", _health_config(FAILED_DOWNLOAD_HANDLING=True))
    monkeypatch.setattr("comicarr.app.downloads.recovery_classify._ddl_link_alive", lambda link: False)
    _insert_issue()
    _insert_downloading()

    service.ddl_health_check()

    assert _ddl_row()["status"] == "Failed"
    journal_row = db.select_one(select(pipeline_journal))
    assert journal_row["fail_reason"] == "download_gone"
    issue = db.select_one(select(issues).where(issues.c.IssueID == "issue-1"))
    assert issue["Status"] == "Wanted"
    blocked = db.select_one(select(failed).where(failed.c.ID == "ddl-1"))
    assert blocked["Status"] == "Failed"


def test_unreachable_link_is_left_for_the_next_check(health_db, monkeypatch):
    _engine, _work, notified = health_db
    monkeypatch.setattr(comicarr, "CONFIG", _health_config())
    monkeypatch.setattr("comicarr.app.downloads.recovery_classify._ddl_link_alive", lambda link: None)
    _insert_downloading()

    service.ddl_health_check()

    assert _ddl_row()["status"] == "Downloading"
    assert notified == []


def test_notify_off_still_fails_stuck_rows(health_db, monkeypatch):
    _engine, _work, notified = health_db
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        _health_config(DDL_STUCK_NOTIFY=False, DDL_AUTORESUME=False),
    )
    _insert_downloading()

    service.ddl_health_check()

    assert _ddl_row()["status"] == "Failed"
    assert notified == []


def test_restart_does_not_renotify_after_fail(health_db, monkeypatch):
    _engine, _work, notified = health_db
    monkeypatch.setattr(comicarr, "CONFIG", _health_config(DDL_AUTORESUME=False))
    _insert_downloading()

    service.ddl_health_check()
    assert len(notified) == 1
    assert _ddl_row()["status"] == "Failed"

    comicarr.DDL_STUCK_NOTIFIED.clear()
    service.ddl_health_check()

    assert len(notified) == 1
    assert _ddl_row()["status"] == "Failed"


def test_restart_does_not_renotify_after_resume(health_db, monkeypatch):
    _engine, work, notified = health_db
    monkeypatch.setattr(comicarr, "CONFIG", _health_config())
    monkeypatch.setattr("comicarr.app.downloads.recovery_classify._ddl_link_alive", lambda link: True)
    _insert_downloading()

    service.ddl_health_check()
    assert _ddl_row()["status"] == "Queued"
    assert len(notified) == 1

    comicarr.DDL_STUCK_NOTIFIED.clear()
    while not work.empty():
        work.get_nowait()
    comicarr.DDL_QUEUED.clear()
    service.ddl_health_check()

    assert len(notified) == 1
    assert _ddl_row()["status"] == "Queued"


def test_invalid_command_fails_instead_of_resuming(health_db, monkeypatch):
    _engine, work, _notified = health_db
    monkeypatch.setattr(comicarr, "CONFIG", _health_config())
    monkeypatch.setattr("comicarr.app.downloads.recovery_classify._ddl_link_alive", lambda link: True)
    with db.get_engine().begin() as conn:
        conn.execute(
            insert(ddl_info),
            {
                "ID": "ddl-bad",
                "series": "Saga",
                "issueid": "issue-1",
                "comicid": "comic-1",
                "link": "https://downloads.invalid/issue.cbz",
                "status": "Downloading",
                "updated_date": _ago(45),
                "site": "DDL(GetComics)",
                "link_type": "GC-Main",
                "comicinfo": json.dumps("not-a-list"),
            },
        )

    service.ddl_health_check()

    assert _ddl_row("ddl-bad")["status"] == "Failed"
    assert work.empty()
