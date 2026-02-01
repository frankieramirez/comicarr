# Release and Maintenance Plan for Mylar3 Public Distribution

## Executive Summary

This plan outlines the steps to take your private Mylar3 fork public, including repository setup, Docker distribution, versioning strategy, release automation, and ongoing maintenance.

---

## Phase 1: Pre-Release Preparation

### 1.1 Repository Decision

**Recommendation: Keep under your personal account initially**

| Option | Pros | Cons |
|--------|------|------|
| Personal account (frankieramirez/mylar4) | Simple, no setup, full control | Less "official" appearance |
| GitHub Organization | Professional look, team management | Extra setup, may seem like overkill for solo project |
| Transfer to existing Mylar org | Legitimacy, existing community | Requires coordination, may lose autonomy |

**Action:** Keep as `frankieramirez/mylar4` initially. You can transfer to an organization later if the project grows.

### 1.2 Documentation Checklist

Create/update these files before going public:

- [ ] **README.md** - Update installation instructions, remove placeholders
- [ ] **CONTRIBUTING.md** - Contribution guidelines, PR process, coding standards
- [ ] **SECURITY.md** - Vulnerability reporting process
- [ ] **CODE_OF_CONDUCT.md** - Community standards (use GitHub's template)
- [ ] **CHANGELOG.md** - Version history starting from v0.8.0
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

**Recommended: GitHub Container Registry (GHCR) + Docker Hub**

| Registry | Why Use It |
|----------|-----------|
| **GHCR (ghcr.io)** | Free, integrates with GitHub Actions, same account |
| **Docker Hub** | Industry standard, better discoverability |

**Naming convention:**
- GHCR: `ghcr.io/frankieramirez/mylar4:latest`
- Docker Hub: `frankieramirez/mylar4:latest`

### 2.2 Docker Hub Setup

1. **Create Docker Hub account** at https://hub.docker.com
   - Use same username as GitHub if available
2. **Create repository**: `frankieramirez/mylar4`
3. **Add repository secrets** to GitHub:
   - `DOCKERHUB_USERNAME`
   - `DOCKERHUB_TOKEN` (create at Docker Hub → Account Settings → Security)

### 2.3 Image Tagging Strategy

```
frankieramirez/mylar4:latest      # Latest stable release
frankieramirez/mylar4:0.8.3       # Specific version
frankieramirez/mylar4:0.8         # Latest in 0.8.x series
frankieramirez/mylar4:develop     # Development builds (optional)
```

### 2.4 Add docker-compose.yml

Create `docker-compose.yml` in repo root for easy user deployment:

```yaml
services:
  mylar4:
    image: frankieramirez/mylar4:latest
    container_name: mylar4
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

Current version: `0.8.0` → Continue from here

### 3.2 Changesets vs Alternatives

| Tool | Complexity | Best For |
|------|------------|----------|
| **Manual tags** | Low | Solo projects, infrequent releases |
| **Changesets** | Medium | Monorepos, multiple packages |
| **Conventional Commits + auto-changelog** | Medium | Automated changelogs |
| **Release Please** | Low-Medium | Google's automated release tool |

**Recommendation: Start with manual releases, add automation later**

For a solo project, manual tagging with a GitHub release workflow is sufficient. You can add Changesets or Release Please once you have more frequent releases or contributors.

### 3.3 Version Sync

Fix the version mismatch between frontend and backend:

1. Keep `pyproject.toml` as the source of truth
2. Update `frontend/package.json` version to match
3. Consider a version bump script that updates both

---

## Phase 4: Release Workflow

### 4.1 Create GitHub Actions Release Workflow

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Extract version
        id: version
        run: echo "VERSION=${GITHUB_REF#refs/tags/v}" >> $GITHUB_OUTPUT

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            ghcr.io/frankieramirez/mylar4:latest
            ghcr.io/frankieramirez/mylar4:${{ steps.version.outputs.VERSION }}
            frankieramirez/mylar4:latest
            frankieramirez/mylar4:${{ steps.version.outputs.VERSION }}
          platforms: linux/amd64,linux/arm64

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v1
        with:
          generate_release_notes: true
```

### 4.2 Release Process

When ready to release:

```bash
# 1. Update version in pyproject.toml and package.json
# 2. Update CHANGELOG.md
# 3. Commit changes
git add -A
git commit -m "chore: release v0.8.4"

# 4. Create and push tag
git tag v0.8.4
git push origin main --tags
```

The workflow automatically:
- Builds Docker images for AMD64 and ARM64
- Pushes to GHCR and Docker Hub
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

1. **Enable Dependabot** for security updates:

Create `.github/dependabot.yml`:
```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

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

- [ ] Update README.md with accurate installation instructions
- [ ] Create CONTRIBUTING.md
- [ ] Create SECURITY.md
- [ ] Create CODE_OF_CONDUCT.md
- [ ] Create CHANGELOG.md
- [ ] Add docker-compose.yml
- [ ] Create .github/workflows/release.yml
- [ ] Create .github/dependabot.yml
- [ ] Sync version numbers (pyproject.toml and package.json)

### Day of Public Release

1. [ ] Create Docker Hub account and repository
2. [ ] Add DOCKERHUB_USERNAME and DOCKERHUB_TOKEN secrets to GitHub
3. [ ] Change repository visibility to Public
4. [ ] Enable branch protection on main
5. [ ] Enable Discussions
6. [ ] Create initial release (tag v0.8.x)
7. [ ] Verify Docker images are published
8. [ ] Test docker pull and docker-compose up

### Post-Release

- [ ] Monitor for issues in first 48 hours
- [ ] Respond to any initial feedback
- [ ] Share on relevant communities (Reddit r/selfhosted, etc.)

---

## Quick Reference: Accounts Needed

| Service | Purpose | Required? |
|---------|---------|-----------|
| **GitHub** | Code hosting, releases, CI/CD | Yes (already have) |
| **Docker Hub** | Docker image distribution | Recommended |
| **GHCR** | Alternative Docker registry | Automatic with GitHub |
| **PyPI** | Python package distribution | No (Docker is primary) |

---

## Summary

1. **Repository**: Keep under personal account, make public when ready
2. **Docker**: Publish to both GHCR and Docker Hub
3. **Versioning**: Use semantic versioning with manual releases initially
4. **Automation**: GitHub Actions release workflow handles Docker builds
5. **Maintenance**: Dependabot for deps, issue labels for triage, 48-72hr response goal
