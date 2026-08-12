# Comicarr

An automated comic book (and manga) manager with a modern React frontend. Part of the *arr ecosystem (like Sonarr, Radarr, Lidarr).

[Website](https://comicarr.com) · [Documentation](https://comicarr.com/docs) · [Installation Guide](https://comicarr.com/docs/installation) · [Contributing](CONTRIBUTING.md)

## Overview

Comicarr is a modernized fork of [Mylar3](https://github.com/mylar3/mylar3), rebuilt with a **React 19** frontend and a **FastAPI** backend. It provides automated comic book library management — monitoring series, searching indexers, downloading via NZB/torrent/DDL clients, and post-processing with metadata tagging.

## Features

- **Modern React 19 Frontend** — Fast, responsive UI with dark/light themes and system preference detection
- **Automated Downloads** — Monitor series and automatically grab new issues
- **Interactive Release Search** — Review every provider candidate and its match verdict before deliberately grabbing a release
- **Library Management** — Scan existing collections, identify missing issues, interactive import matching
- **Multiple Download Clients** — NZB (SABnzbd, NZBGet) and torrent (qBittorrent, Deluge, Transmission, rTorrent, uTorrent)
- **Direct Downloads** — Mega, MediaFire, and Pixeldrain support
- **Metadata Providers** — ComicVine and Metron for series/issue metadata
- **Manga Support** — MangaDex (and optional MyAnimeList) with dedicated manga library paths
- **Weekly Pull Lists** — Track the current week's releases and match them to your library
- **Story Arc Management** — Organize and track story arcs across series
- **OPDS Catalog** — Optional OPDS feed for compatible comic readers (enable via `config.ini`)
- **Optional AI Assist** — Bring-your-own-key LLM features (suggestions, enrichment) when configured in Settings
- **Real-time Updates** — Server-Sent Events for live status without page refreshes
- **Mylar3 Migration** — First-run wizard to import config and library data from an existing Mylar3 install

## Documentation

The [Comicarr documentation](https://comicarr.com/docs) contains complete guides for installing, configuring, using, and maintaining your server. Good places to start:

- [Installation](https://comicarr.com/docs/installation) — Recommended Docker Compose deployment
- [Initial setup](https://comicarr.com/docs/initial-setup) — Create your account and connect metadata, download, and search providers
- [Configuration](https://comicarr.com/docs/configuration) — Settings, credentials, integrations, and database options
- [Updating](https://comicarr.com/docs/deployment/updating) — Back up and upgrade Docker or source installations
- [Troubleshooting](https://comicarr.com/docs/troubleshooting) — Solutions for common setup and runtime issues
- [API reference](https://comicarr.com/docs/api) — REST and Mylar3-compatible API documentation

## Quick Start

### Docker (Recommended)

```bash
docker run -d \
  --name comicarr \
  -p 8090:8090 \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=Etc/UTC \
  -v /path/to/config:/config \
  -v /path/to/comics:/comics \
  -v /path/to/manga:/manga \
  -v /path/to/downloads:/downloads \
  ghcr.io/frankieramirez/comicarr:latest
```

Or use docker Compose:

```bash
curl -o docker-compose.yml https://raw.githubusercontent.com/frankieramirez/comicarr/main/docker-compose.yml
# Edit paths in docker-compose.yml, then:
docker compose up -d
```

### Registries

Multi-architecture images (`amd64`, `arm64`) are published to two registries with identical tags, from the same build:

| Registry | Image reference | |
| -------- | --------------- | - |
| GitHub Container Registry | `ghcr.io/frankieramirez/comicarr` | canonical |
| Docker Hub | `comicarr/comicarr` | mirror |

Either works. GHCR does not rate-limit anonymous pulls; Docker Hub does.

To pin a release instead of tracking `:latest`, note that **image tags are bare semver — they drop the `v` that GitHub releases and git tags carry**. Release `v0.26.0` is image tag `0.26.0`:

```bash
docker pull ghcr.io/frankieramirez/comicarr:0.26.0
```

Pulling on its own never moves a running container to the new image — you have to recreate it:

- **Compose:** change the `image:` line to the pinned tag, then `docker compose up -d`.
- **Standalone:** `docker stop comicarr && docker rm comicarr`, then re-run the `docker run` command above with the pinned tag.

Your config and library are mounted volumes, so both paths leave them untouched.

See the [installation guide](https://comicarr.com/docs/installation) for Docker Compose configuration, volume details, environment variables, and platform-specific notes.

### Manual Installation

**Requirements:**

- Python 3.10+
- Node.js 22+ (to build the frontend)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

**Steps:**

1. Clone the repository:

```bash
git clone https://github.com/frankieramirez/comicarr.git
cd comicarr
```

2. Install Python dependencies:

```bash
# Using uv (recommended — creates .venv automatically)
uv sync

# Or using pip
pip install .
```

`pyproject.toml` is the editable runtime dependency source and `uv.lock` is
the reproducible resolution used by development, CI, and production builds.
The pip command installs from the project metadata but does not reproduce the
exact transitive versions in `uv.lock`.

When changing a dependency, update the project metadata, then run:

```bash
uv lock
uv run pytest tests/unit/test_dependency_manifests.py -q
```

3. Build the frontend:

```bash
cd frontend
npm ci
npm run build
cd ..
```

4. Run the application:

```bash
source .venv/bin/activate  # if using uv
python3 Comicarr.py --nolaunch
```

5. Open `http://localhost:8090`

## Configuration

### Series content kind

Open a series and use **Catalog this as** to choose **Comic** or **Manga**.
This classification is independent of the metadata provider, so a series added
from ComicVine can still use manga chapter labels and matching rules. The
choice applies to future search, refresh, and post-processing behavior; it does
not change the provider or rewrite existing files and issue history.

### Interactive release search

Open **Releases**, stay on the **Mine** tab, and choose **Review releases** for
a Wanted issue. Comicarr searches the configured providers and opens a review
sheet with each release candidate's source, age, size, availability, and match
reasons. Provider failures remain visible even when other providers return
results.

Selecting **Review grab** opens a final confirmation before Comicarr hands the
release to the configured download route. Candidates rejected only by an
operator-overridable match rule require an additional acknowledgement. Comicarr
never lets this workflow bypass an expired session, missing provider result,
duplicate or in-flight acquisition, unavailable download route, or ownership
check.

### First-run setup

On a fresh install, the web UI prompts you to create an admin account. Docker and quiet-mode installs print a setup token in the server/container logs:

```text
[SETUP] *** First-run setup required ***
[SETUP] Setup token: <token>
```

Enter that token (when prompted) along with a username and password (minimum 8 characters). The app restarts once credentials are saved.

### After login

In **Settings**, configure:

1. **Comic Vine API key** — from [Comic Vine](https://comicvine.gamespot.com/api/) (required for most metadata/search workflows)
2. **Download clients** — SABnzbd, NZBGet, and/or torrent clients
3. **Paths** — comic library, optional manga library, and download directories
4. **Optional** — Metron credentials, MangaDex/MyAnimeList, AI (BYOK), indexers, and notifiers

If you are migrating from Mylar3, the first-run onboarding wizard can import an existing install. For Docker, mount the Mylar3 config directory read-only (see comments in `docker-compose.yml`, typically at `/mylar3`).

### Logging verbosity

One dial, three levels: **0** warnings and errors, **1** normal (the default), **2** everything. It applies to the console, the log file, and the log list in the web UI alike.

Set it wherever suits the install — a startup argument wins over the environment variable, which wins over the level saved in Settings, and each only counts when you actually supply it:

```bash
docker run -e COMICARR_LOG_LEVEL=2 ...   # Docker / Compose
python3 Comicarr.py --log-level 2        # source install
```

Changing it in **Settings** takes effect immediately, no restart. Leave `COMICARR_LOG_LEVEL` unset unless you are debugging: setting it wins over Settings on every restart. (`--quiet` still works as an alias for `--log-level 0`, but it is deprecated.)

## Project Structure

```
├── Comicarr.py          # Main entry point (uvicorn → comicarr.app.main)
├── comicarr/            # Python backend package
│   ├── app/             # FastAPI domains (routers, services, middleware)
│   ├── search.py        # Search orchestration
│   ├── postprocessor.py # Download processing
│   └── ...
├── frontend/            # React 19 + Vite frontend
│   ├── src/
│   │   ├── components/  # React components
│   │   ├── pages/       # Page components
│   │   └── lib/         # API client and utilities
│   └── package.json
├── comicarr/_vendor/    # Namespaced bundled third-party integrations
├── docker/              # Docker entrypoint
├── docs/                # Additional documentation
├── tests/               # Backend unit and integration tests
└── pyproject.toml       # Python project metadata and dependencies
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for local development, testing, linting, and PR conventions.

Quick summary:

```bash
uv sync --extra dev
cd frontend && npm ci && cd ..
python3 Comicarr.py --nolaunch   # backend on :8090

# separate terminal — frontend HMR (proxies API to :8090)
cd frontend && npm run dev   # https://comicarr.localhost:1355 (portless)
```

## Attribution

Comicarr is built on the foundation of [Mylar3](https://github.com/mylar3/mylar3), created by the Mylar3 team. The original project provided the robust backend for comic management, downloading, and post-processing.

## Support

- [Documentation](https://comicarr.com/docs) — Setup, configuration, usage, deployment, and API guides
- [Troubleshooting](https://comicarr.com/docs/troubleshooting) — Common problems and their solutions
- [GitHub Discussions](https://github.com/frankieramirez/comicarr/discussions) — Questions, ideas, and community help
- [GitHub Issues](https://github.com/frankieramirez/comicarr/issues) — Confirmed bug reports and feature requests
- [Security policy](SECURITY.md) — How to report vulnerabilities
- [Contributing guide](CONTRIBUTING.md) — Development setup and PR process
- [Code of Conduct](CODE_OF_CONDUCT.md) — Community participation guidelines

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE) (same as Mylar3).
