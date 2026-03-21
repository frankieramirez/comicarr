---
title: "Complete Mylar3 Rebrand & Architecture Audit for Public Release"
type: refactor
status: active
date: 2026-03-21
---

# Complete Mylar3 Rebrand & Architecture Audit for Public Release

## Enhancement Summary

**Deepened on:** 2026-03-21
**Research agents used:** security-sentinel, architecture-strategist, pattern-recognition-specialist, kieran-python-reviewer, deployment-verification-agent, data-integrity-guardian, best-practices-researcher, git-history-analyzer, code-simplicity-reviewer

### Key Improvements

1. **Critical WAL-mode gap discovered** — SQLite uses WAL mode, meaning 3 files exist on disk (`*.db`, `*.db-wal`, `*.db-shm`). A naive file rename loses uncommitted transactions. Must run `PRAGMA wal_checkpoint(TRUNCATE)` before rename.
2. **Git history is clean** — `config.ini` was never committed. No credentials in history. BFG/git-filter-repo step is unnecessary for credential scrub. The repo is safe to make public.
3. **Phase consolidation** — Merged GPL headers (Phase 3) and file renames (Phase 5.1) into Phase 1 to avoid multiple passes over every file. Reduced from 7 phases to 5.
4. **`__pycache__` contamination risk** — Stale `.pyc` files after `git mv` can mask import errors. Must delete all `__pycache__/` immediately after the directory rename.
5. **32 deferred (inline) imports** inside function bodies will survive a top-of-file-only grep. The acceptance criteria now explicitly cover these.
6. **Security hardening opportunities** — `getConfig` API exposes credentials in response, carepackage dumps all env vars, no security headers on CherryPy. Low-effort fixes while touching these files.
7. **Python 3.14 breaking change** — 170+ invalid escape sequences (non-raw regex strings) will become errors. Must fix during the rename pass.
8. **Vendored `lib/` cleanup** — `natsort` and `rarfile` are duplicated (in both `lib/` and `pyproject.toml`). The vendored copies shadow the installed packages due to `sys.path` insertion order.
9. **GPL compliance** — Must preserve original Mylar3 copyright notices alongside new Comicarr copyright. Cannot remove, only add.
10. **Docker modernization** — Recommended 3-stage Dockerfile with `uv sync` replacing `pip install -r requirements.txt`.

### New Considerations Discovered

- `encrypted.py` is base64 obfuscation, not encryption — document this limitation before public release
- `six` and `configparser` are Python 2 backports still listed as dependencies — remove them
- `SAB_TO_MYLAR` config key has existing migration infrastructure (`_BAD_DEFINITIONS`, config version system) that should be used instead of silent drop
- All 67 git tags are neutral `v*` format (no "mylar" tags to clean up)
- `cv_cache.db` does not contain "mylar" in its name — no rename needed
- `test.py` and `req_test.py` inside the package are not tests — misleading for contributors
- `ruff target-version = "py39"` contradicts `requires-python = ">=3.10"` — fix while touching pyproject.toml

---

## Overview

Remove every trace of "Mylar" / "Mylar3" from the Comicarr codebase and restructure the project architecture for a professional public release. This is a clean break — no backward compatibility with Mylar3 configs, databases, or tooling.

**Scope**: 4,174 occurrences of "mylar"/"Mylar" across 120 files. Rename the core Python package `mylar/` → `comicarr/`, update all 289 import statements, fix 64+ GPL headers, replace branding assets, rewrite outdated docs, fix CI, and resolve architectural inconsistencies.

## Problem Statement

Comicarr is built on the Mylar3 foundation but is being released as an independent project. The codebase still carries deep Mylar3 branding throughout:

- The entire Python backend package is named `mylar/`
- User-visible notifications say "Mylar has snatched..."
- The favicon shows the Mylar3 logo
- Version checking phones home to `github.com/mylar3/mylar3`
- Publisher imprints data is fetched from `mylar3.github.io`
- Init scripts, post-processing scripts, and docs all reference Mylar
- The `API_REFERENCE` file still uses terminology from Headphones (the project Mylar was itself forked from)
- CI workflows use `bun` despite the project standardizing on `npm`
- File naming is inconsistent (PascalCase mixed with snake_case)

A public release with these traces would create confusion about the project's identity and signal lack of attention to detail.

## Proposed Solution

Execute the rebrand and restructure in 5 phases, ordered by dependency and risk:

1. **Security first** — credential rotation, verify clean git history
2. **Core rename + headers + file renames** — `mylar/` → `comicarr/`, all imports, GPL headers, PascalCase→snake_case (single atomic pass)
3. **User-visible rebrand** — notifications, OPDS, SSL, ASCII logo, favicon
4. **Infrastructure + cleanup** — CI, Docker, docs, external dependencies
5. **Verification** — full test suite, manual smoke test, final grep audit

## Technical Approach

### Architecture

The rename is primarily mechanical but high-risk due to the global state pattern. Every Python file imports `mylar` and accesses `mylar.CONFIG`, `mylar.DATA_DIR`, `mylar.SIGNAL`, etc. The rename must be atomic — a partial rename will crash the application.

**Strategy**: Use scripted `sed` replacements in a controlled sequence (most-specific identifiers first, then bulk import replacements), then verify with `python -c "import comicarr"` and the full test suite.

### Research Insights: Rename Execution

**Recommended `sed` ordering** (from Python reviewer):
1. Rename specific identifiers first (`cmtagmylar` → `cmtag`, `mylarQueue` → `db_queue`, `SAB_TO_MYLAR` migration)
2. Rename the file (`git mv cmtagmylar.py cmtag.py`)
3. Then bulk import replacements (`from mylar import` → `from comicarr import`, `import mylar` → `import comicarr`)
4. Then `mylar.` → `comicarr.` for global state access
5. Then user-visible string replacements

