---
title: "Prepare Repository for Public Release"
type: feat
status: completed
date: 2026-03-21
---

# Prepare Repository for Public Release

## Overview

Transition the Comicarr repository from private to public on GitHub, ensuring no sensitive data is exposed, git history is clean enough, community files are in place, and Docker image publishing is properly configured for self-hosters to pull from GHCR (and optionally Docker Hub).

## Problem Statement / Motivation

Comicarr is ready for community use but the repo is private. Before flipping visibility, we need to audit for secrets, clean up tracked artifacts that leak personal info, add standard open-source community files, and verify the CI/CD pipeline works correctly for a public repo context. The goal is a professional, trustworthy first impression.

## Audit Findings Summary

### Secrets & Sensitive Data

| Finding | Severity | Status |
|---------|----------|--------|
| `config.ini` with real API keys/passwords | N/A | **Safe** — never committed, properly gitignored |
| ComicVine API key `27431e...` in `lib/comictaggerlib/comicvinetalker.py` (vendored ComicTagger default) | LOW | In working tree + history. This is ComicTagger's publicly distributed default key, not personal. |
| CherryPy `test.pem` RSA key in git history (commit `eaed1460`, since deleted) | LOW | Well-known test fixture from CherryPy project. Will trigger GitHub secret scanning. |
| Hardcoded path `/Users/f/Projects/@self-host/comicarr` in `monitor_performance.sh:9` and `view_search_stats.sh:10` | MEDIUM | **Fix required** — leaks local filesystem path |
| `comicarr.pen` (228KB Pencil design file) tracked in git | MEDIUM | **Fix required** — no value to public users |
| `.claude/` directory not in `.gitignore` (contains local paths in `settings.local.json`) | MEDIUM | **Fix required** — could be accidentally committed |
| `.secure/` directory not in `.gitignore` | LOW | **Fix required** — future-proofing |
| API key plaintext logging fixed in commit `8acd23cb` | N/A | **Already fixed** in current code |

### Git History

| Finding | Assessment |
|---------|------------|
| No secrets ever committed to tracked files | **Clean** |
| ComicVine API key in vendored library history | Inherited from upstream Mylar3/ComicTagger — same key is public in their repos |
| CherryPy test PEM in deleted vendored dir | Test fixture, not a real credential |
| Commit messages | Professional. Minor informality inherited from upstream ("dumb", "stupid blank.gif") — typical OSS style |
| Author emails | 93 unique contributors from Mylar3 era. All inherited from the already-public Mylar3 repo. One display name `doucheymcdoucherson` from upstream contributor |
| Large binary files | **Clean** — largest blob is a 640KB PNG |
| Your commits | All professional, conventional commit format, using GitHub noreply email |

### Repository Configuration

| Item | Status |
|------|--------|
| README.md | Good — Docker + manual install, features, attribution |
| LICENSE (GPLv3) | Present and complete |
| Bug report template | Present |
| Feature request template | Present |
| CI workflow | Present (frontend + backend lint) |
| Test workflow | Present (Python 3.10/3.11/3.12 matrix + frontend + E2E) |
| Release workflow | Present (tag-triggered, multi-arch, GHCR) |
| `config.ini.sample` | Present with placeholders |
| **CONTRIBUTING.md** | **Missing** |
| **SECURITY.md** | **Missing** |
| **CODE_OF_CONDUCT.md** | **Missing** |
| **CHANGELOG.md** | **Missing** |
| **PR template** | **Missing** |

### Docker / CI

| Item | Status |
|------|--------|
| Dockerfile (3-stage, non-root, multi-arch) | Good |
| docker-compose.yml | Good — minor fix: `restart: always` → `unless-stopped` |
| GHCR publishing via release.yml | Working |
| Docker Hub publishing | Not configured (see Docker Hub section below) |
| `docker/entrypoint.sh` | Dead code — Dockerfile doesn't use it, references wrong path `/app/comicarr` vs `/opt/comicarr` |
| `claude.yml` workflow | **Security risk on public repo** — any user can trigger Claude Code via `@claude` comment |
| `test.yml` CODECOV_TOKEN | Referenced but not configured — uploads silently fail |
| `ci.yml` `continue-on-error: true` on lint | Lint failures never break CI — looks unprofessional |

## Proposed Solution

Three phases: (1) security fixes and cleanup, (2) community files and CI hardening, (3) publish and verify.

### Decision: Git History Rewrite

**Recommendation: Do NOT rewrite history.**

Reasons:
- The ComicVine API key is ComicTagger's publicly distributed default — not a personal secret
- The CherryPy test.pem is a well-known test fixture
- Rewriting 2,753 commits from 93 contributors would break all SHA references
- Both artifacts already exist in the public Mylar3 repository
- Document these in `SECURITY.md` and dismiss GitHub secret scanning alerts

### Decision: Docker Hub

**Recommendation: Start with GHCR only, add Docker Hub later.**

| Registry | Pros | Cons |
|----------|------|------|
| GHCR (current) | Zero config needed, integrated with GitHub, free for public repos | Less discoverable for Docker-native users |
| Docker Hub | Largest registry, `docker pull comicarr` without prefix, better SEO | Requires separate account, rate limits on free tier, separate CI config |
| Both | Maximum reach | More maintenance, two registries to keep in sync |

GHCR is sufficient for launch. The *arr community is technical enough to use `ghcr.io/` prefix. Docker Hub can be added in a follow-up by extending `release.yml` with a second `docker/login-action` + push target.

### Decision: CLAUDE.md and AGENTS.md

