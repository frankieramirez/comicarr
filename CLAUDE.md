# CLAUDE.md

<!-- Enhanced by /optimize-claude-md on 2026-03-23 -->

IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for any Comicarr tasks. When in doubt, consult the actual codebase files rather than relying on general Python knowledge.

## Project Overview

Comicarr is built on the foundation of Mylar3 with a completely rebuilt React 19 frontend and performance improvements. The HTTP layer is FastAPI + uvicorn (`comicarr.app.main`).

## Architecture

[Comicarr Code Index]|root: ./comicarr
|Web Layer:{app/main.py:FastAPI app+lifespan,app/<domain>/router.py:HTTP routes,app/core/security.py:JWT+API key+OPDS auth,app/core/middleware.py:CSRF+headers+setup gate}
|Business Logic:{search.py:provider search,postprocessor.py:post-processing,cv.py:ComicVine,metron.py:Metron,mangadex.py:MangaDex,importer.py:library scanning,rsscheck.py:RSS,weeklypull.py:pull list,app/attention/:needs-attention policy+resolution,app/downloads/:journal+recovery}
|Config/Data:{config.py:INI config,encrypted.py:Fernet,db.py:SQLAlchemy Core,__init__.py:global state+scheduler,helpers.py:compat re-exports,migration.py:Mylar3 migration}
|Downloaders:{downloaders/:Mega/MediaFire/Pixeldrain,torrent/clients/:qBittorrent/Deluge/Transmission/rTorrent/uTorrent,nzbget.py,sabnzbd.py}
|Frontend:{frontend/src/pages,components,hooks,lib,contexts,types}
|Tests:{tests/unit,tests/integration,frontend/tests}

Domain packages under `comicarr/app/`: `series`, `search`, `attention`, `downloads`, `system`, `dashboard`, `metadata`, `storyarcs`, `weekly`, `opds`, `ai`, plus `core` and `common`.

## Commands

| Action | Command |
|--------|---------|
| Validate dependency lock | `uv lock --check` |
| Run app | `python3 Comicarr.py --nolaunch` |
| Test backend | `pytest tests/unit -v` |
| Lint modern backend | `npm run lint:modern` (`comicarr/app` + `Comicarr.py`) |
| Run every contributor gate | `npm run lint:guards` (`scripts/check_retired_globals.py`, `scripts/check_fail_reason_registry.py`, `scripts/check_upsert_tables.py`, `scripts/check_attention_seam.py`, `scripts/check_support_bundle_terms.py`) |
| Lint all (CI parity) | `npm run lint` |
| Regenerate settings types | `npm run lint:fix:generated` (after editing the config registry) |

`frontend/src/types/config.generated.ts` is generated from `comicarr/app/config/registry.py` and committed. `npm run lint` fails if it is stale; a pre-commit hook regenerates it when the registry or `system/service.py` changes.

Default HTTP port is **8090**. Vite dev proxy targets `http://localhost:8090` (override with `VITE_API_PROXY_TARGET`). Frontend `npm run dev` uses **portless** → **https://comicarr.localhost:1355** (raw Vite: `npm run dev:vite`).

## Releases

Releases are automated via Changesets. See the `releases` skill (`.claude/skills/releases/SKILL.md`) for the full workflow. Human-facing prose rules live in `CONTRIBUTING.md` → *Writing a changeset (operator-facing)*.

**When a refactor earns a changeset:** when it changes something an *operator* could observe. Pure internal restructuring with verified-identical behaviour does not get one, and neither does tooling/CI-only work — `changeset-status.yml` treats a missing changeset as an allowed warning for exactly that. A change only a *contributor* can observe (a new lint gate, a type that now rejects a bad key) is documented here, not in the changelog.

**How to write the summary:** Changeset text is **operator-facing** by default — outcome-first prose naming what the operator can see or do. Avoid ticket-only, filename-only, or internals-as-headline bullets. In-app What's New / update notes render `CHANGELOG.md` with only a mechanical transform (no editorial filter). Never land a changeset whose whole body is "No user-visible behaviour changes." — omit the changeset instead and let the next operator-visible change carry the version bump.

## Branch & PR Conventions

**Branch names** must use a conventional prefix with `/` separator:
- `feat/description` — new features
- `fix/description` — bug fixes
- `refactor/description` — code restructuring
- `docs/description` — documentation only
- `chore/description` — maintenance, deps, CI

**PR titles** must follow conventional commit format — CI enforces this:
- `feat: Add manga search provider`
- `fix: Correct metadata parsing for annuals`
- `refactor: Extract search deduplication logic`

Conventional PR titles keep history readable, but they do not control releases. Changesets are the source of release intent and determine version bumps/changelog entries.

## Anti-Patterns / What NOT to Do

