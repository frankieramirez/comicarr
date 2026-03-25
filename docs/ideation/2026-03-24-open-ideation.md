---
date: 2026-03-24
topic: open-ideation
focus: open-ended
---

# Ideation: Comicarr Open-Ended Improvements

## Codebase Context

**Project shape:** Python 3.10+/CherryPy backend + React 19/TypeScript frontend (Vite, TanStack Query, Radix UI, Tailwind 4). Forked from Mylar3 with a rebuilt UI. Docker deployed to Synology NAS.

**Notable patterns:**
- Conventional commits enforced; release-please automates versioning
- No Python type hints (by policy), no auto-formatter
- Global state via `comicarr.__init__` (80+ module-level mutable globals)
- DB access is raw SQL through `DBConnection` wrapper — SQLAlchemy Core installed but underutilized
- Frontend has clean domain separation (9 pages, 11+ hooks) that backend doesn't mirror

**Pain points:**
- God files: webserve.py (12k lines, 202 routes), helpers.py (6k, 106 functions), postprocessor.py (5k), search.py (4.3k) — totaling ~28k lines
- 237 raw SQL calls in webserve.py bypass SQLAlchemy Core (SQLite-only tech debt)
- Security audit completed (32 vulns hardened) but CI security gates never implemented
- Silent failures: Fernet decryption, Docker UID mismatches, config init ordering
- 54 `time.sleep` calls across 21 files blocking CherryPy's 15-thread pool
- CV cache uses separate raw `sqlite3.connect()` bypassing all SQLAlchemy pragmas/WAL
- Vendored `lib/` with unmaintained copies of torrent client libraries

**Past learnings (from docs/solutions/):**
- SQLAlchemy Core migration replaced 1,051 raw queries but 237 remain in webserve.py
- 8 duplicate helper functions found during that migration (symptom of 6k-line helpers.py)
- Multi-agent code review caught 5 blocking regressions during security fixes
- React effect cascades fundamentally broken for batch operations — server-side ThreadPoolExecutor is the proven pattern
- Docker UID mismatches and config init ordering burned real deployment time on Synology NAS

## Ranked Ideas

### 1. Vertical Domain Decomposition
**Description:** Reorganize the backend by domain — `series/`, `search/`, `downloads/`, `settings/` — each owning its routes, business logic, and data access. This collapses three recurring ideas (split webserve.py, split helpers.py, extract repository layer) into one coherent decomposition. No file exceeds 500 lines.
**Rationale:** webserve.py (12k lines, 202 routes, 249 raw SQL calls), helpers.py (6k lines, 106 functions), postprocessor.py (5k lines), and search.py (4.3k lines) total ~28k lines — roughly half the backend. Every feature, bugfix, and review touches these files. Vertical slices mean a developer working on search never touches download code. This is the prerequisite that unblocks everything else.
**Downsides:** Large migration with high merge conflict risk during transition. Requires careful import management to avoid circular dependencies. CherryPy's class-based routing makes sub-mounting less elegant than framework-native routers.
**Confidence:** 85%
**Complexity:** High
**Status:** Explored (brainstorm 2026-03-24)

### 2. CI Security & Quality Ratchet
**Description:** Add three CI jobs from the security audit (`ruff --select S`, `pip-audit`, grep gates for `shell=True`/SQL concat) plus a god-file metrics reporter that comments on PRs with lines-per-file changes. Start as warnings, promote to blocking after 2 weeks of green.
**Rationale:** The 32-vulnerability security audit was a point-in-time snapshot with no enforcement mechanism. Current CI has PR title lint, ruff check, and tests — zero security scanning. The god-file reporter creates visibility that compounds: "this PR added 30 lines to webserve.py, now 12,151 lines" changes behavior without mandating anything.
**Downsides:** False positives from bandit rules can be noisy. God-file metrics are vanity unless decomposition work actually happens. Adds ~2 min to CI time.
**Confidence:** 90%
**Complexity:** Low
**Status:** Unexplored

### 3. Resilient Download Pipeline with Dead Letter Queue
**Description:** Refactor postprocessor.py into discrete stages (detect, extract, tag metadata, move, update DB, notify) with per-stage retry policies. Items that fail N times are quarantined in a dead letter queue visible in the UI, with inspect/retry actions.
**Rationale:** postprocessor.py is 5k lines with 57 try/except blocks and 366 logger calls — defensive catch-and-continue that loses context. Docker UID mismatches (a known deployment gotcha) cause every post-processing cycle to retry the same broken items indefinitely, blocking the PP_QUEUE for items that could succeed.
**Downsides:** Requires careful state machine design. The dead letter UI is a new frontend surface. Migration of in-flight items during deployment needs handling.
**Confidence:** 75%
**Complexity:** High
**Status:** Unexplored

### 4. Fail-Fast Operations Dashboard
**Description:** Build a `/system` page showing: credential decryption status (can every Fernet-encrypted value round-trip?), download client connectivity, CherryPy thread pool utilization, database lock contention, disk space on library paths, and Docker volume/UID validation. Add a startup health check that surfaces broken credentials immediately instead of failing silently at runtime.
**Rationale:** Comicarr runs headless on a Synology NAS. Silent failures are the recurring theme: Fernet decryption passes through `gAAAAA...` strings, Docker UID mismatches cause invisible permission errors, config init ordering breaks credentials. Currently requires SSH + log grepping to diagnose. A self-diagnosis page turns hours into a glance.
**Downsides:** Thread pool metrics require CherryPy internals access. Some health checks (download client connectivity) add latency. Dashboard itself could become stale if not auto-refreshing.
**Confidence:** 80%
**Complexity:** Medium
**Status:** Unexplored

