# Mylar4

A modern comic book manager with an automated downloader, rebuilt with a React 19 frontend.

Mylar4 is a fork of [Mylar3](https://github.com/mylar3/mylar3) that replaces the legacy Mako template UI with a modern React-based interface while preserving the powerful backend functionality for managing your comic book collection.

## What's New in Mylar4

- **Modern React 19 Frontend** - Responsive, fast UI built with React 19, TanStack Query, and Tailwind CSS
- **Metron API Integration** - Enhanced comic search with Metron database support alongside Comic Vine
- **Real-time Updates** - Server-Sent Events for live status updates without page refreshes
- **Dark/Light Themes** - Native theme support with system preference detection
- **Improved UX** - Data tables with sorting/filtering, better error handling, and cleaner navigation

## Features

### Library Management
- Monitor comic series and automatically download new issues
- Scan existing libraries and identify missing issues
- Support for CBR/CBZ formats, TPBs, and graphic novels
- Configurable file and folder renaming
- Automatic metadata tagging via ComicTagger

### Downloading
- Support for SABnzbd, NZBGet, and torrent clients (qBittorrent, Deluge, Transmission, rTorrent)
- Multiple newznab indexer support
- Direct download support (Mega, MediaFire, Pixeldrain)
- Failed download handling with automatic retries

### Organization
- Weekly pull list monitoring up to 4 weeks ahead
- Story arc tracking and management
- Series.json generation for third-party applications
- Notifications via various services (Pushover, Telegram, etc.)

## Installation

### Docker (Recommended)

```bash
docker build -t mylar4 .
docker run -d \
  --name mylar4 \
  -p 8090:8090 \
  -v /path/to/config:/config \
  -v /path/to/comics:/comics \
  -v /path/to/downloads:/downloads \
  mylar4
```

### Manual Installation

**Requirements:**
- Python 3.8.1+
- Node.js 18+

**Steps:**

1. Clone the repository:
```bash
git clone https://github.com/your-username/mylar4.git
cd mylar4
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Build the frontend:
```bash
cd frontend
npm install
npm run build
cd ..
```

4. Run the application:
```bash
python3 Mylar.py --nolaunch
```

5. Access the web interface at `http://localhost:8090`

### Development Mode

For frontend development with hot reload:

```bash
# Terminal 1: Run the backend
python3 Mylar.py --nolaunch

# Terminal 2: Run the frontend dev server
cd frontend
npm run dev
```

The Vite dev server proxies API requests to the backend automatically.

## Project Structure

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
- `mangadex.py` - MangaDex API integration for metadata
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

## Configuration

On first run, navigate to Settings to configure:

1. **Comic Vine API Key** - Required for metadata lookups
2. **Metron Credentials** - Optional, for enhanced search
3. **Download Clients** - Configure SABnzbd, NZBGet, or torrent clients
4. **Indexers** - Add your newznab indexers
5. **Paths** - Set your comic library and download locations

## Screenshots

*Screenshots coming soon*

## Attribution

Mylar4 is built on the foundation of [Mylar3](https://github.com/mylar3/mylar3), created by the Mylar3 team. The original project provides the robust backend for comic management, downloading, and post-processing.

## Support

- [GitHub Issues](https://github.com/your-username/mylar4/issues) - Bug reports and feature requests

## License

This project is a fork of Mylar3 and maintains the same license terms.
