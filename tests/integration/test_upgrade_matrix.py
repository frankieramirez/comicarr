#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Upgrade matrix: every supported starting point must reach head intact.

Each row is a fixture database plus the ``config.ini`` its release wrote
(``tests/fixtures/upgrade_matrix/``). Every row must pass the seven checks in
section 6 of ``docs/architecture/foundations-plan.md``. A new row is one more
``Row`` in ``ROWS``. A check that exposes a migration bug gets an entry in
the row's ``xfail`` (check name to issue link) until the fix lands.

With ``DATABASE_URL`` naming PostgreSQL or MySQL, the dialect CI job runs the
``DIALECT_ROWS`` against that server instead. Their Comicarr rows are built
there by the release's own code, and Mylar3 rows keep their SQLite source and
import into it. An ``xfail`` key of ``check@dialect`` applies on that dialect only.
"""

from __future__ import annotations

import configparser
import importlib.util
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url

import comicarr
from alembic import command
from comicarr import config as config_module
from comicarr import db
from comicarr.app.core import runtime
from comicarr.app.core.schema import (
    DatabaseState,
    alembic_config,
    classify_database,
    current_revision,
    upgrade_database,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "upgrade_matrix"

# The dialect job points DATABASE_URL at PostgreSQL or MySQL; every other run is SQLite.
MATRIX_URL = os.environ.get("DATABASE_URL") or None
DIALECT = make_url(MATRIX_URL).get_backend_name() if MATRIX_URL else "sqlite"
if DIALECT == "sqlite":
    MATRIX_URL = None
# Section 6 of the Foundations plan: the rows that also run on PostgreSQL and MySQL.
DIALECT_ROWS = ("Fresh", "0.2x", "0.5x", "Mylar3 current")

_spec = importlib.util.spec_from_file_location("upgrade_matrix_build", FIXTURES / "build.py")
build = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = build
_spec.loader.exec_module(build)

# Columns check 3 compares, keyed by each table's identifying columns.
PRESERVED_VALUES = {
    "comics": (("ComicID",), ("Status", "ComicLocation", "ContentType")),
    "issues": (("IssueID",), ("Status", "AcquisitionIntent", "Location")),
    "annuals": (("IssueID",), ("Status", "AcquisitionIntent", "Location")),
    "storyarcs": (("IssueArcID",), ("Status", "Location")),
    "snatched": (("IssueID", "Provider", "Status"), ("FolderName",)),
    "failed": (("ID", "Provider", "NZBName"), ("Status",)),
    "weekly": (("ComicID", "IssueID"), ("STATUS",)),
}


# Append-only ledgers that a later release legitimately extends on upgrade.
GROWING_TABLES = {
    # ensure_acquisition_schema records each acquisition schema version it applies.
    "acquisition_schema_versions",
}

# config.ini migrations in ``Config.read`` that rewrite or drop a key on purpose,
# by the config_version that introduced them. ``None`` means the key is removed.
_RETIRED_BEFORE_16 = {("General", "auto_update"): None, ("Git", "check_github_on_startup"): None}
_GITHUB_ON_BEFORE_16 = {("Git", "check_github"): "True"}
_RETIRED_BEFORE_17 = {("Interface", "host_return"): None}
_RETIRED_BEFORE_18 = {("General", "folder_scan_log_verbose"): None}
_SEARCH_DELAY_SECONDS_BEFORE_19 = {("General", "search_delay"): "60"}  # default 1 minute
_CURRENT_CONFIG_VERSION = {("General", "config_version"): "19"}

DRIFT_1251 = "https://github.com/frankieramirez/comicarr/issues/1251"
DRIFT_1252 = "https://github.com/frankieramirez/comicarr/issues/1252"
MYLAR_IMPORT_1256 = "https://github.com/frankieramirez/comicarr/issues/1256"
DRIFT_1257 = "https://github.com/frankieramirez/comicarr/issues/1257"
MYLAR_CONFIG_1254_1255 = (
    "https://github.com/frankieramirez/comicarr/issues/1254 and https://github.com/frankieramirez/comicarr/issues/1255"
)


@dataclass(frozen=True)
class Row:
    name: str
    sql: str | None = None
    config: str | None = None
    config_changes: dict = field(default_factory=dict)
    # Check test name -> issue link, for a known migration bug.
    xfail: dict = field(default_factory=dict)
    # A release from before Alembic: no alembic_version, adopted on upgrade.
    legacy: bool = False
    # A Mylar3 data directory, imported into a fresh Comicarr install.
    mylar: bool = False

    @property
    def seeded(self):
        return self.sql is not None


ROWS = (
    Row("Fresh"),
    Row(
        "Pre-Alembic",
        sql="pre-alembic.sql",
        config="pre-alembic.config.ini",
        legacy=True,
        xfail={"test_1_upgrade_reaches_head_without_drift": DRIFT_1252},
        config_changes={
            **_RETIRED_BEFORE_16,
            **_GITHUB_ON_BEFORE_16,
            **_RETIRED_BEFORE_17,
            **_RETIRED_BEFORE_18,
            **_SEARCH_DELAY_SECONDS_BEFORE_19,
            **_CURRENT_CONFIG_VERSION,
        },
    ),
    Row(
        "0.2x",
        sql="0.2x.sql",
        config="0.2x.config.ini",
        config_changes={
            **_RETIRED_BEFORE_16,
            **_GITHUB_ON_BEFORE_16,
            **_RETIRED_BEFORE_17,
            **_RETIRED_BEFORE_18,
            **_SEARCH_DELAY_SECONDS_BEFORE_19,
            **_CURRENT_CONFIG_VERSION,
        },
        xfail={
            "test_1_upgrade_reaches_head_without_drift": DRIFT_1251,
            "test_1_upgrade_reaches_head_without_drift@postgresql": "%s and %s" % (DRIFT_1251, DRIFT_1257),
        },
    ),
    Row(
        "0.3x",
        sql="0.3x.sql",
        config="0.3x.config.ini",
        config_changes={**_SEARCH_DELAY_SECONDS_BEFORE_19, **_CURRENT_CONFIG_VERSION},
        xfail={"test_1_upgrade_reaches_head_without_drift": DRIFT_1251},
    ),
    Row(
        "0.4x",
        sql="0.4x.sql",
        config="0.4x.config.ini",
        xfail={"test_1_upgrade_reaches_head_without_drift": DRIFT_1251},
    ),
    Row(
        "0.5x",
        sql="0.5x.sql",
        config="0.5x.config.ini",
        xfail={"test_1_upgrade_reaches_head_without_drift@postgresql": DRIFT_1257},
    ),
    *(
        Row(
            name,
            sql=build.fixture_paths(name)[0].name,
            config=build.fixture_paths(name)[1].name,
            mylar=True,
            config_changes={
                **_SEARCH_DELAY_SECONDS_BEFORE_19,
                **_CURRENT_CONFIG_VERSION,
                # Mylar3 writes an empty provider order; Comicarr writes its None.
                ("Providers", "provider_order"): "None",
            },
            xfail={
                "test_6_config_ini_loads_saves_and_reloads_with_no_key_lost": MYLAR_CONFIG_1254_1255,
                # The import writes to a SQLite file, so a server database stays empty.
                **{
                    "%s@%s" % (check, dialect): MYLAR_IMPORT_1256
                    for check in (
                        "test_2_row_counts_are_preserved",
                        "test_3_statuses_wanted_flags_and_locations_are_unchanged",
                        "test_4_and_5_app_boots_and_serves_the_seeded_library",
                    )
                    for dialect in ("postgresql", "mysql")
                },
            },
        )
        for name in build.MYLAR_ROWS
    ),
)

# Process globals the Mylar3 import writes as it reports progress.
_MIGRATION_GLOBALS = (
    "DB_FILE",
    "DB_EMPTY",
    "MIGRATION_IN_PROGRESS",
    "MIGRATION_STATUS",
    "MIGRATION_ERROR",
    "MIGRATION_RECONCILIATION",
    "MIGRATION_TABLES_COMPLETE",
    "MIGRATION_TABLES_TOTAL",
    "MIGRATION_CURRENT_TABLE",
)


# Process-global worker queues, which lifespan shutdown fills with "exit".
_WORKER_QUEUES = (
    "SNATCHED_QUEUE",
    "NZB_QUEUE",
    "PP_QUEUE",
    "SEARCH_QUEUE",
    "DDL_QUEUE",
    "RETURN_THE_NZBQUEUE",
    "ADD_LIST",
    "REFRESH_QUEUE",
)


def _head_revision():
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def _ini_values(path):
    parser = configparser.RawConfigParser()
    parser.read(path, encoding="utf-8")
    return {(section, key): value for section in parser.sections() for key, value in parser.items(section)}


def _reset_database(url):
    """Empty the dialect job's database so each row starts from nothing."""

    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            if engine.dialect.name == "postgresql":
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
                return
            if engine.dialect.name == "mysql":
                connection.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for table in inspect(connection).get_table_names():
                connection.execute(text("DROP TABLE %s" % connection.dialect.identifier_preparer.quote(table)))
            if engine.dialect.name == "mysql":
                connection.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    finally:
        engine.dispose()


