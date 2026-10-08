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
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import comicarr
from comicarr import db
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema, maintenance_retry_delay
from comicarr.app.attention import Failure, ManualReview
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


def _unreachable():
    return {"snatch_status": "MONITOR ERROR", "error": "connection refused", "client_unreachable": True}


class _LeaseTracker:
    def __init__(self):
        self.held = False
        self.held_during_sleep = []

    def assert_lease_current(self, lease):
        return None

    @contextmanager
    def lease(self, *_args, **_kwargs):
        self.held = True
        try:
            yield SimpleNamespace(lease_id="lease")
        finally:
            self.held = False


def test_worker_main_escalates_outage_backoff_and_releases_lease_before_sleep(monkeypatch):
    """worker_main pops the fence counter every probe; outage delay must still grow.

    Without this, every MONITOR ERROR used attempt 1 (5s) and hit Manual Review
    in about 10s. The sleep must run after the maintenance lease is released.
    """
    import queue as queue_module

    clock = {"now": 0.0}
    sleeps = []
    recorded = []
    tracker = _LeaseTracker()
    item = _item()
    q = queue_module.Queue()
    q.put(item)

    def fake_sleep(seconds):
        tracker.held_during_sleep.append(tracker.held)
        sleeps.append(seconds)
        clock["now"] += seconds

    def capturing_record(entry, **_kwargs):
        recorded.append(entry)
        q.put("exit")

    monkeypatch.setattr(service.time, "sleep", fake_sleep)
    monkeypatch.setattr(service.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(service, "record", capturing_record)
    monkeypatch.setattr(
        "comicarr.app.acquisition.maintenance.MaintenanceController",
        lambda: tracker,
    )
    monkeypatch.setattr(
        "comicarr.app.search.service.torrentinfo",
        lambda **_kwargs: _unreachable(),
    )

    service.worker_main(q)

    assert tracker.held is False
    assert tracker.held_during_sleep
    assert all(held is False for held in tracker.held_during_sleep)
    assert sleeps[0] == maintenance_retry_delay(1)
    assert sleeps[1] == maintenance_retry_delay(2)
    assert sleeps[0] < sleeps[1] <= sleeps[2]
    assert sum(sleeps) >= service.MONITOR_OUTAGE_BUDGET_SECONDS
    assert len(recorded) == 1
    assert isinstance(recorded[0], ManualReview)
    assert recorded[0].reason == "torrent_monitor_unreachable"
    assert recorded[0].payload["error"] == "connection refused"


def test_worker_main_invalid_hash_is_not_client_unreachable(monkeypatch):
    import queue as queue_module

    recorded = []
    tracker = _LeaseTracker()
    q = queue_module.Queue()
    q.put(_item(hash="short"))
    q.put("exit")
    monkeypatch.setattr(service.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(service, "record", lambda entry, **_kwargs: recorded.append(entry))
    monkeypatch.setattr(
        "comicarr.app.acquisition.maintenance.MaintenanceController",
        lambda: tracker,
    )
    monkeypatch.setattr(
        "comicarr.app.search.service.torrentinfo",
        lambda **_kwargs: {"snatch_status": "INVALID HASH", "error": "invalid hash"},
    )

    service.worker_main(q)

    assert len(recorded) == 1
    assert isinstance(recorded[0], Failure)
    assert recorded[0].reason == "torrent_invalid_hash"
    assert recorded[0].reason != "torrent_monitor_unreachable"


def test_script_error_is_not_client_unreachable(monkeypatch):
    recorded = []
    monkeypatch.setattr(service, "record", lambda entry, **_kwargs: recorded.append(entry))

    delay = service._handle_torrent_monitor_result(
        _item(),
        {"snatch_status": "SCRIPT ERROR", "error": "No such file"},
    )

    assert delay is None
    assert len(recorded) == 1
    assert isinstance(recorded[0], ManualReview)
    assert recorded[0].reason == "torrent_autosnatch_script_error"
    assert recorded[0].reason != "torrent_monitor_unreachable"


def test_monitor_error_without_unreachable_flag_does_not_retry(monkeypatch):
    recorded = []
    monkeypatch.setattr(service, "record", lambda entry, **_kwargs: recorded.append(entry))

    delay = service._handle_torrent_monitor_result(_item(), {"snatch_status": "MONITOR ERROR"})

    assert delay is None
    assert recorded == []


def test_in_progress_returns_delay_without_sleeping(monkeypatch):
    slept = []
    monkeypatch.setattr(service.time, "sleep", lambda seconds: slept.append(seconds))

    delay = service._handle_torrent_monitor_result(_item(), {"snatch_status": "IN PROGRESS"})

    assert delay == service.IN_PROGRESS_POLL_SECONDS
    assert slept == []


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

    pp_queue = queue.Queue()
    monkeypatch.setattr(comicarr, "PP_QUEUE", pp_queue)

    item = _item(journal_release_key=key)
    delay = service._handle_torrent_monitor_result(item, _unreachable())
    assert delay == maintenance_retry_delay(1)
    assert item["_monitor_error_attempt"] == 1

    delay = service._handle_torrent_monitor_result(item, {"snatch_status": "IN PROGRESS"})
    assert delay == service.IN_PROGRESS_POLL_SECONDS
    assert "_monitor_error_attempt" not in item

    delay = service._handle_torrent_monitor_result(
        item,
        {"snatch_status": "MONITOR COMPLETE", "copied_filepath": str(artifact)},
    )
    assert delay is None
    assert journal.read_one(key)["stage"] == journal.DOWNLOADED
    assert pp_queue.qsize() == 1
    assert pp_queue.get_nowait()["journal_release_key"] == key
