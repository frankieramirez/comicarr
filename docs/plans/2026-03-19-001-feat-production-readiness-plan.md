---
title: "feat: Production Readiness - Replace Mylar3 with Comicarr"
type: feat
status: active
date: 2026-03-19
deepened: 2026-03-19
---

# feat: Production Readiness - Replace Mylar3 with Comicarr

## Enhancement Summary

**Deepened on:** 2026-03-19
**Research agents used:** Security Sentinel, Performance Oracle, Deployment Verification, Architecture Strategist, Data Integrity Guardian, Pattern Recognition Specialist, Code Simplicity Reviewer, Frontend Races Reviewer, Best Practices Researcher, Framework Docs Researcher

### Key Improvements from Research
1. **NEW Phase 0 added:** SQL injection remediation — the original plan missed pervasive SQL injection via string concatenation in `api.py`
2. **Plan dramatically simplified for self-use:** Simplicity review found the original plan was ~10x more work than needed. Phases 3-6 are deferred to "going public" — only ~15 tasks needed to replace Mylar3
3. **Critical bug discovered:** `_setConfig` is missing `configure(update=True)` call — config changes from React Settings don't take effect at runtime
4. **Missing SQLite PRAGMA:** `busy_timeout` not set — concurrent writes fail immediately instead of waiting
5. **Upsert race condition:** Must fix TOCTOU bug in `db.py:upsert()` BEFORE removing the global lock
6. **WriteOnly worker bug is dead code:** Queue-based write path is commented out — fix is low priority
7. **Synology-specific:** PUID/PGID defaults (1000/1000) are wrong for Synology (typically 1026/100)

### New Considerations Discovered
- SSE + mutation double-invalidation causes UI flicker on every action
- `getAPI` endpoint sends username/password as URL query parameters
- `/cache` directory served as static files without authentication
- `Access-Control-Allow-Origin: *` on all API responses
- Open redirect vulnerability in login flow (`from_page` parameter)
- SSE key scope enforcement broken due to `self.apiktype` typo
- Both cfscrape AND cloudscraper are effectively unmaintained
- CherryPy thread pool of 50 is excessive for NAS (should be 10-15)

---

## Overview

Comprehensive plan to make Comicarr production-ready for self-hosted deployment on Synology NAS (Docker), with the goal of confidently replacing a working Mylar3 setup and eventually going public. The backend is mature (inherited from Mylar3), but the React frontend has critical gaps, error handling is concerning, and several infrastructure pieces need hardening.

### Simplicity Principle

**This is a new frontend on a working backend.** The Mylar3 backend has been running in production for years. For self-use, the minimum is: fix the handful of bugs that block the React frontend from working, get Docker building correctly, and copy your existing Mylar3 `config.ini`. Everything else is polish for going public.

---

## Problem Statement

Comicarr cannot currently replace Mylar3 because:

1. **SQL injection in api.py** — queries use string concatenation with user input instead of parameterized queries
2. **Settings can't be configured from the UI** — Download Clients tab is read-only, `setConfig` API only allows 12 keys, and it's missing the `configure(update=True)` call so changes don't take effect
3. **First-run is broken** — no way to log in on a fresh Docker install
4. **Docker setup has gaps** — wrong PUID/PGID defaults for Synology, missing `.dockerignore`, bun/npm contradiction
5. **Database has latent bugs** — upsert race condition, missing `busy_timeout` PRAGMA
6. **243 bare `except:` clauses** silently swallow errors (but only ~13 in PostProcessor.py matter for daily use)

---

## Phase 0: Security Fixes (Immediate)

*These are exploitable vulnerabilities that should be fixed before any deployment.*

### 0.1 SQL Injection Remediation in api.py

**Problem:** Nearly every database query in `mylar/api.py` uses string concatenation with user-supplied `self.id` instead of parameterized queries. The codebase's own CLAUDE.md documents the correct pattern but the API module violates it.

