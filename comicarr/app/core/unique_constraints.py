#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Unique-constraint migration for the upsert tables.

Called once, from revision ``0002_legacy_adoption`` through
``schema._adopt_legacy_database``: it removes duplicate rows a pre-Alembic
install may hold (keeping the best library copy), backs up SQLite first, and
adds the unique constraints ``db.upsert`` relies on. Moved here from the
package ``__init__`` (#1479); the behavior is unchanged.
"""

import glob
import hashlib
import os
import re
import shutil

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from comicarr.app.core import logger, runtime
from comicarr.app.system import maintenance

_UPSERT_UNIQUE_CONSTRAINT_NAMES = {
    "issues": "uq_issues_issueid",
    "annuals": "uq_annuals_issueid",
    "storyarcs": "uq_storyarcs_issuearcid",
    "readlist": "uq_readlist_issueid",
    "failed": "uq_failed_id_provider_nzbname",
    "upcoming": "uq_upcoming_comicid_issuenum",
    "nzblog": "uq_nzblog_issueid_provider",
    "importresults": "uq_importresults_impid",
    "jobhistory": "uq_jobhistory_jobname",
    "snatched": "uq_snatched_issue_status_provider",
    "oneoffhistory": "uq_oneoffhistory_comicid_issueid",
    "weekly": "uq_weekly_comicid_issueid",
}

_PRE_UNIQUE_MIGRATION_BACKUP = "comicarr.db.pre-unique-migration.bak"


def _build_upsert_unique_constraints():
    """Map allowlisted tables to (key_cols from UPSERT_KEYS, constraint name)."""
    from comicarr.app.core.tables import UPSERT_KEYS

    constraints = {}
    for table_name, constraint_name in _UPSERT_UNIQUE_CONSTRAINT_NAMES.items():
        key_cols = UPSERT_KEYS.get(table_name)
        if not key_cols:
            raise RuntimeError("[UNIQUE-MIGRATION] UPSERT_KEYS has no entry for allowlisted table %s" % table_name)
        constraints[table_name] = (list(key_cols), constraint_name)
    return constraints


_UPSERT_UNIQUE_CONSTRAINTS = _build_upsert_unique_constraints()


def _index_has_partial_predicate(index):
    dialect_options = index.get("dialect_options") or {}
    if any(name.endswith("_where") and value is not None for name, value in dialect_options.items()):
        return True
    return any(index.get(name) is not None for name in ("filter_definition", "predicate", "where"))


def _has_unique_enforcement(bind, table_name, key_cols):
    """Return whether a table has a unique constraint or index on ``key_cols``."""
    inspector = inspect(bind)
    expected_columns = tuple(sorted(key_cols))
    constraints = inspector.get_unique_constraints(table_name)
    constraint_columns = {tuple(sorted(constraint.get("column_names") or [])) for constraint in constraints}
    if expected_columns in constraint_columns:
        return True

    for index in inspector.get_indexes(table_name):
        index_columns = tuple(sorted(index.get("column_names") or []))
        if not index.get("unique") or index_columns != expected_columns:
            continue
        if bind.dialect.name != "sqlite":
            if not _index_has_partial_predicate(index):
                return True
            continue

        sqlite_where = (index.get("dialect_options") or {}).get("sqlite_where")
        if sqlite_where is None:
            if not _index_has_partial_predicate(index):
                return True
        elif _sqlite_valid_key_predicate_matches(sqlite_where, key_cols):
            return True

    return False


def _valid_key_predicate(columns):
    return " AND ".join(f"{column} IS NOT NULL AND {column} != ''" for column in columns)


def _canonical_sqlite_predicate(predicate):
    predicate_sql = re.sub(r'["`\[\]]', "", str(predicate))
    predicate_sql = predicate_sql.replace("<>", "!=")
    predicate_sql = re.sub(r"[()]", "", predicate_sql)
    predicate_sql = re.sub(r"\s*!=\s*", " != ", predicate_sql)
    return re.sub(r"\s+", " ", predicate_sql).strip().casefold()


def _sqlite_valid_key_predicate_matches(predicate, key_cols):
    expected_predicate = _valid_key_predicate(key_cols)
    return _canonical_sqlite_predicate(predicate) == _canonical_sqlite_predicate(expected_predicate)


def _sqlite_unique_index_sql(engine, table_name, key_cols, constraint_name):
    """Build a safely quoted partial UNIQUE index for valid legacy keys."""
    quote = engine.dialect.identifier_preparer.quote_identifier
    quoted_columns = [quote(column) for column in key_cols]
    valid_key_predicate = _valid_key_predicate(quoted_columns)
    return (
        f"CREATE UNIQUE INDEX {quote(constraint_name)} ON {quote(table_name)} "
        f"({', '.join(quoted_columns)}) WHERE {valid_key_predicate}"
    )


def _sqlite_database_path(engine, connection=None):
    database = engine.url.database
    database_name = str(database).casefold() if database else ""
    if not database or database_name == ":memory:":
        return None

    uri = engine.url.query.get("uri")
    uri_values = uri if isinstance(uri, (tuple, list)) else (uri,)
    uri_mode_enabled = any(
        value is not None and str(value).casefold() in {"1", "true", "yes", "on"} for value in uri_values
    )
    if not uri_mode_enabled:
        return os.path.abspath(os.path.expanduser(str(database)))

    if database_name.startswith("file:"):
        mode = engine.url.query.get("mode")
        mode_values = mode if isinstance(mode, (tuple, list)) else (mode,)
        if any(value is not None and str(value).casefold() == "memory" for value in mode_values):
            return None

        if database_name.startswith("file::memory:"):
            return None

    if connection is not None:
        for _sequence, schema_name, database_path in connection.exec_driver_sql("PRAGMA database_list"):
            if schema_name == "main" and database_path:
                return os.path.abspath(os.path.expanduser(database_path))
    else:
        with engine.connect() as conn:
            for _sequence, schema_name, database_path in conn.exec_driver_sql("PRAGMA database_list"):
                if schema_name == "main" and database_path:
                    return os.path.abspath(os.path.expanduser(database_path))
    return os.path.abspath(os.path.expanduser(str(database)))


def _row_identity_column(dialect):
    """Return the dialect-native physical row identity used for deduplication."""
    if dialect == "sqlite":
        return "rowid"
    if dialect == "postgresql":
        return "ctid"
    return None


_LIBRARY_QUALITY_DEDUP_TABLES = frozenset({"issues", "annuals", "readlist", "storyarcs"})


def _status_rank_sql(quoted_status_column):
    """Higher is better — prefer completed/on-disk states over Wanted stubs."""
    return (
        f"CASE {quoted_status_column} "
        f"WHEN 'Downloaded' THEN 50 "
        f"WHEN 'Archived' THEN 50 "
        f"WHEN 'Snatched' THEN 40 "
        f"WHEN 'Failed' THEN 20 "
        f"WHEN 'Wanted' THEN 10 "
        f"WHEN 'Skipped' THEN 10 "
        f"ELSE 15 END"
    )


def _library_quality_order_sql(quote, column_names, row_identity):
    """ORDER BY clause for library-quality survivor selection (DESC ranks first)."""
    columns = {name.casefold() for name in column_names}
    order_parts = []
    if "location" in columns:
        loc = quote("Location")
        order_parts.append(f"CASE WHEN {loc} IS NOT NULL AND {loc} != '' THEN 1 ELSE 0 END DESC")
    if "status" in columns:
        order_parts.append(f"{_status_rank_sql(quote('Status'))} DESC")
    order_parts.append(f"{row_identity} DESC")
    return ", ".join(order_parts)


def _dedup_delete_sql(
    dialect,
    quoted_table,
    quoted_keys,
    valid_key_predicate,
    table_name=None,
    column_names=None,
    quote=None,
):
    """Build DELETE that keeps one row per valid key group.

    Default is MAX(rowid/ctid). For library tables with Status/Location columns,
    prefer non-empty Location and stronger Status, then row identity.
    """
    row_identity = _row_identity_column(dialect)
    if row_identity is None:
        return None

    use_quality = (
        table_name in _LIBRARY_QUALITY_DEDUP_TABLES
        and column_names is not None
        and quote is not None
        and ({name.casefold() for name in column_names} & {"location", "status"})
    )
    if not use_quality:
        group_by = ", ".join(quoted_keys)
        return (
            f"DELETE FROM {quoted_table} WHERE {row_identity} NOT IN ("
            f"SELECT MAX({row_identity}) FROM {quoted_table} WHERE {valid_key_predicate} "
            f"GROUP BY {group_by}"
            f") AND {valid_key_predicate}"
        )

    partition = ", ".join(quoted_keys)
    order_by = _library_quality_order_sql(quote, column_names, row_identity)
    return (
        f"DELETE FROM {quoted_table} WHERE {row_identity} IN ("
        f"SELECT {row_identity} FROM ("
        f"SELECT {row_identity}, ROW_NUMBER() OVER ("
        f"PARTITION BY {partition} ORDER BY {order_by}"
        f") AS _comicarr_rn FROM {quoted_table} WHERE {valid_key_predicate}"
        f") AS _comicarr_ranked WHERE _comicarr_rn > 1"
        f")"
    )


def _mysql_dedup_valid_keys(conn, table_name, key_cols):
    """Remove duplicate valid-key rows on MySQL/MariaDB primary-less tables.

    Legacy Comicarr tables often lack a primary key, so MySQL has no rowid/ctid.
    For each valid key group with count C > 1, DELETE ... LIMIT C-1 keeps one
    arbitrary survivor. Must run in the same connection/transaction as ADD CONSTRAINT
    where the engine allows (MySQL DDL may still implicitly commit).
    """
    quote = conn.dialect.identifier_preparer.quote_identifier
    quoted_table = quote(table_name)
    quoted_keys = [quote(column) for column in key_cols]
    valid_key_predicate = _valid_key_predicate(quoted_keys)
    group_by = ", ".join(quoted_keys)

    dup_rows = (
        conn.execute(
            text(
                f"SELECT {group_by}, COUNT(*) AS _comicarr_cnt FROM {quoted_table} "
                f"WHERE {valid_key_predicate} "
                f"GROUP BY {group_by} HAVING COUNT(*) > 1"
            )
        )
        .mappings()
        .all()
    )

    for row in dup_rows:
        cnt = int(row["_comicarr_cnt"])
        if cnt < 2:
            continue
        predicates = []
        params = {}
        for index, column in enumerate(key_cols):
            param = f"k{index}"
            predicates.append(f"{quote(column)} = :{param}")
            params[param] = row[column]
        where_clause = " AND ".join(predicates) + " AND " + valid_key_predicate
        conn.execute(
            text(f"DELETE FROM {quoted_table} WHERE {where_clause} LIMIT {cnt - 1}"),
            params,
        )


def _add_unique_constraint_sql(quoted_table, quoted_constraint, quoted_keys):
    return f"ALTER TABLE {quoted_table} ADD CONSTRAINT {quoted_constraint} UNIQUE ({', '.join(quoted_keys)})"


def _backup_sqlite_unique_migration(engine, backup_func=None, connection=None):
    """Create the mandatory WAL-safe backup for a destructive SQLite migration.

    Backups are co-located with the live database file under
    ``<db-dir>/backups/migrations/``. A fixed-name pin
    (``comicarr.db.pre-unique-migration.bak``) is written once and preserved
    across retention rotation of timestamped backups.
    """
    source_path = _sqlite_database_path(engine, connection=connection)
    if source_path is None:
        return

    backup_dir = os.path.join(os.path.dirname(source_path), "backups", "migrations")
    pin_path = os.path.join(backup_dir, _PRE_UNIQUE_MIGRATION_BACKUP)
    abs_source = os.path.abspath(source_path)
    abs_backup_dir = os.path.abspath(backup_dir)
    abs_pin = os.path.abspath(pin_path)

    logger.info(
        "[UNIQUE-MIGRATION] Pre-migration backup source=%s dest_dir=%s pin=%s",
        abs_source,
        abs_backup_dir,
        abs_pin,
    )

    if os.path.isfile(pin_path):
        logger.info(
            "[UNIQUE-MIGRATION] Reusing existing pre-unique-migration pin backup at %s",
            abs_pin,
        )
        return

    config = runtime.current().config
    retention = getattr(config, "BACKUP_RETENTION", 4) if config is not None else 4
    retention = retention or 4
    backup = backup_func or maintenance.auto_backup_db

    try:
        backup_succeeded = backup(source_path, backup_dir, retention)
    except Exception as e:
        message = "SQLite unique-constraint backup failed before migration"
        logger.error("[UNIQUE-MIGRATION] %s: %s", message, e)
        raise RuntimeError(message) from e

    if not backup_succeeded:
        message = "SQLite unique-constraint backup failed; migration was not started"
        logger.error("[UNIQUE-MIGRATION] %s", message)
        raise RuntimeError(message)

    if not os.path.isfile(pin_path):
        timestamped = sorted(
            path
            for path in glob.glob(os.path.join(backup_dir, "comicarr.db.*.bak"))
            if re.match(r"^comicarr\.db\.\d{8}_\d{6}\.bak$", os.path.basename(path))
        )
        if timestamped:
            try:
                shutil.copy2(timestamped[-1], pin_path)
                logger.info("[UNIQUE-MIGRATION] Wrote pre-unique-migration pin backup to %s", abs_pin)
            except OSError as e:
                message = "SQLite unique-constraint pin backup failed before migration"
                logger.error("[UNIQUE-MIGRATION] %s: %s", message, e)
                raise RuntimeError(message) from e


def _pending_unique_constraints(bind):
    pending = []
    inspector = inspect(bind)
    for table_name, (key_cols, constraint_name) in _UPSERT_UNIQUE_CONSTRAINTS.items():
        try:
            if not inspector.has_table(table_name):
                continue
            if not _has_unique_enforcement(bind, table_name, key_cols):
                pending.append((table_name, key_cols, constraint_name))
        except SQLAlchemyError as e:
            logger.warn("[UNIQUE-MIGRATION] Could not inspect UNIQUE enforcement for %s: %s", table_name, e)
    return pending


def _remaining_unenforced_tables(bind, pending_constraints):
    """Return allowlisted table names from ``pending_constraints`` still lacking enforcement."""
    remaining = []
    for table_name, key_cols, _constraint_name in pending_constraints:
        try:
            if not inspect(bind).has_table(table_name):
                continue
            if not _has_unique_enforcement(bind, table_name, key_cols):
                remaining.append(table_name)
        except SQLAlchemyError as e:
            logger.warn(
                "[UNIQUE-MIGRATION] Could not verify UNIQUE enforcement for %s after migration: %s",
                table_name,
                e,
            )
            remaining.append(table_name)
    return remaining


def _bounded_alternate_index_name(engine, constraint_name, table_name, key_cols, attempt):
    max_length = max(int(getattr(engine.dialect, "max_identifier_length", 128) or 128), 1)
    identity = f"{table_name}|{','.join(key_cols)}|{attempt}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    suffix = f"_ca_{digest}"
    if len(suffix) >= max_length:
        return digest[:max_length]
    return f"{constraint_name[: max_length - len(suffix)]}{suffix}"


def _sqlite_available_index_name(engine, constraint_name, table_name, key_cols, connection=None):
    if connection is not None:
        existing_names = {
            str(name).casefold()
            for name in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'index' AND name IS NOT NULL")
            ).scalars()
        }
    else:
        with engine.connect() as conn:
            existing_names = {
                str(name).casefold()
                for name in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'index' AND name IS NOT NULL")
                ).scalars()
            }

    max_length = max(int(getattr(engine.dialect, "max_identifier_length", 128) or 128), 1)
    if len(constraint_name) <= max_length and constraint_name.casefold() not in existing_names:
        return constraint_name

    for attempt in range(100):
        candidate = _bounded_alternate_index_name(engine, constraint_name, table_name, key_cols, attempt)
        if candidate.casefold() not in existing_names:
            return candidate
    raise RuntimeError(f"Could not allocate a unique index name for {table_name}")


def _migrate_unique_constraints(engine_or_connection, backup_func=None):
    """Install the unique enforcement required by atomic upserts.

    Legacy SQLite databases receive partial unique indexes so duplicate null or
    empty keys remain valid. File-backed databases are backed up once after
    preflight and before the first deduplication. Each table's deterministic
    deduplication and index creation share one transaction, ensuring a failed
    DDL statement restores the rows deleted by that attempt.

    After the per-table loop, any still-pending tables cause a RuntimeError so
    startup fails closed rather than soft-succeeding without enforcement.
    """
    connection = engine_or_connection if hasattr(engine_or_connection, "exec_driver_sql") else None
    engine = connection.engine if connection is not None else engine_or_connection
    bind = connection or engine
    dialect = bind.dialect.name

    pending_constraints = _pending_unique_constraints(bind)
    if not pending_constraints:
        return

    if dialect == "sqlite":
        _backup_sqlite_unique_migration(engine, backup_func, connection=connection)

    for table_name, key_cols, constraint_name in pending_constraints:
        try:
            if _has_unique_enforcement(bind, table_name, key_cols):
                continue
        except SQLAlchemyError as e:
            logger.warn(
                "[UNIQUE-MIGRATION] Could not recheck UNIQUE enforcement for %s; proceeding with migration: %s",
                table_name,
                e,
            )

        quote = bind.dialect.identifier_preparer.quote_identifier
        quoted_table = quote(table_name)
        quoted_keys = [quote(column) for column in key_cols]
        valid_key_predicate = _valid_key_predicate(quoted_keys)
        try:
            column_names = [col["name"] for col in inspect(bind).get_columns(table_name)]
        except SQLAlchemyError:
            column_names = []
        dedup_sql = _dedup_delete_sql(
            dialect,
            quoted_table,
            quoted_keys,
            valid_key_predicate,
            table_name=table_name,
            column_names=column_names,
            quote=quote,
        )
        constraint_sql = _add_unique_constraint_sql(quoted_table, quote(constraint_name), quoted_keys)
        index_name = constraint_name
        index_sql = None

        if dialect == "sqlite":
            index_name = _sqlite_available_index_name(
                engine,
                constraint_name,
                table_name,
                key_cols,
                connection=connection,
            )
            index_sql = _sqlite_unique_index_sql(engine, table_name, key_cols, index_name)

        def install_unique_enforcement(
            active_connection,
            dialect=dialect,
            dedup_sql=dedup_sql,
            index_sql=index_sql,
            constraint_sql=constraint_sql,
            table_name=table_name,
            key_cols=key_cols,
        ):
            if dialect == "sqlite":
                active_connection.execute(text(dedup_sql))
                active_connection.execute(text(index_sql))
            elif dialect == "postgresql":
                active_connection.execute(text(dedup_sql))
                active_connection.execute(text(constraint_sql))
            elif dialect == "mysql":
                _mysql_dedup_valid_keys(active_connection, table_name, key_cols)
                active_connection.execute(text(constraint_sql))

        if dialect not in {"sqlite", "postgresql", "mysql"}:
            logger.warn(
                "[UNIQUE-MIGRATION] Unsupported dialect %s for unique-constraint migration on %s",
                dialect,
                table_name,
            )
            continue

        if connection is not None:
            try:
                install_unique_enforcement(connection)
            except SQLAlchemyError as e:
                message = "Could not add UNIQUE enforcement %s on %s" % (constraint_name, table_name)
                logger.error(
                    "[UNIQUE-MIGRATION] %s using the active Alembic connection: %s",
                    message,
                    e,
                )
                raise RuntimeError(message) from e
        else:
            try:
                with engine.begin() as active_connection:
                    install_unique_enforcement(active_connection)
            except SQLAlchemyError as e:
                logger.warn(
                    "[UNIQUE-MIGRATION] Could not add UNIQUE enforcement %s on %s; changes rolled back: %s",
                    index_name,
                    table_name,
                    e,
                )
                continue

        try:
            constraint_installed = _has_unique_enforcement(bind, table_name, key_cols)
        except SQLAlchemyError as e:
            logger.warn("[UNIQUE-MIGRATION] Could not verify UNIQUE enforcement for %s: %s", table_name, e)
            continue

        if constraint_installed:
            logger.info(
                "[UNIQUE-MIGRATION] Added UNIQUE enforcement %s on %s(%s)",
                index_name,
                table_name,
                ", ".join(key_cols),
            )
        else:
            logger.warn(
                "[UNIQUE-MIGRATION] UNIQUE enforcement %s on %s was not installed",
                constraint_name,
                table_name,
            )

    remaining = _remaining_unenforced_tables(bind, pending_constraints)
    if remaining:
        message = "Unique-constraint migration incomplete for: %s" % ", ".join(remaining)
        logger.error("[UNIQUE-MIGRATION] %s", message)
        raise RuntimeError(message)
