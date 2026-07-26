#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Migration completion must leave a durable acquisition reconciliation gate."""

from types import SimpleNamespace

import pytest
from sqlalchemy import update

import comicarr
from comicarr import db
from comicarr.app.acquisition.maintenance import (
    MaintenanceBlocked,
    MaintenanceController,
    ensure_acquisition_schema,
    get_reconciliation_status,
    refresh_runtime_state,
    set_reconciliation_state,
)
from comicarr.app.core.context import AppContext
from comicarr.app.system import service as system_service
from comicarr.tables import acquisition_reconciliation, metadata


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("COMICARR_ACQUISITION_MAINTENANCE", raising=False)
    db.shutdown_engine()
    metadata.create_all(db.get_engine())
    assert ensure_acquisition_schema(db.get_engine()).ready
    yield
    db.shutdown_engine()


def test_pending_reconciliation_survives_runtime_refresh_and_blocks_workers():
    set_reconciliation_state(
        "pending_preview",
        "Mylar3 migration copied rows; preview reconciliation before automatic acquisition",
        db.get_engine(),
    )

    persisted = get_reconciliation_status(db.get_engine())
    gate = refresh_runtime_state(SimpleNamespace(ACQUISITION_MAINTENANCE=False), db.get_engine())

    assert persisted["state"] == "pending_preview"
    assert "preview reconciliation" in persisted["reason"]
    assert gate.blocked is True
    assert gate.reason == "migration_reconciliation_pending_preview"
    assert gate.reconciliation_state == "pending_preview"
    assert comicarr.ACQUISITION_WORKERS_BLOCKED is True


def test_pending_reconciliation_blocks_new_leases_after_the_migration_fence_releases():
    set_reconciliation_state("pending_preview", "review required", db.get_engine())
    controller = MaintenanceController(db.get_engine())

    with pytest.raises(MaintenanceBlocked, match="reconciliation"):
        controller.acquire_lease("search-worker", "search")


def test_lease_claim_rechecks_reconciliation_in_its_insert_transaction(monkeypatch):
    controller = MaintenanceController(db.get_engine())

    def stale_ready_read(engine):
        with engine.begin() as conn:
            conn.execute(
                update(acquisition_reconciliation)
                .where(acquisition_reconciliation.c.control_id == "migration-reconciliation")
                .values(state="pending_preview", reason="migration began after the read")
            )
        return {"state": "ready", "reason": None, "updated_at": None}

    monkeypatch.setattr("comicarr.app.acquisition.maintenance.get_reconciliation_status", stale_ready_read)

    with pytest.raises(MaintenanceBlocked, match="maintenance blocks"):
        controller.acquire_lease("search-worker", "search")


def test_operator_can_record_reconciliation_ready_only_after_explicit_transition():
    set_reconciliation_state("pending_preview", "review required", db.get_engine())
    blocked = refresh_runtime_state(SimpleNamespace(ACQUISITION_MAINTENANCE=False), db.get_engine())
    assert blocked.blocked is True

    set_reconciliation_state("ready", "operator verified reconciliation", db.get_engine())
    ready = refresh_runtime_state(SimpleNamespace(ACQUISITION_MAINTENANCE=False), db.get_engine())

    assert ready.blocked is False
    assert ready.reconciliation_state == "ready"


def test_reconciliation_resume_requires_a_reason_and_no_active_fence(monkeypatch):
    ctx = AppContext(config=SimpleNamespace(ACQUISITION_MAINTENANCE=False))
    set_reconciliation_state("pending_preview", "review required", db.get_engine())

    missing_reason = system_service.mark_reconciliation_ready(ctx, actor="owner", reason="")
    assert missing_reason["success"] is False

    controller = MaintenanceController(db.get_engine())
    fence = controller.acquire_fence("owner", "repair-1", "repair")
    blocked = system_service.mark_reconciliation_ready(ctx, actor="owner", reason="verified backup and repair")
    assert blocked["status_code"] == 423
    controller.release_fence("owner", "repair-1", fence.epoch)

    runtime = {"replayed": {"search": 2, "refresh": 1}, "queues_started": ["search_queue"]}
    monkeypatch.setattr(comicarr, "resume_acquisition_runtime", lambda _config: runtime)
    resumed = system_service.mark_reconciliation_ready(ctx, actor="owner", reason="verified backup and repair")
    assert resumed["success"] is True
    assert resumed["reconciliation"]["state"] == "ready"
    assert resumed["runtime"] == runtime


def test_runtime_resume_replays_obligations_starts_queues_and_resumes_jobs(monkeypatch):
    class FakeJob:
        def __init__(self):
            self.resumed = False

        def resume(self):
            self.resumed = True

    class FakeScheduler:
        def __init__(self):
            self.jobs = {name: FakeJob() for name in ("dbupdater", "search", "weekly", "rss", "monitor", "importinbox")}

        def get_job(self, job_id):
            return self.jobs.get(job_id)

    config = SimpleNamespace(ACQUISITION_MAINTENANCE=False)
    scheduler = FakeScheduler()
    queues = []
    monkeypatch.setattr(comicarr, "ACQUISITION_SCHEMA_READY", True)
    monkeypatch.setattr(comicarr, "SCHED", scheduler)
    monkeypatch.setattr(comicarr, "replay_acquisition_obligations", lambda: {"search": 2, "refresh": 1})
    monkeypatch.setattr(comicarr, "queue_schedule", lambda queue_name, mode: queues.append((queue_name, mode)))
    for name in (
        "UPDATER_STATUS",
        "SEARCH_STATUS",
        "WEEKLY_STATUS",
        "RSS_STATUS",
        "MONITOR_STATUS",
        "IMPORTINBOX_STATUS",
    ):
        monkeypatch.setattr(comicarr, name, "Waiting")

    result = comicarr.resume_acquisition_runtime(config)

    assert result["replayed"] == {"search": 2, "refresh": 1}
    assert queues == [("search_queue", "start")]
    assert set(result["scheduler_jobs_resumed"]) == set(scheduler.jobs)
    assert all(job.resumed for job in scheduler.jobs.values())