**Examples found:**
- Line 1458: `'SELECT * from issues WHERE issueID="' + self.id + '"'`
- Line 785: `'SELECT ComicName... FROM comics where ComicID="' + self.id + '"'`
- Lines 791-793: `DELETE` statements with concatenated IDs
- Line 192: `LIMIT`/`OFFSET` via f-string interpolation

**Tasks:**
- [ ] Audit every SQL query in `mylar/api.py` — convert all string concatenation to parameterized queries (`?` placeholders)
- [ ] Pattern: `'SELECT * FROM issues WHERE issueID=?', [self.id]`
- [ ] Check `mylar/webserve.py` for the same pattern (10K lines, likely more instances)

### Research Insights

**Security Sentinel:** This is the single most exploitable vulnerability. An attacker with a valid API key (trivially leaked from URL query parameters or access logs) can execute arbitrary SQL. Priority should be higher than any feature work.

**Pattern Recognition:** The codebase's own `db.DBConnection().action()` method accepts parameterized queries — the correct infrastructure exists, it's just not used consistently in the API module.

### 0.2 Remove CORS Wildcard

**Problem:** `mylar/api.py:290` sets `Access-Control-Allow-Origin: *` on every JSON response. Combined with API key in query parameters, any website can make cross-origin requests to the API.

**Tasks:**
- [ ] Remove the wildcard CORS header — the React SPA is same-origin, CORS is not needed
- [ ] If needed for dev (Vite proxy), use Vite's built-in proxy config instead

### 0.3 Fix SSE Key Scope Enforcement

**Problem:** The `self.apiktype` typo at `mylar/api.py:262` breaks SSE key scope restriction. The SSE key can access any API command, not just `checkGlobalMessages`.

**Tasks:**
- [ ] Fix `self.apiktype` → `self.apitype`
- [ ] Fix `checkGlobalMessags` → `checkGlobalMessages`
- [ ] Enforce: SSE keys only allow SSE commands, download keys only allow download commands

---

## Phase 1: Critical Blockers (Must-Fix Before Self-Use)

*These prevent the app from functioning as a Mylar3 replacement.*

### 1.1 Fix Settings Page — Make Download Clients Configurable

**Problem:** `DownloadClientsTab` says "Coming Soon" and is read-only. `GeneralTab` is read-only. The `setConfig` API endpoint only whitelists 12 keys, excluding all download client config. **AND** `_setConfig` is missing the `configure(update=True)` call that `configUpdate` performs, so even whitelisted changes may not take effect at runtime.

**Tasks:**
- [ ] **Fix `_setConfig` immediately:** Add `mylar.CONFIG.configure(update=True, startup=False)` after `writeconfig()` in `mylar/api.py` — this is a one-line fix that prevents a whole class of bugs
- [ ] Build editable `DownloadClientsTab` with forms for SABnzbd and qBittorrent (your two clients)
- [ ] Add a "Test Connection" button for each client (the *arr apps all do this)
- [ ] Expand `setConfig` API whitelist to include download client keys
- [ ] Make `GeneralTab` editable for critical paths: `comic_dir`, `destination_dir`

### Research Insights

**Architecture Strategist:** Do NOT merge the two config update paths (`configUpdate` vs `_setConfig`). Instead, progressively expand `_setConfig` as the canonical React frontend path. Add structured provider management endpoints (addProvider/removeProvider) rather than the suffix-based form pattern in `configUpdate`.

**Best Practices (Sonarr/Radarr pattern):** The *arr apps use modal dialogs for Add/Edit download clients, not inline editing. Each modal has a "Test" button that validates connectivity before saving. This is the battle-tested pattern.

**Simplicity Reviewer:** Consider whether you even need this UI for self-use. You configure download clients once. If your Mylar3 `config.ini` already has SABnzbd + qBittorrent configured, just copy it and skip this entirely.

