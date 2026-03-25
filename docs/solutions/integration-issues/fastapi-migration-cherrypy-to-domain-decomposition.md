---
title: "FastAPI Migration: CherryPy Monolith to Vertical Domain Decomposition"
category: integration-issues
date: 2026-03-25
tags:
  - fastapi
  - cherrypy
  - migration
  - domain-decomposition
  - strangler-fig
  - security
  - performance
components:
  - comicarr/app/
  - comicarr/helpers.py
  - comicarr/webserve.py
  - frontend/src/lib/api.ts
related_issues: []
related_docs:
  - docs/solutions/security-issues/cherrypy-webapp-security-audit-hardening.md
  - docs/solutions/database-issues/sqlalchemy-core-migration-sqlite-to-portable.md
---

# FastAPI Migration: CherryPy Monolith to Vertical Domain Decomposition

## Problem

Comicarr's CherryPy backend was a monolith with 4 god files: `webserve.py` (12k lines/202 routes), `helpers.py` (6k lines/101 functions), `api.py` (1.9k lines/68 commands), and `postprocessor.py` (5k lines). 130+ mutable module-level globals served as the only shared-state mechanism. Every feature touched these files, creating merge conflicts and fear of change.

## Root Cause

CherryPy's attribute-based dispatch (`method.exposed = True`) and lack of dependency injection forced all state into `comicarr/__init__.py` globals. The single `WebInterface` class with 197 methods made decomposition impossible without a framework change.

## Solution

### Architecture: 9-Phase Strangler Fig Migration

Migrated to FastAPI with 6 vertical domains, each following a 3-layer pattern (`router.py` -> `service.py` -> `queries.py`):

```
comicarr/app/
  main.py              # App factory, lifespan, CachedStaticFiles
  core/                # AppContext, JWT auth, EventBus, CSRF middleware
  common/              # Extracted pure utilities (strings, dates, numbers, filesystem)
  system/              # Auth, SSE, config, admin
  series/              # Comics, issues, imports
  metadata/            # ComicVine, Metron, MangaDex, metatag
  search/              # Provider orchestration, RSS
  downloads/           # Queue, history, DDL, file serving
  storyarcs/           # Arcs, reading list, weekly
  opds/                # OPDS XML feeds (HTTP Basic auth)
```

### Key Design Decisions

1. **AppContext dataclass** replaces 130+ globals. Created once in lifespan, injected via `Depends(get_context)`. The `helpers.py` re-export shim bridges 30+ legacy callers.

2. **EventBus** with per-subscriber `asyncio.Queue` and `loop.call_soon_threadsafe()` replaces the single-slot `GLOBAL_MESSAGES` dict that lost events under concurrency.

3. **JWT cookie auth** with HS256 pinning, generation counter for revocation, and separate `jwt.key` file replaces CherryPy file-based sessions.

4. **Module-level functions** (not service classes) for domain services, matching existing codebase style.

### Critical Pitfalls Found During Code Review

**Security issues that were NOT obvious:**

- CSRF middleware exempted ALL `/api` routes (every FastAPI endpoint) because the exemption list was carried over from the CherryPy transition. Fix: narrow to only `/opds` and `/api/health`.
- `PUT /api/config` accepted arbitrary keys including `HTTP_PASSWORD` and `AUTHENTICATION`. Fix: writable-keys allowlist.
- CSP header was `Content-Security-Policy-Report-Only` (zero XSS protection). Fix: one-line change to enforcing.
- SSE endpoint had no auth dependency. Fix: add `Depends(require_session)`.
- File download endpoint failed open when no allowed directories configured. Fix: fail closed + use `os.path.commonpath` instead of `startswith`.
- OPDS file serving had no path validation at all (unlike the downloads router).

**Performance issues in OPDS router:**

- N+1 query storms: `opds_recent` opened 360 DB connections per page (3 queries x 120 records). Fix: batch queries with `IN` clause + lookup dicts.
- `havetotals()` ran full table scans on 4+ endpoints per request with no caching. Fix: 30-second TTL module-level cache.
- `ThreadPoolExecutor(20)` reference was lost, leaking threads on every restart. Fix: store reference, shut down in lifespan.

**Code quality issues from extraction:**

- 56 bare `except:` clauses carried forward from legacy code (CLAUDE.md explicitly prohibits).
- 20/35 service functions accepted `ctx` but never used it (YAGNI).
- `multikeysort()` used Python 2 `cmp()` builtin (would crash if called).
- `DDL_QUEUED` was a list in globals but a set in AppContext (`.append()` vs `.add()`).

### Frontend Migration

All hooks migrated from `apiCall("command", {params})` to `apiRequest("METHOD", "/api/path", body)`. The legacy `apiCall()` function was deleted along with API key query parameter auth (now JWT cookie-based).

## Result

- **76 files changed**, +14k / -24k lines (net -10,973 lines)
- Deleted `webserve.py`, `api.py`, `webstart.py`, `auth.py`, `opds.py`
- `helpers.py` reduced from 6,075 to 211 lines (re-export shim)
- Removed CherryPy, cheroot, portend, Mako, a2wsgi dependencies
- 306 backend tests passing, 26 frontend tests passing

## Prevention

1. **Run the full review agent suite on large refactors.** The 5-agent parallel review (security, Python quality, performance, architecture, simplicity) found issues that no single reviewer would catch. The CSRF exemption was the most dangerous -- it passed local testing perfectly.

2. **Don't carry forward legacy code verbatim during extraction.** Bare `except:` clauses, Python 2 code, and debug prints were all copied from helpers.py into new domain modules without cleanup. The extraction is the opportunity to fix these.

3. **Fail closed on security checks.** The `if allowed_dirs and not any(...)` pattern silently passes when the list is empty. Security validations should deny by default.

4. **Check CSP mode.** `Content-Security-Policy-Report-Only` looks correct in browser devtools (violations appear in console) but provides zero protection. Always verify the actual header name.

5. **Cache expensive per-request computations.** `havetotals()` was called 4+ times per OPDS browse session, each doing a full table scan. A 30-second TTL cache eliminated redundant work.

## Cross-References

- Security audit (pre-migration): `docs/solutions/security-issues/cherrypy-webapp-security-audit-hardening.md` -- 32 vulnerabilities fixed in CherryPy. Every mechanism needed a FastAPI equivalent.
- SQLAlchemy Core migration: `docs/solutions/database-issues/sqlalchemy-core-migration-sqlite-to-portable.md` -- case-sensitivity trap with `sqlite3.Row` vs SQLAlchemy `Row._mapping`.
- Docker deployment: `docs/solutions/integration-issues/mylar3-migration-docker-deployment.md` -- `SECURE_DIR` must be initialized before `encrypt_items()`.
