#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Application-owned Alembic migration entry points and adoption checks."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Column, UniqueConstraint, insert, inspect, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from alembic import command
from comicarr.db import get_engine
from comicarr.tables import metadata


class DatabaseState(str, Enum):
    """The only database states that the automatic runner accepts."""

    FRESH = "fresh"
    VERSIONED = "versioned"
    LEGACY = "legacy"


class MigrationStateError(RuntimeError):
    """A nonempty database failed the conservative adoption fingerprint."""


_ALEMBIC_VERSION_TABLE = "alembic_version"
_LEGACY_ONLY_TABLES = {"readinglist"}
_REQUIRED_LEGACY_TABLES = {"comics", "issues", "annuals", "mylar_info"}
_REQUIRED_LEGACY_COLUMNS = {
    "comics": {"ComicID", "ComicName"},
    "issues": {"IssueID", "ComicID", "ComicName"},
    "annuals": {"IssueID", "Issue_Number"},
    "mylar_info": {"DatabaseVersion"},
}
_REVISION_INTRODUCED_TABLES = {
    "0003_library_chat": frozenset(
        {
            "ai_chat_threads",
            "ai_chat_messages",
            "ai_chat_attachments",
        }
    ),
    "0005_activity_events": frozenset({"activity_events"}),
    "0006_interactive_search_sessions": frozenset({"interactive_search_sessions", "interactive_search_candidates"}),
    "0007_interactive_search_progress": frozenset(),
    "0008_manga_series_modes": frozenset(),
}
_READINGLIST_TO_STORYARCS_COLUMNS = (
    "StoryArcID",
    "ComicName",
    "IssueNumber",
    "SeriesYear",
    "IssueYEAR",
    "StoryArc",
    "TotalIssues",
    "Status",
    "inCacheDir",
    "Location",
    "IssueArcID",
    "ReadingOrder",
    "IssueID",
    "ComicID",
    "ReleaseDate",
    "IssueDate",
    "Publisher",
    "IssuePublisher",
    "IssueName",
    "CV_ArcID",
    "Int_IssueNumber",
    "DynamicComicName",
    "Volume",
    "Manual",
)


def _application_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _tables_introduced_after(revision: str, scripts: ScriptDirectory) -> frozenset[str]:
    """Return tables first created by revisions strictly after ``revision``.

    Head metadata includes every table that exists at the migration head. A
    database stamped at an earlier known revision is expected to lack tables
    that later revisions introduce; those absences must not fail closed or
    upgrade can never create them.
    """

    introduced: set[str] = set()
    for script in scripts.walk_revisions():
        if script.revision == revision:
            break
        introduced.update(_REVISION_INTRODUCED_TABLES.get(script.revision, ()))
    return frozenset(introduced)


def _legacy_fingerprint_error(
    engine: Engine,
    *,
    require_control_row: bool = True,
    require_complete_schema: bool = False,
    optional_tables: frozenset[str] | set[str] | None = None,
) -> str | None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names()) - {_ALEMBIC_VERSION_TABLE}
    allowed_tables = set(metadata.tables) | _LEGACY_ONLY_TABLES
    unexpected = sorted(table_names - allowed_tables)
    if unexpected:
        return "contains unrecognized tables: %s" % ", ".join(unexpected)

    missing = sorted(_REQUIRED_LEGACY_TABLES - table_names)
    if missing:
        return "is missing required Comicarr tables: %s" % ", ".join(missing)

    deferred = frozenset(optional_tables or ())
    if require_complete_schema:
        missing = sorted((set(metadata.tables) - deferred) - table_names)
        if missing:
            return "is missing tables required by its Comicarr revision: %s" % ", ".join(missing)

    for table_name, required_columns in _REQUIRED_LEGACY_COLUMNS.items():
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing_columns = sorted(required_columns - columns)
        if missing_columns:
            return "%s is missing identifying columns: %s" % (table_name, ", ".join(missing_columns))

    expected_columns = {name: {column.name for column in table.columns} for name, table in metadata.tables.items()}
    for table_name in table_names - _LEGACY_ONLY_TABLES:
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        unknown_columns = sorted(actual_columns - expected_columns[table_name])
        if unknown_columns:
            return "%s has unrecognized columns: %s" % (table_name, ", ".join(unknown_columns))

    if require_control_row:
        with engine.connect() as connection:
            has_control_row = connection.execute(text("SELECT 1 FROM mylar_info LIMIT 1")).first() is not None
        if not has_control_row:
            return "is missing the mylar_info control row"
    return None


