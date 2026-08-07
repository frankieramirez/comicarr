#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Versioned acquisition schema and persistent maintenance fencing."""

import datetime
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import func, insert, inspect, literal, select, text, update
from sqlalchemy.exc import IntegrityError

import comicarr
from comicarr import logger
from comicarr.db import get_engine
from comicarr.tables import (
    acquisition_canary_permits,
    acquisition_maintenance,
    acquisition_maintenance_events,
    acquisition_maintenance_leases,
    acquisition_reconciliation,
    acquisition_repair_canaries,
    acquisition_repair_events,
    acquisition_repair_items,
    acquisition_repair_manifests,
    acquisition_repair_runs,
    acquisition_repair_series,
    acquisition_run_items,
    acquisition_runs,
    acquisition_schema_versions,
    acquisition_search_previews,
    annuals,
    issues,
)

SCHEMA_COMPONENT = "acquisition"
SCHEMA_VERSION = 7
CONTROL_ID = "acquisition"
RECONCILIATION_CONTROL_ID = "migration-reconciliation"

_BASE_SCHEMA_TABLES = (
    acquisition_schema_versions,
    acquisition_runs,
    acquisition_run_items,
    acquisition_maintenance,
    acquisition_maintenance_leases,
    acquisition_maintenance_events,
)
_REPAIR_SCHEMA_TABLES = (
    acquisition_repair_runs,
    acquisition_repair_manifests,
    acquisition_repair_items,
    acquisition_repair_series,
    acquisition_repair_events,
    acquisition_repair_canaries,
)
_SEARCH_PREVIEW_SCHEMA_TABLES = (acquisition_search_previews,)
_RECOVERY_CONTROL_SCHEMA_TABLES = (acquisition_reconciliation, acquisition_canary_permits)
_SCHEMA_TABLES = (
    _BASE_SCHEMA_TABLES + _REPAIR_SCHEMA_TABLES + _SEARCH_PREVIEW_SCHEMA_TABLES + _RECOVERY_CONTROL_SCHEMA_TABLES
)

_BASE_REQUIRED_INDEXES = {
    "issues": {"issues_acquisition_intent"},
    "annuals": {"annuals_acquisition_intent"},
    "acquisition_runs": {"acquisition_runs_state"},
    "acquisition_run_items": {"acquisition_run_items_run_state", "acquisition_run_items_entity"},
    "acquisition_maintenance_leases": {"acquisition_maintenance_leases_active"},
    "acquisition_maintenance_events": {"acquisition_maintenance_events_epoch"},
}
_REPAIR_REQUIRED_INDEXES = {
    "acquisition_repair_runs": {"acq_repair_runs_state"},
    "acquisition_repair_manifests": {"acq_repair_manifest_run"},
    "acquisition_repair_items": {
        "acq_repair_items_run_state",
        "acq_repair_items_entity",
    },
    "acquisition_repair_series": {"acq_repair_series_run_state"},
    "acquisition_repair_events": {"acq_repair_events_run"},
    "acquisition_repair_canaries": {"acq_repair_canary_run"},
}
_SEARCH_PREVIEW_REQUIRED_INDEXES = {
    "acquisition_search_previews": {
        "acq_search_preview_series_state",
        "acq_search_preview_run",
    },
}
_RECOVERY_CONTROL_REQUIRED_INDEXES = {
    "acquisition_reconciliation": {"acq_reconciliation_state"},
    "acquisition_canary_permits": {"acq_canary_permit_state", "acq_canary_permit_release"},
}


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def maintenance_retry_delay(attempt_count):
    """Return bounded backoff for a deliberately requeued fenced command."""

    try:
        attempt = max(1, int(attempt_count))
    except (TypeError, ValueError):
        attempt = 1
    return min(60, 5 * (2 ** min(attempt - 1, 4)))


@dataclass(frozen=True)
class SchemaStatus:
    ready: bool
    version: int
    error: str | None = None


@dataclass(frozen=True)
class FenceStatus:
    active: bool
    epoch: int
    owner: str | None
    run_id: str | None
    reason: str | None
    heartbeat_at: str | None
    active_leases: int

    @property
    def drained(self):
        return self.active_leases == 0


@dataclass(frozen=True)
class Lease:
    lease_id: str
    epoch: int
    owner: str
    work_kind: str
    entity_type: str | None = None
    entity_id: str | None = None
    canary_permit_id: str | None = None


@dataclass(frozen=True)
class RuntimeGateStatus:
    blocked: bool
    reason: str | None
    schema_ready: bool
    maintenance_active: bool
    epoch: int
    owner: str | None = None
    run_id: str | None = None
    heartbeat_at: str | None = None
    reconciliation_state: str | None = None

    def as_dict(self):
        return {
            "blocked": self.blocked,
            "reason": self.reason,
            "schema_ready": self.schema_ready,
            "maintenance_active": self.maintenance_active,
            "epoch": self.epoch,
            "owner": self.owner,
            "run_id": self.run_id,
            "heartbeat_at": self.heartbeat_at,
            "reconciliation_state": self.reconciliation_state,
        }