**Files:**
- `mylar/api.py:2281-2333` — add `configure(update=True)` call, expand whitelist
- `frontend/src/components/settings/DownloadClientsTab.tsx` — rebuild
- `frontend/src/components/settings/GeneralTab.tsx` — add onChange

### 1.2 Fix First-Run / Docker Onboarding

**Problem:** A fresh `docker-compose up` leads to a login page with no credentials configured.

**Tasks:**
- [ ] Follow Sonarr v4 pattern: if no auth is configured, force a single-screen credential setup (username + password) before granting access — no multi-step wizard
- [ ] Add "DisabledForLocalAddresses" option (the *arr standard) — local network access without login, external requires auth
- [ ] Update `docker/entrypoint.sh` to generate a default `config.ini` if none exists

### Research Insights

**Best Practices (Sonarr v4):** Sonarr v4 made authentication mandatory after security incidents where users exposed instances to the internet. The pattern is: force credential setup on first launch, no wizard, just one gate. The "DisabledForLocalAddresses" compromise is the most popular option for NAS users.

**Simplicity Reviewer:** The simplest approach: if no auth is configured, just let the user in (Mylar3 behavior) and show a banner prompting setup. This is less secure but gets you running immediately.

**Files:**
- `frontend/src/contexts/AuthContext.tsx` — handle no-auth state
- `docker/entrypoint.sh` — default config generation

### 1.3 Fix Docker Build & Deployment

**Problem:** Dockerfile uses bun (contradicting CLAUDE.md), PUID/PGID defaults are wrong for Synology, no `.dockerignore`, and volume permissions aren't verified.

