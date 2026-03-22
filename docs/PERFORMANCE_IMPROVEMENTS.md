# Comicarr Performance Improvement Plan

**Created:** 2026-01-29
**Last Updated:** 2026-01-29
**Status:** Phase 1, 2 & 3 Complete, Phase 4 Pending

---

## Progress Summary

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | **COMPLETE** | Critical fixes (commit bug, HTTP timeouts) |
| Phase 2 | **COMPLETE** | Quick wins (indexes, thread pool, pragmas, template caching) |
| Phase 3 | **COMPLETE** | Architectural improvements (connection pooling, pagination, locks, parallel search) |
| Phase 4 | Pending | Optimization |

---

## Completed Changes

### Phase 1: Critical Fixes

#### 1.1 Fixed `conn.commit()` bug
- **File:** `comicarr/__init__.py:829`
- **Change:** `conn.commit` → `conn.commit()`
- **Impact:** Database schema changes now persist correctly

#### 1.2 Added HTTP request timeouts
- **Files:** `comicarr/search.py`, `comicarr/rsscheck.py`
- **Change:** Added `timeout=30` to `requests.get()` calls
- **Impact:** Requests no longer hang indefinitely

### Phase 2: Quick Wins

#### 2.1 Added 9 new database indexes
- **File:** `comicarr/__init__.py`
- **New indexes:**
  - `issues_comicid ON issues(ComicID)`
  - `issues_status ON issues(Status)`
  - `annuals_comicid ON annuals(ComicID)`
  - `comics_status ON comics(Status)`
  - `snatched_issueid ON snatched(IssueID)`
  - `weekly_comicid ON weekly(ComicID)`
  - `storyarcs_comicid ON storyarcs(ComicID)`
  - `storyarcs_storyarcid ON storyarcs(StoryArcID)`
  - `failed_issueid ON failed(IssueID)`
- **Impact:** Significantly faster database queries

#### 2.2 Increased CherryPy thread pool
- **File:** `comicarr/webstart.py:55`
- **Change:** `thread_pool: 10` → `thread_pool: 50`
- **Impact:** 5x more concurrent request capacity

#### 2.3 Enabled SQLite performance pragmas
- **File:** `comicarr/__init__.py`
- **Changes:**
  - `PRAGMA journal_mode = WAL`
  - `PRAGMA synchronous = NORMAL`
  - `PRAGMA cache_size = -64000` (64MB)
- **Impact:** Better concurrent access and caching

#### 2.4 Cached TemplateLookup and icons
- **File:** `comicarr/webserve.py`
- **Change:** Added `_template_cache` and `_icons_cache` dictionaries with helper functions
- **Impact:** Template lookups and icon paths no longer recreated on every request

### Phase 3: Architectural Improvements

#### 3.1 Database connection pooling
- **File:** `comicarr/db.py`
- **Change:** Added `ConnectionPool` class with thread-local storage for SQLite connections
- **Impact:** Reuses database connections per-thread instead of creating new ones for each `DBConnection` instance

#### 3.2 API pagination
- **File:** `comicarr/api.py`
- **Change:** Added `limit` and `offset` parameters to `_getIndex()`, `_getHistory()`, and `_getWanted()`
- **New helper:** `_paginatedResultsFromQuery()` for paginated queries with metadata
- **Impact:** Large API responses can now be paginated (backwards compatible - no params = all results)

#### 3.3 Thread-safe locks
- **File:** `comicarr/__init__.py`
- **Change:** Replaced `APILOCK`, `SEARCHLOCK`, `DDL_LOCK` boolean flags with `ThreadSafeLock` class
- **Files updated:** `helpers.py`, `search.py`, `PostProcessor.py`, `getcomics.py`
- **Impact:** Proper thread synchronization instead of race-prone boolean flags

#### 3.4 HTTP connection pooling
- **File:** `comicarr/search.py`
- **Change:** Added `get_http_session()` with connection pooling, retry strategy, and adapter configuration
- **Impact:** Reuses TCP connections across HTTP requests, reducing latency

#### 3.5 Parallel search infrastructure
- **File:** `comicarr/search.py`
- **Change:** Added `get_search_executor()` and `parallel_search_providers()` functions
- **Impact:** Infrastructure for searching multiple providers simultaneously (5 worker threads)

