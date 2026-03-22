#  Copyright (C) 2012–2024 Mylar3 contributors
#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Originally based on Mylar3 (https://github.com/mylar3/mylar3).
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Database connection handler using SQLAlchemy Core.

Provides:
  - get_engine()      — lazily creates the SQLAlchemy Engine
  - get_connection()  — context manager yielding a Connection
  - get_dialect()     — returns "sqlite" | "postgresql" | "mysql"
  - upsert()          — dialect-aware atomic upsert
  - ci_compare()      — dialect-aware case-insensitive comparison
  - DBConnection      — compatibility shim for legacy raw-SQL callers

The compatibility shim (DBConnection) translates raw SQL with ? placeholders
to SQLAlchemy text() queries with :param_N named parameters. It will be
removed once all callers are migrated to SQLAlchemy Core expressions.
"""

import os
import re
import threading
import time

import sqlalchemy
from sqlalchemy import create_engine, event, func, text
from sqlalchemy.exc import OperationalError

import comicarr
from comicarr import logger
from comicarr.tables import TABLE_MAP, UPSERT_KEYS

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_engine = None
_engine_lock = threading.Lock()

# Retained during shim period for SQLite write serialization.
# Removed after all upsert calls use atomic ON CONFLICT.
db_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Engine management
# ---------------------------------------------------------------------------


def _get_database_url():
    """Build database URL from config or environment."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    if hasattr(comicarr, "CONFIG") and comicarr.CONFIG is not None:
        config_url = getattr(comicarr.CONFIG, "DATABASE_URL", None)
        if config_url:
            return config_url

    # Default: SQLite in DATA_DIR
    db_path = os.path.join(comicarr.DATA_DIR, "comicarr.db")
    return f"sqlite:///{db_path}"


def _mask_password(url):
    """Mask password in database URL for logging."""
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", url)


def _apply_sqlite_pragmas(dbapi_conn, _connection_record):
    """Set SQLite PRAGMAs on every new connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA busy_timeout = 15000")
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute("PRAGMA mmap_size = 67108864")  # 64MB
    cursor.execute("PRAGMA journal_size_limit = 67108864")  # 64MB
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA cache_size = -64000")  # 64MB
    cursor.close()


def get_engine():
    """Get or create the global SQLAlchemy Engine."""
    global _engine
    if _engine is not None:
        return _engine

    with _engine_lock:
        if _engine is not None:
            return _engine

        url = _get_database_url()
        dialect = url.split("://")[0].split("+")[0] if "://" in url else "sqlite"

        kwargs = {
            "query_cache_size": 1500,
        }

        if dialect == "sqlite":
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 20}
            # QueuePool is the SQLAlchemy 2.x default for file-based SQLite
        else:
            # PostgreSQL / MySQL
            kwargs["pool_size"] = 2
            kwargs["max_overflow"] = 3
            kwargs["pool_pre_ping"] = True
            kwargs["pool_recycle"] = 1800

            # Warn if non-localhost without SSL
            if dialect in ("postgresql", "mysql") and "@" in url:
                host_part = url.split("@")[1].split("/")[0].split(":")[0]
                if host_part not in ("localhost", "127.0.0.1", "::1"):
                    ssl_indicators = ("sslmode=", "ssl=", "ssl_ca=", "ssl_cert=")
                    if not any(s in url for s in ssl_indicators):
                        logger.warn(
                            "Database URL connects to non-localhost host '%s' without SSL parameters. "
                            "Consider adding ?sslmode=require for PostgreSQL or ?ssl=true for MySQL.",
                            host_part,
                        )

        logger.fdebug("Initializing database engine: %s", _mask_password(url))
        _engine = create_engine(url, **kwargs)

        # SQLite PRAGMA listener
        if dialect == "sqlite":
            event.listen(_engine, "connect", _apply_sqlite_pragmas)

        return _engine


def shutdown_engine():
    """Dispose of the engine and all pooled connections."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
        logger.fdebug("Database engine shut down.")


def get_connection():
    """Context manager yielding a SQLAlchemy Connection."""
    return get_engine().connect()


def get_dialect():
    """Return the dialect name: 'sqlite', 'postgresql', or 'mysql'."""
    return get_engine().dialect.name