**Tasks:**
- [ ] Switch Dockerfile frontend build stage from `oven/bun:latest` to `node:22-alpine` with npm
- [ ] Add `.dockerignore`: `.git/`, `.venv/`, `frontend/node_modules/`, `nvim-macos-x86_64/`, `nvim-macos-x86_64.tar.gz`, `*.pyc`, `__pycache__/`, `.agents/`, `.claude/`, `tests/`
- [ ] Add write-access verification for `/comics`, `/downloads`, `/manga` in entrypoint.sh — log warnings, do NOT recursive chown (would take hours on large libraries)
- [ ] Add `UMASK=002` env var support to entrypoint (enables group-writable files for multi-container setups like Comicarr + SABnzbd sharing a download dir)
- [ ] Optimize Dockerfile layer caching: copy `requirements.txt` first, install, then copy app code
- [ ] Add `stop_grace_period: 30s` to docker-compose.yml (shutdown path has 2s sleep + 5s thread join, exceeding Docker's 10s default)
- [ ] Add `STOPSIGNAL SIGTERM` to Dockerfile

### Research Insights

**Deployment Verification (Synology-specific):**
- Synology admin user is typically UID 1026, GID 100 — NOT 1000/1000
- Use absolute `/volume1/...` paths in docker-compose, not relative paths
- `restart: unless-stopped` does not survive DSM updates — consider `restart: always`
- If on Btrfs volume, disable CoW for the database directory: `chattr +C /config/comicarr/`
- 32-bit ARM Synology models (armv7l) are NOT supported — only amd64 and arm64 are built

**Framework Docs:** `python:3.12-slim` (Debian) avoids Alpine's musl libc compilation issues with C-extension packages (Pillow, pycryptodome). The current Alpine build works but is slower to build.

**Performance Oracle:** The `chown -R comicarr:comicarr /config` runs on every container start. If `/config` has thousands of cached covers/sessions, this adds significant startup time. Change to non-recursive chown on `/config` and only fix specific subdirectories.

### 1.4 Fix Database Fundamentals

**Problem:** Missing `busy_timeout` PRAGMA means concurrent writes fail immediately. The `upsert()` method has a TOCTOU race condition. The WriteOnly worker bug exists but is in dead code.

**Tasks:**
- [ ] **Add `PRAGMA busy_timeout=5000`** to `mylar/__init__.py` alongside existing PRAGMAs — this is the single most impactful database fix (prevents `SQLITE_BUSY` errors under concurrent access)
- [ ] **Fix upsert race condition:** Replace the UPDATE-then-check-`total_changes`-then-INSERT pattern in `mylar/db.py:257-268` with SQLite's `INSERT ... ON CONFLICT DO UPDATE` (available since SQLite 3.24, ships with Python 3.7+). The current approach has a TOCTOU bug masked by the global lock.
- [ ] Add `PRAGMA foreign_keys=ON` for referential integrity
- [ ] Add `PRAGMA mmap_size=134217728` (128MB) for memory-mapped I/O on NAS
- [ ] Mark WriteOnly worker as deprecated (the queue path at `db.py:271-274` is commented out — this is dead code, not an active bug)

### Research Insights

**Data Integrity Guardian:** The `total_changes` approach in upsert is fundamentally broken for concurrent use — it's connection-scoped, not statement-scoped. If another thread writes between the UPDATE and the `total_changes` check, the count is wrong and the INSERT is skipped, causing **silent data loss**. Fix this BEFORE removing the global lock.

**Framework Docs:** A WAL-reset bug was fixed in SQLite 3.51.3 (released 2026-03-13). Verify the SQLite version in your Alpine image is >= 3.51.3.

**Performance Oracle:** Also set `PRAGMA journal_size_limit=67108864` (64MB) to prevent unbounded WAL file growth on NAS.

### 1.5 Fix Remaining Critical Bugs

**Tasks:**
- [ ] Fix `sys.exit(0)` → `sys.exit(1)` on port conflict in `mylar/webstart.py:183`
- [ ] Fix StoryArcsPage link pointing to Mylar3 GitHub instead of Comicarr
- [ ] Fix SSE `_eventStreamResponse` in `mylar/api.py:78-141` — replace string concatenation with `json.dumps()` to prevent data corruption when comic names contain quotes/newlines
- [ ] Fix open redirect in `mylar/auth.py:163` — validate `from_page` is a relative path, reject absolute URLs

---

## Phase 2: Stability & Reliability (Must-Fix Before Daily Use)

*These prevent confident unattended operation on a NAS.*

### 2.1 Bare `except:` Cleanup (Critical Path Only)

**Problem:** 243 bare `except:` clauses across 35 files. For self-use, only the download pipeline matters.

**Tasks (for self-use — just these 2 files):**
- [ ] `mylar/PostProcessor.py` (13 bare excepts) — silent failures here = lost downloads
- [ ] `mylar/cv.py` (43 bare excepts) — fix the ones in the main API call path; categorize by exception type (use `except (AttributeError, IndexError)` for XML DOM access, not blanket `except Exception`)

**Defer for public release:**
- `mylar/search.py` — only 1 bare except, trivial
- `mylar/webserve.py` — 34 bare excepts, mostly defensive inherited code
- `mylar/helpers.py` — 59 bare excepts, most are type-coercion fallbacks that are safe

### Research Insights

**Pattern Recognition:** Not all bare excepts are equal. In `cv.py`, many guard XML DOM access (`getElementsByTagName`) — these should become `except (AttributeError, IndexError)`, not blanket `except Exception`. The ones that `return` are control-flow exceptions that should propagate with a meaningful error.

**Simplicity Reviewer:** The backend has been running in Mylar3 for years with these bare excepts. Fix PostProcessor.py (where silent failures lose downloads) and defer the rest.

### 2.2 Database Lock Fix

**Problem:** Global `db_lock` serializes ALL operations. With WAL mode, reads don't need locking.

**Prerequisites (must complete Phase 1.4 first):**
- [ ] Upsert race condition must be fixed first (replace with `INSERT ... ON CONFLICT DO UPDATE`)
- [ ] `busy_timeout` must be set

**Tasks:**
- [ ] Remove `db_lock` from `fetch()` (read path) — WAL mode handles read concurrency
- [ ] Keep `db_lock` on `action()` (write path) as a safety measure during transition, or rely on `busy_timeout`
- [ ] Reduce CherryPy thread pool from 50 to 10-15 (50 threads on a NAS with 2-4 cores causes excessive context switching; with the global lock, more threads makes things worse)

### Research Insights

**Data Integrity Guardian:** SQLite WAL mode explicitly permits concurrent readers alongside a single writer. The lock removal for reads is safe. However, removing the write lock requires the upsert fix — otherwise the TOCTOU race becomes exploitable.

**Performance Oracle:** Reducing to 10-15 threads saves ~280MB of thread stack memory (8MB per thread). SSE connections pin threads — with 50 threads and 3 open tabs, 30% of the pool is consumed. Consider if SSE should use a polling fallback.

**Framework Docs (CherryPy):** `server.thread_pool` default is 10. CherryPy issue #1120 documents SSE/long-polling thread exhaustion. Each SSE connection holds a thread for its entire duration.

### 2.3 Frontend Resilience

**Tasks:**
- [ ] Add try/catch to `SeriesDetailPage` mutations (pause/resume/refresh/delete) with toast notifications — copy existing pattern from `WantedPage`/`UpcomingPage`
- [ ] Fix SSE + mutation double-invalidation: let SSE be the sole cache invalidation mechanism, remove `onSuccess` invalidations from mutation hooks (or add debounce)
- [ ] Return `{ isConnected, isReconnecting }` from `useServerEvents` hook, display connection status banner
- [ ] On SSE reconnect after disconnection, call `checkSession` — if invalid, force re-login
- [ ] Fix `queryClient.invalidateQueries()` nuclear option on `tables === "tabs"` — scope to specific query keys

### Research Insights

**Frontend Races Reviewer:** The double-invalidation stampede is the biggest UX issue. Every mutation fires `invalidateQueries` in `onSuccess`, then SSE fires the same invalidation. Worse: the SSE event can arrive BEFORE the mutation completes, refetching stale data and causing a visible flicker. Solution: either let SSE be the sole invalidation source, or use optimistic updates.

**Frontend Races Reviewer:** Bulk operations in `useQueue.ts` use sequential `for` loops — SSE events arrive mid-loop causing the table to re-render repeatedly. Use `Promise.allSettled` and suppress SSE invalidation during bulk mutations.

**Frontend Races Reviewer:** `ComicCard.tsx` has a stale closure — the `comic-added` event listener is conditionally registered only when `isProcessing` is true. Re-renders remove and re-add the listener, creating a window where events are lost. Fix: always register the listener, check `isProcessing` inside the callback.

### 2.4 Missing HTTP Timeouts

**Tasks:**
- [ ] Add `timeout=30` to `requests.get()`/`requests.post()` in: `mylar/cv.py`, `mylar/sabnzbd.py`, `mylar/torrent/clients/*.py`
- [ ] Defer others (`versioncheck.py`, `notifiers.py`, `getimage.py`) — less critical for daily use

---

## Phase 3: Feature Parity (Before Going Public — NOT needed for self-use)

*Missing frontend pages that Mylar3 users expect. The backend endpoints already exist and work.*

> **Simplicity Note:** For self-use, skip this entire phase. The backend has all these features via the existing API. You can access history via `docker logs` and the API directly. Build these pages when you personally miss them.

### 3.1 Log Viewer Page (Build First — Most Useful for Debugging)

- [ ] Create `LogsPage` using backend `getLog`/`getLogs` endpoint
- [ ] Level filtering (debug, info, warning, error), clear action, auto-scroll

### 3.2 History Page

- [ ] Create `HistoryPage` using backend `getHistory` endpoint
- [ ] Show snatched/downloaded/post-processed events with timestamps

### 3.3 Weekly Pull List Page

- [ ] Create `WeeklyPullListPage` using backend `pullist` endpoint

### 3.4 Story Arcs Page (Replace Stub)

- [ ] Replace placeholder with functional page

### 3.5 Reading List Page

- [ ] Create `ReadingListPage` using backend `readlist` endpoint

### Research Insights (Frontend Patterns for New Pages)

**Pattern Recognition — follow existing conventions:**
- One custom hook per data domain (`useLogs.ts`, `useHistory.ts`)
- Use `<ErrorDisplay>` component (not inline error rendering like SettingsPage does)
- Use `refetch()` for retry (not `window.location.reload()` like HomePage does)
- Wrap content in `<div className="page-transition">`
- Extract `usePagination` hook — `WantedPage` and `ImportPage` duplicate identical pagination logic
- Consolidate `useQueueIssue`/`useUnqueueIssue` into `useQueue.ts` only (currently duplicated across `useSeries.ts` and `useQueue.ts`)

---

## Phase 4: Security & Dependencies (Before Going Public)

### 4.1 API Key Security

**Tasks:**
- [ ] Move API key from query parameter to `Authorization: Bearer <key>` header
- [ ] **Also fix `getAPI` endpoint** — it sends username/password as query parameters (`apiCall("getAPI", { username, password })`). Return the API key as part of the login response instead.
- [ ] Mask secrets in `getConfig` API response
- [ ] Add `Referrer-Policy: no-referrer` header immediately (mitigates API key leakage via Referer until header migration is done)
- [ ] For SSE: `EventSource` cannot set custom headers — accept URL parameter for SSE only, use headers for everything else

### 4.2 Security Headers

- [ ] Add CherryPy tool for security headers on every response:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: no-referrer`
  - `Content-Security-Policy` (basic)
- [ ] Remove `/cache` static directory from public serving without auth (`webstart.py:95-98`)
- [ ] Fix open redirect in `auth.py:163` (if not done in Phase 1.5)

### 4.3 Stale Dependencies

- [ ] Replace `cfscrape` with `cloudscraper` — used in 3 files: `rsscheck.py`, `auth32p.py`, `wwt.py`. Migration is near-drop-in (`import cfscrape` → `import cloudscraper`). Main benefit: removes `urllib3<2` pin.
- [ ] **Note:** Both cfscrape AND cloudscraper are effectively unmaintained. Neither reliably bypasses modern Cloudflare (Turnstile). The migration is still worthwhile for urllib3 2.x compatibility.
- [ ] Remove `six` and `configparser` from pyproject.toml

### 4.4 Authentication Hardening

- [ ] Add rate limiting to login endpoint (exponential backoff after failed attempts)
- [ ] Configure session cookies: `httponly=True`, `samesite='Lax'`, `secure=True` when HTTPS
- [ ] Evaluate `sessionStorage` → `localStorage` for auth tokens (sessionStorage prevents opening links in new tabs — annoying for power users)

### Research Insights

**Security Sentinel:** CSRF protection is less critical for a self-hosted app behind a home network. The CORS wildcard removal (Phase 0.2) eliminates the main cross-origin attack vector. Rate limiting on login matters more.

**Frontend Races:** `sessionStorage` means every new tab requires re-login. `localStorage` with a `storage` event listener for cross-tab logout sync is better for a comic library manager where users open series in new tabs.

---

## Phase 5: CI/CD & Testing (Before Going Public)

> **Simplicity Note:** Zero contributors, zero PRs. Skip until going public.

### 5.1 GitHub Actions CI Pipeline

- [ ] Create `.github/workflows/ci.yml`: ruff lint, pytest, eslint, frontend build, Docker build test

### 5.2 Minimal Test Coverage

- [ ] API endpoint tests (getIndex, getComic, setConfig)
- [ ] Database upsert test (verify `INSERT ... ON CONFLICT DO UPDATE` works correctly)
- [ ] Post-processor file rename test

### 5.3 Pre-Release Documentation

- [ ] CONTRIBUTING.md, SECURITY.md, CHANGELOG.md
- [ ] Mylar3 migration guide: document that migration is one-way, `dbcheck()` adds columns on first launch, the cleanup DELETEs at `__init__.py:1800-1807` destroy records with NULL comic names

### Research Insights

**Data Integrity Guardian:** Before Mylar3 → Comicarr migration, create an automatic backup of the database (detect first run by checking if Comicarr-specific columns like `ContentType` exist). Document clearly that migration is one-way.

**Data Integrity Guardian:** Use `PRAGMA user_version` for schema migrations — store version as integer, apply numbered SQL migration files on startup. This is the *arr app pattern and requires zero dependencies.

---

## Phase 6: Polish & Public Release

### 6.1 Performance

- [ ] Enable `tools.gzip` on CherryPy for API JSON responses only (not static assets — Vite already minifies)
- [ ] Add `tools.expires` cache headers: `/assets` = 1 year (Vite hashes filenames), `index.html` = no-cache
- [ ] Fix busy-wait queue loops in `helpers.py:3304, 3590, 3623` — replace `while True` + `time.sleep(5)` with `queue.get(block=True, timeout=30)`
- [ ] Fix lock polling in `search.py:1638` — replace `while mylar.SEARCHLOCK.locked()` + `time.sleep(5)` with `SEARCHLOCK.acquire(blocking=True)`
- [ ] Convert `IMPORTLOCK` and `DBLOCK` boolean flags to `ThreadSafeLock` instances (currently unsynchronized data races)
- [ ] Frontend: paginate `getIndex` (currently returns ALL comics at once), add `loading="lazy"` to cover images, code-split routes with `React.lazy()`

### 6.2 Docker Hardening

- [ ] Add resource limits: `mem_limit: 512m` (DS220+ class) or `768m` (DS918+ class)
- [ ] Add logging config: `--log-driver=json-file --log-opt max-size=10m --log-opt max-file=3`
- [ ] Add unauthenticated `/ping` health endpoint (current healthcheck hits `/auth/check_session` which only proves CherryPy is alive)
- [ ] Add `.env.example` with Synology documentation (PUID=1026, PGID=100, TZ, volume paths)
- [ ] Pin Docker base images to specific versions (not `:latest`)
- [ ] Add SQLite backup: implement `VACUUM INTO '/config/backups/mylar-YYYYMMDD.db'` scheduled command
- [ ] Increase `--start-period` to 120s (database migration on first boot may take longer than 60s)

### 6.3 Public Release Checklist

Per existing `docs/RELEASE_PLAN.md`:
- [ ] Rename repo from `mylar4` to `comicarr`
- [ ] Change visibility to Public
- [ ] Enable branch protection on main, enable Discussions
- [ ] Create initial release (tag v0.1.0)
- [ ] Verify Docker images publish to GHCR for AMD64 + ARM64
- [ ] Test `docker pull` and `docker-compose up` on fresh Synology
- [ ] Share on r/selfhosted, r/comics, r/usenet

---

## Acceptance Criteria

### For Self-Use (Phases 0-2) — The Real MVP

- [ ] SQL injection fixed in api.py
- [ ] Can `docker-compose up` on Synology with correct PUID/PGID and reach the app
- [ ] Can configure SABnzbd + qBittorrent (via UI or by copying Mylar3 config.ini)
- [ ] Config changes from Settings page actually take effect at runtime
- [ ] `busy_timeout` set — no `SQLITE_BUSY` errors under concurrent access
- [ ] PostProcessor.py bare excepts fixed — download failures are visible
- [ ] App runs unattended for 7 days without crashes or data loss

### For Public Release (Phases 3-6)

- [ ] All 5 missing pages implemented
- [ ] CI pipeline passes on every PR
- [ ] API key not leaked in URLs
- [ ] Migration guide exists and is tested
- [ ] Docker image builds for AMD64 + ARM64
- [ ] Fresh install → working downloads in under 10 minutes

---

## Dependencies & Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| SQL injection is more pervasive than api.py | Medium | Critical | Grep for string concatenation in SQL across all files |
| Settings page is more complex than expected | High | Medium | Start with SABnzbd + qBittorrent only; copy Mylar3 config.ini as fallback |
| Upsert fix (`INSERT ... ON CONFLICT`) changes behavior | Low | High | Test with actual comic adds, series refreshes, and import operations |
| Synology PUID/PGID mismatch causes write failures | High | High | Document clearly; add write-access check in entrypoint |
| Both cfscrape AND cloudscraper are unmaintained | High | Medium | Accept this — the migration is worthwhile for urllib3 2.x alone |
| SQLite WAL corruption bug (pre-3.51.3) | Low | Critical | Verify Alpine image has SQLite >= 3.51.3 |
| CherryPy gzip + caching bug (#1190) | Low | Low | Only enable gzip on API JSON, not static files |

---

## Quick-Start: The 6 Things to Do Today

If you want the absolute minimum to start using Comicarr:

1. **Fix SQL injection in api.py** — convert string concatenation to parameterized queries
2. **Add `PRAGMA busy_timeout=5000`** to `mylar/__init__.py` alongside existing PRAGMAs
3. **Add `configure(update=True)` to `_setConfig`** in `mylar/api.py` — one-line fix
4. **Fix Dockerfile** — switch bun → npm, add `.dockerignore`
5. **Fix first-run auth** — if no auth configured, let the user in (Mylar3 behavior)
6. **Fix PostProcessor.py bare excepts** — 13 instances, prevents lost downloads

Everything else can wait until you've been running for a week.

---

## Sources & References

### Internal References
- Performance improvements: `docs/PERFORMANCE_IMPROVEMENTS.md`
- Release plan: `docs/RELEASE_PLAN.md`
- Community features: `docs/COMMUNITY_FEATURES.md`
- API endpoints: `mylar/api.py:35-47` (cmd_list)
- Settings whitelist: `mylar/api.py:2281-2333`
- Database upsert: `mylar/db.py:254-268`
- Frontend routes: `frontend/src/App.tsx`
- SSE hook: `frontend/src/hooks/useServerEvents.ts`

### Key Files by Phase
- **Phase 0:** `mylar/api.py` (SQL injection, CORS, SSE typo)
- **Phase 1:** `mylar/api.py` (setConfig fix), `frontend/src/components/settings/*.tsx`, `Dockerfile`, `docker/entrypoint.sh`, `mylar/__init__.py` (PRAGMAs), `mylar/db.py` (upsert)
- **Phase 2:** `mylar/PostProcessor.py`, `mylar/cv.py`, `mylar/db.py` (lock removal), `frontend/src/hooks/useServerEvents.ts`, `frontend/src/pages/SeriesDetailPage.tsx`
- **Phase 3:** `frontend/src/pages/` (new pages)
- **Phase 4:** `frontend/src/lib/api.ts`, `pyproject.toml`, `mylar/auth.py`
- **Phase 5:** `.github/workflows/ci.yml` (new)

### External References
- [Sonarr v4 forced auth pattern](https://wiki.servarr.com/sonarr/faq-v4)
- [Servarr Docker Guide](https://wiki.servarr.com/docker-guide)
- [SQLite WAL documentation](https://sqlite.org/wal.html)
- [SQLite recommended PRAGMAs](https://highperformancesqlite.com/articles/sqlite-recommended-pragmas)
- [SQLite production setup (2026)](https://oneuptime.com/blog/post/2026-02-02-sqlite-production-setup/view)
- [CherryPy gzip/caching bug (#1190)](https://github.com/cherrypy/cherrypy/issues/1190)
- [CherryPy SSE thread exhaustion (#1120)](https://github.com/cherrypy/cherrypy/issues/1120)
- [TanStack Query v5 optimistic updates](https://tanstack.com/query/v5/docs/framework/react/guides/optimistic-updates)
- [cloudscraper GitHub](https://github.com/VeNoMouS/cloudscraper)
