# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.4.4](https://github.com/frankieramirez/comicarr/compare/v0.4.3...v0.4.4) (2026-03-24)


### Bug Fixes

* replace broken db.rawdb calls with direct raw_select_all/raw_select_one ([#56](https://github.com/frankieramirez/comicarr/issues/56)) ([d1a7429](https://github.com/frankieramirez/comicarr/commit/d1a7429b9c6d17e73091bf94014da37d7003a704))

## [0.4.3](https://github.com/frankieramirez/comicarr/compare/v0.4.2...v0.4.3) (2026-03-23)


### Bug Fixes

* dark mode issues in settings and remove placeholder UI ([#54](https://github.com/frankieramirez/comicarr/issues/54)) ([069f57e](https://github.com/frankieramirez/comicarr/commit/069f57e4955c28899d909a4957a3482f9612781e))

## [0.4.2](https://github.com/frankieramirez/comicarr/compare/v0.4.1...v0.4.2) (2026-03-23)


### Bug Fixes

* run uv lock in Docker build to handle version bumps ([27b610d](https://github.com/frankieramirez/comicarr/commit/27b610d2ca42316577ccc8ba1b2b67bfee44ad1b))

## [0.4.1](https://github.com/frankieramirez/comicarr/compare/v0.4.0...v0.4.1) (2026-03-23)


### Bug Fixes

* sync uv.lock and prevent stale lockfile on release ([#51](https://github.com/frankieramirez/comicarr/issues/51)) ([0efcc3e](https://github.com/frankieramirez/comicarr/commit/0efcc3e3c2d2bbb95c42ab24a47bfa8a6ec8457d))

## [0.4.0](https://github.com/frankieramirez/comicarr/compare/v0.3.0...v0.4.0) (2026-03-23)


### Features

* Automate releases with release-please ([#47](https://github.com/frankieramirez/comicarr/issues/47)) ([12adb79](https://github.com/frankieramirez/comicarr/commit/12adb79b4347b59f7bd583fb7b6fb11ff47ed005))


### Bug Fixes

* Metron search missing cover images + API hardening ([#48](https://github.com/frankieramirez/comicarr/issues/48)) ([639c9d3](https://github.com/frankieramirez/comicarr/commit/639c9d39a394fbbdebf4c7c3f0d1d6bb1195c4cd))

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