def _tables(engine):
    reflected = MetaData()
    reflected.reflect(bind=engine)
    return reflected.tables


def _sortable(value):
    return (value is None, type(value).__name__, str(value))


class Install:
    """One row materialized as a data directory, and on the dialect job a server database."""

    def __init__(self, row, tmp_path, monkeypatch):
        self.row = row
        self.data_dir = tmp_path / "data"
        self.data_dir.mkdir()
        self.database = self.data_dir / "comicarr.db"
        self.config_file = self.data_dir / "config.ini"
        self._monkeypatch = monkeypatch

        # A Mylar3 row starts as a Mylar3 data directory beside an empty install.
        self.source_dir = tmp_path / "mylar3" if row.mylar else self.data_dir
        self.source_dir.mkdir(exist_ok=True)
        self.source_config = self.source_dir / "config.ini"
        if MATRIX_URL and not row.mylar:
            # The release's own code builds the row on the server.
            _reset_database(MATRIX_URL)
            if row.sql:
                build.build_release_database(row.name, MATRIX_URL)
        else:
            if MATRIX_URL:
                _reset_database(MATRIX_URL)
            source = self.source_dir / ("mylar.db" if row.mylar else "comicarr.db")
            connection = sqlite3.connect(source)
            try:
                if row.sql:
                    connection.executescript((FIXTURES / row.sql).read_text(encoding="utf-8"))
            finally:
                connection.close()
        if row.config:
            shutil.copyfile(FIXTURES / row.config, self.source_config)

        if MATRIX_URL:
            monkeypatch.setenv("DATABASE_URL", MATRIX_URL)
        else:
            monkeypatch.delenv("DATABASE_URL", raising=False)
        # An operator maintenance override would hold the gate shut in check 4.
        monkeypatch.delenv("COMICARR_ACQUISITION_MAINTENANCE", raising=False)
        monkeypatch.setattr(comicarr, "DATA_DIR", str(self.data_dir), raising=False)
        monkeypatch.setattr(comicarr, "PROG_DIR", str(tmp_path), raising=False)
        monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
        for name in (
            "ACQUISITION_SCHEMA_READY",
            "ACQUISITION_SCHEMA_VERSION",
            "ACQUISITION_SCHEMA_ERROR",
            "ACQUISITION_WORKERS_BLOCKED",
            "ACQUISITION_BLOCK_REASON",
            "SIGNAL",
        ):
            monkeypatch.setattr(comicarr, name, getattr(comicarr, name, None), raising=False)
        # Lifespan shutdown puts "exit" on every worker queue the runtime adopts.
        for name in _WORKER_QUEUES:
            monkeypatch.setattr(comicarr, name, type(getattr(comicarr, name))(), raising=False)
        for name in _MIGRATION_GLOBALS:
            monkeypatch.setattr(comicarr, name, getattr(comicarr, name, None), raising=False)
        monkeypatch.setattr(comicarr, "DB_FILE", str(self.database), raising=False)
        monkeypatch.setattr(runtime, "_runtime", None)
        monkeypatch.setattr(
            "comicarr.maintenance.Maintenance.backup_files",
            lambda self, **kwargs: True,
            raising=False,
        )
        db.shutdown_engine()
        self.engine = db.get_engine()
        # Where the row's data starts: the Mylar3 database, or the install itself.
        if row.mylar:
            self.source = create_engine("sqlite:///%s" % (self.source_dir / "mylar.db"))
        else:
            self.source = self.engine

    def close(self):
        if self.source is not self.engine:
            self.source.dispose()

    def snapshot(self):
        """The whole database, schema and rows, in a form two runs can compare."""

        if self.engine.dialect.name == "sqlite":
            connection = sqlite3.connect(self.database)
            try:
                return build.dump_sql(connection)
            finally:
                connection.close()
        inspector = inspect(self.engine)
        snapshot = {}
        with self.engine.connect() as connection:
            for name, table in sorted(_tables(self.engine).items()):
                snapshot[name] = {
                    "columns": [(column["name"], str(column["type"])) for column in inspector.get_columns(name)],
                    "indexes": sorted(
                        (index["name"], tuple(index["column_names"])) for index in inspector.get_indexes(name)
                    ),
                    "rows": sorted(
                        (tuple(row) for row in connection.execute(select(table))),
                        key=lambda row: [_sortable(value) for value in row],
                    ),
                }
        return snapshot

    def table_counts(self, engine=None):
        engine = engine or self.engine
        with engine.connect() as connection:
            return {
                name: connection.execute(select(func.count()).select_from(table)).scalar_one()
                for name, table in _tables(engine).items()
            }

    def preserved_columns(self, engine=None):
        """The check-3 columns this database has, so later columns are not compared."""

        tables = _tables(engine or self.engine)
        found = {}
        for name, (keys, columns) in PRESERVED_VALUES.items():
            if name in tables:
                present = tables[name].c
                found[name] = (keys, tuple(column for column in columns if column in present))
        return found

    def preserved_values(self, preserved_columns, engine=None):
        engine = engine or self.engine
        tables = _tables(engine)
        values = {}
        with engine.connect() as connection:
            for name, (keys, columns) in preserved_columns.items():
                table = tables[name]
                for row in connection.execute(select(*(table.c[column] for column in keys + columns))):
                    values[(name, tuple(row[: len(keys)]))] = tuple(row[len(keys) :])
        return values

    def import_mylar3(self):
        """Run the Mylar3 import as Settings does, minus the background fence."""

        from comicarr import migration
        from comicarr.app.acquisition.maintenance import get_reconciliation_status

        assert migration.Mylar3Migration(str(self.source_dir)).execute() is True
        return get_reconciliation_status(self.engine)["state"]

    def load_config(self):
        """Read config.ini the way startup does, with side effects stubbed."""

        self._monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
        cfg = config_module.Config(str(self.config_file))
        cfg.configure = MagicMock()
        cfg.provider_sequence = MagicMock()
        cfg.read(startup=False)
        return cfg