# ---------------------------------------------------------------------------
# Portable helpers
# ---------------------------------------------------------------------------


def ci_compare(column, value):
    """Build a dialect-aware case-insensitive comparison expression.

    - SQLite: plain == (relies on COLLATE NOCASE on column/index)
    - PostgreSQL: func.lower() on both sides
    - MySQL: plain == (utf8mb4_general_ci is case-insensitive by default)
    """
    dialect = get_dialect()
    if dialect == "postgresql":
        return func.lower(column) == func.lower(value)
    # sqlite and mysql: default collation handles case
    return column == value


def upsert(table_name, value_dict, key_dict):
    """Dialect-aware atomic upsert.

    Uses ON CONFLICT DO UPDATE (SQLite/PostgreSQL) or
    ON DUPLICATE KEY UPDATE (MySQL) for atomicity.

    Falls back to db_lock-protected UPDATE-then-INSERT for tables
    not yet in TABLE_MAP (should not happen after tables.py is complete).
    """
    table = TABLE_MAP.get(table_name)
    if table is None:
        # Fallback for unknown tables — uses legacy pattern under lock
        _upsert_legacy(table_name, value_dict, key_dict)
        return

    upsert_keys = UPSERT_KEYS.get(table_name)
    if upsert_keys is None:
        _upsert_legacy(table_name, value_dict, key_dict)
        return

    all_values = {**value_dict, **key_dict}
    dialect = get_dialect()

    if dialect in ("sqlite", "postgresql"):
        if dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as dialect_insert
        else:
            from sqlalchemy.dialects.postgresql import insert as dialect_insert

        stmt = dialect_insert(table).values(**all_values)
        stmt = stmt.on_conflict_do_update(
            index_elements=upsert_keys,
            set_=value_dict,
        )
    elif dialect == "mysql":
        from sqlalchemy.dialects.mysql import insert as dialect_insert

        stmt = dialect_insert(table).values(**all_values)
        stmt = stmt.on_duplicate_key_update(**value_dict)
    else:
        _upsert_legacy(table_name, value_dict, key_dict)
        return

    attempt = 0
    while attempt < 5:
        try:
            with get_engine().begin() as conn:
                conn.execute(stmt)
            return
        except OperationalError as e:
            err_msg = str(e)
            if "locked" in err_msg or "unable to open" in err_msg:
                logger.warn("Database locked during upsert, retry %d: %s", attempt + 1, e)
                attempt += 1
                time.sleep(1)
            else:
                logger.error("Database error during upsert on %s: %s", table_name, e)
                raise


def _upsert_legacy(table_name, value_dict, key_dict):
    """Legacy UPDATE-then-INSERT upsert under db_lock."""
    with db_lock:

        def gen_params(d):
            return [f"{k} = :_p_{k}" for k in d]

        update_query = (
            f"UPDATE {table_name} SET "
            + ", ".join(gen_params(value_dict))
            + " WHERE "
            + " AND ".join(gen_params(key_dict))
        )
        update_params = {f"_p_{k}": v for k, v in {**value_dict, **key_dict}.items()}

        attempt = 0
        while attempt < 5:
            try:
                with get_engine().begin() as conn:
                    result = conn.execute(text(update_query), update_params)
                    if result.rowcount == 0:
                        all_cols = {**value_dict, **key_dict}
                        cols = ", ".join(all_cols.keys())
                        placeholders = ", ".join(f":_p_{k}" for k in all_cols)
                        insert_query = f"INSERT INTO {table_name} ({cols}) VALUES ({placeholders})"
                        insert_params = {f"_p_{k}": v for k, v in all_cols.items()}
                        conn.execute(text(insert_query), insert_params)
                return
            except OperationalError as e:
                err_msg = str(e)
                if "locked" in err_msg or "unable to open" in err_msg:
                    logger.warn("Database locked during legacy upsert, retry %d: %s", attempt + 1, e)
                    attempt += 1
                    time.sleep(1)
                else:
                    logger.error("Database error in legacy upsert on %s: %s", table_name, e)
                    raise


# ---------------------------------------------------------------------------
# Query parameter conversion (? -> :param_N)
# ---------------------------------------------------------------------------