**Do NOT use a global `sed 's/mylar/comicarr/g'`** — this would corrupt `cmtagmylar` to `cmtagcomicarr` and other substring matches.

**Relative imports (`from . import`) survive the directory rename automatically** — they do not reference the package name. The ~20 files using relative imports need no changes for the directory rename itself (only for renamed files like `cmtagmylar`).

### Implementation Phases

---

#### Phase 0: Security — Credential Verification & Rotation

**Why first**: Must be resolved before any public visibility.

### Research Insights: Git History Is Clean

The git-history-analyzer confirmed:
- **`config.ini` was never committed** — it has been in `.gitignore` since the very first commit (2012). No `git filter-repo` / BFG step is needed.
- **No credentials, private keys, or `.env` files exist in git history.**
- Two `.pem` files exist in history but are harmless (CherryPy test fixture and requests CA bundle).
- **The repo is safe to make public from a credentials perspective.**
- Full Mylar3 history is carried (2,740 commits, 14 years, ~90 contributors). All 67 tags use neutral `v*` format.

**Tasks**:

- [ ] Confirm with `git log --all --full-history -- config.ini` that it returns nothing
- [ ] Rotate all exposed credentials (on-disk `config.ini` has real values):
  - ComicVine API key — re-register at comicvine.gamespot.com/api/
  - Metron password — change at metron.cloud account settings
  - Internal API key — generate new: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
  - **Generate new credentials BEFORE revoking old ones** (zero-downtime pattern)
- [ ] Verify new credentials work against live services before proceeding
- [ ] Verify `config.ini` is in `.gitignore` (confirmed: it is)
- [ ] Create `config.ini.sample` with structure but placeholder values (use obvious placeholders like `YOUR_API_KEY_HERE`, not fake hex strings) — `config.ini.sample`
- [ ] Audit `.pem`/`.key`/`.cert` files in history: `git log --all --full-history -- "*.pem" "*.key" "*.cert" "*.crt"` — verify none are private keys
- [ ] **Change `http_password = admin`** in the live deployment's `config.ini` (security sentinel finding)

### Research Insights: Security Hardening Opportunities

The security sentinel found several pre-existing vulnerabilities that are low-effort to fix during the rebrand since the files are already being touched:

| Finding | Severity | File | Recommended Action |
|---------|----------|------|-------------------|
| `encrypted.py` is base64 obfuscation, not encryption | High | `encrypted.py` | Document limitation; do not claim "encryption" |
| `getConfig` API returns `api_key`, `comicvine_api`, `metron_password` in plaintext | High | `api.py:2203-2244` | Mask as `****...last4` in response |
| Carepackage dumps ALL env vars (including secrets) | High | `carepackage.py:167-170` | Add exclusion list for `*_KEY`, `*_SECRET`, `*_PASSWORD`, `*_TOKEN` |
| No security headers on CherryPy | Medium | `webstart.py` | Add `X-Content-Type-Options`, `X-Frame-Options`, `CSP` |
| SSL key file written with no permission restriction | Medium | `helpers.py:2414-2443` | Set `0600` on generated key file |
| No brute-force protection on login | Medium | `auth.py` | Track for future hardening (not in this PR) |

**Acceptance criteria**:
- [ ] `git log --all -- config.ini` returns nothing
- [ ] All three credentials rotated and verified working
- [ ] `config.ini.sample` exists with placeholder values

---

#### Phase 1: Core Package Rename + GPL Headers + File Renames

This is the highest-risk phase. Every Python file depends on the `mylar` module name.

### Research Insights: Consolidated Single Pass

The architecture strategist recommends merging GPL headers (originally Phase 3) and PascalCase file renames (originally Phase 5.1) into this phase to avoid multiple passes over every file. Touching each file once reduces total risk and eliminates intermediate inconsistent states.

**Tasks**:

##### 1.1 Rename the directory + clean bytecode cache

- [ ] `git mv mylar/ comicarr/` — rename the package directory
- [ ] **`find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null`** — delete ALL `__pycache__` directories immediately. Stale `.pyc` files can mask import errors during testing (Python reviewer critical finding).

##### 1.2 Rename PascalCase files (do this BEFORE bulk sed)

- [ ] `git mv comicarr/PostProcessor.py comicarr/postprocessor.py`
- [ ] `git mv comicarr/Failed.py comicarr/failed.py`
- [ ] `git mv comicarr/cmtagmylar.py comicarr/cmtag.py`
- [ ] Update all imports for these renamed files:
  - `PostProcessor` importers: `__init__.py:43`, `opds.py:19`, `helpers.py:1407` (deferred import)
  - **Self-import in `PostProcessor.py:3580`**: `from . import PostProcessor, logger` → `from . import postprocessor, logger` (highest-risk line — a module importing itself by its own filename)
  - `Failed` importers: `search.py` (1 deferred import at line 3937)
  - `cmtagmylar` importers: `webserve.py:8260`, `PostProcessor.py:1881,2494,3092` (3 deferred imports)

##### 1.3 Rename specific identifiers (BEFORE bulk import sed)

- [ ] `comicarr/db.py:32,143` — `mylarQueue` → `db_queue`
- [ ] `comicarr/logger.py:57,78,127,193` — `logging.getLogger('mylar')` → `logging.getLogger('comicarr')`
- [ ] `comicarr/logger.py:160-161` — `'mylar.log'` → `'comicarr.log'`

##### 1.4 Config key migration (use existing infrastructure)