### 5. Provider Plugin Architecture with Circuit Breaker
**Description:** Define `SearchProvider` and `MetadataProvider` Protocol classes, refactor cv.py/metron.py/mangadex.py to implement them, and add a circuit breaker that trips after N consecutive failures per provider and auto-routes to alternates. The search orchestrator becomes a thin loop over registered providers.
**Rationale:** search.py (4.3k lines) has deeply interleaved provider-specific logic — adding a new provider means editing the god file. ComicVine has historically had outages and aggressive rate limiting. Currently, 30+ `time.sleep` calls across the backend handle retries by blocking CherryPy threads. A circuit breaker would let Metron serve metadata instantly when ComicVine is down, instead of stacking `sleep(15)` calls.
**Downsides:** Protocol abstraction may not fit all providers cleanly (MangaDex is manga-specific). Circuit breaker tuning requires real failure data. Metadata quality varies by provider, so automatic failover may surprise users.
**Confidence:** 70%
**Complexity:** Medium
**Status:** Unexplored

### 6. SQLite Write Queue with Batching
**Description:** Replace the `_db_lock` mutex with a dedicated writer thread consuming from a write queue. Batch writes into transactions. Also unify the CV cache database (which bypasses SQLAlchemy entirely with raw `sqlite3.connect()` and its own lock) into the main managed database.
**Rationale:** 15 CherryPy threads + 6 background queues (SNATCHED, PP, SEARCH, etc.) + APScheduler with `max_instances=3` all funnel writes through one `threading.Lock`. Under load (library scan + RSS check + post-processing), threads pile up on `_db_lock` causing UI timeouts. The CV cache's separate `sqlite3.connect()` with no WAL mode, no pragmas, and unbounded growth is a ticking time bomb.
**Downsides:** Writer thread introduces eventual consistency for writes. Error propagation from the writer back to the requesting thread needs careful design. CV cache migration requires schema changes.
**Confidence:** 70%
**Complexity:** Medium
**Status:** Unexplored

### 7. Lean Into SQLite Features
**Description:** Instead of abstracting away from SQLite, leverage its strengths: FTS5 for full-text comic library search, JSON1 extension for flexible metadata storage (provider responses as JSON columns instead of dozens of flat columns), WAL mode verification on startup, and `STRICT` tables for type safety the app currently lacks.
**Rationale:** The 237 raw SQL calls are a maintenance burden not because they're raw SQL, but because they're unstructured. Comic search currently happens in Python (search.py, 4.3k lines) when FTS5 could handle local library search at the database level. Metadata from different providers has different shapes — JSON columns handle this naturally instead of schema explosion. This reframes SQLite from "limitation we work around" to "advantage we exploit."
**Downsides:** FTS5 requires maintaining a shadow table with triggers. JSON queries are slower than indexed columns for frequent access patterns. Locks in deeper to SQLite if PostgreSQL support is ever wanted.
**Confidence:** 65%
**Complexity:** Medium
**Status:** Unexplored

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | Kill CherryPy for ASGI | Too ambitious; working system replacement with massive risk for uncertain gain |
| 2 | Database-first config (replace INI) | Massive scope; INI works, config bugs are ordering issues not format issues |
| 3 | Event sourcing for downloads | Over-engineered; dead letter queue captures the pragmatic version |
| 4 | Frontend BFF with OpenAPI | Real bottleneck is backend structure, not API shape |
| 5 | Filesystem-first library model | Interesting reframe but requires complete rearchitecture |
| 6 | Incremental type hints | CLAUDE.md explicitly forbids type hints — project policy |
| 7 | Contract tests (frontend/backend) | Lower priority than structural decomposition |
| 8 | Delete vendored lib/ | Valid chore, not idea-level — just do it |
| 9 | OPDS streaming reader | Feature request, not structural improvement |
| 10 | Global state elimination | Subsumed by vertical domain decomposition |
| 11 | Search executor thread leak | Bug fix, not ideation-level |
| 12 | RSS feed size limits | Bug fix, not ideation-level |
| 13 | Config hot-reload race condition | Too specific for ideation |
| 14 | TanStack Query dedup audit | Too specific for ideation |
| 15 | Smart duplicate detection | Feature request, not structural improvement |
| 16 | SSE notification center | Already partially exists; lower priority |
| 17 | Finish raw SQL via code generator | Subsumed by vertical decomposition + repository extraction |
| 18 | Blocking sleep audit | Subsumed by circuit breaker + write queue work |
| 19 | Docker UID auto-detect | Folded into fail-fast operations dashboard |
| 20 | Automated raw SQL migration script | Clever but brittle; manual conversion with vertical decomposition is more reliable |

## Session Log
- 2026-03-24: Initial ideation — 48 raw ideas generated across 6 agents, deduped to ~28 unique candidates, 4 cross-cutting combinations synthesized, 7 survivors after adversarial filtering
- 2026-03-24: Brainstorm initiated for idea #1 (Vertical Domain Decomposition)
