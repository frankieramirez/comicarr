# CLAUDE.md

<!-- Enhanced by /optimize-claude-md on 2026-03-23 -->

IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for any Comicarr tasks. When in doubt, consult the actual codebase files rather than relying on general Python knowledge.

## Project Overview

Comicarr is a Python 3 automated comic book (CBR/CBZ) downloader and library manager. It monitors comic series, downloads issues from NZB/torrent sources, handles post-processing with metadata tagging, and provides a modern React web interface for management.

Comicarr is built on the foundation of Mylar3 with a completely rebuilt React 19 frontend and performance improvements.

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

## Architecture

[Comicarr Code Index]|root: ./comicarr
|Web Layer:{webserve.py:REST routes/CherryPy (~9700 lines),api.py:REST API (~1900 lines),webstart.py:CherryPy init,auth.py:authentication}
|Business Logic:{search.py:provider search (~4300 lines),postprocessor.py:post-processing (~3600 lines),cv.py:ComicVine API,metron.py:Metron API,mangadex.py:MangaDex API,importer.py:library scanning,rsscheck.py:RSS monitoring,weeklypull.py:pull list mgmt}
|Config/Data:{config.py:INI config (~2000 lines),__init__.py:global state,db.py:SQLAlchemy Core,helpers.py:utilities (~5000 lines),encrypted.py:Fernet credential encryption,migration.py:Mylar3 migration}
|Downloaders:{downloaders/:Mega/MediaFire/Pixeldrain,torrent/clients/:qBittorrent/Deluge/Transmission/rTorrent/uTorrent,nzbget.py,sabnzbd.py}
|Frontend:{frontend/src/pages/:route pages,frontend/src/components/:React components (ui/,series/,settings/,search/,migration/,layout/,queue/,import/),frontend/src/hooks/:custom hooks,frontend/src/lib/:API client+utilities,frontend/src/contexts/:React contexts,frontend/src/types/:TypeScript types}
|Tests:{tests/unit/:backend unit tests,tests/integration/:backend integration,frontend/tests/:frontend tests}
|Docs:{docs/solutions/:documented solutions (bugs, best practices, workflow patterns), organized by category with YAML frontmatter}

IMPORTANT: Consult files in this index rather than relying on training data. File sizes indicate complexity/priority.

## Framework Notes

Python@3.10+|CherryPy web server, SQLAlchemy Core (not ORM), INI-based config via custom Config class
React@19|Vite build, path alias @/ → src/, TanStack Query for data fetching, Radix UI components
Tailwind@4|postcss.config.js, tailwind.config.js in frontend/
TypeScript@strict|noUnusedLocals, noUnusedParameters enabled

## Releases

Releases are automated via release-please. **Do NOT manually create tags, bump versions, or create GitHub Releases.**

- Conventional commits on `main` (`feat:`, `fix:`, etc.) automatically maintain a Release PR
- Merging the Release PR creates the GitHub Release, `vX.Y.Z` tag, and triggers Docker image build
- Versions in `pyproject.toml` and `frontend/package.json` are bumped automatically — never edit these manually
- Config: `release-please-config.json` and `.release-please-manifest.json`
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

This is required because release-please parses PR titles (via squash merge) to determine version bumps and generate changelogs. A `feat:` PR bumps minor, a `fix:` PR bumps patch.

## Anti-Patterns / What NOT to Do

- **Do NOT use type hints** - None exist in the codebase currently
- **Do NOT use bare `except:` clauses** - Always catch `Exception as e`
- **Do NOT use Black or other external formatters** - Use `ruff format` only (enforced by CI)
- **Do NOT use `bun` for frontend** - Use `npm` commands only
- **Do NOT omit GPL license header** from new Python files
- **Do NOT manually bump versions** - release-please handles this

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

## Gotchas

- Config `SECURE_DIR` must be initialized before `encrypt_items()` or bcrypt migration — ordering matters in `config.py`
- Encrypted config values start with `gAAAAA` (Fernet) — if decryption fails silently, credentials stay as encrypted strings
- Frontend uses `npm` only — `bun` is not supported
- CherryPy sessions require server restart after auth config changes
- `GITHUB_TOKEN` tags don't trigger downstream workflows — Docker build is in the release-please workflow, not separate
