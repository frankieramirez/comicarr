#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Torrent monitor treats client outages as transient and requeues with backoff."""

import queue
from types import SimpleNamespace

import pytest

import comicarr
from comicarr import db
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.acquisition.runs import MAX_RECOVERY_ATTEMPTS
from comicarr.app.attention import ManualReview
from comicarr.app.downloads import journal, service
from comicarr.tables import metadata


@pytest.fixture
def sqlite_ddl_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    db.shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            DDL_LOCATION=str(tmp_path / "downloads"),
            CACHE_DIR=str(tmp_path / "cache"),
            ENFORCE_PERMS=False,
            CHMOD_FILE="0660",
            CHMOD_DIR="0777",
        ),
    )
    engine = db.get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready
    yield engine
    db.shutdown_engine()


def _item(**overrides):
    item = {
        "issueid": "torrent-issue",
        "comicid": "comic-1",
        "provider": "torznab",
        "hash": "hash",
        "nzbname": "Torrent.cbz",
        "journal_release_key": "torrent-issue|torznab|Torrent.cbz",
    }
    item.update(overrides)
    return item


def test_monitor_error_requeues_until_cap_then_records_manual_review(monkeypatch):
    snatched = queue.Queue()
    recorded = []
    monkeypatch.setattr(comicarr, "SNATCHED_QUEUE", snatched)
    monkeypatch.setattr(service, "record", lambda entry, **_kwargs: recorded.append(entry))
    monkeypatch.setattr(service.time, "sleep", lambda _seconds: None)

    item = _item()
    service._handle_torrent_monitor_result(item, {"snatch_status": "MONITOR ERROR"})
    assert snatched.qsize() == 1
    assert recorded == []

    for _ in range(MAX_RECOVERY_ATTEMPTS - 2):
        item = snatched.get_nowait()
        service._handle_torrent_monitor_result(item, {"snatch_status": "MONITOR ERROR"})
        assert snatched.qsize() == 1
        assert recorded == []

    item = snatched.get_nowait()
    service._handle_torrent_monitor_result(item, {"snatch_status": "MONITOR ERROR"})
    assert snatched.empty()
    assert len(recorded) == 1
    assert isinstance(recorded[0], ManualReview)
    assert recorded[0].reason == "torrent_monitor_unreachable"


def test_monitor_error_then_progress_then_complete_reaches_pp(sqlite_ddl_db, monkeypatch, tmp_path):
    artifact = tmp_path / "downloads" / "Torrent.cbz"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"comic")
    key = journal.release_key("torrent-issue", "torznab", nzbname="Torrent.cbz")
    journal.record_transition(
        key,
        journal.SNATCHED,
        payload={"issueid": "torrent-issue", "provider": "torznab", "route": "rtorrent", "hash": "hash"},
        issueid="torrent-issue",
        provider="torznab",
        downloader_type="rtorrent",
        hash="hash",
    )

    snatched = queue.Queue()
    pp_queue = queue.Queue()
    monkeypatch.setattr(comicarr, "SNATCHED_QUEUE", snatched)
    monkeypatch.setattr(comicarr, "PP_QUEUE", pp_queue)
    monkeypatch.setattr(service.time, "sleep", lambda _seconds: None)

    item = _item(journal_release_key=key)
    service._handle_torrent_monitor_result(item, {"snatch_status": "MONITOR ERROR"})
    assert snatched.qsize() == 1
    item = snatched.get_nowait()
    assert item["_monitor_error_attempt"] == 1

    service._handle_torrent_monitor_result(item, {"snatch_status": "IN PROGRESS"})
    assert snatched.qsize() == 1
    item = snatched.get_nowait()
    assert "_monitor_error_attempt" not in item

    service._handle_torrent_monitor_result(
        item,
        {"snatch_status": "MONITOR COMPLETE", "copied_filepath": str(artifact)},
    )
    assert snatched.empty()
    assert journal.read_one(key)["stage"] == journal.DOWNLOADED
    assert pp_queue.qsize() == 1
    assert pp_queue.get_nowait()["journal_release_key"] == key
