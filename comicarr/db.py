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
  - DBConnection      — deprecated compatibility shim for legacy raw-SQL callers

The compatibility shim (DBConnection) translates raw SQL with ? placeholders
to SQLAlchemy text() queries with :param_N named parameters. It will be
removed once all callers are migrated to SQLAlchemy Core expressions.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import TYPE_CHECKING, Any

import sqlalchemy
from sqlalchemy import create_engine, event, func, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

if TYPE_CHECKING:
    from sqlalchemy import Column
    from sqlalchemy.engine import Connection, Engine
    from sqlalchemy.sql.expression import BinaryExpression

import comicarr
from comicarr import logger
from comicarr.tables import TABLE_MAP, UPSERT_KEYS

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_engine = None
_engine_lock = threading.Lock()

# Retained only for DBConnection.action() write serialization during shim period.
# Remove together with DBConnection once all callers are migrated.
_db_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Engine management
# ---------------------------------------------------------------------------


def _get_database_url() -> str:
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


def _mask_password(url: str) -> str:
    """Mask password in database URL for logging."""
    try:
        u = make_url(url)
        return u.render_as_string(hide_password=True)
    except Exception:
        return re.sub(r"(://[^:]+:)(.+)@", r"\1***@", url)


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


def get_engine() -> Engine:
    """Get or create the global SQLAlchemy Engine."""
    global _engine
    if _engine is not None:
        return _engine

    with _engine_lock:
        if _engine is not None:
            return _engine

        url = _get_database_url()
        dialect = make_url(url).get_backend_name()

        kwargs = {
            "query_cache_size": 1500,
        }

        if dialect == "sqlite":
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 20}
            # QueuePool is the SQLAlchemy 2.x default for file-based SQLite
        else:
            # PostgreSQL / MySQL
            kwargs["pool_size"] = 5
            kwargs["max_overflow"] = 5
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


def shutdown_engine() -> None:
    """Dispose of the engine and all pooled connections."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
        logger.fdebug("Database engine shut down.")


def get_connection() -> Connection:
    """Context manager yielding a SQLAlchemy Connection."""
    return get_engine().connect()


def get_dialect() -> str:
    """Return the dialect name: 'sqlite', 'postgresql', or 'mysql'."""
    return get_engine().dialect.name


# ---------------------------------------------------------------------------
# Public query helpers (used by all modules instead of local copies)
# ---------------------------------------------------------------------------


def select_all(stmt):
    """Execute a SELECT statement and return all rows as list of dicts."""
    with get_engine().connect() as conn:
        result = conn.execute(stmt)
        return [dict(row._mapping) for row in result]


def select_one(stmt):
    """Execute a SELECT statement and return the first row as dict, or None."""
    with get_engine().connect() as conn:
        result = conn.execute(stmt)
        row = result.fetchone()
        return dict(row._mapping) if row is not None else None


def raw_select_all(sql, args=None):
    """Execute raw SQL with ? placeholders and return all rows as list of dicts."""
    converted, params = _convert_positional_to_named(sql, args)
    with get_engine().connect() as conn:
        result = conn.execute(text(converted), params)
        return [dict(row._mapping) for row in result]


def raw_select_one(sql, args=None):
    """Execute raw SQL with ? placeholders and return the first row as dict, or None."""
    converted, params = _convert_positional_to_named(sql, args)
    with get_engine().connect() as conn:
        result = conn.execute(text(converted), params)
        row = result.fetchone()
        return dict(row._mapping) if row is not None else None


def raw_execute(sql, args=None, executemany=False):
    """Execute a raw SQL write statement with ? placeholders inside a transaction."""
    converted, params = _convert_positional_to_named(sql, args)
    with get_engine().begin() as conn:
        if executemany and args is not None:
            if isinstance(args, list) and args and isinstance(args[0], (list, tuple)):
                params_list = [{f"param_{i}": v for i, v in enumerate(row)} for row in args]
            else:
                params_list = args
            return conn.execute(text(converted), params_list)
        return conn.execute(text(converted), params)



# ---------------------------------------------------------------------------
# Portable helpers
# ---------------------------------------------------------------------------


def ci_compare(column: Column, value: Any) -> BinaryExpression:
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


def upsert(table_name: str, value_dict: dict, key_dict: dict) -> None:
    """Dialect-aware atomic upsert.

    Uses ON CONFLICT DO UPDATE (SQLite/PostgreSQL) or
    ON DUPLICATE KEY UPDATE (MySQL) for atomicity.
    """
    table = TABLE_MAP.get(table_name)
    if table is None:
        raise ValueError(f"Unknown table for upsert: {table_name}")

    upsert_keys = UPSERT_KEYS.get(table_name)
    if upsert_keys is None:
        raise ValueError(f"Unknown table for upsert: {table_name}")

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
        raise ValueError(f"Unsupported dialect for upsert: {dialect}")

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
    else:
        raise OperationalError(f"Upsert on {table_name} failed after 5 retries", None, None)


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
# DBConnection -- deprecated compatibility shim
# ---------------------------------------------------------------------------
# DEPRECATED: This class is a legacy compatibility shim. All new code should
# use SQLAlchemy Core expressions via get_engine()/get_connection() directly,
# or the public helpers (select_all, select_one, raw_select_all, etc.) above.
# This class will be removed once all callers have been migrated.


class DBConnection:
    """Deprecated compatibility shim wrapping SQLAlchemy for legacy raw-SQL callers.

    Translates ? placeholders to named params, executes via text(),
    returns results as lists of dicts (preserving row["ColumnName"] access).

    .. deprecated::
        Will be removed after Phase 2 query migration is complete.
        Use SQLAlchemy Core expressions or the public helpers instead.
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
        with _db_lock:
            if query is None:
                return

            converted, _ = _convert_positional_to_named(query)
            attempt = 0

            while attempt < 5:
                try:
                    with get_engine().begin() as conn:
                        if executemany and args is not None:
                            # Convert list of tuples to list of dicts
                            param_names = [f"param_{i}" for i in range(converted.count(":param_"))]
                            if not param_names:
                                # Count params from the converted query
                                import re as _re

                                param_names = [m.group(0).lstrip(":") for m in _re.finditer(r":param_\d+", converted)]
                            if isinstance(args, list) and args and isinstance(args[0], (list, tuple)):
                                params_list = [{f"param_{i}": v for i, v in enumerate(row)} for row in args]
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