def classify_database(engine: Engine | None = None) -> DatabaseState:
    """Classify a database before any Alembic stamp or schema mutation.

    A legacy database is accepted only when it matches a conservative Comicarr
    fingerprint. Everything else fails closed so a database from another
    application can never be stamped accidentally.
    """

    engine = engine or get_engine()
    table_names = set(inspect(engine).get_table_names())
    if not table_names:
        return DatabaseState.FRESH
    if _ALEMBIC_VERSION_TABLE in table_names:
        _validate_versioned_database(engine)
        return DatabaseState.VERSIONED

    error = _legacy_fingerprint_error(engine)
    if error:
        raise MigrationStateError("database is not a recognized Comicarr database and will not be adopted: %s" % error)
    return DatabaseState.LEGACY


def _validate_versioned_database(engine: Engine) -> None:
    """Fail closed unless the database records one exact Comicarr revision."""

    with engine.connect() as connection:
        revisions = MigrationContext.configure(connection).get_current_heads()

    if not revisions:
        raise MigrationStateError("Alembic version table is empty; refusing to mutate an untrusted database")
    if len(revisions) != 1:
        raise MigrationStateError(
            "Alembic version table must contain exactly one revision for Comicarr's single-head migration graph"
        )

    revision = revisions[0]
    scripts = ScriptDirectory.from_config(alembic_config(engine))
    try:
        resolved = scripts.get_revision(revision)
    except CommandError as e:
        raise MigrationStateError("Alembic version table contains an unknown Comicarr revision: %s" % revision) from e
    if resolved is None or resolved.revision != revision:
        raise MigrationStateError("Alembic version table contains an unknown Comicarr revision: %s" % revision)

    error = _legacy_fingerprint_error(
        engine,
        require_control_row=False,
        require_complete_schema=True,
        optional_tables=_tables_introduced_after(revision, scripts),
    )
    if error:
        raise MigrationStateError("versioned database is not a recognized Comicarr database: %s" % error)


def alembic_config(engine: Engine | None = None, connection=None) -> Config:
    """Create Alembic configuration without duplicating application credentials."""

    root = _application_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.attributes["engine"] = engine or get_engine()
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def autogenerate_include_object(connection: Connection):
    """Treat full unique indexes as equivalent to table unique constraints.

    SQLite cannot add a table constraint without rebuilding the table, so the
    reviewed legacy path restores equivalent enforcement with unique indexes.
    This filter suppresses only the corresponding autogenerate representation
    difference; absent, partial, or differently ordered enforcement remains a
    schema diff.
    """

    metadata_unique_constraints = {
        (table.name, tuple(column.name for column in constraint.columns))
        for table in metadata.sorted_tables
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    reflected_unique_indexes = None

    def get_reflected_unique_indexes():
        nonlocal reflected_unique_indexes
        if reflected_unique_indexes is not None:
            return reflected_unique_indexes

        reflected_unique_indexes = set()
        inspector = inspect(connection)
        for table_name in set(inspector.get_table_names()) & set(metadata.tables):
            for index in inspector.get_indexes(table_name):
                dialect_options = index.get("dialect_options") or {}
                is_partial = any(
                    name.endswith("_where") and value is not None for name, value in dialect_options.items()
                )
                columns = tuple(index.get("column_names") or ())
                if index.get("unique") and columns and not is_partial:
                    reflected_unique_indexes.add((table_name, columns))
        return reflected_unique_indexes

    def include_object(schema_object, _name, object_type, reflected, compare_to):
        if compare_to is not None:
            return True
        if object_type not in {"index", "unique_constraint"}:
            return True
        signature = (schema_object.table.name, tuple(column.name for column in schema_object.columns))
        if object_type == "unique_constraint" and not reflected:
            return signature not in get_reflected_unique_indexes()
        if object_type == "index" and reflected and schema_object.unique:
            return signature not in metadata_unique_constraints
        return True

    return include_object


def current_revision(engine: Engine | None = None) -> str | None:
    """Return the current Alembic revision without creating a second engine."""

    engine = engine or get_engine()
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _copy_column_for_add(column):
    """Return the portable portion of a declared column for Alembic ADD COLUMN."""

    return Column(
        column.name,
        column.type,
        nullable=column.nullable,
        server_default=column.server_default,
    )


def _has_single_column_unique_enforcement(connection: Connection, table_name: str, column_name: str) -> bool:
    """Return whether a legacy table enforces a declared ``unique=True`` column."""

    inspector = inspect(connection)
    expected_columns = [column_name]
    for constraint in inspector.get_unique_constraints(table_name):
        if constraint.get("column_names") == expected_columns:
            return True
    for index in inspector.get_indexes(table_name):
        if index.get("unique") and index.get("column_names") == expected_columns:
            dialect_options = index.get("dialect_options") or {}
            if not any(name.endswith("_where") and value is not None for name, value in dialect_options.items()):
                return True
    return False


def _add_missing_single_column_unique_constraints(connection: Connection) -> None:
    """Restore unique enforcement that ``create_all(checkfirst=True)`` cannot add."""

    quote = connection.dialect.identifier_preparer.quote_identifier
    for table in metadata.sorted_tables:
        for column in table.columns:
            if not column.unique or _has_single_column_unique_enforcement(connection, table.name, column.name):
                continue
            index_name = "uq_%s_%s" % (table.name, column.name.lower())
            try:
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX %s ON %s (%s)" % (quote(index_name), quote(table.name), quote(column.name))
                    )
                )
            except SQLAlchemyError as error:
                raise MigrationStateError(
                    "legacy adoption could not restore unique enforcement for %s.%s" % (table.name, column.name)
                ) from error