def _matrix_rows():
    if MATRIX_URL is None:
        return ROWS
    return tuple(row for row in ROWS if row.name in DIALECT_ROWS)


@pytest.fixture(params=[pytest.param(row, id=row.name) for row in _matrix_rows()])
def install(request, tmp_path, monkeypatch):
    check = request.node.originalname
    reason = request.param.xfail.get("%s@%s" % (check, DIALECT)) or request.param.xfail.get(check)
    if reason:
        request.applymarker(pytest.mark.xfail(reason=reason, strict=True))
    item = Install(request.param, tmp_path, monkeypatch)
    yield item
    item.close()
    db.shutdown_engine()


@pytest.fixture
def upgraded(install):
    if install.row.legacy:
        assert "alembic_version" not in install.table_counts()
        assert classify_database(install.engine) is DatabaseState.LEGACY
    before = install.table_counts(install.source)
    if install.row.mylar:
        from comicarr.migration import MIGRATABLE_TABLES

        before = {table: count for table, count in before.items() if table in MIGRATABLE_TABLES}
    install.before_counts = before
    install.preserved_columns = install.preserved_columns(install.source)
    install.before_values = install.preserved_values(install.preserved_columns, install.source)

    if install.row.mylar:
        from comicarr.app.acquisition.maintenance import set_reconciliation_state

        install._monkeypatch.setattr(comicarr, "CONFIG", install.load_config(), raising=False)
        # Startup brings the empty install to head before Settings offers the import.
        assert upgrade_database(install.engine) == _head_revision()
        # The import leaves acquisition gated until the operator reviews it.
        assert install.import_mylar3() == "pending_preview"
        set_reconciliation_state("ready", "upgrade matrix: operator reviewed the import", install.engine)
    else:
        assert upgrade_database(install.engine) == _head_revision()
    return install