The data-integrity-guardian found that Comicarr already has a config version system (`CONFIG_VERSION` at v14) with a `config_update()` method and `_BAD_DEFINITIONS` mechanism designed exactly for key migrations. Use it instead of silently dropping the old value.

- [ ] Increment `CONFIG_VERSION` to 15 in `comicarr/config.py`
- [ ] Add `SAB_TO_MYLAR` to `_BAD_DEFINITIONS` mapping it to new key `SAB_DIRECT_UNPACK`
- [ ] Add migration step in `config_update()` that reads old value and writes new key
- [ ] Update all references in: `api.py`, `search.py`, `webserve.py`, `sabnzbd.py`, `postprocessor.py`

##### 1.5 Bulk import replacement (289 statements across 79+ files)

Run targeted `sed` replacements in this order:

```bash
# Inside comicarr/ package, lib/rtorrent/, tests/, and entry point
find comicarr/ lib/rtorrent/ tests/ Comicarr.py -name '*.py' -exec \
  sed -i '' 's/from mylar import/from comicarr import/g; s/from mylar\./from comicarr./g; s/import mylar$/import comicarr/g' {} +
```

**Critical: Also catch deferred (inline) imports inside function bodies** — the pattern-recognition-specialist found 32 instances of `from mylar import ...` inside functions. These will be caught by the bulk `sed` above since it searches all content, not just top-of-file. But verify with:

```bash
grep -rn "from mylar\|import mylar" comicarr/ lib/ tests/ Comicarr.py
```

Key deferred imports to verify:
- `comicarr/__init__.py:400,427,435,449` — 4 inline imports of submodules
- `comicarr/config.py:1458` — `import comictaggerlib.ctversion`
- `comicarr/webserve.py:8625` — `from comicarr.torrent.clients import qbittorrent`
- `comicarr/helpers.py:1407,2980,3528` — 3 deferred imports
- `comicarr/postprocessor.py:1881,2494,3092,3580` — 4 deferred imports
- `comicarr/filechecker.py:1679` — deferred `from comicarr import db`

Also verify dynamic attribute access (Python reviewer finding):
- `comicarr/__init__.py:803,812` — `getattr(mylar, pool_attr)` / `setattr(mylar, pool_attr, ...)` — these reference the module by its imported name, not a string. Will fail at runtime (not startup) if missed.

In `lib/` (vendored third-party):
- [ ] `lib/rtorrent/__init__.py:27` — `from comicarr import logger`
- [ ] `lib/rtorrent/rpc/__init__.py:27` — same
- [ ] `lib/rtorrent/torrent.py:27` — same
- [ ] Add comment: `# Modified for Comicarr (originally from python-rtorrent)`

##### 1.6 Update `mylar.` global state references

- [ ] Replace all `mylar.CONFIG`, `mylar.DATA_DIR`, `mylar.SIGNAL`, `mylar.PROG_DIR`, `mylar.DB_FILE`, etc. → `comicarr.*` across all files
- [ ] Also catch `sys.path` manipulations in `comicarr/logger.py:89,211` that reference `mylar.PROG_DIR` (architecture strategist finding)

##### 1.7 Database and maintenance file renames (in source code only)

- [ ] `comicarr/db.py:63,68,132,138` — `"mylar.db"` → `"comicarr.db"`
- [ ] `comicarr/maintenance.py:32` — `'.mylar_maintenance.db'` → `'.comicarr_maintenance.db'`
- [ ] `comicarr/maintenance.py:383` — `'mylar.db.backup'` → `'comicarr.db.backup'`
- [ ] `comicarr/solicit.py:170` — `"mylar.db"` → `"comicarr.db"`
- [ ] `Comicarr.py:371` — `'mylar.db'` → `'comicarr.db'`
- [ ] `comicarr/carepackage.py` — update all `mylar.db`, `mylar.log*` glob references

**Note**: `cv_cache.db` does NOT need renaming — its filename contains no "mylar" branding (data-integrity-guardian confirmed).

##### 1.8 Update pyproject.toml

- [ ] Line 49: `include = ["mylar*"]` → `include = ["comicarr*"]`
- [ ] Line 75: `source = ["mylar"]` → `source = ["comicarr"]`
- [ ] Lines 77-78: `"mylar/test.py"`, `"mylar/req_test.py"` → `"comicarr/..."`
- [ ] **Fix `target-version = "py39"` → `"py310"`** to match `requires-python = ">=3.10"` (Python reviewer finding)
- [ ] **Remove `configparser` from dependencies** — it is part of the Python 3 standard library (Python 2 backport)
- [ ] **Remove `six` from dependencies** — Python 2/3 compatibility layer, unnecessary with `>=3.10`

##### 1.9 Update .gitignore

- [ ] `mylar.db` → `comicarr.db`
- [ ] `.mylar_maintenance.db` → `.comicarr_maintenance.db`

##### 1.10 GPL license headers (same pass as imports)

All 64+ Python files carry the Mylar GPL header. GPL v3 requires preserving original copyright notices (best-practices-researcher confirmed).

- [ ] Replace in all `comicarr/*.py` files:
  ```
  #  This file is part of Mylar.
  #  Mylar is free software: ...
  #  along with Mylar.
  ```
  →
  ```
  #  Copyright (C) [original year] Mylar3 contributors
  #  Copyright (C) 2026 Comicarr contributors
  #
  #  This file is part of Comicarr.
  #  Originally based on Mylar3 (https://github.com/mylar3/mylar3).
  #  Comicarr is free software: ...
  #  along with Comicarr.
  ```
- [ ] Update `Comicarr.py` header
- [ ] Update test file headers

##### 1.11 Remove dead Python 2 code