def apply_legacy_schema_compatibility(connection: Connection) -> None:
    """Apply the reviewed, non-destructive structural legacy adoption step.

    This function is called exclusively from revision ``0002_legacy_adoption``.
    It intentionally rejects additions that need a non-null value for existing
    rows; those require a separately reviewed migration instead of a hidden
    startup repair.
    """

    from alembic import op

    original_tables = set(inspect(connection).get_table_names())
    migrate_readinglist = "readinglist" in original_tables and "storyarcs" not in original_tables
    metadata.create_all(connection, checkfirst=True)
    inspector = inspect(connection)
    for table in metadata.sorted_tables:
        existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            if not column.nullable and column.server_default is None:
                raise MigrationStateError(
                    "legacy adoption requires a value for %s.%s; run an explicit repair before upgrading"
                    % (table.name, column.name)
                )
            op.add_column(table.name, _copy_column_for_add(column))

    for table in metadata.sorted_tables:
        for index in table.indexes:
            index.create(connection, checkfirst=True)

    _add_missing_single_column_unique_constraints(connection)

    if migrate_readinglist:
        _migrate_readinglist_to_storyarcs(connection)

    import comicarr

    comicarr._migrate_unique_constraints(connection)

    _seed_acquisition_schema_ledger(connection)


def _migrate_readinglist_to_storyarcs(connection: Connection) -> None:
    """Move the one known reading-list layout without guessing at source data."""

    available_columns = {column["name"] for column in inspect(connection).get_columns("readinglist")}
    missing_columns = sorted(set(_READINGLIST_TO_STORYARCS_COLUMNS) - available_columns)
    if missing_columns:
        raise MigrationStateError(
            "readinglist does not match the supported legacy layout; missing columns: %s" % ", ".join(missing_columns)
        )
    quote = connection.dialect.identifier_preparer.quote
    columns = ", ".join(quote(column) for column in _READINGLIST_TO_STORYARCS_COLUMNS)
    connection.execute(
        text("INSERT INTO %s (%s) SELECT %s FROM %s" % (quote("storyarcs"), columns, columns, quote("readinglist")))
    )
    connection.execute(text("DROP TABLE readinglist"))


def _seed_acquisition_schema_ledger(connection: Connection) -> None:
    """Record the current acquisition shape inside the same Alembic connection."""

    from datetime import datetime, timezone

    from comicarr.app.acquisition.maintenance import (
        CONTROL_ID,
        RECONCILIATION_CONTROL_ID,
        SCHEMA_COMPONENT,
        SCHEMA_VERSION,
    )
    from comicarr.tables import acquisition_maintenance, acquisition_reconciliation, acquisition_schema_versions

    now = datetime.now(timezone.utc).isoformat()
    recorded_versions = set(
        connection.execute(
            select(acquisition_schema_versions.c.version).where(
                acquisition_schema_versions.c.component == SCHEMA_COMPONENT
            )
        ).scalars()
    )
    for version in range(1, SCHEMA_VERSION + 1):
        if version not in recorded_versions:
            connection.execute(
                insert(acquisition_schema_versions).values(
                    component=SCHEMA_COMPONENT,
                    version=version,
                    applied_at=now,
                )
            )

    if (
        connection.execute(
            select(acquisition_maintenance.c.control_id).where(acquisition_maintenance.c.control_id == CONTROL_ID)
        ).first()
        is None
    ):
        connection.execute(
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
    if (
        connection.execute(
            select(acquisition_reconciliation.c.control_id).where(
                acquisition_reconciliation.c.control_id == RECONCILIATION_CONTROL_ID
            )
        ).first()
        is None
    ):
        connection.execute(
            insert(acquisition_reconciliation).values(
                control_id=RECONCILIATION_CONTROL_ID,
                state="ready",
                reason=None,
                updated_at=now,
            )
        )


def upgrade_database(engine: Engine | None = None) -> str | None:
    """Adopt a recognized database and upgrade it to the reviewed Alembic head."""

    engine = engine or get_engine()
    state = classify_database(engine)
    with engine.connect() as connection:
        config = alembic_config(engine, connection)
        if state is DatabaseState.LEGACY:
            command.stamp(config, "0001_baseline")
        command.upgrade(config, "head")
    from comicarr.app.acquisition.maintenance import ensure_acquisition_schema

    acquisition_status = ensure_acquisition_schema(engine)
    if not acquisition_status.ready:
        raise RuntimeError("acquisition schema verification failed: %s" % acquisition_status.error)
    return current_revision(engine)
