# Release and Maintenance Plan for Comicarr Public Distribution

## Executive Summary

This plan outlines the steps to take Comicarr public, including repository setup, Docker distribution, versioning strategy, release automation, and ongoing maintenance.

---

## Phase 1: Pre-Release Preparation

### 1.1 Repository Decision

**Recommendation: Keep under your personal account initially**

| Option | Pros | Cons |
|--------|------|------|
| Personal account (frankieramirez/comicarr) | Simple, no setup, full control | Less "official" appearance |
| GitHub Organization | Professional look, team management | Extra setup, may seem like overkill for solo project |

**Action:** Keep as `frankieramirez/comicarr` initially. You can transfer to an organization later if the project grows.

### 1.2 Documentation Checklist

Create/update these files before going public:

- [x] **README.md** - Update installation instructions, remove placeholders
- [ ] **CONTRIBUTING.md** - Contribution guidelines, PR process, coding standards
- [ ] **SECURITY.md** - Vulnerability reporting process
- [ ] **CODE_OF_CONDUCT.md** - Community standards (use GitHub's template)
- [ ] **CHANGELOG.md** - Version history starting from v0.1.0
- [ ] **.github/PULL_REQUEST_TEMPLATE.md** - PR submission template

### 1.3 Repository Settings

Configure these GitHub settings when going public:

1. **Repository visibility**: Change from Private → Public
2. **Branch protection**: Enable on `main` branch
   - Require PR reviews before merging
   - Require status checks (CI) to pass
3. **Features to enable**:
   - Issues (already enabled)
   - Discussions (for community Q&A)
   - Projects (optional, for roadmap tracking)
4. **Disable**: Wiki (use docs folder or README instead)

---

## Phase 2: Docker Distribution

### 2.1 Where to Publish Docker Images

**Recommended: GitHub Container Registry (GHCR)**

| Registry | Why Use It |
|----------|-----------|
| **GHCR (ghcr.io)** | Free, integrates with GitHub Actions, same account |

**Naming convention:**
- GHCR: `ghcr.io/frankieramirez/comicarr:latest`

### 2.2 Image Tagging Strategy

```
ghcr.io/frankieramirez/comicarr:latest      # Latest stable release
ghcr.io/frankieramirez/comicarr:0.1.0       # Specific version
ghcr.io/frankieramirez/comicarr:0.1         # Latest in 0.1.x series
ghcr.io/frankieramirez/comicarr:develop     # Development builds (optional)
```

### 2.3 Add docker-compose.yml

Already created at repository root:

```yaml
services:
  comicarr:
    image: ghcr.io/frankieramirez/comicarr:latest
    container_name: comicarr
    ports:
      - "8090:8090"
    volumes:
      - ./config:/config
      - /path/to/comics:/comics
      - /path/to/downloads:/downloads
    restart: unless-stopped
```

---

## Phase 3: Versioning Strategy

### 3.1 Semantic Versioning

Adopt **Semantic Versioning (SemVer)**: `MAJOR.MINOR.PATCH`

- **MAJOR**: Breaking changes, incompatible API changes
- **MINOR**: New features, backwards compatible
- **PATCH**: Bug fixes, backwards compatible

Current version: `0.1.0` → Continue from here

### 3.2 Manual Releases

For a solo project, manual tagging with a GitHub release workflow is sufficient.

### 3.3 Version Sync

Fixed - `pyproject.toml` and `frontend/package.json` both at v0.1.0

---

## Phase 4: Release Workflow

### 4.1 GitHub Actions Release Workflow

Already created at `.github/workflows/release.yml`:

- Builds Docker images for AMD64 and ARM64
- Pushes to GHCR
- Creates GitHub Release with auto-generated notes

### 4.2 Release Process

When ready to release:

```bash
# 1. Update version in pyproject.toml and package.json if needed
# 2. Update CHANGELOG.md
# 3. Commit changes
git add -A
git commit -m "chore: release v0.1.x"

# 4. Create and push tag
git tag v0.1.x
git push origin main --tags
```

The workflow automatically:
- Builds Docker images for AMD64 and ARM64
- Pushes to GHCR
- Creates a GitHub Release with auto-generated notes

---

## Phase 5: Ongoing Maintenance

### 5.1 Issue Triage

Set up labels for issue management:
- `bug` - Something isn't working
- `enhancement` - New feature request
- `documentation` - Documentation improvements
- `good first issue` - Good for newcomers
- `help wanted` - Extra attention needed
- `wontfix` - Won't be worked on

### 5.2 Dependency Updates

Enable Dependabot for security updates (optional for solo project)

### 5.3 Community Management

- **Response time goal**: Acknowledge issues within 48-72 hours
- **Stale issue policy**: Close issues inactive for 90+ days
- **Feature requests**: Use Discussions for ideas before creating issues

### 5.4 Release Cadence

Suggested schedule:
- **Patch releases**: As needed for bug fixes
- **Minor releases**: Monthly or bi-monthly with new features
- **Major releases**: When breaking changes are necessary

---

## Phase 6: Implementation Checklist

### Before Going Public

- [x] Update README.md with accurate installation instructions
- [ ] Create CONTRIBUTING.md
- [ ] Create SECURITY.md
- [ ] Create CODE_OF_CONDUCT.md
- [ ] Create CHANGELOG.md
- [x] Add docker-compose.yml
- [x] Create .github/workflows/release.yml
- [x] Sync version numbers (pyproject.toml and package.json)

### Day of Public Release

1. [ ] Rename GitHub repo from `mylar4` to `comicarr`
2. [ ] Change repository visibility to Public
3. [ ] Enable branch protection on main
4. [ ] Enable Discussions
5. [ ] Create initial release (tag v0.1.0)
6. [ ] Verify Docker images are published
7. [ ] Test docker pull and docker-compose up

### Post-Release

- [ ] Monitor for issues in first 48 hours
- [ ] Respond to any initial feedback
- [ ] Share on relevant communities (Reddit r/selfhosted, etc.)

---

## Quick Reference: Accounts Needed

| Service | Purpose | Required? |
|---------|---------|-----------|
| **GitHub** | Code hosting, releases, CI/CD | Yes (already have) |
| **GHCR** | Docker image distribution | Automatic with GitHub |

---

## Summary

1. **Repository**: Keep under personal account, make public when ready
2. **Docker**: Publish to GHCR only
3. **Versioning**: Use semantic versioning with manual releases
4. **Automation**: GitHub Actions release workflow handles Docker builds
5. **Maintenance**: Issue labels for triage, 48-72hr response goal