class MaintenanceBlocked(RuntimeError):
    """A maintenance fence or startup gate rejected new acquisition work."""


class MaintenanceConflict(RuntimeError):
    """A different owner or active lease prevents a fence transition."""


def _set_schema_globals(status):
    """Project schema readiness through the canonical runtime when available."""
    from comicarr.app.core.runtime import set_runtime_acquisition_status

    set_runtime_acquisition_status(
        schema_ready=status.ready,
        schema_version=status.version,
        schema_error=status.error,
    )


def _current_version(engine):
    with engine.connect() as conn:
        value = conn.execute(
            select(func.max(acquisition_schema_versions.c.version)).where(
                acquisition_schema_versions.c.component == SCHEMA_COMPONENT
            )
        ).scalar_one_or_none()
    return int(value or 0)


def _create_declared_index(engine, table, index_name):
    index = next((candidate for candidate in table.indexes if candidate.name == index_name), None)
    if index is None:
        raise RuntimeError("missing declared acquisition index %s" % index_name)
    index.create(engine, checkfirst=True)


def _add_intent_column(engine, table_name):
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "AcquisitionIntent" in columns:
        return
    quoted_table = engine.dialect.identifier_preparer.quote(table_name)
    quoted_column = engine.dialect.identifier_preparer.quote("AcquisitionIntent")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE %s ADD COLUMN %s VARCHAR(16)" % (quoted_table, quoted_column)))


def _add_item_dispatch_state_column(engine):
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("acquisition_run_items")}
    if "dispatch_state" in columns:
        return
    quoted_table = engine.dialect.identifier_preparer.quote("acquisition_run_items")
    quoted_column = engine.dialect.identifier_preparer.quote("dispatch_state")
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE %s ADD COLUMN %s VARCHAR(32) NOT NULL DEFAULT 'pending'" % (quoted_table, quoted_column))
        )


def _add_item_queue_priority_column(engine):
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("acquisition_run_items")}
    if "queue_priority" in columns:
        return
    quoted_table = engine.dialect.identifier_preparer.quote("acquisition_run_items")
    quoted_column = engine.dialect.identifier_preparer.quote("queue_priority")
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE %s ADD COLUMN %s VARCHAR(16) NOT NULL DEFAULT 'routine'" % (quoted_table, quoted_column))
        )


def _add_item_recovery_count_column(engine):
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("acquisition_run_items")}
    if "recovery_count" in columns:
        return
    quoted_table = engine.dialect.identifier_preparer.quote("acquisition_run_items")
    quoted_column = engine.dialect.identifier_preparer.quote("recovery_count")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE %s ADD COLUMN %s INTEGER NOT NULL DEFAULT 0" % (quoted_table, quoted_column)))


def _cancel_prebound_residue(engine):
    """One-time reap of non-terminal items that predate the recovery bound.

    Before #555, replay re-drove every ``accepted``/``running`` item forever
    and nothing ever terminalised one that could not make progress, so a
    deployment accumulated hundreds of rows that the in-flight counter reported
    as live work. Those rows carry no recovery_count history, so the new bound
    would take three more restarts to clear them; reaping them once here makes
    the health number honest on the first start after upgrade instead.

    This is safe because the run ledger records **attempts, not intent**.
    Wanting lives on ``issues.Status``, so cancelling a dead attempt row cannot
    lose a want — anything still Wanted is picked up by the next search sweep.
    Migrations run before workers start, so nothing legitimately in flight can
    be cancelled here.
    """
    now = _utcnow()
    with engine.begin() as conn:
        result = conn.execute(
            update(acquisition_run_items)
            .where(acquisition_run_items.c.state.in_(["accepted", "running"]))
            .values(
                state="cancelled",
                reason="stale_before_recovery_bound",
                next_attempt_at=None,
                updated_at=now,
                completed_at=now,
            )
        )
    if result.rowcount:
        logger.warn(
            "[ACQUISITION] Cancelled %s in-flight run items stranded before the "
            "recovery bound existed (#555). Anything still Wanted is re-searched "
            "by the next sweep." % result.rowcount
        )


def _ensure_control_row(engine):
    with engine.begin() as conn:
        existing = conn.execute(
            select(acquisition_maintenance.c.control_id).where(acquisition_maintenance.c.control_id == CONTROL_ID)
        ).first()
        if existing is not None:
            return
        try:
            with conn.begin_nested():
                conn.execute(
                    insert(acquisition_maintenance).values(
                        control_id=CONTROL_ID,
                        epoch=0,
                        active=0,
                        owner=None,
                        run_id=None,
                        reason=None,
                        acquired_at=None,
                        heartbeat_at=None,
                        released_at=None,
                    )
                )
        except IntegrityError:
            # A concurrent initializer won after our read; the desired row is
            # now present and normal controller construction stays read-only.
            pass


