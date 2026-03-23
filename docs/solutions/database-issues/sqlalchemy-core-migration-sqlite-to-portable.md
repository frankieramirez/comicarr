---
title: "SQLAlchemy Core 2.x Migration: Replacing 1,051 Raw SQLite Queries for Multi-Database Support"
category: database-issues
date: 2026-03-22
tags:
  - sqlalchemy
  - sqlite
  - postgresql
  - mysql
  - database-migration
  - python
  - cherrypy
  - multi-database
  - connection-pooling
  - upsert
severity: major
component: database-layer
symptoms:
  - application locked to SQLite with no multi-database support
  - 1,051 raw SQL queries scattered across 39 source files
  - custom thread-local connection pool with no pooling standards
  - SQLite-specific syntax incompatible with PostgreSQL or MySQL
  - production data contained duplicates blocking UNIQUE constraint creation
---

## Problem

Comicarr was hardcoded to SQLite with 1,051 raw SQL queries across 39 files, a custom thread-local connection pool in `db.py`, and SQLite-specific syntax throughout (`IS NOT "deleted"`, `COLLATE NOCASE`, `INSERT OR IGNORE`, `SUBSTR(x,-2)`, `||` concatenation). Self-hosters running PostgreSQL or MySQL infrastructure had no option to use their preferred database. The application was deployed to a Synology NAS with SQLite as the production database (auto memory [claude]).

## Root Cause

No database abstraction layer existed. `db.py` used `sqlite3` directly with raw string queries everywhere. Schema management used raw DDL strings via 147 try/except ALTER TABLE blocks. The upsert pattern (`INSERT OR REPLACE`) was SQLite-only. No portability was designed in from the start.

## Solution

