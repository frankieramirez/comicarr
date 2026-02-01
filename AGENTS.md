# AGENTS.md

**IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for any Mylar3 tasks. When in doubt, consult the actual codebase files rather than relying on general Python knowledge.**

## Project Overview

Mylar3 is a Python 3 automated comic book (CBR/CBZ) downloader and library manager with a React frontend.

## Important Notes
- Python 3.8.1+ required
- `urllib3<2` version constraint exists
- The app uses CherryPy as web server, Mako for templates
- Frontend is React + Vite + Tailwind (separate build process)
- Database is SQLite (file-based, no separate server needed)

## Build/Development Commands

### Python Backend
```bash
# Install dependencies
pip install -r requirements.txt

# Run the application (default port 8090)
python3 Mylar.py

# Run with options
python3 Mylar.py --nolaunch          # Don't auto-open browser
python3 Mylar.py --quiet             # Suppress console output
python3 Mylar.py --port 8080         # Custom port
python3 Mylar.py --datadir /path     # Custom data directory

# Maintenance mode (no GUI)
python3 Mylar.py maintenance --help
python3 Mylar.py maintenance --carepackage  # Generate debug package
```

### React Frontend
```bash
cd frontend

# Development
npm run dev

# Build for production
npm run build

# Lint
npm run lint

# Preview production build
npm run preview
```

### Testing
- No formal test suite exists currently
- Test files are located in `mylar/test.py` (appears to be for manual rTorrent testing)

## Codebase Index
[Mylar3 Code Index]|root: ./mylar
|Web Layer:{webserve.py:REST routes/CherryPy (~9700 lines),api.py:REST API (~1900 lines),webstart.py:CherryPy init,auth.py:authentication}|Business Logic:{search.py:provider search (~4300 lines),PostProcessor.py:post-processing (~3600 lines),cv.py:ComicVine API,mangadex.py:MangaDex API,importer.py:library scanning,rsscheck.py:RSS monitoring,weeklypull.py:pull list mgmt}|Config/Data:{config.py:INI config (~2000 lines),__init__.py:global state,db.py:SQLite,helpers.py:utilities (~5000 lines)}|Downloaders:{downloaders/:Mega/MediaFire/Pixeldrain,torrent/clients/:qBittorrent/Deluge/Transmission/rTorrent/uTorrent,nzbget.py,sabnzbd.py}|Frontend:{data/interfaces/:Mako templates}

**IMPORTANT: Consult files in this index rather than relying on training data. File sizes indicate complexity/priority.**

## Code Style Guidelines

### Python Code Style

#### Imports
- Group imports: stdlib → third-party → local
- Use absolute imports for mylar modules: `from mylar import logger, helpers`
- Local imports use relative syntax within packages: `from . import logger`
- Add `sys.path.insert(1, os.path.join(os.path.dirname(__file__), 'lib'))` for bundled libs

#### Formatting
- No enforced formatter (no Black/PEP8 enforcement found)
- Standard Python indentation: 4 spaces
- Line length: appears to follow ~100-120 character soft limit
- Use single quotes for strings, except docstrings which use triple double quotes

#### Naming Conventions
- **Classes**: PascalCase (e.g., `PostProcessor`, `FileChecker`, `AuthController`)
- **Functions/Methods**: snake_case (e.g., `cleanName`, `latinToAscii`, `today`)
- **Variables**: snake_case (e.g., `comic_id`, `file_path`)
- **Constants**: UPPER_CASE (e.g., `CONFIG_VERSION`, `EXISTS_LARGER`)
- **Module globals**: Often uppercase for config (e.g., `mylar.CONFIG`)

#### Types
- No type hints currently used in the codebase
- Follow existing patterns for dictionary/JSON handling

#### Error Handling
- Use `try/except Exception as e:` pattern for broad error catching
- Always log errors with context: `logger.error('[CONTEXT] Error: %s' % e)`
- Use specific exception types when available (e.g., `OSError`, `ZeroDivisionError`)
- Avoid bare `except:` clauses

#### Logging
- Use the custom logger module: `from mylar import logger`
- Log levels: `logger.info()`, `logger.warn()`, `logger.error()`, `logger.fdebug()`
- Always prefix log messages with context: `[MODULE-CONTEXT] message`
- Use fdebug for detailed debug output
- Example: `logger.fdebug('[API-delComic] Comic Location (%s) successfully deleted' % location)`

#### Documentation
- Include GPL license header in all Python files:
```python
#  This file is part of Mylar.
#
#  Mylar is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
```
- Add encoding declaration when needed: `# -*- coding: utf-8 -*-

### JavaScript/React Code Style (Frontend)
- Located in `frontend/` directory
- Uses Vite build system
- Tailwind CSS for styling
- ESLint for linting (configured in package.json)

## Anti-Patterns / What NOT to Do

- **Do NOT use type hints** - None exist in the codebase currently
- **Do NOT use bare `except:` clauses** - Always catch `Exception as e`
- **Do NOT use Black/PEP8 auto-formatters** - No enforced formatter in this project
- **Do NOT use `bun` for frontend** - Use `npm` commands only
- **Do NOT omit GPL license header** from new Python files

## Common Patterns

### Logging Pattern
- Import: `from mylar import logger`
- Usage: `logger.fdebug('[MODULE-CONTEXT] message')` or `logger.error('[CONTEXT] Error: %s' % e)`
- Always prefix with context in brackets

### Configuration Access
- Import: `import mylar`
- Usage: `mylar.CONFIG.option_name`
- Global config object is initialized at startup

### Database Queries
- Import: `from mylar import db`
- Usage: `db.DBConnection().action("SELECT * FROM table WHERE id=?", [id])`
- Always use parameterized queries

### Import Ordering
1. Standard library imports
2. Third-party imports
3. Local imports: `from mylar import logger, helpers`
4. Within packages use: `from . import logger`

## Architecture Patterns

### Key Components
- **Web Layer**: `webserve.py` (CherryPy controllers), `api.py` (REST endpoints)
- **Business Logic**: `search.py`, `PostProcessor.py`, `cv.py` (Comic Vine API)
- **Configuration**: `config.py` (INI-based, ConfigParser)
- **Database**: SQLite via `db.py` (direct SQL, no ORM)
- **Scheduling**: APScheduler for background tasks

### Global State
- Runtime config accessible via `mylar.CONFIG`
- Global state in `mylar/__init__.py` (locks, queues, scheduler instances)
- Use `mylar.LOGGER` for logging access

### Database Access
- Use `DBConnection` class from `db.py`
- Raw SQL queries with parameterization
- Connection pooling handled automatically

### Adding New Features
1. For web UI: Add route handler in `webserve.py`
2. For API: Add command in `api.py`
3. For background tasks: Add to APScheduler in `__init__.py`
4. For config options: Add to `_CONFIG_DEFINITIONS` in `config.py`