- [ ] `comicarr/logger.py:27` — remove `from six import PY2`
- [ ] `comicarr/logger.py:142-148` — remove dead `PY2` code branch (can never execute on Python 3.10+)

**Acceptance criteria**:
- [ ] `python -c "import comicarr"` succeeds
- [ ] `python -c "from comicarr import config, db, logger, helpers"` succeeds
- [ ] `grep -rn "from mylar\|import mylar" comicarr/ lib/ tests/ Comicarr.py` returns zero results
- [ ] `grep -rn "getattr(mylar\|setattr(mylar" comicarr/` returns zero results (catches dynamic attribute access)
- [ ] No `__pycache__` directories from the old `mylar/` package exist
- [ ] `grep -r "This file is part of Mylar" .` returns zero results
- [ ] Full test suite passes: `pytest tests/unit -v`
- [ ] Application starts: `python Comicarr.py --nolaunch --quiet`

---

#### Phase 2: User-Visible Rebrand

All strings that end users see in notifications, feeds, logs, and UI.

**Tasks**:

##### 2.1 Notification strings — `comicarr/notifiers.py`

- [ ] Line 135: `"Mylar has snatched: "` → `"Comicarr has snatched: "`
- [ ] Line 253: same
- [ ] Line 297: same
- [ ] Line 429: `"Mylar notification - Test"` → `"Comicarr notification - Test"`
- [ ] Line 528: `"username": "Mylar"` → `"username": "Comicarr"` (Slack webhook)
- [ ] Line 641: `"name": "Mylar Error"` → `"name": "Comicarr Error"` (Discord embed)
- [ ] Update informal attribution comment at line 36: `# This was obviously all taken from headphones with great appreciation :)` → professional attribution

##### 2.2 Post-processor notifications — `comicarr/postprocessor.py`

- [ ] Line 3521: `'Mylar has downloaded and post-processed: '` → `'Comicarr has downloaded and post-processed: '`
- [ ] Line 3561: `"Mylar notification - Processed"` → `"Comicarr notification - Processed"`

##### 2.3 Search notifications — `comicarr/search.py`

- [ ] Line 3906: `"Mylar notification - Snatch"` → `"Comicarr notification - Snatch"`

##### 2.4 OPDS feed titles — `comicarr/opds.py`

- [ ] Line 131: `'Mylar OPDS'` → `'Comicarr OPDS'` (plus ~10 more OPDS title references)

##### 2.5 SSL certificate — `comicarr/helpers.py`

- [ ] Line 2432: `CN="Mylar"` → `CN="Comicarr"`
- [ ] **Set file permissions `0600` on generated SSL key file** (security sentinel finding)

##### 2.6 Startup/shutdown messages — `comicarr/__init__.py`

- [ ] Line 1877: `'Mylar is shutting down...'` → `'Comicarr is shutting down...'`
- [ ] Line 1879: `'Mylar is updating...'` → `'Comicarr is updating...'`
- [ ] Line 1883: `'Mylar failed to update'` → `'Comicarr failed to update'`
- [ ] Line 1890: `'Mylar is restarting...'` → `'Comicarr is restarting...'`

##### 2.7 Comictagger messages — `comicarr/cmtag.py`

- [ ] Lines 352-399: Replace 6 occurrences of `"Mylar metatagging error: "`

##### 2.8 Version check messages — `comicarr/versioncheck.py`

- [ ] Line 333: `'Mylar is up to date'` → `'Comicarr is up to date'`

##### 2.9 Auth realm — `comicarr/webstart.py`, `comicarr/maintenance_webstart.py`

- [ ] `webstart.py:135` — `'Mylar'` → `'Comicarr'`
- [ ] `webstart.py:159` — `'Mylar OPDS'` → `'Comicarr OPDS'`
- [ ] `maintenance_webstart.py:126` — `'Mylar'` → `'Comicarr'`
- [ ] **Add security headers** while touching `webstart.py` (security sentinel finding):
  ```python
  'tools.response_headers.on': True,
  'tools.response_headers.headers': [
      ('X-Content-Type-Options', 'nosniff'),
      ('X-Frame-Options', 'DENY'),
  ],
  ```

##### 2.10 MangaDex User-Agent — `comicarr/mangadex.py`

- [ ] Line 85: `'Mylar3/1.0'` → `'Comicarr/1.0'`

##### 2.11 Carepackage — `comicarr/carepackage.py`

- [ ] Line 95: `'MylarRunningEnvironment.txt'` → `'ComicarrRunningEnvironment.txt'`
- [ ] **Add env var exclusion list** (security sentinel finding — carepackage dumps ALL env vars):
  ```python
  SECRET_PATTERNS = ['KEY', 'SECRET', 'PASSWORD', 'TOKEN', 'API', 'CREDENTIAL']
  for param in list(os.environ.keys()):
      if any(s in param.upper() for s in SECRET_PATTERNS + ['SSH', 'LS_COLORS']):
          continue
      f.write(...)
  ```

##### 2.12 API credential masking — `comicarr/api.py`

- [ ] In `_getConfig()` (lines 2203-2244): mask `api_key`, `comicvine_api`, and `metron_password` as `****...last4` instead of returning full plaintext values (security sentinel finding)

##### 2.13 Entry point help text — `Comicarr.py`

- [ ] Line 220: `'Force mylar to run on a specified port'` → `'Force Comicarr to run on a specified port'`
- [ ] Line 231: `'Export existing mylar.db to json file'` → `'Export existing comicarr.db to json file'`
- [ ] Line 232: `'Import a mylar.db into current db'` → `'Import a database into current db'`
- [ ] Line 403: `'Backing up mylar.db & config.ini'` → `'Backing up comicarr.db & config.ini'`
- [ ] Line 463: `'Attempting to update Mylar...'` → `'Attempting to update Comicarr...'`
- [ ] Line 467: `'Mylar failed to update'` → `'Comicarr failed to update'`
- [ ] Line 517: `'Starting Mylar on forced port: %i'` → `'Starting Comicarr on forced port: %i'`

