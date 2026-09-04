# Contributing to Comicarr

Thank you for your interest in contributing to Comicarr! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.10+
- Node.js 22+
- [uv](https://docs.astral.sh/uv/) (recommended for Python dependency management)

### Getting Started

```bash
# Clone the repository
git clone https://github.com/frankieramirez/comicarr.git
cd comicarr

# Install Python dependencies
uv sync --extra dev

# Activate virtual environment
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install frontend dependencies (lockfile-respecting; matches CI)
cd frontend
npm ci
cd ..

# Install git pre-commit hooks (lint/format on commit)
pre-commit install

# Run the application
python3 Comicarr.py --nolaunch
```

### Dependency updates

`pyproject.toml` is the editable dependency declaration and `uv.lock` is the
committed resolution. Dependabot tracks the uv project directly; do not add a
second generated Python dependency manifest.

```bash
# Change pyproject.toml (or use uv add), then refresh the committed lock
uv lock
uv run pytest tests/unit/test_dependency_manifests.py -q
```

### Pre-commit hooks

Hooks run automatically on `git commit` and mirror the CI lint/format checks:

- **Backend**: `ruff` (lint + autofix) and `ruff format` on `comicarr/`
- **Frontend**: Prettier and ESLint (via `frontend/` lockfile tools)

One-time install: `uv sync --extra dev && pre-commit install` (and `cd frontend && npm ci` for frontend hooks).

Useful commands:

```bash
pre-commit run --all-files   # run hooks on the whole tree
npm run lint                 # same checks CI uses (backend + frontend)
npm run lint:fix             # autofix what can be fixed
```

If a hook rewrites files, stage the changes and commit again. Avoid `git commit --no-verify` unless you have a deliberate reason — CI will still enforce the same rules.

### Frontend Development

```bash
cd frontend
npm run dev        # https://comicarr.localhost:1355 (portless + HMR)
npm run dev:vite   # raw Vite on localhost:5173 if needed
npm run lint       # Run ESLint
npm run typecheck  # Run TypeScript checks
npm run build      # Production build
```

The default `dev` script goes through [portless](https://github.com/vercel-labs/portless)
(`https://comicarr.localhost:1355`) so other local apps can keep their own named
URLs without stealing port 5173. First HTTPS session may need `npx portless trust`.

When using the Vite dev server with a separately running backend, Comicarr
defaults to port **8090**. The Vite proxy targets `http://localhost:8090`
(override with `VITE_API_PROXY_TARGET` if needed).

### Running Tests

```bash
# Backend tests
pytest tests/unit -v
pytest tests/integration -v

# Frontend tests
cd frontend
npm run test:run
```

## Code Style

### Python

- **Formatting**: `ruff format comicarr/` is enforced in CI and by pre-commit; run it before pushing
- **Lint**: `ruff check comicarr/`
- **Type hints**: not required on large legacy modules; allowed in new `comicarr/app/**` code to match neighbors
- **Always catch specific exceptions** — use `except Exception as e`, never bare `except:`
- **Logging pattern**: `logger.fdebug('[MODULE-CONTEXT] message')` or `logger.error('[CONTEXT] Error: %s' % e)`
- **Config access**: `comicarr.CONFIG.option_name`
- **Database**: SQLAlchemy Core expressions through the `db` helpers — `db.select_one(stmt)`, `db.select_all(stmt)`, `db.upsert(table, values, keys)`. When raw SQL is genuinely needed, `db.raw_select_one` / `db.raw_select_all` / `db.raw_execute` take `?` placeholders and parameterize them. Never interpolate values into SQL. `db.DBConnection()` is a deprecated shim awaiting removal — do not use it in new code

### Frontend (React/TypeScript)

- React 19 with TypeScript
- Tailwind CSS 4 for styling
- TanStack Query for data fetching
- Radix UI for accessible components
- **Lint**: `cd frontend && npm run lint` (ESLint)
- **Format**: `cd frontend && npm run format` / `npm run format:check` (Prettier; enforced in CI and pre-commit)

### Import Ordering

1. Standard library imports
2. Third-party imports
3. Local imports: `from comicarr import logger, helpers`

### GPL License Header

All new Python files must include the GPL v3 license header at the top.

## Pull Request Process

1. Create a feature branch from `main` using a conventional prefix:
   ```
   feat/add-manga-search
   fix/metadata-parsing
   refactor/search-deduplication
   docs/api-guide
   chore/update-deps
   ```
2. Make your changes with clear, conventional commit messages (pre-commit hooks will lint/format staged files)
3. Ensure all tests pass and linting is clean (`npm run lint` from the repo root)
4. Open a PR — **the title must follow conventional commit format** (CI enforces this):
   ```
   feat: Add manga search provider
   fix: Correct metadata parsing for annual issues
   refactor: Extract search result deduplication
   docs: Update API configuration guide
   ```
5. Fill out the PR template

PR titles keep history readable, but they do not control releases. Add a changeset when the PR should affect the next app release.

## Releases

Releases are fully automated via [Changesets](https://github.com/changesets/changesets). **Do not manually create tags, bump versions, or create GitHub Releases.**

How it works:

1. For user-visible app changes, run `npm run changeset` and choose the bump type
2. For maintenance-only work, omit the changeset; CI will warn but will not block the PR
3. Changesets automatically maintains a `Version Packages` PR with changelog and version bumps
4. Merging the `Version Packages` PR creates the GitHub Release, git tag, and triggers the Docker image build

Version files (`package.json`, `pyproject.toml`, `frontend/package.json`, and lockfiles) are updated automatically — never edit versions by hand outside release automation.

### Registries

One build pushes identical tags to both registries:

| Registry | Reference | Role |
| -------- | --------- | ---- |
| GitHub Container Registry | `ghcr.io/frankieramirez/comicarr` | canonical — what docs and in-app update instructions point at |
| Docker Hub | `comicarr/comicarr` | mirror — what the website advertises |

**Registry tags are bare semver** (`0.26.0`). Only git tags and GitHub Releases carry the `v` prefix. Conflating the two produces a reference that does not resolve; `asRegistryTag` / `asGitTag` in `frontend/src/lib/updateGuidance.ts` keep the two lines apart.

The Docker Hub push needs the `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repo secrets. When they are absent the release still succeeds and publishes to GHCR only, logging a workflow warning — a missing or expired token degrades the mirror, never the release. Run `scripts/setup-dockerhub-publishing.sh` to provision or rotate them; the token needs **Read, Write, Delete** scope, because the description-sync step rejects narrower ones.

### Writing a changeset (operator-facing)

Changeset summary text is copied into `CHANGELOG.md` and shown to operators in-app (What's New / update notes) with only a **mechanical** transform — strip commit hashes, drop bucket headings, flatten links. There is **no** editorial filter in the app. Write every entry as if an operator will read it after upgrading.

| Do | Don't |
|----|--------|
| Outcome first: what the operator can see or do differently | Ticket-only or filename-only bullets (`Fix #123`, `Update search.py`) |
| Name the UI surface or behaviour (`Settings → API`, Wanted filter, manual import) | Internals as the headline (`Make METRON_PASSWORD writable`, `Route through series_kind`) |
| Skip the changeset when nothing an operator can observe changed | Ship a release whose only line is "No user-visible behaviour changes." |

Examples:

- **Good:** `The Metron Password field in Settings → API now actually saves.`
- **Good:** `Wanted filtering now searches the full queue, not only the currently loaded page.`
- **Bad:** `Make METRON_PASSWORD writable in the config registry.`
- **Bad:** `No user-visible behaviour changes.` — omit the changeset instead; let the next operator-visible change carry the bump.

When to add one:

- **Add a changeset** when an *operator* could notice a change (UI, settings behaviour, downloads, migration outcomes, defaults that affect running installs).
- **Omit the changeset** for pure internal restructuring with verified-identical behaviour, tooling/CI-only work, docs, or contributor-only gates (lint rules, types). CI treats a missing changeset as an allowed warning.

## Reporting Issues

- Use the [Bug Report](https://github.com/frankieramirez/comicarr/issues/new?template=bug_report.md) template
- Include a Support bundle from **Settings → About** when reporting bugs (review the three files first; share privately with a maintainer if anything looks sensitive)
- For feature requests, use the [Feature Request](https://github.com/frankieramirez/comicarr/issues/new?template=feature_request.md) template

## License

By contributing, you agree that your contributions will be licensed under the GPL v3 License.
