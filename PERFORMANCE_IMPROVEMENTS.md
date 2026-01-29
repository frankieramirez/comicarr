# Mylar3 Performance Improvement Plan

**Created:** 2026-01-29
**Last Updated:** 2026-01-29
**Status:** Phase 1 & 2 Complete, Phase 3 & 4 Pending

---

## Progress Summary

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | **COMPLETE** | Critical fixes (commit bug, HTTP timeouts) |
| Phase 2 | **COMPLETE** | Quick wins (indexes, thread pool, pragmas, template caching) |
| Phase 3 | Pending | Architectural improvements |
| Phase 4 | Pending | Optimization |

---

## Completed Changes

### Phase 1: Critical Fixes

#### 1.1 Fixed `conn.commit()` bug
- **File:** `mylar/__init__.py:829`
- **Change:** `conn.commit` → `conn.commit()`
- **Impact:** Database schema changes now persist correctly

#### 1.2 Added HTTP request timeouts
- **Files:** `mylar/search.py`, `mylar/rsscheck.py`
- **Change:** Added `timeout=30` to `requests.get()` calls
- **Impact:** Requests no longer hang indefinitely

### Phase 2: Quick Wins

#### 2.1 Added 9 new database indexes
- **File:** `mylar/__init__.py`
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
- **File:** `mylar/webstart.py:55`
- **Change:** `thread_pool: 10` → `thread_pool: 50`
- **Impact:** 5x more concurrent request capacity

#### 2.3 Enabled SQLite performance pragmas
- **File:** `mylar/__init__.py`
- **Changes:**
  - `PRAGMA journal_mode = WAL`
  - `PRAGMA synchronous = NORMAL`
  - `PRAGMA cache_size = -64000` (64MB)
- **Impact:** Better concurrent access and caching

#### 2.4 Cached TemplateLookup and icons
- **File:** `mylar/webserve.py`
- **Change:** Added `_template_cache` and `_icons_cache` dictionaries with helper functions
- **Impact:** Template lookups and icon paths no longer recreated on every request

---

## Remaining Work

### Phase 3: Architectural Improvements

#### 3.1 Database connection pooling
- **File:** `mylar/db.py`
- **Task:** Implement singleton pattern or connection pool for `DBConnection`
- **Why:** Currently 222+ new SQLite connections created throughout codebase

#### 3.2 Add API pagination
- **File:** `mylar/api.py`
- **Task:** Add `limit` and `offset` parameters to:
  - `_getHistory()` (line 374)
  - `_getWanted()` (line 403)
  - `_getIndex()` (line 313)
- **Why:** Currently returns ALL records as JSON (could be megabytes)

#### 3.3 Replace boolean locks with threading primitives
- **File:** `mylar/__init__.py:173-175`
- **Task:** Replace `APILOCK = False` with `APILOCK = threading.Lock()`
- **Why:** Boolean locks serialize entire task types inefficiently

#### 3.4 HTTP connection pooling
- **File:** `mylar/search.py`
- **Task:** Create module-level `requests.Session()` object
- **Why:** New TCP connection created for every HTTP request

#### 3.5 Parallelize provider searches
- **File:** `mylar/search.py`
- **Task:** Use `concurrent.futures.ThreadPoolExecutor` to search multiple providers simultaneously
- **Why:** Currently searches providers one-by-one sequentially

### Phase 4: Optimization

#### 4.1 Fix N+1 queries
- **Files:** `mylar/webserve.py:4707-4742`, `mylar/importer.py:1130-1149`
- **Task:** Combine multiple queries into single aggregation queries
- **Why:** 100+ separate queries instead of 1 batch in some operations

#### 4.2 Static file cache headers
- **File:** `mylar/webstart.py:81-100`
- **Task:** Add `Cache-Control` headers for CSS/JS/images
- **Why:** Browser re-downloads assets on every page load

#### 4.3 Remove blocking sleep
- **File:** `mylar/webserve.py:1384`
- **Task:** Replace `time.sleep(5)` with polling/callback pattern
- **Why:** Holds web thread for 5 seconds during `addComic()`

#### 4.4 Replace busy-wait queues
- **File:** `mylar/helpers.py:3293-3636`
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
- `mylar/cv.py`
- `mylar/sabnzbd.py`
- `mylar/versioncheck.py`
- `mylar/notifiers.py`
- `mylar/getimage.py`
- And others (search for `requests.get` or `requests.post` without `timeout=`)

---

## Verification Commands

### After Phase 1 & 2 (Current)
```bash
# Check new indexes exist
sqlite3 /path/to/mylar.db ".indexes"

# Verify index usage
sqlite3 /path/to/mylar.db "EXPLAIN QUERY PLAN SELECT * FROM issues WHERE ComicID=1"

# Check thread pool in logs (should show 50)
grep -i "thread" mylar.log
```

### After Phase 3
```bash
# Test pagination
curl "http://localhost:8090/api?apikey=YOUR_KEY&cmd=getIndex&limit=10"

# Monitor connection count
lsof -p $(pgrep -f Mylar.py) | grep -c mylar.db
```

### After Phase 4
```bash
# Profile performance
python -m cProfile -s cumtime Mylar.py

# Load test
ab -n 100 -c 10 http://localhost:8090/
```

---

## Files Modified

| File | Changes Made |
|------|--------------|
| `mylar/__init__.py` | Fixed commit bug, added 9 indexes, enabled WAL mode and pragmas |
| `mylar/webstart.py` | Increased thread pool from 10 to 50 |
| `mylar/webserve.py` | Added template and icon caching |
| `mylar/search.py` | Added timeout=30 to HTTP requests |
| `mylar/rsscheck.py` | Added timeout=30 to HTTP requests |

## Files To Be Modified (Future Phases)

| File | Planned Changes |
|------|-----------------|
| `mylar/db.py` | Connection pooling, improve upsert |
| `mylar/api.py` | Add pagination to all endpoints |
| `mylar/helpers.py` | Replace busy-wait with proper queue blocking |
| `mylar/webserve.py` | Fix N+1 queries, remove blocking sleep |
| `mylar/search.py` | HTTP session pooling, parallelize searches |
