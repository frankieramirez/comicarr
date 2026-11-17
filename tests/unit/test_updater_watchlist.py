#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import queue
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from sqlalchemy import create_engine, select

import comicarr
from comicarr import importer, updater
from comicarr.app.acquisition.maintenance import MaintenanceBlocked, MaintenanceController, ensure_acquisition_schema
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.series import folder_rescan
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import issues, metadata


class _LeaseContext:
    def __enter__(self):
        return SimpleNamespace(lease_id="test", epoch=0)

    def __exit__(self, *_args):
        return False


class _OpenMaintenance:
    def lease(self, *_args, **_kwargs):
        return _LeaseContext()

    def assert_lease_current(self, _lease):
        return True


def test_bulk_issue_update_persists_issue_location(monkeypatch):
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(issues.insert(), {"IssueID": "issue-1", "Status": "Wanted"})

    monkeypatch.setattr(updater.db, "get_engine", lambda: engine)

    folder_rescan._bulk_update_issue_rows(
        issues,
        [
            {
                "IssueID": "issue-1",
                "Status": "Downloaded",
                "ComicSize": "123",
                "Location": "Absolute Batman 001.cbz",
            }
        ],
        ("Status", "ComicSize", "Location"),
    )

    with engine.connect() as conn:
        row = conn.execute(select(issues).where(issues.c.IssueID == "issue-1")).mappings().one()

    assert row["Status"] == "Downloaded"
    assert row["Location"] == "Absolute Batman 001.cbz"


@pytest.fixture
def acquisition_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    metadata.create_all(get_engine())
    assert ensure_acquisition_schema(get_engine()).ready
    ledger = RunLedger(get_engine())
    yield ledger
    shutdown_engine()


def test_refresh_worker_survives_legacy_missing_year_payload(monkeypatch):
    refresh_queue = queue.Queue()
    refresh_queue.put({"comicid": "1", "comicname": "Legacy Series"})
    refresh_queue.put({"comicid": "2", "comicname": "Current Series", "seriesyear": "2026"})
    refresh_queue.put("exit")
    update = MagicMock()
    monkeypatch.setattr(updater, "dbUpdate", update)
    monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)

    updater.addvialist(refresh_queue, maintenance=_OpenMaintenance())

    assert update.call_args_list == [
        call(["1"], calledfrom="refresh"),
        call(["2"], calledfrom="refresh"),
    ]


def test_idle_refresh_worker_cannot_retire_across_concurrent_enqueue():
    refresh_queue = queue.Queue()
    started = threading.Event()
    result = []

    def attempt_retirement():
        started.set()
        result.append(importer.refresh_worker_should_retire(refresh_queue))

    with importer._REFRESH_WORKER_LOCK:
        worker = threading.Thread(target=attempt_retirement)
        worker.start()
        assert started.wait(timeout=1)
        refresh_queue.put({"comicid": "160294"})
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert result == [False]


def test_refresh_thread_persists_before_queue_handoff(monkeypatch, acquisition_ledger):
    class InspectingQueue(queue.Queue):
        def put(self, item, *args, **kwargs):
            persisted = acquisition_ledger.get_item(item["run_id"], "series", item["comicid"])
            assert persisted["state"] == "accepted"
            super().put(item, *args, **kwargs)

    refresh_queue = InspectingQueue()
    monkeypatch.setattr(comicarr, "REFRESH_QUEUE", refresh_queue)

    importer.refresh_thread(
        [{"comicid": "160294", "comicname": "Absolute Batman", "seriesyear": "2024"}],
        ledger=acquisition_ledger,
        run_id="refresh-run",
        trigger="test",
        start_worker=False,
    )

    assert refresh_queue.get_nowait()["run_id"] == "refresh-run"
    assert acquisition_ledger.get_run("refresh-run")["accepted_count"] == 1


