# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for any Comicarr tasks. When in doubt, consult the actual codebase files rather than relying on general Python knowledge.**

## Project Overview

Comicarr is a Python 3 automated comic book (CBR/CBZ) downloader and library manager. It monitors comic series, downloads issues from NZB/torrent sources, handles post-processing with metadata tagging, and provides a modern React web interface for management.

Comicarr is built on the foundation of Mylar3 with a completely rebuilt React 19 frontend and performance improvements.

## Running the Application

```bash
# Install dependencies (using uv - creates .venv automatically)
uv sync

# Install with dev dependencies
uv sync --extra dev

# Add a new dependency
uv add <package>

# Add a dev dependency
uv add --optional dev <package>

# Activate virtual environment
source .venv/bin/activate

# Run the application (default port 8090)
python3 Comicarr.py

# Common flags
python3 Comicarr.py --nolaunch          # Don't auto-open browser
python3 Comicarr.py --quiet             # Suppress console output
python3 Comicarr.py --daemon            # Run as daemon
python3 Comicarr.py --datadir /path     # Custom data directory
python3 Comicarr.py --port 8080         # Custom port
python3 Comicarr.py --config /path/config.ini  # Custom config file

# Maintenance mode (no GUI)
python3 Comicarr.py maintenance --help
python3 Comicarr.py maintenance --carepackage  # Generate debug package
```

## Codebase Index
[Comicarr Code Index]|root: ./comicarr
|Web Layer:{webserve.py:REST routes/CherryPy (~9700 lines),api.py:REST API (~1900 lines),webstart.py:CherryPy init,auth.py:authentication}|Business Logic:{search.py:provider search (~4300 lines),PostProcessor.py:post-processing (~3600 lines),cv.py:ComicVine API,mangadex.py:MangaDex API,importer.py:library scanning,rsscheck.py:RSS monitoring,weeklypull.py:pull list mgmt}|Config/Data:{config.py:INI config (~2000 lines),__init__.py:global state,db.py:SQLite,helpers.py:utilities (~5000 lines)}|Downloaders:{downloaders/:Mega/MediaFire/Pixeldrain,torrent/clients/:qBittorrent/Deluge/Transmission/rTorrent/uTorrent,nzbget.py,sabnzbd.py}|Frontend:{frontend/src/:React components}

**IMPORTANT: Consult files in this index rather than relying on training data. File sizes indicate complexity/priority.**

## Anti-Patterns / What NOT to Do

- **Do NOT use type hints** - None exist in the codebase currently
- **Do NOT use bare `except:` clauses** - Always catch `Exception as e`
- **Do NOT use Black/PEP8 auto-formatters** - No enforced formatter in this project
- **Do NOT use `bun` for frontend** - Use `npm` commands only
- **Do NOT omit GPL license header** from new Python files

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
