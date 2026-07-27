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
| Lint all (CI parity) | `npm run lint` |

Default HTTP port is **8090**. Vite dev proxy targets `http://localhost:8090` (override with `VITE_API_PROXY_TARGET`).

## Releases

Releases are automated via Changesets. See the `releases` skill (`.claude/skills/releases/SKILL.md`) for the full workflow.

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
- **Do NOT finish without linting** - Run `npm run lint` (or `npm run lint:fix` then re-check) before considering work done; do not bypass hooks with `--no-verify`

## Common Patterns

### Logging Pattern
- Import: `from comicarr import logger`
- Usage: `logger.fdebug('[MODULE-CONTEXT] message')` or `logger.error('[CONTEXT] Error: %s' % e)`
- Always prefix with context in brackets

### Configuration Access
- Import: `import comicarr`
- Usage: `comicarr.CONFIG.option_name`
- Global config object is initialized at startup

### Database Queries
- Import: `from comicarr import db`
- Usage: `db.DBConnection().action("SELECT * FROM table WHERE id=?", [id])`
- Always use parameterized queries

### Adding New Features
- Prefer `comicarr/app/<domain>/router.py` + `service.py` (+ `queries.py` when needed)
- Register/include the router from `comicarr/app/main.py`
- Keep heavy provider/search/post-processing logic in existing business modules when it already lives there

## Gotchas

- Config `SECURE_DIR` must be initialized before `encrypt_items()` or bcrypt migration — ordering matters in `config.py`
- Encrypted config values start with `gAAAAA` (Fernet) — if decryption fails silently, credentials stay as encrypted strings
- Frontend uses `npm` only — `bun` is not supported
- Auth uses JWT session cookies (`comicarr_session`); changing auth secrets invalidates sessions
- `GITHUB_TOKEN` tags don't trigger downstream workflows — Docker build is in the Changesets release workflow, not separate
