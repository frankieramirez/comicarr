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
``Row`` in ``ROWS``; a row that exposes a migration bug gets
``xfail=<issue link>`` until the fix lands.
"""

from __future__ import annotations

import configparser
import importlib.util
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

import comicarr
from alembic import command
from comicarr import config as config_module
from comicarr import db
from comicarr.app.core import runtime
from comicarr.app.core.schema import alembic_config, current_revision, upgrade_database

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "upgrade_matrix"

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


@dataclass(frozen=True)
class Row:
    name: str
    sql: str | None = None
    config: str | None = None
    xfail: str | None = None

    @property
    def seeded(self):
        return self.sql is not None


ROWS = (
    Row("Fresh"),
    Row("0.5x", sql="0.5x.sql", config="0.5x.config.ini"),
)


def _params():
    for row in ROWS:
        marks = [pytest.mark.xfail(reason=row.xfail, strict=True)] if row.xfail else []
        yield pytest.param(row, id=row.name, marks=marks)


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


class Install:
    """One row materialized as a data directory on disk."""

    def __init__(self, row, tmp_path, monkeypatch):
        self.row = row
        self.data_dir = tmp_path / "data"
        self.data_dir.mkdir()
        self.database = self.data_dir / "comicarr.db"
        self.config_file = self.data_dir / "config.ini"
        self._monkeypatch = monkeypatch

        connection = sqlite3.connect(self.database)
        try:
            if row.sql:
                connection.executescript((FIXTURES / row.sql).read_text(encoding="utf-8"))
        finally:
            connection.close()
        if row.config:
            shutil.copyfile(FIXTURES / row.config, self.config_file)

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
        monkeypatch.setattr(runtime, "_runtime", None)
        monkeypatch.setattr(
            "comicarr.maintenance.Maintenance.backup_files",
            lambda self, **kwargs: True,
            raising=False,
        )
        db.shutdown_engine()
        self.engine = db.get_engine()

    def snapshot(self):
        connection = sqlite3.connect(self.database)
        try:
            return build.dump_sql(connection)
        finally:
            connection.close()

    def table_counts(self):
        connection = sqlite3.connect(self.database)
        try:
            tables = [
                name
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            return {table: connection.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0] for table in tables}
        finally:
            connection.close()

    def preserved_values(self):
        connection = sqlite3.connect(self.database)
        try:
            present = {name for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            values = {}
            for table, (keys, columns) in PRESERVED_VALUES.items():
                if table not in present:
                    continue
                selected = ", ".join('"%s"' % column for column in keys + columns)
                for row in connection.execute('SELECT %s FROM "%s"' % (selected, table)):
                    values[(table, row[: len(keys)])] = row[len(keys) :]
            return values
        finally:
            connection.close()

    def load_config(self):
        """Read config.ini the way startup does, with side effects stubbed."""

        self._monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
        cfg = config_module.Config(str(self.config_file))
        cfg.configure = MagicMock()
        cfg.provider_sequence = MagicMock()
        cfg.read(startup=False)
        return cfg


@pytest.fixture(params=list(_params()))
def install(request, tmp_path, monkeypatch):
    item = Install(request.param, tmp_path, monkeypatch)
    yield item
    db.shutdown_engine()


@pytest.fixture
def upgraded(install):
    install.before_counts = install.table_counts()
    install.before_values = install.preserved_values()
    assert upgrade_database(install.engine) == _head_revision()
    return install


def test_1_upgrade_reaches_head_without_drift(upgraded):
    assert current_revision(upgraded.engine) == _head_revision()
    command.check(alembic_config(upgraded.engine))


def test_2_row_counts_are_preserved(upgraded):
    after = upgraded.table_counts()
    migrated = {table: count for table, count in upgraded.before_counts.items() if table != "alembic_version"}
    assert {table: after.get(table) for table in migrated} == migrated
    if upgraded.row.seeded:
        assert all(migrated[seed.table] == len(seed.rows) for seed in build.SEED)


def test_3_statuses_wanted_flags_and_locations_are_unchanged(upgraded):
    assert upgraded.preserved_values() == upgraded.before_values
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
    era = _ini_values(upgraded.config_file) if upgraded.config_file.exists() else {}

    cfg = upgraded.load_config()
    assert cfg.writeconfig() is not False
    saved = _ini_values(upgraded.config_file)
    assert {key: saved.get(key) for key in era} == era

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


@pytest.mark.parametrize("name", sorted(build.ROWS))
def test_rebuilding_a_fixture_reproduces_the_committed_files(name):
    sql, config_ini = build.build_row(name)
    sql_path, config_path = build.fixture_paths(name)
    assert sql == sql_path.read_text(encoding="utf-8")
    assert config_ini == config_path.read_text(encoding="utf-8")