---

## Remaining Work

### Phase 4: Optimization

#### 4.1 Fix N+1 queries
- **Files:** `comicarr/webserve.py:4707-4742`, `comicarr/importer.py:1130-1149`
- **Task:** Combine multiple queries into single aggregation queries
- **Why:** 100+ separate queries instead of 1 batch in some operations

#### 4.2 Static file cache headers
- **File:** `comicarr/webstart.py:81-100`
- **Task:** Add `Cache-Control` headers for CSS/JS/images
- **Why:** Browser re-downloads assets on every page load

#### 4.3 Remove blocking sleep
- **File:** `comicarr/webserve.py:1384`
- **Task:** Replace `time.sleep(5)` with polling/callback pattern
- **Why:** Holds web thread for 5 seconds during `addComic()`

#### 4.4 Replace busy-wait queues
- **File:** `comicarr/helpers.py:3293-3636`
- **Task:** Replace `while True` + `time.sleep()` pattern with `queue.get(block=True)`
- **Why:** 5-15 second sleeps waste CPU and add latency

---

## Known Issues Not Yet Addressed

### Database
- `SELECT *` used everywhere instead of specific columns
- Inefficient `upsert()` always tries UPDATE first
- No query result caching for frequently-accessed data

### Web
- No gzip compression configured
- No ETag/cache headers on API responses
- Large DataTables transformations in Python instead of SQL

### I/O
- Full CRC validation (`testzip()`/`testrar()`) on every archive
- `shutil.copy()`/`shutil.move()` blocks without streaming
- Random 0-15 second "DDoS protection" sleep per RSS feed

### HTTP Timeouts (additional files)
Many other files still have requests without timeouts:
- `comicarr/cv.py`
- `comicarr/sabnzbd.py`
- `comicarr/versioncheck.py`
- `comicarr/notifiers.py`
- `comicarr/getimage.py`
- And others (search for `requests.get` or `requests.post` without `timeout=`)

---

## Verification Commands

### After Phase 1 & 2 (Current)
```bash
# Check new indexes exist
sqlite3 /path/to/comicarr.db ".indexes"

# Verify index usage
sqlite3 /path/to/comicarr.db "EXPLAIN QUERY PLAN SELECT * FROM issues WHERE ComicID=1"

# Check thread pool in logs (should show 50)
grep -i "thread" comicarr.log
```

### After Phase 3
```bash
# Test pagination
curl "http://localhost:8090/api?apikey=YOUR_KEY&cmd=getIndex&limit=10"

# Monitor connection count
lsof -p $(pgrep -f Comicarr.py) | grep -c comicarr.db
```

### After Phase 4
```bash
# Profile performance
python -m cProfile -s cumtime Comicarr.py

# Load test
ab -n 100 -c 10 http://localhost:8090/
```

---

## Files Modified

| File | Changes Made |
|------|--------------|
| `comicarr/__init__.py` | Fixed commit bug, added 9 indexes, enabled WAL mode, pragmas, `ThreadSafeLock` class |
| `comicarr/webstart.py` | Increased thread pool from 10 to 50 |
| `comicarr/webserve.py` | Added template and icon caching |
| `comicarr/search.py` | Added timeout=30, HTTP connection pooling, parallel search infrastructure, thread-safe locks |
| `comicarr/rsscheck.py` | Added timeout=30 to HTTP requests |
| `comicarr/db.py` | Added `ConnectionPool` class for thread-local connection pooling |
| `comicarr/api.py` | Added pagination support with `_paginatedResultsFromQuery()` |
| `comicarr/helpers.py` | Updated to use `ThreadSafeLock` methods |
| `comicarr/PostProcessor.py` | Updated to use `ThreadSafeLock` methods |
| `comicarr/getcomics.py` | Updated to use `ThreadSafeLock` methods |

## Files To Be Modified (Future Phases)

| File | Planned Changes |
|------|-----------------|
| `comicarr/db.py` | Improve upsert efficiency |
| `comicarr/helpers.py` | Replace busy-wait with proper queue blocking |
| `comicarr/webserve.py` | Fix N+1 queries, remove blocking sleep |
| `comicarr/webstart.py` | Add static file cache headers |
