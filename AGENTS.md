# AGENTS.md

Agent-oriented project guide for Comicarr. Prefer retrieval-led reasoning: consult the codebase over general assumptions.

## Stack (current)

- **Python 3.10+** (`requires-python = ">=3.10"`)
- **FastAPI + uvicorn** — `Comicarr.py` runs `uvicorn.run("comicarr.app.main:app", ...)`
- **SQLAlchemy Core** (not ORM), INI config via `comicarr.config.Config`
- **urllib3>=2.7.0**
- **React 19 + Vite + Base UI** frontend; production assets served from `frontend/dist`
- Default HTTP port: **8090**

## Commands

| Action | Command |
|--------|---------|
| Install (backend) | `uv sync` |
| Install (dev) | `uv sync --extra dev` |
| Validate dependency lock | `uv lock --check` |
| Install with pip (unlocked) | `pip install .` |
| Install (frontend) | `cd frontend && npm ci` |
| Run app | `python3 Comicarr.py --nolaunch` |
| Dev frontend | `cd frontend && npm run dev` → **https://comicarr.localhost:1355** (portless) |
| Dev frontend (raw Vite) | `cd frontend && npm run dev:vite` → localhost:5173 |
| Build frontend | `cd frontend && npm run build` |
| Test backend | `pytest tests/unit -v` |
| Test frontend | `cd frontend && npm run test:run` |
| Lint backend | `ruff check comicarr/` |
| Lint modern backend | `npm run lint:modern` (`comicarr/app` + `Comicarr.py`) |
| Format check | `ruff format --check comicarr/` |
| Format fix | `ruff format comicarr/` |
| Lint frontend | `cd frontend && npm run lint` |
| Format frontend | `cd frontend && npm run format` / `format:check` |
| Typecheck | `cd frontend && npm run typecheck` |
| Lint all (CI parity) | `npm run lint` |
| Lint fix all | `npm run lint:fix` |
| Install git hooks | `pre-commit install` (after `uv sync --extra dev`) |
| Run hooks on tree | `pre-commit run --all-files` |
| Add dependency | `uv add <package>` |
| Add dev dep | `uv add --optional dev <package>` |

When using Vite with a separate backend process, the proxy targets `http://localhost:8090`. Override with `VITE_API_PROXY_TARGET` if needed.

**Local frontend URL:** `npm run dev` runs through [portless](https://github.com/vercel-labs/portless) at **https://comicarr.localhost:1355** (proxy on unprivileged port 1355 — no sudo). Other projects can use their own names without stealing 5173. First HTTPS session may need `npx portless trust` once. Optional clean URL without `:1355`: `sudo npx portless proxy start --https` then set `PORTLESS_PORT=443` (or stop the 1355 proxy and re-run). Escape hatch: `npm run dev:vite` for bare `localhost:PORT` (feval uses this).

## Architecture

[Comicarr Code Index]|root: ./comicarr
|Web Layer:{app/main.py:FastAPI app+lifespan,app/<domain>/router.py:HTTP routes,app/core/security.py:JWT+API key+OPDS auth,app/core/middleware.py:CSRF+headers+setup gate}
|Business Logic:{search.py:provider search,postprocessor.py:post-processing,cv.py:ComicVine,metron.py:Metron,mangadex.py:MangaDex,importer.py:library scanning,rsscheck.py:RSS,weeklypull.py:pull list,app/attention/:needs-attention policy+resolution,app/downloads/:journal+recovery}
|Config/Data:{config.py:INI config,encrypted.py:Fernet,db.py:SQLAlchemy Core,__init__.py:global state+scheduler,helpers.py:compat re-exports,migration.py:Mylar3 migration}
|Downloaders:{downloaders/:Mega/MediaFire/Pixeldrain,torrent/clients/:qBittorrent/Deluge/Transmission/rTorrent/uTorrent,nzbget.py,sabnzbd.py}
|Frontend:{frontend/src/pages,components,hooks,lib,contexts,types}
|Tests:{tests/unit,tests/integration,frontend/tests}

Domain packages under `comicarr/app/`: `series`, `search`, `attention`, `downloads`, `system`, `dashboard`, `metadata`, `storyarcs`, `weekly`, `opds`, `ai`, plus `core` and `common`.

## Tests

- Backend: `tests/unit/`, `tests/integration/` via pytest
- Frontend: `frontend/tests/` (unit) and Playwright e2e under `frontend/`
- CI runs pytest, frontend tests, lint/format, and Playwright smoke

## Style & anti-patterns

- **Formatting**: `ruff format` enforced in CI and pre-commit; do not use Black
- **Lint**: `ruff check comicarr/`; modern FastAPI-layer code (`comicarr/app/**` and `Comicarr.py`) must also pass `npm run lint:modern`, which ratchets `E722`, `F821`, `F823`, and `B904`. Frontend ESLint + Prettier are enforced in CI and pre-commit.
- **Legacy boundary**: global Ruff waivers remain for inherited modules; do not add new waivers in modern code or expand legacy scope without a focused cleanup plan.
- **Type hints**: do not mass-add to large legacy modules (`search.py`, `postprocessor.py`); new `comicarr/app/**` code may use annotations like neighboring files
- Always `except Exception as e` — never bare `except:`
- GPL license header on new Python files
- Frontend: `npm` only (not bun)
- Do not manually bump versions — Changesets automation
- **Before finishing a change**: run `npm run lint` (or `npm run lint:fix` then re-check). Do not skip with `--no-verify`

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