def test_active_maintenance_blocks_refresh_handoff_but_keeps_obligation(monkeypatch, acquisition_ledger):
    refresh_queue = queue.Queue()
    monkeypatch.setattr(comicarr, "REFRESH_QUEUE", refresh_queue)
    controller = MaintenanceController(get_engine())
    controller.acquire_fence("owner", "repair-1", reason="repair apply")

    with pytest.raises(MaintenanceBlocked):
        importer.refresh_thread(
            [{"comicid": "160294", "comicname": "Absolute Batman", "seriesyear": "2024"}],
            ledger=acquisition_ledger,
            run_id="refresh-blocked",
            trigger="test",
            start_worker=False,
            maintenance=controller,
        )

    assert refresh_queue.empty()
    assert acquisition_ledger.get_item("refresh-blocked", "series", "160294")["state"] == "accepted"


def test_refresh_replay_resets_running_item_without_count_inflation(monkeypatch, acquisition_ledger):
    acquisition_ledger.create_run("refresh-replay", "refresh", "test")
    acquisition_ledger.accept_item(
        "refresh-replay",
        "series",
        "160294",
        payload={"comicid": "160294", "comicname": "Absolute Batman", "seriesyear": "2024"},
    )
    acquisition_ledger.claim_item("refresh-replay", "series", "160294")
    refresh_queue = queue.Queue()
    monkeypatch.setattr(comicarr, "REFRESH_QUEUE", refresh_queue)

    replayed = importer.replay_refresh_obligations(ledger=acquisition_ledger, start_worker=False)

    assert replayed == 1
    assert refresh_queue.get_nowait()["run_id"] == "refresh-replay"
    assert acquisition_ledger.get_item("refresh-replay", "series", "160294")["state"] == "accepted"
    assert acquisition_ledger.get_run("refresh-replay")["accepted_count"] == 1


def test_refresh_replay_preserves_weekly_mode_arguments(monkeypatch, acquisition_ledger):
    refresh_queue = queue.Queue()
    monkeypatch.setattr(comicarr, "REFRESH_QUEUE", refresh_queue)
    importer.refresh_thread(
        {
            "r_mode": "updateissuedata",
            "comicid": "160294",
            "comicname": "Absolute Batman",
            "seriesyear": "2024",
            "calledfrom": "weeklycheck",
            "serieslast_updated": "2026-07-10 08:00:00",
        },
        ledger=acquisition_ledger,
        run_id="refresh-weekly",
        trigger="test",
        start_worker=False,
    )
    refresh_queue.get_nowait()
    acquisition_ledger.claim_item("refresh-weekly", "series", "160294")

    importer.replay_refresh_obligations(ledger=acquisition_ledger, start_worker=False)

    replayed = refresh_queue.get_nowait()
    assert replayed["run_id"] == "refresh-weekly"
    assert replayed["r_mode"] == "updateissuedata"
    assert replayed["calledfrom"] == "weeklycheck"
    assert replayed["serieslast_updated"] == "2026-07-10 08:00:00"


def test_import_lock_requeues_refresh_before_durable_claim(monkeypatch, acquisition_ledger):
    refresh_queue = queue.Queue()
    monkeypatch.setattr(comicarr, "REFRESH_QUEUE", refresh_queue)
    monkeypatch.setattr(comicarr, "IMPORTLOCK", True)
    monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)
    importer.refresh_thread(
        [{"comicid": "160294", "comicname": "Absolute Batman", "seriesyear": "2024"}],
        ledger=acquisition_ledger,
        run_id="refresh-import-lock",
        trigger="test",
        start_worker=False,
    )
    original_put = refresh_queue.put

    def stop_before_requeued_item(item, *args, **kwargs):
        original_put("exit")
        original_put(item, *args, **kwargs)

    monkeypatch.setattr(refresh_queue, "put", stop_before_requeued_item)

    updater.addvialist(refresh_queue, ledger=acquisition_ledger)

    item = acquisition_ledger.get_item("refresh-import-lock", "series", "160294")
    assert item["state"] == "accepted"
    assert item["attempt_count"] == 0