- **Keep `CLAUDE.md`** — increasingly standard for public repos, helps AI-assisted contributors
- **Remove `AGENTS.md`** from tracking — duplicates CLAUDE.md with less polish, add to `.gitignore`

## Technical Considerations

### GitHub Actions on Public Repos

- Forked PR workflows get **read-only** `GITHUB_TOKEN` — current `ci.yml` and `test.yml` use `pull_request` trigger correctly
- `claude.yml` needs an author association guard or should be disabled — any anonymous user can trigger it
- Codecov doesn't require a token for public repos — simplify `test.yml`

### GitHub Secret Scanning

Once public, GitHub will scan the repo and history. Expected alerts:
1. ComicVine API key in `comicvinetalker.py` → dismiss as "used in tests" / upstream default
2. CherryPy test PEM in history → dismiss as test fixture

Document both in `SECURITY.md` so future maintainers understand.

### GPLv3 Compliance

Current attribution ("modernized fork of Mylar3" in README) satisfies GPLv3 Section 5. No additional `NOTICE` file needed, but adding a copyright line strengthens it.

## Acceptance Criteria

### Phase 1: Security & Cleanup (Blockers)

- [ ] Update `.gitignore` to add: `.claude/`, `.secure/`, `*.pen`, `.env`, `.env.*`, `AGENTS.md`
- [ ] Run `git rm --cached comicarr.pen` to untrack design file
- [ ] Run `git rm --cached AGENTS.md` to untrack internal dev notes
- [ ] Fix `monitor_performance.sh` — replace hardcoded `/Users/f/Projects/@self-host/comicarr` with `$(cd "$(dirname "$0")" && pwd)` or similar
- [ ] Fix `view_search_stats.sh` — same path fix
- [ ] Disable or guard `claude.yml` workflow — add `if: github.event.comment.author_association == 'MEMBER' || github.event.comment.author_association == 'OWNER'` condition, or delete the workflow
- [ ] Remove dead `docker/entrypoint.sh` or reconcile with Dockerfile
- [ ] Fix `docker-compose.yml` restart policy: `always` → `unless-stopped`
- [ ] Remove `docs/RELEASE_PLAN.md` from tracking (internal checklist) or keep if comfortable with it being public

### Phase 2: Community Files & CI

- [ ] Create `CONTRIBUTING.md` — dev setup (uv, npm), PR process, code style (no type hints, GPL headers), testing
- [ ] Create `SECURITY.md` — vulnerability reporting process, document known scanner false positives (ComicVine key, test PEM)
- [ ] Create `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1
- [ ] Create `CHANGELOG.md` — initial entry for v0.1.0 summarizing major changes from Mylar3
- [ ] Create `.github/PULL_REQUEST_TEMPLATE.md`
- [ ] Fix `ci.yml` — remove `continue-on-error: true` from ruff lint steps (or make it a separate advisory check)
- [ ] Fix `test.yml` — remove `CODECOV_TOKEN` env var (public repos don't need it) or configure the secret
- [ ] Add `.github/dependabot.yml` for Python (pip) and npm ecosystem security updates

### Phase 3: Publish & Verify

- [ ] Create and push tag `v0.1.0`
- [ ] Verify release workflow triggers and builds Docker image to GHCR
- [ ] Switch GitHub repo visibility from private to public
- [ ] Verify GitHub Actions still run on the public repo
- [ ] Dismiss expected secret scanning alerts with documented rationale
- [ ] Enable branch protection on `main` (available free on public repos)
- [ ] Enable GitHub Discussions
- [ ] Verify `docker pull ghcr.io/frankieramirez/comicarr:latest` works from a clean machine

## Success Metrics

- Zero real secrets exposed in repo or git history
- GitHub secret scanning shows only dismissed false positives
- All CI workflows pass on `main` after going public
- Docker image pullable and runnable by a new user following README instructions
- Community files (CONTRIBUTING, SECURITY, CODE_OF_CONDUCT) present and linked from README

## Dependencies & Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Someone forks before all cleanup is done | Low (private → public is instant) | Complete all Phase 1+2 commits before flipping visibility |
| GitHub secret scanning creates noisy alerts | High | Pre-document in SECURITY.md, dismiss promptly |
| CI breaks on public repo due to token permissions | Medium | Test with a fork before going public, or fix quickly after |
| `cfscrape` dependency flagged by security scanners | Medium | Replace with `cloudscraper` in a follow-up PR (not a blocker) |
| GetComics integration draws legal attention | Low | Inherited from Mylar3 (already public). Standard in *arr ecosystem |

## File Reference

Key files to modify:
- `.gitignore` — add missing patterns
- `monitor_performance.sh:9` — hardcoded path
- `view_search_stats.sh:10` — hardcoded path
- `.github/workflows/claude.yml` — public repo security
- `.github/workflows/ci.yml` — remove continue-on-error
- `.github/workflows/test.yml` — Codecov token
- `docker-compose.yml` — restart policy
- `docker/entrypoint.sh` — dead code removal

Files to create:
- `CONTRIBUTING.md`
- `SECURITY.md`
- `CODE_OF_CONDUCT.md`
- `CHANGELOG.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/dependabot.yml`

Files to untrack:
- `comicarr.pen`
- `AGENTS.md`

## Sources

- [docs/RELEASE_PLAN.md](../../docs/RELEASE_PLAN.md) — existing internal release checklist (overlaps with this plan)
- [GitHub Secret Scanning docs](https://docs.github.com/en/code-security/secret-scanning)
- [Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/)
- Mylar3 public repo — confirms inherited artifacts are already publicly visible
