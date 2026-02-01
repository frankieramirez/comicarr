# Comicarr

An automated comic book manager with a modern React frontend. Part of the *arr ecosystem (like Sonarr, Radarr, Lidarr).

## Overview

Comicarr is a modernized fork of Mylar3, rebuilt with a React 19 frontend and focused on performance improvements. It provides automated comic book library management with an intuitive web interface.

## Features

- **Modern React 19 Frontend** - Fast, responsive UI with real-time updates
- **Automated Downloads** - Monitor series and automatically grab new issues
- **Library Management** - Scan existing collections, identify missing issues
- **Multiple Download Support** - NZB clients (SABnzbd, NZBGet) and torrent clients (qBittorrent, Deluge, Transmission, rTorrent)
- **Direct Downloads** - Mega, MediaFire, Pixeldrain support
- **Weekly Pull Lists** - Track upcoming releases up to 4 weeks ahead
- **Story Arc Management** - Organize and track story arcs across series
- **Dark/Light Themes** - Native theme support with system preference detection
- **Real-time Updates** - Server-Sent Events for live status without page refreshes

## Quick Start

### Docker (Recommended)

```bash
docker run -d \
  --name comicarr \
  -p 8090:8090 \
  -v /path/to/config:/config \
  -v /path/to/comics:/comics \
  -v /path/to/downloads:/downloads \
  ghcr.io/frankieramirez/comicarr:latest
```

Or use docker-compose:

```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/frankieramirez/comicarr/main/docker-compose.yml
# Edit paths in docker-compose.yml, then:
docker-compose up -d
```

### Manual Installation

**Requirements:**
- Python 3.8.1+
- Node.js 18+

**Steps:**

1. Clone the repository:
```bash
git clone https://github.com/frankieramirez/comicarr.git
cd comicarr
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
python3 Comicarr.py --nolaunch
```

5. Access at `http://localhost:8090`

## Configuration

On first run:
1. Get a Comic Vine API key from https://comicvine.gamespot.com/api/
2. Configure download clients (SABnzbd, NZBGet, or torrent clients)
3. Set your comic library and download paths
4. Optionally configure Metron credentials for enhanced search

## Project Structure

```
├── Comicarr.py          # Main entry point
├── mylar/               # Python backend package
│   ├── webserve.py      # Web UI and API routes
│   ├── search.py        # Search orchestration
│   ├── PostProcessor.py # Download processing
│   └── ...
├── frontend/            # React frontend
│   ├── src/
│   │   ├── components/  # React components
│   │   ├── pages/       # Page components
│   │   └── lib/         # API and utilities
│   └── package.json
├── data/                # Static assets and templates
├── lib/                 # Bundled libraries
└── docs/                # Documentation
```

## Attribution

Comicarr is built on the foundation of [Mylar3](https://github.com/mylar3/mylar3), created by the Mylar3 team. The original project provided the robust backend for comic management, downloading, and post-processing.

## Support

- [GitHub Issues](https://github.com/frankieramirez/comicarr/issues) - Bug reports and feature requests

## License

This project maintains the same license as the original Mylar3 project (GPL v3).
