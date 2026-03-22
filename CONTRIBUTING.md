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
source .venv/bin/activate

# Install frontend dependencies
cd frontend
npm install
cd ..

# Run the application
python3 Comicarr.py --nolaunch
```

### Frontend Development

```bash
cd frontend
npm run dev     # Start dev server with HMR
npm run lint    # Run ESLint
npm run typecheck  # Run TypeScript checks
npm run build   # Production build
```

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

- **No type hints** — the codebase does not use them currently
- **No auto-formatters enforced** — but `ruff` is used for linting in CI
- **Always catch specific exceptions** — use `except Exception as e`, never bare `except:`
- **Logging pattern**: `logger.fdebug('[MODULE-CONTEXT] message')` or `logger.error('[CONTEXT] Error: %s' % e)`
- **Config access**: `comicarr.CONFIG.option_name`
- **Database**: Always use parameterized queries — `db.DBConnection().action("SELECT * FROM table WHERE id=?", [id])`

### Frontend (React/TypeScript)

- React 19 with TypeScript
- Tailwind CSS 4 for styling
- TanStack Query for data fetching
- Radix UI for accessible components

### Import Ordering

1. Standard library imports
2. Third-party imports
3. Local imports: `from comicarr import logger, helpers`

### GPL License Header

All new Python files must include the GPL v3 license header at the top.

## Pull Request Process

1. Create a feature branch from `main`
2. Make your changes with clear, conventional commit messages
3. Ensure all tests pass and linting is clean
4. Open a PR with a clear description of what and why
5. Fill out the PR template

### Commit Message Format

Use [conventional commits](https://www.conventionalcommits.org/):

```
feat: add new download client support
fix: correct metadata parsing for annual issues
refactor: extract search result deduplication
docs: update API configuration guide
```

## Reporting Issues

- Use the [Bug Report](https://github.com/frankieramirez/comicarr/issues/new?template=bug_report.md) template
- Include a CarePackage (available on the config page) when reporting bugs
- For feature requests, use the [Feature Request](https://github.com/frankieramirez/comicarr/issues/new?template=feature_request.md) template

## License

By contributing, you agree that your contributions will be licensed under the GPL v3 License.