def _convert_positional_to_named(query, args=None):
    """Convert ? placeholders to :param_N named parameters.

    Uses a state machine to skip ? inside single-quoted strings.
    Returns (converted_query, params_dict).
    """
    result = []
    param_index = 0
    in_string = False
    i = 0
    while i < len(query):
        char = query[i]
        if char == "'" and not in_string:
            in_string = True
        elif char == "'" and in_string:
            if i + 1 < len(query) and query[i + 1] == "'":
                result.append("''")
                i += 2
                continue
            in_string = False
        elif char == "?" and not in_string:
            result.append(f":param_{param_index}")
            param_index += 1
            i += 1
            continue
        result.append(char)
        i += 1

    converted = "".join(result)

    if args is None:
        return converted, {}

    if isinstance(args, (list, tuple)):
        return converted, {f"param_{i}": v for i, v in enumerate(args)}

    return converted, args


# ---------------------------------------------------------------------------
# DBConnection — compatibility shim
# ---------------------------------------------------------------------------


def dbFilename(filename="comicarr.db"):
    return os.path.join(comicarr.DATA_DIR, filename)


class DBConnection:
    """Compatibility shim wrapping SQLAlchemy for legacy raw-SQL callers.

    Translates ? placeholders to named params, executes via text(),
    returns results as lists of dicts (preserving row["ColumnName"] access).

    Will be removed after Phase 2 query migration is complete.
    """

    def __init__(self, filename="comicarr.db"):
        self.filename = filename

    def fetch(self, query, args=None):
        if query is None:
            return None

        converted, params = _convert_positional_to_named(query, args)
        attempt = 0

        while attempt < 5:
            try:
                with get_engine().connect() as conn:
                    result = conn.execute(text(converted), params)
                    # Return a list of dicts for compatibility with sqlite3.Row access
                    rows = [dict(row._mapping) for row in result]
                    return rows
            except OperationalError as e:
                err_msg = str(e)
                if "unable to open" in err_msg or "locked" in err_msg:
                    logger.warn("Database Error: %s", e)
                    attempt += 1
                    time.sleep(1)
                else:
                    logger.warn("DB error: %s", e)
                    raise
            except sqlalchemy.exc.DatabaseError as e:
                logger.error("Fatal error executing query: %s", e)
                raise
        return None

    def action(self, query, args=None, executemany=False):
        with db_lock:
            if query is None:
                return

            converted, _ = _convert_positional_to_named(query)
            attempt = 0

            while attempt < 5:
                try:
                    with get_engine().begin() as conn:
                        if executemany and args is not None:
                            # Convert list of tuples to list of dicts
                            param_names = [
                                f"param_{i}"
                                for i in range(converted.count(":param_"))
                            ]
                            if not param_names:
                                # Count params from the converted query
                                import re as _re

                                param_names = [
                                    m.group(0).lstrip(":")
                                    for m in _re.finditer(r":param_\d+", converted)
                                ]
                            if isinstance(args, list) and args and isinstance(args[0], (list, tuple)):
                                params_list = [
                                    {f"param_{i}": v for i, v in enumerate(row)}
                                    for row in args
                                ]
                            else:
                                params_list = args
                            conn.execute(text(converted), params_list)
                        elif args is not None:
                            _, params = _convert_positional_to_named(query, args)
                            conn.execute(text(converted), params)
                        else:
                            conn.execute(text(converted))
                    return
                except OperationalError as e:
                    err_msg = str(e)
                    if "unable to open" in err_msg or "locked" in err_msg:
                        logger.warn("Database Error: %s", e)
                        logger.warn("sqlresult: %s", query)
                        attempt += 1
                        time.sleep(1)
                    else:
                        logger.error("Database error executing %s :: %s", query, e)
                        raise

    def select(self, query, args=None):
        rows = self.fetch(query, args)
        if rows is None:
            return []
        return rows

    def selectone(self, query, args=None):
        rows = self.fetch(query, args)
        if rows is None:
            return []
        if not rows:
            return []
        return rows[0]

    def upsert(self, tableName, valueDict, keyDict):
        upsert(tableName, valueDict, keyDict)