Multi-phase migration to SQLAlchemy Core 2.x (PR #45, 36 files changed, +5,767/-3,392 lines):

### Phase 1: Foundation

**`comicarr/tables.py`** — 24 declarative table definitions with UNIQUE constraints, indexes, and auto-derived `UPSERT_KEYS`:

```python
from sqlalchemy import MetaData, Table, Column, Text, Integer, UniqueConstraint

metadata = MetaData()

comics = Table("comics", metadata,
    Column("ComicID", Text, unique=True),
    Column("ComicName", Text),
    # ... 55 columns total
)

issues = Table("issues", metadata,
    Column("IssueID", Text),
    Column("ComicID", Text),
    # ...
    UniqueConstraint("IssueID", name="uq_issues_issueid"),
)

# Auto-derive upsert keys from UniqueConstraint metadata
def _derive_upsert_keys():
    keys = {}
    for name, table in TABLE_MAP.items():
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint) and constraint.name:
                keys[name] = [col.name for col in constraint.columns]
                break
    return keys

UPSERT_KEYS = _derive_upsert_keys()
```

**`comicarr/db.py`** — SQLAlchemy Engine with dialect-aware helpers:

```python
from sqlalchemy import create_engine, func
from sqlalchemy.engine import make_url

def get_engine() -> Engine:
    url = os.environ.get("DATABASE_URL") or config_url or f"sqlite:///{db_path}"
    dialect = make_url(url).get_backend_name()
    kwargs = {"query_cache_size": 1500}
    if dialect == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 20}
    else:
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 5
        kwargs["pool_pre_ping"] = True
    return create_engine(url, **kwargs)

def upsert(table_name: str, value_dict: dict, key_dict: dict) -> None:
    """Dialect-aware atomic upsert."""
    if dialect in ("sqlite", "postgresql"):
        stmt = dialect_insert(table).values(**all_values)
        stmt = stmt.on_conflict_do_update(index_elements=upsert_keys, set_=value_dict)
    elif dialect == "mysql":
        stmt = dialect_insert(table).values(**all_values)
        stmt = stmt.on_duplicate_key_update(**value_dict)

def ci_compare(column, value):
    """Portable case-insensitive comparison."""
    if dialect == "postgresql":
        return func.lower(column) == func.lower(value)
    return column == value  # SQLite COLLATE NOCASE / MySQL utf8mb4_general_ci

# Centralized query helpers (replaced 8 duplicate copies across files)
def select_all(stmt): ...
def select_one(stmt): ...
def raw_select_all(sql, args=None): ...
```

**`dbcheck()`** rewritten to use `metadata.create_all(engine)` + `inspect()`-based column migration replacing 147 try/except blocks.

### Phase 2: Query Migration (33 files)

Every raw SQL string replaced with SQLAlchemy Core expressions:

```python
# Before:
myDB = db.DBConnection()
myDB.select("SELECT * FROM comics WHERE Status = ?", ["Wanted"])

# After:
from sqlalchemy import select
from comicarr.tables import comics
stmt = select(comics).where(comics.c.Status == "Wanted")
results = db.select_all(stmt)
```

Key conversions:
- `SUBSTR('0' || col, -2)` -> `func.right(func.concat('0', col), 2)`
- `COLLATE NOCASE` -> `ci_compare()` or `column.ilike()`
- `INSERT OR IGNORE` -> `on_conflict_do_nothing()`
- `IS NOT "deleted"` -> `!= 'deleted'` (double quotes = column identifier in PostgreSQL)
- `executemany` -> `conn.execute(stmt, list_of_dicts)` with `bindparam`
- VariableTable in rsscheck.py -> `TEMPORARY TABLE` within single connection context

### Phase 3: Migration Tool (`db_migrate.py`)

CLI tool for SQLite-to-target migration with data cleaning:

```bash
python3 Comicarr.py migrate \
  --from sqlite:///data/comicarr.db \
  --to postgresql://user:pass@localhost/comicarr \
  --yes
```

Features: batch inserts (5000 rows), string `"None"` -> NULL, empty INT -> NULL, dedup during migration, post-migration row count verification.

### Code Review Fixes (P1-P3)

- `_mask_password()` -> `make_url().render_as_string(hide_password=True)` (regex failed on `@` in passwords)
- Retry exhaustion now raises `OperationalError` instead of silent data loss
- Centralized 8 duplicate `_select_all`/`_select_one` into `db.py`
- Pool size increased from 2 -> 5 for PostgreSQL/MySQL
- N+1 query in updater.py replaced with `column.in_()` clause
- Type hints added to all public API functions
- `UPSERT_KEYS` auto-derived from `UniqueConstraint` metadata
- Backup operations guarded with dialect check

## Investigation Steps Tried

1. **Phase 0 audit**: Ran duplicate analysis against production `mylar.db` — found duplicates in `weekly` (15 rows) and `jobhistory` (1 row). No string "None" sentinels or type mismatches found.
2. **Schema extraction**: Dumped `.schema` for all 24 tables from production DB to build `tables.py`.
3. **Upsert call site audit**: Found 80+ upsert calls across 20 files, documented key columns per table.
4. **SQLite syntax catalog**: Identified all SQLite-specific constructs (IS NOT "deleted", COLLATE NOCASE, INSERT OR IGNORE, SUBSTR negative index, || concatenation, PRAGMA table_info).
5. **Migration order**: Simple files first (failed.py, readinglist.py) to validate patterns before high-impact files (webserve.py with 251 queries).

## Known Limitations

- `webserve.py` still has ~237 raw SQL calls routed through `raw_select_all()`/`raw_select_one()` — functionally correct but not fully portable to PostgreSQL/MySQL if SQLite-specific syntax remains in those strings.
- No actual PostgreSQL or MySQL testing done — only SQLite-to-SQLite migration was validated.
- `cv_cache.py` and `lib/comictaggerlib/` remain SQLite-only (intentionally excluded).

## Prevention: Gotchas for Similar Migrations

1. **`IS NOT "string"` is not a NULL check** — in PostgreSQL, double quotes denote column identifiers. `IS NOT "deleted"` compares to a column named `deleted`, not the string value.
2. **`SUBSTR(x, -2)` negative offsets** are undefined in ANSI SQL. Use `func.right(x, 2)`.
3. **`||` concatenation** does not exist in MySQL. Use `func.concat()`.
4. **`sqlite3.Row` is case-insensitive**, SQLAlchemy `Row._mapping` is case-sensitive. `row["comicid"]` works in sqlite3 but returns `KeyError` in SQLAlchemy if the column is `ComicID`.
5. **Production data has duplicates** — always run `GROUP BY ... HAVING COUNT(*) > 1` before adding UNIQUE constraints.
6. **Password masking regex** — never use `@` as a delimiter. Use `make_url().render_as_string(hide_password=True)`.
7. **Silent retry exhaustion** — every retry loop must raise or log on exhaustion, never silently return.
8. **`text()` wrapping is not migration** — it's a deferral. Track it as explicit tech debt.
9. **Test against real target databases in CI** — SQLite-only testing does not validate PostgreSQL/MySQL compatibility.
10. **Centralize helpers from day one** — duplicated `_select_all` across 8 files creates maintenance burden during migration.

## Related Documentation

- `docs/brainstorms/2026-03-22-mylar3-migration-requirements.md` — original requirements (partially stale: migration mechanism differs from implemented approach)
- `docs/plans/2026-03-22-002-feat-mylar3-migration-wizard-plan.md` — Mylar3 wizard plan (SQLite-to-SQLite scope; `db_migrate.py` is broader)
- `docs/COMMUNITY_FEATURES.md` — "Postgres/MySQL Support" listed as Tier 4 future work (now implemented, needs status update)
- PR #45: https://github.com/frankieramirez/comicarr/pull/45
