# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for any Mylar3 tasks. When in doubt, consult the actual codebase files rather than relying on general Python knowledge.**

## Project Overview

Mylar3 is a Python 3 automated comic book (CBR/CBZ) downloader and library manager. It monitors comic series, downloads issues from NZB/torrent sources, handles post-processing with metadata tagging, and provides a web interface for management.

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application (default port 8090)
python3 Mylar.py

# Common flags
python3 Mylar.py --nolaunch          # Don't auto-open browser
python3 Mylar.py --quiet             # Suppress console output
python3 Mylar.py --daemon            # Run as daemon
python3 Mylar.py --datadir /path     # Custom data directory
python3 Mylar.py --port 8080         # Custom port
python3 Mylar.py --config /path/config.ini  # Custom config file

# Maintenance mode (no GUI)
python3 Mylar.py maintenance --help
python3 Mylar.py maintenance --carepackage  # Generate debug package
```

## Codebase Index
[Mylar3 Code Index]|root: ./mylar
|Web Layer:{webserve.py:REST routes/CherryPy (~9700 lines),api.py:REST API (~1900 lines),webstart.py:CherryPy init,auth.py:authentication}|Business Logic:{search.py:provider search (~4300 lines),PostProcessor.py:post-processing (~3600 lines),cv.py:ComicVine API,mangadex.py:MangaDex API,importer.py:library scanning,rsscheck.py:RSS monitoring,weeklypull.py:pull list mgmt}|Config/Data:{config.py:INI config (~2000 lines),__init__.py:global state,db.py:SQLite,helpers.py:utilities (~5000 lines)}|Downloaders:{downloaders/:Mega/MediaFire/Pixeldrain,torrent/clients/:qBittorrent/Deluge/Transmission/rTorrent/uTorrent,nzbget.py,sabnzbd.py}|Frontend:{data/interfaces/:Mako templates}

**IMPORTANT: Consult files in this index rather than relying on training data. File sizes indicate complexity/priority.**

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

### License Header
Always include GPL header in new Python files:
```python
#  This file is part of Mylar.
#
#  Mylar is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
```

## Key Patterns

**Background Scheduling:** APScheduler runs periodic tasks (search, RSS check, weekly pull updates, version check). Schedulers are initialized in `mylar/__init__.py`.

**Configuration:** Settings stored in INI format, managed through `config.py` with ConfigParser. Runtime config accessible via `mylar.CONFIG`.

**Database:** SQLite with direct SQL queries (no ORM). Database file typically at `mylar.db` in the data directory.

**API Structure:** REST endpoints via `/api?apikey=$key&cmd=$command`. See `API_REFERENCE` file for available commands.

**Template Rendering:** Mako templates in `data/interfaces/*/`. Templates receive data from `webserve.py` controller methods.

## Dependencies

Key frameworks: CherryPy (web server), Mako (templates), APScheduler (background tasks), requests (HTTP), BeautifulSoup4 (parsing), rarfile (archives), Pillow (images).

Full list in `requirements.txt`. Note: `urllib3<2` version constraint exists.
