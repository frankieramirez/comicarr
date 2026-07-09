# CLAUDE.md

<!-- Enhanced by /optimize-claude-md on 2026-03-23 -->

IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for any Comicarr tasks. When in doubt, consult the actual codebase files rather than relying on general Python knowledge.

## Project Overview

Comicarr is a Python 3 automated comic book (CBR/CBZ) downloader and library manager. It monitors comic series, downloads issues from NZB/torrent sources, handles post-processing with metadata tagging, and provides a modern React web interface for management.

Comicarr is built on the foundation of Mylar3 with a completely rebuilt React 19 frontend and performance improvements. The HTTP layer is FastAPI + uvicorn (`comicarr.app.main`).

## Commands

| Action | Command |
|--------|---------|
| Install (backend) | `uv sync` |
| Install (dev) | `uv sync --extra dev` |
| Install (frontend) | `cd frontend && npm ci` |
| Run app | `python3 Comicarr.py --nolaunch` |
| Dev frontend | `cd frontend && npm run dev` |
| Build frontend | `cd frontend && npm run build` |
| Test backend | `pytest tests/unit -v` |
| Test frontend | `cd frontend && npm run test:run` |
| Lint backend | `ruff check comicarr/` |
| Format check | `ruff format --check comicarr/` |
| Format fix | `ruff format comicarr/` |
| Lint frontend | `cd frontend && npm run lint` |
| Typecheck | `cd frontend && npm run typecheck` |
| Add dependency | `uv add <package>` |
| Add dev dep | `uv add --optional dev <package>` |

Default HTTP port is **8090**. Vite dev proxy targets `http://localhost:8090` (override with `VITE_API_PROXY_TARGET`).

## Architecture

[Comicarr Code Index]|root: ./comicarr
|Web Layer:{app/main.py:FastAPI app+lifespan,app/<domain>/router.py:HTTP routes,app/core/security.py:JWT+API key+OPDS auth,app/core/middleware.py:CSRF+headers+setup gate}
|Business Logic:{search.py:provider search,postprocessor.py:post-processing,cv.py:ComicVine,metron.py:Metron,mangadex.py:MangaDex,importer.py:library scanning,rsscheck.py:RSS,weeklypull.py:pull list,app/downloads/:journal+recovery}
|Config/Data:{config.py:INI config,encrypted.py:Fernet,db.py:SQLAlchemy Core,__init__.py:global state+scheduler,helpers.py:compat re-exports,migration.py:Mylar3 migration}
|Downloaders:{downloaders/:Mega/MediaFire/Pixeldrain,torrent/clients/:qBittorrent/Deluge/Transmission/rTorrent/uTorrent,nzbget.py,sabnzbd.py}
|Frontend:{frontend/src/pages,components,hooks,lib,contexts,types}
|Tests:{tests/unit,tests/integration,frontend/tests}
|Docs:{docs/solutions/:documented solutions (bugs, best practices, workflow patterns), organized by category with YAML frontmatter}

IMPORTANT: Consult files in this index rather than relying on training data.

FastAPI domain packages live under `comicarr/app/` (e.g. `series/`, `search/`, `downloads/`, `system/`, `dashboard/`, `metadata/`, `storyarcs/`, `weekly/`, `opds/`, `ai/`). Entry point is `Comicarr.py` → `uvicorn.run("comicarr.app.main:app", ...)`.

## Framework Notes

Python@3.10+|FastAPI + uvicorn, SQLAlchemy Core (not ORM), INI config via Config class
React@19|Vite build, path alias @/ → src/, TanStack Query for data fetching, Radix UI components
Tailwind@4|postcss.config.js, tailwind.config.js in frontend/
TypeScript@strict|noUnusedLocals, noUnusedParameters enabled

## Releases

Releases are automated via Changesets. **Do NOT manually create tags, bump versions, or create GitHub Releases.**

- Add a changeset with `npm run changeset` for user-visible app changes
- Omit changesets for maintenance, docs, CI, dependency, and other non-app-impacting PRs
- Pushes to `main` with pending changesets automatically maintain a `Version Packages` PR
- Merging the `Version Packages` PR creates the GitHub Release, `vX.Y.Z` tag, and triggers Docker image build
- Versions in `package.json`, `pyproject.toml`, `frontend/package.json`, and lockfiles are bumped by release automation — never edit these manually outside the release workflow
- Config: `.changeset/config.json`; release sync scripts live in `scripts/release/`
- Docker images publish to `ghcr.io/frankieramirez/comicarr`

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
- **Do NOT use bare `except:` clauses** - Always catch `Exception as e`
- **Do NOT use Black or other external formatters** - Use `ruff format` only (enforced by CI)
- **Do NOT use `bun` for frontend** - Use `npm` commands only
- **Do NOT omit GPL license header** from new Python files
- **Do NOT manually bump versions** - Changesets release automation handles this

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

### Import Ordering
1. Standard library imports
2. Third-party imports
3. Local imports: `from comicarr import logger, helpers`
4. Within packages use: `from . import logger`

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