##### 2.14 Frontend references

- [ ] `frontend/src/components/ui/EmptyState.tsx:58` — `"Mylar will automatically search for them."` → `"Comicarr will automatically search for them."`
- [ ] `frontend/src/types/entities.ts:139` — `// Mapped to Mylar issue structure` → `// Mapped to Comicarr issue structure`

##### 2.15 ASCII logo — `ascii_logo.nfo`

- [ ] Replace `mylar3` ASCII art with Comicarr ASCII art

##### 2.16 Favicon

- [ ] Verify `frontend/public/favicon.ico` is Comicarr-branded (not the Mylar yellow icon from the screenshot)
- [ ] Generate proper `.ico` file (currently a PNG misnamed as .ico)
- [ ] Verify `logo.svg` has no Mylar references

##### 2.17 Test assertion strings

- [ ] `tests/unit/notifiers/test_discord.py` — update `"Mylar Notification"` assertions
- [ ] `tests/unit/notifiers/conftest.py` — update `"snline": "Mylar Notification"` fixture
- [ ] `tests/__init__.py` — `# Mylar3 Test Suite` → `# Comicarr Test Suite`
- [ ] `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/factories/__init__.py` — same

**Acceptance criteria**:
- [ ] `grep -ri "mylar" comicarr/notifiers.py comicarr/opds.py comicarr/webstart.py comicarr/__init__.py Comicarr.py frontend/src/` returns zero user-visible "Mylar" strings
- [ ] Notifications display "Comicarr" in Pushover, Slack, Discord, email
- [ ] OPDS feeds show "Comicarr OPDS" as title
- [ ] Browser tab shows Comicarr favicon and title

---

#### Phase 3: Infrastructure + Cleanup

##### 3.1 CI Workflows — Fix bun→npm and Mylar references

`.github/workflows/ci.yml`:
- [ ] Replace `oven-sh/setup-bun@v2` with `actions/setup-node@v4` (node-version: 22, cache: npm)
- [ ] Replace `bun install --frozen-lockfile` → `npm ci`
- [ ] Replace `bun run` → `npm run`
- [ ] Line 61: `ruff check mylar/` → `ruff check comicarr/`
- [ ] Line 65: `ruff format --check mylar/` → `ruff format --check comicarr/`

