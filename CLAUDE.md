# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

## Architecture

### Entry Point
`Mylar.py` - Validates Python version (≥3.8.1), checks dependencies, initializes configuration, starts the CherryPy web server with APScheduler for background tasks.

### Core Package Structure (`mylar/`)

**Web Layer:**
- `webserve.py` - Main web UI controller (~9,700 lines), handles all page routes
- `webstart.py` - CherryPy server initialization and configuration
- `api.py` - REST API implementation (~1,900 lines), JSON responses at `/api?apikey=&cmd=`
- `auth.py` - Authentication controller

**Business Logic:**
- `search.py` - Comic search orchestration across multiple providers (~4,300 lines)
- `PostProcessor.py` - Download post-processing, file validation, renaming (~3,600 lines)
- `cv.py` - Comic Vine API integration for metadata
- `importer.py` - Library scanning and import functionality
- `rsscheck.py` - RSS feed monitoring for new releases
- `weeklypull.py` - Weekly pull list management

**Configuration & Data:**
- `config.py` - INI-based configuration management (~2,000 lines)
- `__init__.py` - Global runtime state and initialization (~1,700 lines)
- `db.py` - SQLite database connection handling
- `helpers.py` - Utility functions (~5,000 lines)

**Download Client Integrations:**
- `downloaders/` - Direct download handlers (Mega, MediaFire, Pixeldrain)
- `torrent/clients/` - Torrent client implementations (qBittorrent, Deluge, Transmission, rTorrent, uTorrent)
- `nzbget.py`, `sabnzbd.py` - NZB client integrations

### Web UI (`data/`)
- `interfaces/` - Mako templates (default and carbon themes)
- `js/`, `css/`, `images/` - Static assets

### Third-Party Libraries (`lib/`)
Contains bundled libraries including a modified ComicTagger fork and rarfile handling.

### Post-Processing Scripts (`post-processing/`)
Integration scripts for download clients:
- `autoProcessComics.py` - Main post-processor entry point
- `nzbget/`, `sabnzbd/`, `torrent-auto-snatch/` - Client-specific integrations

## Key Patterns

**Background Scheduling:** APScheduler runs periodic tasks (search, RSS check, weekly pull updates, version check). Schedulers are initialized in `mylar/__init__.py`.

**Configuration:** Settings stored in INI format, managed through `config.py` with ConfigParser. Runtime config accessible via `mylar.CONFIG`.

**Database:** SQLite with direct SQL queries (no ORM). Database file typically at `mylar.db` in the data directory.

**API Structure:** REST endpoints via `/api?apikey=$key&cmd=$command`. See `API_REFERENCE` file for available commands.

**Template Rendering:** Mako templates in `data/interfaces/*/`. Templates receive data from `webserve.py` controller methods.

## Dependencies

Key frameworks: CherryPy (web server), Mako (templates), APScheduler (background tasks), requests (HTTP), BeautifulSoup4 (parsing), rarfile (archives), Pillow (images).

Full list in `requirements.txt`. Note: `urllib3<2` version constraint exists.