def test_durable_refresh_failure_does_not_kill_following_item(monkeypatch, acquisition_ledger):
    refresh_queue = queue.Queue()
    monkeypatch.setattr(comicarr, "REFRESH_QUEUE", refresh_queue)
    monkeypatch.setattr(comicarr, "IMPORTLOCK", False)
    monkeypatch.setattr(updater.time, "sleep", lambda _seconds: None)
    update = MagicMock(side_effect=[RuntimeError("metadata provider failed"), None])
    monkeypatch.setattr(updater, "dbUpdate", update)
    importer.refresh_thread(
        [
            {"comicid": "1", "comicname": "Broken Series", "seriesyear": "2024"},
            {"comicid": "2", "comicname": "Current Series", "seriesyear": "2026"},
        ],
        ledger=acquisition_ledger,
        run_id="refresh-poison",
        trigger="test",
        start_worker=False,
    )
    refresh_queue.put("exit")

    updater.addvialist(refresh_queue, ledger=acquisition_ledger)

    failed = acquisition_ledger.get_item("refresh-poison", "series", "1")
    succeeded = acquisition_ledger.get_item("refresh-poison", "series", "2")
    assert failed["state"] == "failed"
    assert failed["reason"] == "metadata provider failed"
    assert succeeded["state"] == "succeeded"
    assert update.call_count == 2


def _configure_updater(monkeypatch, *, annuals_on, rows, cv_results):
    refresh_thread = MagicMock()
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(ANNUALS_ON=annuals_on, BACKFILL_TIMESPAN=15),
    )
    monkeypatch.setattr(comicarr, "DB_BACKFILL", False)
    monkeypatch.setattr(comicarr, "UPDATER_STATUS", "Waiting")
    monkeypatch.setattr(comicarr, "REFRESH_QUEUE", SimpleNamespace(queue=[]))
    monkeypatch.setattr(comicarr, "importer", SimpleNamespace(refresh_thread=refresh_thread))
    monkeypatch.setattr(
        updater,
        "cv",
        SimpleNamespace(
            getComic=lambda **_kwargs: {
                "count": max(1, len(cv_results)),
                "totalcount": max(1, len(cv_results)),
                "results": cv_results,
            }
        ),
    )
    monkeypatch.setattr(updater.db, "select_one", MagicMock(return_value=None))
    monkeypatch.setattr(updater.db, "select_all", MagicMock(return_value=rows))
    monkeypatch.setattr(updater.db, "upsert", MagicMock())
    monkeypatch.setattr(updater.helpers, "job_management", MagicMock())
    monkeypatch.setattr(updater.helpers, "utctimestamp", MagicMock(return_value="now"))
    return refresh_thread


def test_watchlist_updater_skips_non_comicvine_series_ids(monkeypatch):
    refresh_thread = _configure_updater(
        monkeypatch,
        annuals_on=False,
        cv_results=[
            {
                "comicid": {"id": 123},
                "last_updated": "2026-07-10 08:00:00",
            }
        ],
        rows=[
            {
                "ComicID": "mal-1",
                "ComicName": "Manga Series",
                "Status": "Active",
                "ComicYear": "2026",
                "LastUpdated": "2026-07-01 08:00:00",
                "Total": 10,
            },
            {
                "ComicID": "123",
                "ComicName": "Comic Series",
                "Status": "Active",
                "ComicYear": "2026",
                "LastUpdated": "2026-07-01 08:00:00",
                "Total": 10,
            },
        ],
    )

    updater.watchlist_updater()

    refresh_thread.assert_called_once_with([{"comicid": 123, "comicname": "Comic Series", "seriesyear": "2026"}])


def test_watchlist_updater_keeps_annual_release_lookup_id_as_text(monkeypatch):
    refresh_thread = _configure_updater(
        monkeypatch,
        annuals_on=True,
        cv_results=[],
        rows=[
            {
                "ComicID": "456",
                "ComicName": None,
                "Status": "Active",
                "ComicYear": "2026",
                "LastUpdated": None,
                "Total": 0,
                "ReleaseComicID": None,
            }
        ],
    )

    updater.watchlist_updater()

    refresh_thread.assert_called_once_with([{"comicid": 456, "comicname": None, "seriesyear": "2026"}])
    annual_lookup = updater.db.select_one.call_args.args[0]
    release_id = next(iter(annual_lookup.compile().params.values()))
    assert release_id == "456"
    assert isinstance(release_id, str)