def get_reconciliation_status(engine=None):
    """Read the durable post-migration reconciliation gate."""

    engine = engine or get_engine()
    with engine.connect() as conn:
        row = (
            conn.execute(
                select(acquisition_reconciliation).where(
                    acquisition_reconciliation.c.control_id == RECONCILIATION_CONTROL_ID
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        return {"state": "unavailable", "reason": "reconciliation control row is missing", "updated_at": None}
    return {"state": row["state"], "reason": row["reason"], "updated_at": row["updated_at"]}


def set_reconciliation_state(state, reason=None, engine=None):
    """Persist a migration/reconciliation gate transition for restart safety."""

    normalized = str(state or "").strip().lower()
    if normalized not in {"ready", "migrating", "pending_preview", "failed"}:
        raise ValueError("invalid reconciliation state")
    engine = engine or get_engine()
    now = _utcnow()
    with engine.begin() as conn:
        result = conn.execute(
            update(acquisition_reconciliation)
            .where(acquisition_reconciliation.c.control_id == RECONCILIATION_CONTROL_ID)
            .values(state=normalized, reason=str(reason)[:255] if reason else None, updated_at=now)
        )
        if result.rowcount != 1:
            conn.execute(
                insert(acquisition_reconciliation).values(
                    control_id=RECONCILIATION_CONTROL_ID,
                    state=normalized,
                    reason=str(reason)[:255] if reason else None,
                    updated_at=now,
                )
            )
    return get_reconciliation_status(engine)


def _apply_schema_v1(engine):
    for table in _BASE_SCHEMA_TABLES:
        table.create(engine, checkfirst=True)
    _add_intent_column(engine, "issues")
    _add_intent_column(engine, "annuals")
    _create_declared_index(engine, issues, "issues_acquisition_intent")
    _create_declared_index(engine, annuals, "annuals_acquisition_intent")
    for table_name, names in _BASE_REQUIRED_INDEXES.items():
        if table_name in {"issues", "annuals"}:
            continue
        table = next(table for table in _BASE_SCHEMA_TABLES if table.name == table_name)
        for name in names:
            _create_declared_index(engine, table, name)
    _ensure_control_row(engine)


def _apply_schema_v2(engine):
    for table in _REPAIR_SCHEMA_TABLES:
        table.create(engine, checkfirst=True)
    for table_name, names in _REPAIR_REQUIRED_INDEXES.items():
        table = next(table for table in _REPAIR_SCHEMA_TABLES if table.name == table_name)
        for name in names:
            _create_declared_index(engine, table, name)


def _apply_schema_v3(engine):
    for table in _SEARCH_PREVIEW_SCHEMA_TABLES:
        table.create(engine, checkfirst=True)
    for table_name, names in _SEARCH_PREVIEW_REQUIRED_INDEXES.items():
        table = next(table for table in _SEARCH_PREVIEW_SCHEMA_TABLES if table.name == table_name)
        for name in names:
            _create_declared_index(engine, table, name)


def _ensure_reconciliation_control_row(engine):
    try:
        with engine.begin() as conn:
            conn.execute(
                insert(acquisition_reconciliation).values(
                    control_id=RECONCILIATION_CONTROL_ID,
                    state="ready",
                    reason=None,
                    updated_at=_utcnow(),
                )
            )
    except IntegrityError:
        pass


def _apply_schema_v4(engine):
    for table in _RECOVERY_CONTROL_SCHEMA_TABLES:
        table.create(engine, checkfirst=True)
    for table_name, names in _RECOVERY_CONTROL_REQUIRED_INDEXES.items():
        table = next(table for table in _RECOVERY_CONTROL_SCHEMA_TABLES if table.name == table_name)
        for name in names:
            _create_declared_index(engine, table, name)
    _ensure_reconciliation_control_row(engine)


def _apply_schema_v5(engine):
    _add_item_dispatch_state_column(engine)


def _apply_schema_v6(engine):
    _add_item_queue_priority_column(engine)


def _apply_schema_v7(engine):
    _add_item_recovery_count_column(engine)
    _cancel_prebound_residue(engine)


def _version_tables(target_version):
    tables = list(_BASE_SCHEMA_TABLES)
    if target_version >= 2:
        tables.extend(_REPAIR_SCHEMA_TABLES)
    if target_version >= 3:
        tables.extend(_SEARCH_PREVIEW_SCHEMA_TABLES)
    if target_version >= 4:
        tables.extend(_RECOVERY_CONTROL_SCHEMA_TABLES)
    return tuple(tables)


def _version_indexes(target_version):
    required = dict(_BASE_REQUIRED_INDEXES)
    if target_version >= 2:
        required.update(_REPAIR_REQUIRED_INDEXES)
    if target_version >= 3:
        required.update(_SEARCH_PREVIEW_REQUIRED_INDEXES)
    if target_version >= 4:
        required.update(_RECOVERY_CONTROL_REQUIRED_INDEXES)
    return required


def _verify_schema(engine, target_version=SCHEMA_VERSION):
    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    version_tables = _version_tables(target_version)
    required_tables = {"issues", "annuals"} | {table.name for table in version_tables}
    missing_tables = sorted(required_tables - actual_tables)
    if missing_tables:
        raise RuntimeError("missing acquisition tables: %s" % ", ".join(missing_tables))

    required_columns = {
        "issues": {"AcquisitionIntent"},
        "annuals": {"AcquisitionIntent"},
        **{table.name: {column.name for column in table.columns} for table in version_tables},
    }
    if target_version < 5:
        required_columns["acquisition_run_items"].discard("dispatch_state")
    if target_version < 6:
        required_columns["acquisition_run_items"].discard("queue_priority")
    if target_version < 7:
        required_columns["acquisition_run_items"].discard("recovery_count")
    missing_columns = []
    for table_name, expected in required_columns.items():
        actual = {column["name"] for column in inspector.get_columns(table_name)}
        missing_columns.extend("%s.%s" % (table_name, name) for name in sorted(expected - actual))
    if missing_columns:
        raise RuntimeError("missing acquisition columns: %s" % ", ".join(missing_columns))

    missing_indexes = []
    for table_name, expected in _version_indexes(target_version).items():
        actual = {index["name"] for index in inspector.get_indexes(table_name)}
        missing_indexes.extend(sorted(expected - actual))
    if missing_indexes:
        raise RuntimeError("missing acquisition indexes: %s" % ", ".join(missing_indexes))

    with engine.connect() as conn:
        control = conn.execute(
            select(acquisition_maintenance.c.control_id).where(acquisition_maintenance.c.control_id == CONTROL_ID)
        ).first()
    if control is None:
        raise RuntimeError("missing acquisition maintenance control row")
    if target_version >= 4:
        with engine.connect() as conn:
            reconciliation = conn.execute(
                select(acquisition_reconciliation.c.control_id).where(
                    acquisition_reconciliation.c.control_id == RECONCILIATION_CONTROL_ID
                )
            ).first()
        if reconciliation is None:
            raise RuntimeError("missing acquisition reconciliation control row")


def ensure_acquisition_schema(engine=None):
    """Apply forward-only acquisition schema versions, then verify exactly.

    Errors are returned as a fail-closed status rather than raised so the web
    process can still expose authenticated diagnostics. Callers must honor the
    resulting runtime gate before starting or claiming acquisition work.
    """

    engine = engine or get_engine()
    version = 0
    try:
        acquisition_schema_versions.create(engine, checkfirst=True)
        version = _current_version(engine)
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                "database acquisition schema version %s is newer than supported version %s" % (version, SCHEMA_VERSION)
            )
        if version < 1:
            _apply_schema_v1(engine)
            _verify_schema(engine, target_version=1)
            with engine.begin() as conn:
                conn.execute(
                    insert(acquisition_schema_versions).values(
                        component=SCHEMA_COMPONENT,
                        version=1,
                        applied_at=_utcnow(),
                    )
                )
            version = 1
        if version < 2:
            _apply_schema_v2(engine)
            _verify_schema(engine, target_version=2)
            with engine.begin() as conn:
                conn.execute(
                    insert(acquisition_schema_versions).values(
                        component=SCHEMA_COMPONENT,
                        version=2,
                        applied_at=_utcnow(),
                    )
                )
            version = 2
        if version < 3:
            _apply_schema_v3(engine)
            _verify_schema(engine, target_version=3)
            with engine.begin() as conn:
                conn.execute(
                    insert(acquisition_schema_versions).values(
                        component=SCHEMA_COMPONENT,
                        version=3,
                        applied_at=_utcnow(),
                    )
                )
            version = 3
        if version < 4:
            _apply_schema_v4(engine)
            _verify_schema(engine, target_version=4)
            with engine.begin() as conn:
                conn.execute(
                    insert(acquisition_schema_versions).values(
                        component=SCHEMA_COMPONENT,
                        version=4,
                        applied_at=_utcnow(),
                    )
                )
            version = 4
        if version < 5:
            _apply_schema_v5(engine)
            _verify_schema(engine, target_version=5)
            with engine.begin() as conn:
                conn.execute(
                    insert(acquisition_schema_versions).values(
                        component=SCHEMA_COMPONENT,
                        version=5,
                        applied_at=_utcnow(),
                    )
                )
            version = 5
        if version < 6:
            _apply_schema_v6(engine)
            _verify_schema(engine, target_version=6)
            with engine.begin() as conn:
                conn.execute(
                    insert(acquisition_schema_versions).values(
                        component=SCHEMA_COMPONENT, version=6, applied_at=_utcnow()
                    )
                )
            version = 6
        if version < 7:
            _apply_schema_v7(engine)
            _verify_schema(engine, target_version=7)
            with engine.begin() as conn:
                conn.execute(
                    insert(acquisition_schema_versions).values(
                        component=SCHEMA_COMPONENT, version=7, applied_at=_utcnow()
                    )
                )
            version = 7
        _verify_schema(engine, target_version=SCHEMA_VERSION)
        status = SchemaStatus(True, version, None)
    except Exception as e:
        status = SchemaStatus(False, version, str(e)[:1000])
    _set_schema_globals(status)
    return status


class MaintenanceController:
    """Persistent epoch fence plus leases held across side-effect boundaries."""

    def __init__(self, engine=None):
        self.engine = engine or get_engine()
        _ensure_control_row(self.engine)

    def status(self):
        with self.engine.connect() as conn:
            row = conn.execute(
                select(acquisition_maintenance).where(acquisition_maintenance.c.control_id == CONTROL_ID)
            ).one()
            active_leases = conn.execute(
                select(func.count())
                .select_from(acquisition_maintenance_leases)
                .where(acquisition_maintenance_leases.c.released_at.is_(None))
            ).scalar_one()
        values = row._mapping
        return FenceStatus(
            active=bool(values["active"]),
            epoch=int(values["epoch"]),
            owner=values["owner"],
            run_id=values["run_id"],
            reason=values["reason"],
            heartbeat_at=values["heartbeat_at"],
            active_leases=int(active_leases),
        )

    def acquire_fence(self, owner, run_id, reason):
        if not owner or not run_id or not reason:
            raise ValueError("owner, run_id, and reason are required")
        now = _utcnow()
        with self.engine.begin() as conn:
            row = conn.execute(
                select(acquisition_maintenance)
                .where(acquisition_maintenance.c.control_id == CONTROL_ID)
                .with_for_update()
            ).one()
            current = row._mapping
            if current["active"]:
                if current["owner"] == str(owner) and current["run_id"] == str(run_id):
                    # Return the durable status only after this transaction
                    # commits. A second connection cannot see an uncommitted
                    # epoch on SQLite/PostgreSQL and would otherwise persist a
                    # stale fence token into the repair manifest.
                    pass
                else:
                    raise MaintenanceConflict("acquisition maintenance is owned by another operation")
            else:
                epoch = int(current["epoch"]) + 1
                result = conn.execute(
                    update(acquisition_maintenance)
                    .where(acquisition_maintenance.c.control_id == CONTROL_ID)
                    .where(acquisition_maintenance.c.epoch == current["epoch"])
                    .where(acquisition_maintenance.c.active == 0)
                    .values(
                        epoch=epoch,
                        active=1,
                        owner=str(owner),
                        run_id=str(run_id),
                        reason=str(reason)[:1000],
                        acquired_at=now,
                        heartbeat_at=now,
                        released_at=None,
                    )
                )
                if result.rowcount != 1:
                    raise MaintenanceConflict("acquisition maintenance fence changed concurrently")
                conn.execute(
                    insert(acquisition_maintenance_events).values(
                        epoch=epoch,
                        action="acquire",
                        actor=str(owner),
                        run_id=str(run_id),
                        reason=str(reason)[:1000],
                        created_at=now,
                    )
                )
        return self.status()

    def heartbeat_fence(self, owner, run_id, epoch):
        with self.engine.begin() as conn:
            result = conn.execute(
                update(acquisition_maintenance)
                .where(acquisition_maintenance.c.control_id == CONTROL_ID)
                .where(acquisition_maintenance.c.active == 1)
                .where(acquisition_maintenance.c.owner == str(owner))
                .where(acquisition_maintenance.c.run_id == str(run_id))
                .where(acquisition_maintenance.c.epoch == int(epoch))
                .values(heartbeat_at=_utcnow())
            )
        if result.rowcount != 1:
            raise MaintenanceConflict("maintenance fence ownership changed")

    def release_fence(self, owner, run_id, epoch):
        now = _utcnow()
        with self.engine.begin() as conn:
            current = (
                conn.execute(
                    select(acquisition_maintenance)
                    .where(acquisition_maintenance.c.control_id == CONTROL_ID)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if (
                not current["active"]
                or current["owner"] != str(owner)
                or current["run_id"] != str(run_id)
                or int(current["epoch"]) != int(epoch)
            ):
                raise MaintenanceConflict("maintenance fence ownership changed")
            active_leases = conn.execute(
                select(func.count())
                .select_from(acquisition_maintenance_leases)
                .where(acquisition_maintenance_leases.c.released_at.is_(None))
            ).scalar_one()
            if active_leases:
                raise MaintenanceConflict("cannot release maintenance fence before active leases drain")
            result = conn.execute(
                update(acquisition_maintenance)
                .where(acquisition_maintenance.c.control_id == CONTROL_ID)
                .where(acquisition_maintenance.c.active == 1)
                .where(acquisition_maintenance.c.owner == str(owner))
                .where(acquisition_maintenance.c.run_id == str(run_id))
                .where(acquisition_maintenance.c.epoch == int(epoch))
                .values(
                    active=0,
                    owner=None,
                    run_id=None,
                    reason=None,
                    heartbeat_at=now,
                    released_at=now,
                )
            )
            if result.rowcount != 1:
                raise MaintenanceConflict("maintenance fence ownership changed")
            conn.execute(
                insert(acquisition_maintenance_events).values(
                    epoch=int(epoch),
                    action="release",
                    actor=str(owner),
                    run_id=str(run_id),
                    reason="completed",
                    created_at=now,
                )
            )
        return self.status()

    def abort_fence(self, actor, reason, *, force_stale_leases=False):
        if not actor or not reason:
            raise ValueError("actor and reason are required for an audited abort")
        now = _utcnow()
        with self.engine.begin() as conn:
            current = (
                conn.execute(
                    select(acquisition_maintenance)
                    .where(acquisition_maintenance.c.control_id == CONTROL_ID)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if not current["active"]:
                raise MaintenanceConflict("no active acquisition maintenance fence")
            active_lease_rows = list(
                conn.execute(
                    select(acquisition_maintenance_leases.c.lease_id).where(
                        acquisition_maintenance_leases.c.released_at.is_(None)
                    )
                )
            )
            if active_lease_rows and not force_stale_leases:
                raise MaintenanceConflict("cannot abort while side-effect leases are active")
            if active_lease_rows:
                lease_ids = [row[0] for row in active_lease_rows]
                conn.execute(
                    update(acquisition_maintenance_leases)
                    .where(acquisition_maintenance_leases.c.lease_id.in_(lease_ids))
                    .where(acquisition_maintenance_leases.c.released_at.is_(None))
                    .values(heartbeat_at=now, released_at=now)
                )
                conn.execute(
                    update(acquisition_canary_permits)
                    .where(acquisition_canary_permits.c.lease_id.in_(lease_ids))
                    .where(acquisition_canary_permits.c.state == "claimed")
                    .values(
                        state="manual_review",
                        completed_at=now,
                        outcome="abandoned_after_restart",
                    )
                )
            result = conn.execute(
                update(acquisition_maintenance)
                .where(acquisition_maintenance.c.control_id == CONTROL_ID)
                .where(acquisition_maintenance.c.active == 1)
                .where(acquisition_maintenance.c.epoch == int(current["epoch"]))
                .values(
                    active=0,
                    owner=None,
                    run_id=None,
                    reason=None,
                    heartbeat_at=now,
                    released_at=now,
                )
            )
            if result.rowcount != 1:
                raise MaintenanceConflict("maintenance fence changed during abort")
            conn.execute(
                insert(acquisition_maintenance_events).values(
                    epoch=int(current["epoch"]),
                    action="abort",
                    actor=str(actor),
                    run_id=current["run_id"],
                    reason=(("forced stale-lease cleanup: " if active_lease_rows else "") + str(reason))[:1000],
                    created_at=now,
                )
            )
        return self.status()

    def acquire_lease(self, owner, work_kind, entity_type=None, entity_id=None, lease_id=None):
        if not owner or not work_kind:
            raise ValueError("owner and work_kind are required")
        if _operator_requested(getattr(comicarr, "CONFIG", None)):
            raise MaintenanceBlocked("operator acquisition maintenance is enabled")
        try:
            reconciliation = get_reconciliation_status(self.engine)
        except Exception as e:
            raise MaintenanceBlocked("acquisition reconciliation gate is unavailable") from e
        if reconciliation["state"] != "ready":
            raise MaintenanceBlocked(
                "acquisition reconciliation state %s blocks new work claims" % reconciliation["state"]
            )
        lease_id = str(lease_id or uuid.uuid4())
        now = _utcnow()
        columns = [
            acquisition_maintenance_leases.c.lease_id,
            acquisition_maintenance_leases.c.epoch,
            acquisition_maintenance_leases.c.owner,
            acquisition_maintenance_leases.c.work_kind,
            acquisition_maintenance_leases.c.entity_type,
            acquisition_maintenance_leases.c.entity_id,
            acquisition_maintenance_leases.c.acquired_at,
            acquisition_maintenance_leases.c.heartbeat_at,
            acquisition_maintenance_leases.c.released_at,
        ]
        gated_values = (
            select(
                literal(lease_id),
                acquisition_maintenance.c.epoch,
                literal(str(owner)),
                literal(str(work_kind)),
                literal(str(entity_type) if entity_type is not None else None),
                literal(str(entity_id) if entity_id is not None else None),
                literal(now),
                literal(now),
                literal(None),
            )
            .select_from(acquisition_maintenance.join(acquisition_reconciliation, literal(True)))
            .where(
                acquisition_maintenance.c.control_id == CONTROL_ID,
                acquisition_maintenance.c.active == 0,
                acquisition_reconciliation.c.control_id == RECONCILIATION_CONTROL_ID,
                acquisition_reconciliation.c.state == "ready",
            )
        )
        try:
            with self.engine.begin() as conn:
                result = conn.execute(insert(acquisition_maintenance_leases).from_select(columns, gated_values))
        except IntegrityError:
            result = None
        with self.engine.connect() as conn:
            row = conn.execute(
                select(acquisition_maintenance_leases).where(
                    acquisition_maintenance_leases.c.lease_id == lease_id,
                    acquisition_maintenance_leases.c.released_at.is_(None),
                )
            ).first()
        if row is None or (result is not None and result.rowcount == 0):
            raise MaintenanceBlocked("acquisition maintenance blocks new work claims")
        values = row._mapping
        if values["owner"] != str(owner) or values["work_kind"] != str(work_kind):
            raise MaintenanceConflict("lease_id belongs to a different acquisition claim")
        return Lease(
            lease_id=lease_id,
            epoch=int(values["epoch"]),
            owner=values["owner"],
            work_kind=values["work_kind"],
            entity_type=values["entity_type"],
            entity_id=values["entity_id"],
        )

    def acquire_canary_handoff_lease(self, owner, release_key, route, lease_id=None):
        """Claim the one authorized handoff that may cross an active fence."""

        lease_id = str(lease_id or uuid.uuid4())
        now = _utcnow()
        with self.engine.begin() as conn:
            control = (
                conn.execute(
                    select(acquisition_maintenance)
                    .where(acquisition_maintenance.c.control_id == CONTROL_ID)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if not control["active"] or not control["run_id"]:
                raise MaintenanceBlocked("no active acquisition canary fence")
            permit = (
                conn.execute(
                    select(acquisition_canary_permits)
                    .where(acquisition_canary_permits.c.permit_id == str(control["run_id"]))
                    .where(acquisition_canary_permits.c.release_key == str(release_key))
                    .where(acquisition_canary_permits.c.route == str(route))
                    .where(acquisition_canary_permits.c.state == "authorized")
                    .where(acquisition_canary_permits.c.expires_at >= now)
                )
                .mappings()
                .first()
            )
            if permit is None:
                raise MaintenanceBlocked("acquisition maintenance blocks this unapproved handoff")
            claimed = conn.execute(
                update(acquisition_canary_permits)
                .where(acquisition_canary_permits.c.permit_id == permit["permit_id"])
                .where(acquisition_canary_permits.c.state == "authorized")
                .values(state="claimed", lease_id=lease_id, claimed_at=now)
            )
            if claimed.rowcount != 1:
                raise MaintenanceBlocked("acquisition canary permit was claimed concurrently")
            conn.execute(
                insert(acquisition_maintenance_leases).values(
                    lease_id=lease_id,
                    epoch=int(control["epoch"]),
                    owner=str(owner),
                    work_kind="canary_handoff",
                    entity_type="release",
                    entity_id=str(release_key),
                    acquired_at=now,
                    heartbeat_at=now,
                    released_at=None,
                )
            )
        return Lease(
            lease_id=lease_id,
            epoch=int(control["epoch"]),
            owner=str(owner),
            work_kind="canary_handoff",
            entity_type="release",
            entity_id=str(release_key),
            canary_permit_id=str(permit["permit_id"]),
        )

    def heartbeat_lease(self, lease_id):
        with self.engine.begin() as conn:
            result = conn.execute(
                update(acquisition_maintenance_leases)
                .where(acquisition_maintenance_leases.c.lease_id == str(lease_id))
                .where(acquisition_maintenance_leases.c.released_at.is_(None))
                .values(heartbeat_at=_utcnow())
            )
        if result.rowcount != 1:
            raise MaintenanceConflict("acquisition lease is no longer active")

    def assert_lease_current(self, lease):
        """Fence-token check immediately before an external side effect.

        The caller keeps the lease until that boundary completes. If a fence
        activates after this check, maintenance observes the active lease and
        must drain it before applying database mutations.
        """

        stmt = (
            select(acquisition_maintenance_leases.c.lease_id)
            .select_from(
                acquisition_maintenance_leases.join(
                    acquisition_maintenance,
                    acquisition_maintenance.c.control_id == CONTROL_ID,
                )
            )
            .where(
                acquisition_maintenance_leases.c.lease_id == str(lease.lease_id),
                acquisition_maintenance_leases.c.epoch == int(lease.epoch),
                acquisition_maintenance_leases.c.released_at.is_(None),
                acquisition_maintenance.c.epoch == int(lease.epoch),
                acquisition_maintenance.c.active == 0,
            )
        )
        with self.engine.connect() as conn:
            current = conn.execute(stmt).first()
            if current is None and lease.canary_permit_id:
                canary_stmt = (
                    select(acquisition_maintenance_leases.c.lease_id)
                    .select_from(
                        acquisition_maintenance_leases.join(
                            acquisition_maintenance,
                            acquisition_maintenance.c.control_id == CONTROL_ID,
                        ).join(
                            acquisition_canary_permits,
                            acquisition_canary_permits.c.lease_id == acquisition_maintenance_leases.c.lease_id,
                        )
                    )
                    .where(
                        acquisition_maintenance_leases.c.lease_id == str(lease.lease_id),
                        acquisition_maintenance_leases.c.epoch == int(lease.epoch),
                        acquisition_maintenance_leases.c.released_at.is_(None),
                        acquisition_maintenance.c.epoch == int(lease.epoch),
                        acquisition_maintenance.c.active == 1,
                        acquisition_maintenance.c.run_id == str(lease.canary_permit_id),
                        acquisition_canary_permits.c.permit_id == str(lease.canary_permit_id),
                        acquisition_canary_permits.c.state == "claimed",
                        acquisition_canary_permits.c.release_key == str(lease.entity_id),
                        acquisition_canary_permits.c.expires_at >= _utcnow(),
                    )
                )
                current = conn.execute(canary_stmt).first()
        if current is None:
            raise MaintenanceBlocked("acquisition lease was fenced before the side effect")
        return True

    def complete_canary_handoff(self, lease, outcome):
        """Terminally record the sole permitted handoff without reopening it."""

        if not lease.canary_permit_id:
            return False
        normalized = str(outcome or "unknown")[:64]
        now = _utcnow()
        with self.engine.begin() as conn:
            result = conn.execute(
                update(acquisition_canary_permits)
                .where(acquisition_canary_permits.c.permit_id == str(lease.canary_permit_id))
                .where(acquisition_canary_permits.c.lease_id == str(lease.lease_id))
                .where(acquisition_canary_permits.c.state == "claimed")
                .values(state="completed", completed_at=now, outcome=normalized)
            )
        return result.rowcount == 1

    def release_lease(self, lease_id):
        now = _utcnow()
        with self.engine.begin() as conn:
            result = conn.execute(
                update(acquisition_maintenance_leases)
                .where(acquisition_maintenance_leases.c.lease_id == str(lease_id))
                .where(acquisition_maintenance_leases.c.released_at.is_(None))
                .values(heartbeat_at=now, released_at=now)
            )
        return result.rowcount == 1

    @contextmanager
    def lease(self, owner, work_kind, entity_type=None, entity_id=None, lease_id=None):
        claim = self.acquire_lease(owner, work_kind, entity_type, entity_id, lease_id)
        try:
            yield claim
        finally:
            self.release_lease(claim.lease_id)

    @contextmanager
    def handoff_lease(self, owner, release_key, route, lease_id=None):
        """Use a normal lease, or the one exact permit while fenced."""

        try:
            claim = self.acquire_lease(
                owner,
                "external-handoff",
                entity_type="release",
                entity_id=release_key,
                lease_id=lease_id,
            )
        except MaintenanceBlocked:
            claim = self.acquire_canary_handoff_lease(owner, release_key, route, lease_id=lease_id)
        try:
            yield claim
        finally:
            self.release_lease(claim.lease_id)

    def list_events(self):
        with self.engine.connect() as conn:
            return [
                dict(row._mapping)
                for row in conn.execute(
                    select(acquisition_maintenance_events).order_by(acquisition_maintenance_events.c.event_id)
                )
            ]


def _operator_requested(config=None):
    return _truthy(os.environ.get("COMICARR_ACQUISITION_MAINTENANCE")) or bool(
        getattr(config, "ACQUISITION_MAINTENANCE", False)
    )


def refresh_runtime_state(config=None, engine=None):
    """Refresh the fail-closed startup/claim projection used by adapters."""

    schema_ready = bool(getattr(comicarr, "ACQUISITION_SCHEMA_READY", False))
    if not schema_ready:
        status = RuntimeGateStatus(
            blocked=True,
            reason="schema_unavailable",
            schema_ready=False,
            maintenance_active=False,
            epoch=0,
        )
    else:
        reconciliation = get_reconciliation_status(engine)
        reconciliation_state = reconciliation["state"]
        fence = MaintenanceController(engine).status()
        if reconciliation_state != "ready":
            reason = (
                "migration_in_progress"
                if reconciliation_state == "migrating"
                else "migration_reconciliation_%s" % reconciliation_state
            )
            blocked = True
        elif _operator_requested(config):
            blocked = True
            reason = "operator_maintenance"
        else:
            blocked = fence.active
            reason = "persistent_maintenance" if fence.active else None
        status = RuntimeGateStatus(
            blocked=blocked,
            reason=reason,
            schema_ready=True,
            maintenance_active=fence.active,
            epoch=fence.epoch,
            owner=fence.owner,
            run_id=fence.run_id,
            heartbeat_at=fence.heartbeat_at,
            reconciliation_state=reconciliation_state,
        )
    from comicarr.app.core.runtime import set_runtime_acquisition_status

    set_runtime_acquisition_status(
        workers_blocked=status.blocked,
        block_reason=status.reason,
    )
    return status
