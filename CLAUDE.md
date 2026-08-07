# CLAUDE.md

<!-- Enhanced by /optimize-claude-md on 2026-03-23 -->

IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for any Comicarr tasks. When in doubt, consult the actual codebase files rather than relying on general Python knowledge.

## Project Overview

Comicarr is built on the foundation of Mylar3 with a completely rebuilt React 19 frontend and performance improvements. The HTTP layer is FastAPI + uvicorn (`comicarr.app.main`).

## Commands

| Action | Command |
|--------|---------|
| Validate dependency lock | `uv lock --check` |
| Run app | `python3 Comicarr.py --nolaunch` |
| Test backend | `pytest tests/unit -v` |
| Lint modern backend | `npm run lint:modern` (`comicarr/app` + `Comicarr.py`) |
| Check retired globals + fail_reason registry + upsert tables | `npm run lint:guards` (`scripts/check_retired_globals.py`, `scripts/check_fail_reason_registry.py`, `scripts/check_upsert_tables.py`) |
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
- **`db.upsert` / `db.upsert_conn` table names must be lowercase `TABLE_MAP` keys** - The table is resolved by dict lookup, so `"Issues"` for `"issues"` lints clean and raises `ValueError: Unknown table for upsert` only when that write branch runs — it broke series refresh in production (#561). `scripts/check_upsert_tables.py` (under `lint:guards`) AST-scans every literal table argument. Runtime-built names are skipped; if you must build one, lowercase it at the source. Contributor-only gate — no changeset.
- **Every `fail_reason` base token must be classified** in `comicarr/app/activity/reasons.py` before merge (`scripts/check_fail_reason_registry.py` under `lint:guards`). Runtime is fail-open; CI is the gate. Excluding a token requires a reconciliation obligation (never leave `Snatched`). See ADR-0001 / #523 / #541.
- **Do NOT make a handoff route depend on the download client reaching back into Comicarr** - A handoff delivers the content, never a pointer to Comicarr, and must be verifiable from the client's own response alone (ADR-0002 / #552 / #564). `blackhole` and `watchdir` are the named exceptions to *verifiability* only — they pay for it by staying out of `_RESTART_SAFE_ROUTES`. There is no cheap static signal for "callback URL", so this is a review gate, not a lint one.
- **Do NOT add per-feature SSE event types** - `activity` is the only narrative channel; `ai_activity`, `restart`, and `shutdown` are the only other listeners in `useServerEvents`. The client invalidates queries from a payload and never accumulates the stream into a list.
- **Do NOT finish without linting** - Run `npm run lint` (or `npm run lint:fix` then re-check) before considering work done; do not bypass hooks with `--no-verify`

## Gotchas

- Config `SECURE_DIR` must be initialized before `encrypt_items()` or bcrypt migration — ordering matters in `config.py`
- Encrypted config values start with `gAAAAA` (Fernet) — if decryption fails silently, credentials stay as encrypted strings
- Frontend uses `npm` only — `bun` is not supported
- Auth uses JWT session cookies (`comicarr_session`); changing auth secrets invalidates sessions
- `GITHUB_TOKEN` tags don't trigger downstream workflows — Docker build is in the Changesets release workflow, not separate
