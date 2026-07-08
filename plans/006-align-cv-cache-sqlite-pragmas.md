# Plan 006: Apply SQLite timeout and WAL pragmas to the ComicVine cache

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report - do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b6d743ea..HEAD -- comicarr/cv_cache.py comicarr/db.py tests/unit`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `b6d743ea`, 2026-07-07

## Why this matters

The main SQLite database is configured with WAL mode and a 15-second busy timeout on every connection. The ComicVine cache uses separate raw `sqlite3.connect()` calls without those settings, so metadata cache reads/writes can fail fast under lock contention even though the rest of the app is tuned for NAS/SQLite behavior. A small connection helper keeps cache behavior aligned with the main DB.

## Current state

- `comicarr/db.py` - central SQLite PRAGMA setup.
- `comicarr/cv_cache.py` - ComicVine metadata cache using raw sqlite connections.
- No current unit tests target `CVCache`.

Relevant excerpts:

```text
db.py:92-101
def _apply_sqlite_pragmas(dbapi_conn, _connection_record):
    cursor.execute("PRAGMA busy_timeout = 15000")
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute("PRAGMA mmap_size = 67108864")
    cursor.execute("PRAGMA journal_size_limit = 67108864")
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA cache_size = -64000")
```

```text
cv_cache.py:38-42
def _init_db(self):
    """Create the cache table if it doesn't exist."""
    with self.lock:
        conn = sqlite3.connect(self.db_path)
```

```text
cv_cache.py:88-90
with self.lock:
    conn = sqlite3.connect(self.db_path)
```

```text
cv_cache.py:135-137
with self.lock:
    conn = sqlite3.connect(self.db_path)
```

Repo conventions to match:

- Legacy modules use broad `except Exception as e` with contextual logger messages.
- Avoid type hints.
- New Python files should include the GPL header.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_cv_cache.py -q -p no:cacheprovider` | new tests pass |
| Related tests | `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit -q -p no:cacheprovider` | all unit tests pass |
| Lint | `./.venv/bin/ruff check --no-cache comicarr/cv_cache.py tests/unit/test_cv_cache.py` | exit 0 |
| Format check | `./.venv/bin/ruff format --check comicarr/cv_cache.py tests/unit/test_cv_cache.py` | exit 0 |

## Scope

**In scope**:

- `comicarr/cv_cache.py`
- `tests/unit/test_cv_cache.py` (create)

**Out of scope**:

- Moving `CVCache` to SQLAlchemy
- Changing cache schema
- Changing ComicVine API behavior
- Changing global DB pragmas in `comicarr/db.py`

## Git workflow

- Branch: `fix/cv-cache-sqlite-pragmas`
- Commit message style: `fix: align ComicVine cache sqlite pragmas`
- Do not push or open a PR unless instructed.

## Steps

### Step 1: Add one connection helper in `CVCache`

In `comicarr/cv_cache.py`, add a private method such as `_connect(self)` that returns a sqlite connection configured for this cache.

Required settings:

- `sqlite3.connect(self.db_path, timeout=15)`
- `PRAGMA busy_timeout = 15000`
- `PRAGMA synchronous = NORMAL`
- `PRAGMA journal_size_limit = 67108864`
- `PRAGMA journal_mode = WAL`
- `PRAGMA cache_size = -64000`

`foreign_keys` and `mmap_size` may also match `comicarr/db.py` if they work reliably on the cache DB. If a PRAGMA fails on a platform, log a warning and keep the cache functional rather than making metadata lookups fail.

**Verify**: `./.venv/bin/ruff check --no-cache comicarr/cv_cache.py` -> `All checks passed!`.

### Step 2: Replace all raw cache connections

Replace every `sqlite3.connect(self.db_path)` in `CVCache` with the helper. At plan time, raw connections exist in `_init_db`, `get`, `set`, `clear_expired`, `clear_all`, and `get_stats`.

Keep the existing `with self.lock:` structure and existing close-in-finally pattern unless you deliberately convert each method to context managers.

**Verify**: `rg -n "sqlite3\\.connect\\(self\\.db_path\\)" comicarr/cv_cache.py` -> no matches.

### Step 3: Add unit tests for pragmas and cache behavior

Create `tests/unit/test_cv_cache.py`.

Test cases:

- Initializing `CVCache(tmp_path / "cv_cache.db")` creates the table and index.
- A stored value can be retrieved before expiry.
- An expired value returns `None`.
- A connection opened through the cache reports `PRAGMA busy_timeout` as `15000`.
- `PRAGMA journal_mode` is `wal` on normal filesystem-backed temp DBs. If the platform returns a different valid mode in CI, assert the helper attempted the PRAGMA by mocking sqlite only for that case.

Model style after existing backend tests: pytest, plain asserts, no type hints.

**Verify**: `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_cv_cache.py -q -p no:cacheprovider` -> all pass.

## Test plan

- New `tests/unit/test_cv_cache.py`.
- Full unit suite after the focused tests.
- No integration test is required because this plan does not change ComicVine request semantics.

## Done criteria

- [x] All `CVCache` sqlite connections use one helper.
- [x] The helper applies busy timeout and WAL-related pragmas.
- [x] Cache set/get/expiry behavior remains unchanged.
- [x] Focused and full unit tests pass.
- [x] Ruff check and format check pass for touched Python files.
- [x] No files outside the in-scope list are modified.
- [x] `plans/README.md` status row updated.

## STOP conditions

Stop and report back if:

- WAL mode cannot be enabled reliably for the cache DB in the supported deployment environment.
- The cache DB is intentionally separate from main DB tuning because of a documented decision not cited here.
- Fixing lock contention requires changing ComicVine request concurrency, not just cache connection behavior.

## Maintenance notes

If more standalone sqlite caches are added, reuse this connection-helper pattern or extract a shared helper. Reviewers should check that new raw sqlite connections do not bypass busy-timeout behavior.
