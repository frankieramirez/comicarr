#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Persistent acquisition maintenance fence and schema-gate tests."""

from types import SimpleNamespace

import pytest
from sqlalchemy import String, create_engine, inspect, text

import comicarr
from comicarr.app.acquisition.maintenance import (
    SCHEMA_VERSION,
    MaintenanceBlocked,
    MaintenanceController,
    ensure_acquisition_schema,
    maintenance_retry_delay,
    refresh_runtime_state,
)
from comicarr.app.core.db import get_engine, shutdown_engine
from comicarr.app.core.tables import (
    acquisition_maintenance,
    acquisition_maintenance_leases,
    acquisition_run_items,
    acquisition_runs,
    acquisition_schema_versions,
    annuals,
    issues,
    metadata,
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("COMICARR_ACQUISITION_MAINTENANCE", raising=False)
    shutdown_engine()
    metadata.create_all(get_engine())
    status = ensure_acquisition_schema(get_engine())
    assert status.ready
    yield
    shutdown_engine()


def test_fence_epoch_is_monotonic_and_waits_for_active_lease_drain():
    controller = MaintenanceController(get_engine())
    lease = controller.acquire_lease("worker-1", work_kind="downloader_submit", entity_type="issue", entity_id="7")

    fence = controller.acquire_fence("owner", "repair-1", reason="repair apply")
    assert fence.active is True
    assert fence.drained is False
    assert fence.epoch > lease.epoch
    with pytest.raises(MaintenanceBlocked, match="fenced"):
        controller.assert_lease_current(lease)
    with pytest.raises(MaintenanceBlocked):
        controller.acquire_lease("worker-2", work_kind="search")

    controller.release_lease(lease.lease_id)
    assert controller.status().drained is True
    controller.release_fence("owner", "repair-1", fence.epoch)

    next_fence = controller.acquire_fence("owner", "repair-2", reason="second repair")
    assert next_fence.epoch == fence.epoch + 1


def test_interrupted_fence_survives_restart_and_requires_explicit_audited_abort():
    first_process = MaintenanceController(get_engine())
    fence = first_process.acquire_fence("owner", "repair-1", reason="repair apply")

    restarted_process = MaintenanceController(get_engine())
    persisted = restarted_process.status()
    assert persisted.active is True
    assert persisted.epoch == fence.epoch
    with pytest.raises(ValueError, match="reason"):
        restarted_process.abort_fence("operator", reason="")

    restarted_process.abort_fence("operator", reason="confirmed abandoned repair")
    assert restarted_process.status().active is False
    assert restarted_process.list_events()[-1]["action"] == "abort"


def test_forced_abort_releases_stale_leases_only_with_explicit_operator_flag():
    controller = MaintenanceController(get_engine())
    lease = controller.acquire_lease("worker", "search", "issue", "issue-1")
    fence = controller.acquire_fence("owner", "repair-1", reason="repair apply")

    with pytest.raises(Exception, match="side-effect leases"):
        controller.abort_fence("owner", "operator checked the crashed worker")

    status = controller.abort_fence(
        "owner",
        "operator confirmed the old worker process is stopped",
        force_stale_leases=True,
    )

    assert status.active is False
    assert status.active_leases == 0
    assert controller.release_lease(lease.lease_id) is False
    assert fence.epoch == status.epoch


def test_schema_migration_is_versioned_idempotent_and_detects_drift():
    first = ensure_acquisition_schema(get_engine())
    second = ensure_acquisition_schema(get_engine())
    assert first.ready and second.ready
    assert first.version == second.version == SCHEMA_VERSION

    with get_engine().begin() as conn:
        conn.execute(text("DROP INDEX issues_acquisition_intent"))

    drift = ensure_acquisition_schema(get_engine())
    assert drift.ready is False
    assert "issues_acquisition_intent" in drift.error


def test_schema_migration_upgrades_a_v0189_shaped_legacy_schema(tmp_path):
    legacy_engine = create_engine("sqlite:///%s" % (tmp_path / "legacy.db"))
    with legacy_engine.begin() as conn:
        conn.execute(text("CREATE TABLE issues (IssueID TEXT, Status TEXT)"))
        conn.execute(text("CREATE TABLE annuals (IssueID TEXT, Status TEXT)"))

    first = ensure_acquisition_schema(legacy_engine)
    second = ensure_acquisition_schema(legacy_engine)

    assert first.ready and second.ready
    assert first.version == second.version == SCHEMA_VERSION
    assert "AcquisitionIntent" in {column["name"] for column in inspect(legacy_engine).get_columns("issues")}
    assert "AcquisitionIntent" in {column["name"] for column in inspect(legacy_engine).get_columns("annuals")}
    legacy_engine.dispose()


def test_schema_migration_adds_row_dispatch_state_to_a_v4_database(tmp_path):
    legacy_engine = create_engine("sqlite:///%s" % (tmp_path / "v4.db"))
    metadata.create_all(legacy_engine)
    with legacy_engine.begin() as conn:
        conn.execute(text("ALTER TABLE acquisition_run_items DROP COLUMN dispatch_state"))

    status = ensure_acquisition_schema(legacy_engine)

    assert status.ready
    assert "dispatch_state" in {
        column["name"] for column in inspect(legacy_engine).get_columns("acquisition_run_items")
    }
    legacy_engine.dispose()


def test_schema_uses_bounded_types_for_every_indexed_text_column():
    indexed_columns = {
        issues.c.AcquisitionIntent,
        annuals.c.AcquisitionIntent,
        acquisition_schema_versions.c.component,
        acquisition_runs.c.run_id,
        acquisition_runs.c.completion_state,
        acquisition_run_items.c.run_id,
        acquisition_run_items.c.command_kind,
        acquisition_run_items.c.entity_type,
        acquisition_run_items.c.entity_id,
        acquisition_run_items.c.state,
        acquisition_maintenance.c.control_id,
        acquisition_maintenance_leases.c.lease_id,
        acquisition_maintenance_leases.c.released_at,
    }

    assert all(isinstance(column.type, String) and column.type.length for column in indexed_columns)


def test_schema_or_operator_gate_fails_closed_without_preventing_runtime_status(monkeypatch):
    monkeypatch.setattr(comicarr, "ACQUISITION_SCHEMA_READY", False, raising=False)
    monkeypatch.setattr(comicarr, "ACQUISITION_SCHEMA_ERROR", "missing required index", raising=False)

    blocked = refresh_runtime_state(SimpleNamespace(ACQUISITION_MAINTENANCE=False), get_engine())
    assert blocked.blocked is True
    assert blocked.reason == "schema_unavailable"
    assert comicarr.ACQUISITION_WORKERS_BLOCKED is True

    monkeypatch.setattr(comicarr, "ACQUISITION_SCHEMA_READY", True, raising=False)
    monkeypatch.setenv("COMICARR_ACQUISITION_MAINTENANCE", "1")
    operator_block = refresh_runtime_state(SimpleNamespace(ACQUISITION_MAINTENANCE=False), get_engine())
    assert operator_block.blocked is True
    assert operator_block.reason == "operator_maintenance"


@pytest.mark.parametrize(("attempt", "expected"), [(0, 5), (1, 5), (2, 10), (3, 20), (4, 40), (5, 60), (20, 60)])
def test_maintenance_retry_backoff_is_bounded(attempt, expected):
    assert maintenance_retry_delay(attempt) == expected