@pytest.mark.parametrize(
    ("downloader", "expected"),
    [
        (0, False),  # watch folder -- no client-side identity to poll
        (1, True),  # uTorrent
        (2, True),  # rTorrent
        (3, True),  # Transmission
        (4, True),  # Deluge
        (5, True),  # qBittorrent
    ],
)
@pytest.mark.parametrize("flag", ("AUTO_SNATCH", "LOCAL_TORRENT_PP"))
def test_snatched_queue_starts_for_every_client_the_searcher_enqueues(monkeypatch, downloader, expected, flag):
    """The producer and consumer of SNATCHED_QUEUE must agree on eligibility.

    comicarr/search.py enqueues whenever torrent_monitor can poll the client.
    If this consumer gate is narrower, releases pile up on a queue nothing
    reads -- silently, and for the life of the process.
    """
    config = SimpleNamespace(
        ACQUISITION_MAINTENANCE=False,
        ENABLE_TORRENTS=True,
        AUTO_SNATCH=flag == "AUTO_SNATCH",
        LOCAL_TORRENT_PP=flag == "LOCAL_TORRENT_PP",
        TORRENT_DOWNLOADER=downloader,
    )
    queues = []
    monkeypatch.setattr(comicarr, "ACQUISITION_SCHEMA_READY", True)
    monkeypatch.setattr(comicarr, "OS_DETECT", "Linux")
    monkeypatch.setattr(comicarr, "SCHED", SimpleNamespace(get_job=lambda _job_id: None))
    monkeypatch.setattr(comicarr, "replay_acquisition_obligations", lambda: {"search": 0, "refresh": 0})
    monkeypatch.setattr(comicarr, "queue_schedule", lambda queue_name, mode: queues.append(queue_name))

    result = comicarr.resume_acquisition_runtime(config)

    assert ("snatched_queue" in queues) is expected
    assert ("snatched_queue" in result["queues_started"]) is expected


def test_runtime_resume_failure_recloses_the_durable_gate(monkeypatch):
    ctx = AppContext(config=SimpleNamespace(ACQUISITION_MAINTENANCE=False))
    set_reconciliation_state("pending_preview", "repair review required", db.get_engine())
    monkeypatch.setattr(
        comicarr,
        "resume_acquisition_runtime",
        lambda _config: (_ for _ in ()).throw(RuntimeError("worker start failed")),
    )

    result = system_service.mark_reconciliation_ready(ctx, actor="owner", reason="review complete")

    assert result["success"] is False
    assert result["status_code"] == 500
    assert result["reconciliation"]["state"] == "failed"
    assert result["gate"]["blocked"] is True
    assert get_reconciliation_status(db.get_engine())["state"] == "failed"


def test_aborting_a_migration_fence_marks_the_gate_failed(monkeypatch):
    set_reconciliation_state("migrating", "migration process stopped", db.get_engine())
    fence = MaintenanceController(db.get_engine()).acquire_fence("migration", "migration-1", "migration")

    result = system_service.abort_acquisition_maintenance(
        AppContext(config=SimpleNamespace(ACQUISITION_MAINTENANCE=False)),
        actor="owner",
        reason="container crashed during migration",
    )

    assert result["success"] is True
    assert result["reconciliation"]["state"] == "failed"
    assert result["gate"]["blocked"] is True
    assert fence.epoch == result["maintenance"]["epoch"]


def test_unreadable_reconciliation_gate_blocks_claims_without_marking_them_failed(monkeypatch):
    controller = MaintenanceController(db.get_engine())

    def unavailable(_engine):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("comicarr.app.acquisition.maintenance.get_reconciliation_status", unavailable)

    with pytest.raises(MaintenanceBlocked, match="reconciliation gate is unavailable"):
        controller.acquire_lease("search-worker", "search")


def test_migration_start_refuses_to_mutate_while_an_acquisition_lease_is_active(monkeypatch):
    class FakeMigration:
        def __init__(self, _path):
            self.execute_called = False

        def validate(self):
            return {"valid": True}

        def execute(self):
            self.execute_called = True
            return True

    monkeypatch.setattr("comicarr.migration.Mylar3Migration", FakeMigration)
    controller = MaintenanceController(db.get_engine())
    lease = controller.acquire_lease("worker", "postprocess", "issue", "issue-1")

    result = system_service.start_migration(AppContext(config=SimpleNamespace()), "/migration-source")

    assert result["success"] is False
    assert result["status_code"] == 423
    assert controller.status().active is False
    controller.release_lease(lease.lease_id)
