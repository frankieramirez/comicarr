# AGENTS.md

Agent-oriented project guide for Comicarr. Prefer retrieval-led reasoning: consult the codebase over general assumptions.

## Stack (current)

- **Python 3.10+** (`requires-python = ">=3.10"`)
- **FastAPI + uvicorn** — `Comicarr.py` runs `uvicorn.run("comicarr.app.main:app", ...)`
- **SQLAlchemy Core** (not ORM), INI config via `comicarr.config.Config`
- **urllib3>=2.7.0**
- **React 19 + Vite** frontend; production assets served from `frontend/dist`
- Default HTTP port: **8090**

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

When using Vite (`npm run dev`) with a separate backend process, the proxy targets `http://localhost:8090`. Override with `VITE_API_PROXY_TARGET` if needed.

## Architecture

[Comicarr Code Index]|root: ./comicarr
|Web Layer:{app/main.py:FastAPI app+lifespan,app/<domain>/router.py:HTTP routes,app/core/security.py:JWT+API key+OPDS auth,app/core/middleware.py:CSRF+headers+setup gate}
|Business Logic:{search.py:provider search,postprocessor.py:post-processing,cv.py:ComicVine,metron.py:Metron,mangadex.py:MangaDex,importer.py:library scanning,rsscheck.py:RSS,weeklypull.py:pull list,app/downloads/:journal+recovery}
|Config/Data:{config.py:INI config,encrypted.py:Fernet,db.py:SQLAlchemy Core,__init__.py:global state+scheduler,helpers.py:compat re-exports,migration.py:Mylar3 migration}
|Downloaders:{downloaders/:Mega/MediaFire/Pixeldrain,torrent/clients/:qBittorrent/Deluge/Transmission/rTorrent/uTorrent,nzbget.py,sabnzbd.py}
|Frontend:{frontend/src/pages,components,hooks,lib,contexts,types}
|Tests:{tests/unit,tests/integration,frontend/tests}

Domain packages under `comicarr/app/`: `series`, `search`, `downloads`, `system`, `dashboard`, `metadata`, `storyarcs`, `weekly`, `opds`, `ai`, plus `core` and `common`.

## Tests

- Backend: `tests/unit/`, `tests/integration/` via pytest
- Frontend: `frontend/tests/` (unit) and Playwright e2e under `frontend/`
- CI runs pytest, frontend tests, lint/format, and Playwright smoke

## Style & anti-patterns

- **Formatting**: `ruff format` enforced in CI; do not use Black
- **Lint**: `ruff check comicarr/`
- **Type hints**: do not mass-add to large legacy modules (`search.py`, `postprocessor.py`); new `comicarr/app/**` code may use annotations like neighboring files
- Always `except Exception as e` — never bare `except:`
- GPL license header on new Python files
- Frontend: `npm` only (not bun)
- Do not manually bump versions — Changesets automation

## Common patterns

```python
from comicarr import logger
logger.fdebug('[MODULE-CONTEXT] message')

import comicarr
comicarr.CONFIG.option_name

from comicarr import db
db.DBConnection().action("SELECT * FROM table WHERE id=?", [id])
```

Import order: stdlib → third-party → local (`from comicarr import ...`).

## Adding new features

1. Prefer FastAPI domain code: `comicarr/app/<domain>/router.py` + `service.py` (+ `queries.py`)
2. Wire the router in `comicarr/app/main.py`
3. Reuse existing business modules (`search.py`, `postprocessor.py`, providers) for heavy logic
4. Frontend: pages/components under `frontend/src/`, API client in `frontend/src/lib/`

## Gotchas

- `SECURE_DIR` must be initialized before `encrypt_items()` / bcrypt migration in `config.py`
- Fernet-encrypted config values start with `gAAAAA`
- Auth: JWT session cookie `comicarr_session`; changing auth secrets invalidates sessions
- Vite proxy default is 8090 to match `HTTP_PORT`

Keep this file aligned with `CLAUDE.md` when architecture changes.
