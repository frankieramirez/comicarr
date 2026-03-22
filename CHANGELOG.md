# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-03-21

### Added

- Modern React 19 frontend with Tailwind CSS 4, replacing the legacy jQuery/Bootstrap UI
- Real-time updates via Server-Sent Events (SSE)
- Dark and light theme support with system preference detection
- Smart search with parallel pagination and result caching
- Server-side search sorting with mode-aware controls
- Weekly pull list tracking up to 4 weeks ahead
- Story arc management with lazy loading
- Direct download support for Mega, MediaFire, and Pixeldrain
- Multi-stage Docker build with non-root user and dynamic PUID/PGID support
- GitHub Actions CI/CD: linting, testing (Python 3.10-3.12 matrix), and automated releases to GHCR
- Multi-architecture Docker images (amd64, arm64)
- Comprehensive test suite with unit, integration, and E2E tests

### Changed

- Rebranded from Mylar3 to Comicarr throughout the codebase
- Switched to `uv` for Python dependency management
- Upgraded to Python 3.12 runtime in Docker
- Upgraded to Node.js 22 for frontend builds
- Improved search performance with parallel provider queries
- Enhanced API key and credential handling — secrets are redacted in logs and CarePackage exports

### Fixed

- API key plaintext logging vulnerability
- SABnzbd integration regression
- ComicVine result display when MangaDex is disabled
- Various startup and configuration issues

### Attribution

Comicarr is built on the foundation of [Mylar3](https://github.com/mylar3/mylar3), created by the Mylar3 team. The original project provided the robust backend for comic management, downloading, and post-processing.