- **Do NOT mass-add type hints** to large legacy modules (`search.py`, `postprocessor.py`, etc.)
- **New code under `comicarr/app/`** may use annotations matching neighboring files
- **Do NOT use bare `except:` clauses** - Always catch `Exception as e`; modern backend code is enforced by the strict `lint:modern` lane for `E722`, `F821`, `F823`, and `B904`.
- **Do NOT weaken the modern lint boundary** with new `# noqa` markers or by expanding legacy waivers; inherited global suppressions remain temporary and are handled by focused cleanup plans.
- **Do NOT use Black or other external formatters** - Use `ruff format` only (enforced by CI and pre-commit)
- **Do NOT use `bun` for frontend** - Use `npm` commands only
- **Do NOT omit GPL license header** from new Python files
- **Do NOT manually bump versions** - Changesets release automation handles this
- **Do NOT call `useReactTable` directly** - `no-restricted-imports` allows it only in `frontend/src/components/data-table/useTableState.ts`. Call `useTableState`, which wraps it so `getRowId` is required and row identity can never fall back to TanStack's index default. Tables still awaiting migration are listed in an `overrides` allowlist in `eslint.config.js`; that list only ever shrinks — never add to it.
- **Do NOT reintroduce `GLOBAL_MESSAGES`** - The pre-EventBus message bus is retired. Deleting the declaration cannot make its return fail (Python creates the attribute on first assignment), so `npm run lint:guards` scans source for it instead. Narrate through `comicarr.app.activity.events.record_activity`; that facade publishes the single `activity` SSE event after a durable commit. Add further retired names to `RETIRED_GLOBALS` in `scripts/check_retired_globals.py`. Contributor-only gate — no changeset.
- **Log verbosity has exactly one dial** - `comicarr.LOG_LEVEL` (0/1/2) resolves through `logger.threshold_for_level()` and is applied identically to the logger, file, console, and Web UI sinks; ask for the current value with `logger.current_log_level()`, never by reading a global. Level 0 means warnings and errors, not silence. Whether a console sink exists at all is the orthogonal `console=` argument to `initLogger()`. The second dial (`comicarr.QUIET`) is retired and guarded by `RETIRED_GLOBALS`; it caused #610, where raising verbosity under Docker *removed* console output. Contract and history: `docs/architecture/logging-levels.md`.
- **Do NOT show the saved log level as if it were the running one** - Settings writes `LOG_LEVEL` at the *bottom* of the precedence chain and the write applies live, so the running level, the saved level, and the level the next restart resolves to can all differ. Any surface that reports the level must use `resolve_effective_log_level` (which returns all three plus `pinned`) rather than reading `config.log_level` alone; `GET /system/logs` already carries it. Showing one number where three exist is #610 restated in the UI.
- **`db.upsert` / `db.upsert_conn` table names must be lowercase `TABLE_MAP` keys** - The table is resolved by dict lookup, so `"Issues"` for `"issues"` lints clean and raises `ValueError: Unknown table for upsert` only when that write branch runs — it broke series refresh in production (#561). `scripts/check_upsert_tables.py` (under `lint:guards`) AST-scans every literal table argument. Runtime-built names are skipped; if you must build one, lowercase it at the source. Contributor-only gate — no changeset.
- **Every `fail_reason` base token must be classified** in the private `comicarr.app.attention` reason registry before merge (`scripts/check_fail_reason_registry.py` under `lint:guards`). Runtime is fail-open; CI is the gate. Excluding a token requires reconciliation through `attention.record` (never leave `Snatched`). See ADR-0001, ADR-0003, #523, and #541.
- **Do NOT import `comicarr.app.attention._*` from outside the module** - ADR-0003 gives Attention one public seam — `read`, `resolve`, `record`, plus the contract types in `__all__` — and calls everything else an implementation detail. `scripts/check_attention_seam.py` (under `lint:guards`) AST-scans `comicarr/` for crossings, including function-local and relative ones. Existing crossings are waived by an allowlist keyed on `(file, private submodule)`, split into permanent internal hooks and deprecated shims; each entry names its removal trigger. The list only ever shrinks — a stale entry fails the guard, so a deleted shim takes its waiver with it. Widening `__all__` is not the fix. Contributor-only gate — no changeset.
- **Do NOT make a handoff route depend on the download client reaching back into Comicarr** - A handoff delivers the content, never a pointer to Comicarr, and must be verifiable from the client's own response alone (ADR-0002 / #552 / #564). `blackhole` and `watchdir` are the named exceptions to *verifiability* only — they pay for it by staying out of `_RESTART_SAFE_ROUTES`. There is no cheap static signal for "callback URL", so this is a review gate, not a lint one.
- **Do NOT add per-feature SSE event types** - `activity` is the only narrative channel; `ai_activity`, `restart`, and `shutdown` are the only other listeners in `useServerEvents`. The client invalidates queries from a payload and never accumulates the stream into a list.
- **Do NOT finish without linting** - Run `npm run lint` (or `npm run lint:fix` then re-check) before considering work done; do not bypass hooks with `--no-verify`

## Gotchas

- Config `SECURE_DIR` must be initialized before `encrypt_items()` or bcrypt migration — ordering matters in `config.py`
- Encrypted config values start with `gAAAAA` (Fernet) — if decryption fails silently, credentials stay as encrypted strings
- Frontend uses `npm` only — `bun` is not supported
- Auth uses JWT session cookies (`comicarr_session`); changing auth secrets invalidates sessions
- `GITHUB_TOKEN` tags don't trigger downstream workflows — Docker build is in the Changesets release workflow, not separate