def test_1_upgrade_reaches_head_without_drift(upgraded):
    assert current_revision(upgraded.engine) == _head_revision()
    command.check(alembic_config(upgraded.engine))


def test_2_row_counts_are_preserved(upgraded):
    after = upgraded.table_counts()
    migrated = {table: count for table, count in upgraded.before_counts.items() if table != "alembic_version"}
    for table in GROWING_TABLES & set(migrated):
        assert after[table] >= migrated.pop(table)
    assert {table: after.get(table) for table in migrated} == migrated
    if upgraded.row.seeded:
        assert all(migrated.get(seed.table) == len(seed.rows) for seed in build.SEED)


def test_3_statuses_wanted_flags_and_locations_are_unchanged(upgraded):
    assert upgraded.preserved_values(upgraded.preserved_columns) == upgraded.before_values
    expected = sum(len(seed.rows) for seed in build.SEED) if upgraded.row.seeded else 0
    assert len(upgraded.before_values) == expected


def test_4_and_5_app_boots_and_serves_the_seeded_library(upgraded):
    from comicarr.app.acquisition.maintenance import refresh_runtime_state
    from comicarr.app.core.security import COOKIE_NAME, create_session_token
    from comicarr.app.main import app

    cfg = upgraded.load_config()
    upgraded._monkeypatch.setattr(comicarr, "CONFIG", cfg, raising=False)
    assert refresh_runtime_state(cfg).blocked is False

    ctx = runtime.create_runtime()
    with TestClient(app) as client:
        assert app.state.acquisition_maintenance["blocked"] is False
        assert client.get("/api/health").status_code == 200

        token = create_session_token("matrix-admin", ctx.jwt_secret_key, ctx.jwt_generation)
        client.cookies.set(COOKIE_NAME, token)

        listing = client.get("/api/series")
        assert listing.status_code == 200
        seeded_series = {row["ComicID"]: row["ComicName"] for row in build.SEED[0].rows}
        if not upgraded.row.seeded:
            assert listing.json() == []
            assert client.get("/api/series/900001").status_code == 404
            return
        assert {row["ComicID"]: row["ComicName"] for row in listing.json()} == seeded_series

        detail = client.get("/api/series/900001")
        assert detail.status_code == 200
        body = detail.json()
        assert body["comic"][0]["ComicLocation"] == "/library/comics/Starfall Rangers (2019)"
        seeded_issues = {row["IssueID"]: row["Status"] for row in build.SEED[1].rows if row["ComicID"] == "900001"}
        assert {issue["id"]: issue["legacyStatus"] for issue in body["issues"]} == seeded_issues