`.github/workflows/test.yml`:
- [ ] Same bun→npm replacement
- [ ] Line 44: `--cov=mylar` → `--cov=comicarr`
- [ ] Line 48: `--cov=mylar` → `--cov=comicarr`
- [ ] Line 147: `mkdir -p /tmp/mylar_test` → `mkdir -p /tmp/comicarr_test`
- [ ] Line 150: `python Mylar.py` → `python Comicarr.py` (this is ALREADY BROKEN — entry point was renamed but CI wasn't updated)
- [ ] Line 151: `/tmp/mylar.pid` → `/tmp/comicarr.pid`
- [ ] Lines 168-169: same pid file reference
- [ ] E2E: `bunx playwright install` → `npx playwright install --with-deps chromium`

`.github/workflows/release.yml` and `.github/workflows/claude.yml`:
- [ ] Replace any `bun` references with `npm`

##### 3.2 Dockerfile — Modernize with uv

The current Dockerfile uses `pip install -r requirements.txt` while development uses `uv sync` with `pyproject.toml`. This creates dependency drift (architecture strategist finding).

### Research Insights: Recommended Docker Build

The best-practices-researcher recommends a 3-stage build with `uv`:

```dockerfile
# Stage 1: Frontend build (npm ci + npm run build)
# Stage 2: Backend build (uv sync --locked, compiles bytecode)
# Stage 3: Minimal runtime (no build tools, no uv binary, non-root user)
```

Key improvements over current:
- `uv sync --locked` is 5-10x faster than `pip install`
- `python:3.12-slim` instead of Alpine (avoids musl libc compatibility issues)
- Non-root user (UID 1001) for security
- BuildKit cache mounts for faster rebuilds
- Build tools NOT in final image (separate stage)

- [ ] Rewrite Dockerfile with 3-stage uv-based build
- [ ] Generate `uv.lock` if not present: `uv lock`
- [ ] Replace any `Mylar.py` references → `Comicarr.py`
- [ ] Replace `/opt/mylar` → `/opt/comicarr`
- [ ] Verify `docker-compose.yml` uses correct image name

##### 3.3 Vendored `lib/` cleanup

The architecture strategist found that `natsort` and `rarfile` exist in BOTH `lib/` (vendored) AND `pyproject.toml` (proper dependency). Because `Comicarr.py` line 26 inserts `lib/` into `sys.path` at position 1 (before site-packages), the vendored copies **shadow the installed packages** — you may be running ancient versions.

- [ ] **Remove `lib/natsort/`** — already a proper dependency in pyproject.toml
- [ ] **Remove `lib/rarfile/`** — already a proper dependency in pyproject.toml
- [ ] Add to `pyproject.toml` as proper dependencies: `configobj`, `bencodepy`
- [ ] Remove `lib/configobj.py` and `lib/bencode.py` after adding to deps
- [ ] Keep vendored (modified): `lib/rtorrent/`, `lib/comictaggerlib/`, `lib/certgen.py`
- [ ] Evaluate: `lib/transmissionrpc/`, `lib/deluge_client/`, `lib/mega/`, `lib/get_image_size.py`

##### 3.4 Post-processing scripts

- [ ] `post-processing/autoProcessComics.cfg.sample` — `[Mylar]` → `[Comicarr]`
- [ ] `post-processing/autoProcessComics.py` — 6 `config.get("Mylar", ...)` → `config.get("Comicarr", ...)`
- [ ] `post-processing/torrent-auto-snatch/read.me` — update 6 mylar references
- [ ] `post-processing/nzbget/ComicRN.py` — update mylar reference
- [ ] `post-processing/sabnzbd/ComicRN.py` — update mylar reference

##### 3.5 Init scripts

- [ ] Rename `init-scripts/systemd/mylar.service` → `comicarr.service`, update Description and ExecStart
- [ ] Rename `init-scripts/init.d/ubuntu.default.mylar` → `ubuntu.default.comicarr`, rename `MYLAR_*` → `COMICARR_*`
- [ ] Update `init-scripts/init.d/ubuntu.init.d` — all 45 `MYLAR_*` references → `COMICARR_*`
- [ ] Update `init-scripts/centos.init.d` — all 12 mylar references
- [ ] Update all read.me files in init-scripts/

##### 3.6 Shell scripts

- [ ] `monitor_performance.sh` — update hardcoded `mylar3` paths and `mylar.log`
- [ ] `view_search_stats.sh` — update hardcoded `mylar3` paths and `mylar.log`

##### 3.7 Version check URLs — `comicarr/versioncheck.py`

- [ ] Line 124: `'/mylar3/tags'` → `'/comicarr/tags'`
- [ ] Line 139: `'/mylar3/releases/tags/'` → `'/comicarr/releases/tags/'`
- [ ] Line 243: same pattern
- [ ] Line 298: `'/mylar3/commits/'` → `'/comicarr/commits/'`
- [ ] Line 316: `'/mylar3/compare/'` → `'/comicarr/compare/'`
- [ ] Line 378: `'/mylar/tarball/'` → `'/comicarr/tarball/'`
- [ ] Verify `config.py` `GIT_USER` default matches the actual GitHub owner (likely `frankieramirez` per `release.yml`)

##### 3.8 Publisher imprints — `comicarr/__init__.py`

- [ ] Line 505: Change `'https://mylar3.github.io/publisher_imprints/imprints.json'` to the Comicarr-controlled URL (or leave as-is with a `TODO` comment if hosting isn't set up yet)
- [ ] The existing local-cache-on-disk logic already handles the fallback case if the URL is unreachable

##### 3.9 Documentation updates

- [ ] `README.md` — update any remaining Mylar3 references (keep attribution section)
- [ ] `CLAUDE.md` — update codebase index (`mylar/` → `comicarr/`), import patterns
- [ ] `AGENTS.md` — same updates
- [ ] `docs/PERFORMANCE_IMPROVEMENTS.md` — update title, fix `Mylar.py` → `Comicarr.py` references
- [ ] `docs/COMMUNITY_FEATURES.md` — update links and references
- [ ] **Delete `API_REFERENCE`** — it uses Headphones terminology ("ArtistName", "AlbumID") and is actively misleading. An inaccurate API reference is worse than none. Create proper docs separately.
- [ ] **Delete old screenshots** `screens/mylar_*.jpg` — they show the old Mylar3 UI, not the React frontend
- [ ] Clean up `comicarr/db.py:17` — `## Stolen from Sick-Beard's db.py ##` → `## Database connection handler (based on Sick-Beard) ##`

##### 3.10 Remove `bun.lock` if it exists

- [ ] `git rm bun.lock 2>/dev/null || true`

##### 3.11 Rename misleading files (pattern recognition finding)

- [ ] `comicarr/test.py` → `comicarr/rtorrent_test_client.py` (it defines `class RTorrent`, not a test)
- [ ] `comicarr/req_test.py` → `comicarr/dependency_check.py` (tests if required libraries are installed)
- [ ] Update all imports of these renamed files

**Acceptance criteria**:
- [ ] CI pipeline passes on all workflows (using npm, not bun)
- [ ] `docker build .` succeeds
- [ ] `grep -ri "mylar" .github/ init-scripts/ post-processing/ Dockerfile docker-compose.yml` returns zero results
- [ ] No vendored duplicates of declared dependencies in `lib/`

---

#### Phase 4: Verification & Final Sweep

##### 4.1 Automated verification

- [ ] `grep -ri "mylar" comicarr/ lib/ tests/ Comicarr.py frontend/src/ .github/ Dockerfile docker-compose.yml init-scripts/ post-processing/ pyproject.toml .gitignore` — should return ONLY:
  - Attribution in README.md (crediting Mylar3 foundation)
  - Attribution in GPL headers ("Originally based on Mylar3")
  - Historical plan docs in `docs/plans/`
- [ ] `grep -rn "getattr(mylar\|setattr(mylar" comicarr/` — zero results (dynamic attribute access)
- [ ] `python Comicarr.py --nolaunch --quiet` — starts without errors
- [ ] Full test suite: `pytest tests/ -v --cov=comicarr`
- [ ] Frontend builds: `cd frontend && npm run build`
- [ ] Docker builds: `docker build .`
- [ ] Linting passes: `ruff check comicarr/`

##### 4.2 Manual smoke test

- [ ] Add a comic series via the web UI
- [ ] Verify search works
- [ ] Check OPDS feed shows "Comicarr OPDS"
- [ ] Verify notifications display "Comicarr" (test notification)
- [ ] Check browser tab shows correct favicon and title
- [ ] Verify version check runs without errors
- [ ] **Exercise the scheduler start path** — wait for at least one RSS check cycle to verify `getattr(comicarr, pool_attr)` works (Python reviewer finding)

##### 4.3 Final grep audit

- [ ] Run case-insensitive search for ALL of: `mylar`, `Mylar`, `MYLAR`, `mylar3`, `Mylar3`, `MYLAR3`
- [ ] Classify each remaining hit as: attribution (keep), historical doc (acceptable), or missed reference (fix)

**Acceptance criteria**:
- [ ] Zero unintended "mylar" references remain
- [ ] All CI checks pass
- [ ] Application starts and functions correctly
- [ ] Docker image builds and runs

---

## System-Wide Impact

### Interaction Graph

Package rename triggers: every `import comicarr` → module init (`__init__.py`) → config loading → database connection → scheduler start → web server start. A single broken import in this chain crashes the entire application at startup.

### Error Propagation

If the rename is incomplete, errors manifest as `ModuleNotFoundError: No module named 'mylar'` at import time. These are fail-fast — the app will not start, so there's no risk of partial operation with a broken rename.

**Exception**: Dynamic attribute access via `getattr(comicarr, pool_attr)` in `__init__.py:803,812` will fail at **runtime** (when the scheduler fires), not at startup. The smoke test must exercise this path.

### State Lifecycle Risks

- **Database (CRITICAL — WAL mode)**: SQLite uses WAL mode (`PRAGMA journal_mode = WAL`), meaning 3 files exist: `mylar.db`, `mylar.db-wal`, `mylar.db-shm`. A naive rename of only the main file **loses uncommitted transactions** in the WAL. **Required procedure for actual file rename on user systems**:
  1. Shut down the application completely
  2. Run: `sqlite3 mylar.db "PRAGMA wal_checkpoint(TRUNCATE);"`
  3. Verify `mylar.db-wal` is empty (0 bytes) or absent
  4. Only then rename: `mv mylar.db comicarr.db`
  5. Do NOT rename WAL/SHM files — after TRUNCATE checkpoint they should not exist
- **Config**: `SAB_TO_MYLAR` migrated via config version system (v14→v15). Old value is preserved and mapped to new key automatically.
- **Logs**: Renaming `mylar.log` → `comicarr.log` means log rotation configs and monitoring tools that reference the old name will stop working. Users must update their external tooling.
- **Backups**: The existing `shutil.copy2()` backup system is WAL-unaware — backups may be incomplete. Consider migrating to `sqlite3.Connection.backup()` API in a future improvement.

### API Surface Parity

The REST API (`api.py`) and CherryPy routes (`webserve.py`) don't use "mylar" in their URL paths — they use `/api`, `/comic/`, `/series/`, etc. No API breaking changes.

### Integration Test Scenarios

1. **Fresh install**: `python Comicarr.py` with no data dir → creates `comicarr.db`, `comicarr.log` → web UI accessible → add a series
2. **Legacy data dir**: `python Comicarr.py --datadir /path/with/mylar.db` → app creates fresh `comicarr.db`, ignores `mylar.db`
3. **Docker volume mount**: `docker run -v /old/config:/config` with `mylar.db` inside → app creates fresh `comicarr.db`
4. **Notification test**: Settings → test Pushover/Slack/Discord → message says "Comicarr"
5. **OPDS client**: Connect Panels/Chunky to OPDS endpoint → feed title says "Comicarr OPDS"
6. **Scheduler cycle**: Wait for RSS check → verifies `getattr(comicarr, pool_attr)` works at runtime

---

## Deployment Checklist (from deployment-verification-agent)

### Pre-Deploy

- [ ] Tag current HEAD: `git tag pre-rebrand-snapshot`
- [ ] Back up entire Docker `/config` volume on Synology NAS
- [ ] Record database row counts (comics, issues, snatched, annuals, weekly, readlist)
- [ ] Record `config.ini` hash

### Database Migration (WAL-safe procedure)

```bash
# 1. Stop the application
docker compose down

# 2. WAL checkpoint (CRITICAL — prevents data loss)
sqlite3 /path/to/mylar.db "PRAGMA wal_checkpoint(TRUNCATE);"

# 3. Verify WAL is empty
ls -la /path/to/mylar.db-wal  # should be 0 bytes or not exist

# 4. Rename database
mv /path/to/mylar.db /path/to/comicarr.db

# 5. Rename maintenance db (no WAL concerns — uses rollback journal)
mv /path/to/.mylar_maintenance.db /path/to/.comicarr_maintenance.db 2>/dev/null || true

# 6. Rename logs (optional)
for f in /path/to/mylar.log*; do
  mv "$f" "$(echo $f | sed 's/mylar\.log/comicarr.log/')" 2>/dev/null || true
done
```

### Post-Deploy Verification (within 5 minutes)

- [ ] No `ModuleNotFoundError` in logs
- [ ] Web UI loads at configured port
- [ ] Database row counts match pre-deploy baseline
- [ ] At least one scheduled task fires successfully

### Rollback

- Docker: ~5 minutes (stop, rename files back, change image tag, start)
- The database file is byte-identical regardless of its name — rollback is safe
- **Cannot rollback**: rotated credentials (use NEW credentials in old config)

---

## Acceptance Criteria

### Functional Requirements

- [ ] Zero unintended "mylar"/"Mylar" references in codebase (attribution excluded)
- [ ] Application starts, runs, and serves the web UI
- [ ] All notification channels display "Comicarr" branding
- [ ] OPDS feeds identify as "Comicarr"
- [ ] Version check hits the correct Comicarr GitHub repo
- [ ] Favicon displays Comicarr branding
- [ ] Config key migration preserves `SAB_TO_MYLAR` value for existing users

### Non-Functional Requirements

- [ ] CI pipeline passes on all workflows (using npm, not bun)
- [ ] Docker image builds successfully
- [ ] Test coverage reports correctly against `comicarr/` package
- [ ] No credentials on disk or in git history

### Quality Gates

- [ ] Full test suite passes
- [ ] `ruff check comicarr/` passes
- [ ] Manual smoke test completed (including scheduler cycle)
- [ ] Final `grep -ri mylar` audit documented and approved

## Success Metrics

- Zero `ModuleNotFoundError` on startup
- Zero user-visible "Mylar" strings (outside attribution)
- CI passing on all workflows
- Docker build succeeds
- All rotated credentials verified working

## Dependencies & Prerequisites

- GitHub repo must be renamed from `mylar4` to `comicarr` (documented in `docs/RELEASE_PLAN.md`)
- New Comicarr ASCII logo artwork needed for `ascii_logo.nfo`
- New favicon if current one shows Mylar branding
- ComicVine API key rotation requires re-registering at comicvine.gamespot.com
- `uv.lock` must be generated (`uv lock`) before Docker build works with uv

## Risk Analysis & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Missed import crashes app at startup | Medium | High | Automated grep + test suite + `__pycache__` cleanup |
| WAL data loss during db rename | High (if done wrong) | Critical | Document TRUNCATE checkpoint procedure |
| Dynamic `getattr` fails at runtime | Medium | Medium | Smoke test must exercise scheduler cycle |
| Stale `.pyc` masks import errors | Medium | High | Delete all `__pycache__/` after `git mv` |
| `SAB_TO_MYLAR` silently dropped | N/A (mitigated) | N/A | Using config version migration system |
| Version check phones home to wrong repo | Already happening | Low | Fix URLs in Phase 3.7 |
| CI breaks during rename | Medium | Low | Run full CI before merging |
| Python 3.14 breaks regex strings | Future | High | Track as follow-up (170+ invalid escapes) |
| Vendored `lib/` shadows installed packages | Already happening | Medium | Remove duplicates in Phase 3.3 |

## Future Considerations

- **Python 3.14 invalid escape sequences**: 170+ non-raw regex strings will become errors. Fix with `ruff` rule `W605` in a dedicated PR (pattern recognition finding).
- **Global state refactor**: The 205 module-level globals in `__init__.py` should eventually become an `AppContext` class. Not in this PR — blast radius too large (architecture strategist).
- **`webserve.py` split**: At 512KB / ~9,700 lines, this file should be split into route modules (`routes/comics.py`, `routes/search.py`, etc.) for maintainability.
- **Notification dispatch consolidation**: Notification dispatch is copy-pasted in `postprocessor.py` and `search.py` (11 notifier blocks each). A `notify_all()` dispatcher in `notifiers.py` would eliminate this duplication.
- **`helpers.py` split**: At 5,212 lines with 100 functions, this should be split into `utils/strings.py`, `utils/datetime.py`, `utils/filesystem.py`, `workers.py`.
- **114 camelCase functions**: Systematic rename to snake_case in a future PR.
- **189 bare `except:` clauses**: Fix opportunistically per CLAUDE.md convention.
- **`class Foo(object):` syntax**: 45 classes use unnecessary Python 2 style inheritance — cosmetic cleanup.
- **SQLite backup improvement**: Migrate from `shutil.copy2()` to `sqlite3.Connection.backup()` API for WAL-safe backups.
- **PyPI package name**: Claim `comicarr` on PyPI if ever publishing.
- **Docker Hub**: Image planned for `ghcr.io/frankieramirez/comicarr`.
- **New screenshots**: Capture React frontend screenshots closer to actual public release.

## Documentation Plan

- [ ] Update README with branding (keep Mylar3 attribution section)
- [ ] Update CLAUDE.md and AGENTS.md with new package name and import patterns
- [ ] Create migration guide for users coming from Mylar3 (include WAL checkpoint procedure)
- [ ] Update all docs/ files to reflect new naming
- [ ] Delete outdated `API_REFERENCE` (Headphones terminology)

## Sources & References

### Internal References

- Release plan: `docs/RELEASE_PLAN.md:192` — repo rename task
- Production readiness: `docs/plans/2026-03-19-001-feat-production-readiness-plan.md` — Phase 6.3 public release checklist
- Config definition: `comicarr/config.py:306` — SAB_TO_MYLAR key
- Config migration: `comicarr/config.py:724` — `config_update()` method, version system
- Config bad definitions: `comicarr/config.py:550-570` — `_BAD_DEFINITIONS` key migration mechanism
- Version check: `comicarr/versioncheck.py:124-378` — hardcoded GitHub URLs
- Publisher imprints: `comicarr/__init__.py:505` — mylar3.github.io dependency
- WAL mode: `comicarr/__init__.py:981` — `PRAGMA journal_mode = WAL`
- Dynamic getattr: `comicarr/__init__.py:803,812` — runtime module attribute access
- Encryption module: `comicarr/encrypted.py` — base64 obfuscation (not real encryption)

### External References

- git-filter-repo (recommended over BFG): https://github.com/newren/git-filter-repo
- GNU GPL v3 Section 5 (modified source versions): https://www.gnu.org/licenses/gpl-3.0.en.html
- uv Docker guide: https://docs.astral.sh/uv/guides/integration/docker/
- Python Packaging Guide (pyproject.toml): https://packaging.python.org/en/latest/guides/writing-pyproject-toml/

### Related Work

- Existing NAS deployment at port 8091 (parallel with Mylar3 at 8090, validation ends 2026-03-27)
- `cd375dcb` — SVG logo already added