def test_6_config_ini_loads_saves_and_reloads_with_no_key_lost(upgraded):
    era = _ini_values(upgraded.source_config) if upgraded.source_config.exists() else {}
    if upgraded.row.mylar:
        # Only settings Comicarr defines, in the section it defines them, are imported.
        from comicarr.config import _CONFIG_DEFINITIONS

        era = {
            (section, key): value
            for (section, key), value in era.items()
            if key.upper() in _CONFIG_DEFINITIONS and _CONFIG_DEFINITIONS[key.upper()][1] == section
        }

    cfg = upgraded.load_config()
    assert cfg.writeconfig() is not False
    saved = _ini_values(upgraded.config_file)
    expected = {key: upgraded.row.config_changes.get(key, value) for key, value in era.items()}
    assert {key: saved.get(key) for key in era} == expected
    assert set(upgraded.row.config_changes) <= set(era)

    reloaded = upgraded.load_config()
    assert reloaded.writeconfig() is not False
    resaved = _ini_values(upgraded.config_file)
    assert {key: resaved.get(key) for key in saved} == saved
    if upgraded.row.config:
        assert (reloaded.HTTP_PORT, reloaded.COMIC_DIR) == (8091, "/library/inbox")


def test_7_second_upgrade_changes_nothing(upgraded):
    first = upgraded.snapshot()
    assert upgrade_database(upgraded.engine) == _head_revision()
    assert upgraded.snapshot() == first
    if upgraded.row.mylar:
        counts = upgraded.table_counts()
        upgraded.import_mylar3()
        assert upgraded.table_counts() == counts


@pytest.mark.skipif(MATRIX_URL is not None, reason="committed fixtures are SQLite; the SQLite matrix rebuilds them")
@pytest.mark.parametrize(
    "name",
    [
        *sorted(build.ROWS),
        # Mylar3 rows install Mylar3's dependencies first; run them with -m slow.
        *(pytest.param(name, marks=pytest.mark.slow) for name in build.MYLAR_ROWS),
    ],
)
def test_rebuilding_a_fixture_reproduces_the_committed_files(name):
    sql, config_ini = build.build_row(name)
    sql_path, config_path = build.fixture_paths(name)
    assert sql == sql_path.read_text(encoding="utf-8")
    assert config_ini == config_path.read_text(encoding="utf-8")
