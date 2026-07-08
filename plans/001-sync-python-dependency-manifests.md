# Plan 001: Make pip installs and startup checks match pyproject dependencies

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report - do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b6d743ea..HEAD -- README.md requirements.txt pyproject.toml Comicarr.py tests/unit`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `b6d743ea`, 2026-07-07

## Why this matters

The repo declares `pyproject.toml` as the dependency source of truth, but manual install docs and CI still use `requirements.txt`. That file omits runtime packages required by the FastAPI app, so pip users can install an environment that passes the startup preflight but cannot run the current application. Aligning the manifests also gives CI and the dependency-audit plan a trustworthy baseline.

## Current state

- `README.md` - manual install guide still presents pip as supported.
- `requirements.txt` - pip compatibility file, currently missing multiple runtime dependencies.
- `pyproject.toml` - current runtime dependency source of truth.
- `Comicarr.py` - startup preflight reads `requirements.txt` and imports only modules listed there.
- `tests/unit` - backend unit tests use plain pytest, no type hints, and `unittest.mock` where needed.

Relevant excerpts:

```text
README.md:62-68
2. Install Python dependencies:
# Using uv (recommended - creates .venv automatically)
uv sync
# Or using pip
pip install -r requirements.txt
```

```text
requirements.txt:5-7
# This file is kept for backwards compatibility and pip users.
# Dependencies are managed in pyproject.toml
```

```text
requirements.txt:9-25
APScheduler>=3.6.3
...
urllib3<2
user_agent2>=2021.12.11
```

```text
pyproject.toml:8-36
dependencies = [
    "APScheduler>=3.6.3",
    "bcrypt>=5.0.0",
    "cryptography>=46.0.5",
    "fastapi>=0.115.0",
    ...
    "SQLAlchemy>=2.0",
    "sse-starlette>=3.0.0",
    "uvicorn[standard]>=0.30.0",
]
```

```text
Comicarr.py:89-100
with open(self.reqfile, 'r') as file:
    for line in file.readlines():
        operator = [x for x in self.ops if x in line]
        ...
        self.mod_list[module_name] = {'version': module_version, 'operator': operator}
```

Repo conventions to match:

- Python code in this repo avoids type hints.
- Use single-quoted strings in legacy Python files unless existing local style differs.
- Log with the custom logger only when this code already logs; the startup checker currently prints to stdout.
- New Python files should include the GPL header used by files such as `comicarr/app/common/filesystem.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install dev env | `uv sync --extra dev` | exit 0 |
| Unit tests | `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_dependency_manifests.py -q -p no:cacheprovider` | new dependency tests pass |
| Existing backend check | `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_system_domain.py -q -p no:cacheprovider` | all pass |
| Lint | `./.venv/bin/ruff check --no-cache Comicarr.py tests/unit/test_dependency_manifests.py` | exit 0 |
| Format check | `./.venv/bin/ruff format --check Comicarr.py tests/unit/test_dependency_manifests.py` | exit 0 |
| Pip smoke | `python3 -m venv /tmp/comicarr-pip-install-check && /tmp/comicarr-pip-install-check/bin/python -m pip install -r requirements.txt && /tmp/comicarr-pip-install-check/bin/python -c "import fastapi, uvicorn, jwt, sqlalchemy, multipart, cryptography"` | exit 0 |

## Scope

**In scope**:

- `requirements.txt`
- `Comicarr.py`
- `tests/unit/test_dependency_manifests.py` (create)
- `README.md` only if the install wording needs to clarify that `pyproject.toml` is canonical

**Out of scope**:

- Version bumps in `pyproject.toml` or package files
- Security upgrades for vulnerable packages; that is plan 005
- CI workflow changes; that is plan 004
- Switching the project to uv-only installs

## Git workflow

- Branch: `fix/sync-python-dependency-manifests`
- Commit message style: conventional commit, for example `fix: sync pip dependency manifest with pyproject`
- Do not push or open a PR unless instructed.

## Steps

### Step 1: Update `requirements.txt` to cover every runtime dependency

Compare `[project].dependencies` in `pyproject.toml` to `requirements.txt`. Add missing runtime dependencies from `pyproject.toml` to `requirements.txt` while preserving the existing comments and the current `urllib3<2` cap. Do not update package versions as part of this plan.

The known missing runtime dependency names at plan time are: `bcrypt`, `cryptography`, `fastapi`, `openai`, `PyJWT`, `python-multipart`, `SQLAlchemy`, `sse-starlette`, and `uvicorn`.

**Verify**: `./.venv/bin/python - <<'PY'
import tomllib
from pathlib import Path
from packaging.requirements import Requirement
py = tomllib.loads(Path('pyproject.toml').read_text())
project = {Requirement(dep).name.lower() for dep in py['project']['dependencies']}
reqs = set()
for raw in Path('requirements.txt').read_text().splitlines():
    raw = raw.strip()
    if raw and not raw.startswith('#'):
        reqs.add(Requirement(raw).name.lower())
print(sorted(project - reqs))
PY` -> prints `[]`.

### Step 2: Make the startup dependency checker understand modern requirement lines

Update the `test_the_requires` parser in `Comicarr.py` so it can parse requirement extras and names using `packaging.requirements.Requirement` instead of manual operator splitting. Keep the printed failure format compatible with the current output.

Required behavior:

- `requests[socks]>=...` still checks both `requests` and `socks`/`PySocks` as appropriate.
- `uvicorn[standard]>=...` checks import module `uvicorn`, not a literal module named `uvicorn[standard]`.
- Distribution-to-import mappings include at least: `APScheduler -> apscheduler`, `beautifulsoup4 -> bs4`, `Pillow -> PIL`, `PyJWT -> jwt`, `python-multipart -> multipart`, `SQLAlchemy -> sqlalchemy`, `sse-starlette -> sse_starlette`, and `pycryptodome -> Crypto`.
- Existing missing-module behavior stays intact: missing optional proxy support should not exit if it is the only failure.

**Verify**: `./.venv/bin/ruff check --no-cache Comicarr.py` -> `All checks passed!`.

### Step 3: Add a manifest drift test

Create `tests/unit/test_dependency_manifests.py`. The test should parse `pyproject.toml` with `tomllib` and `requirements.txt` with `packaging.requirements.Requirement`, then assert that every runtime dependency from `pyproject.toml` is present in `requirements.txt` by normalized distribution name.

Also add a focused test for any pure helper you create in `Comicarr.py` to resolve requirement names to import module names. If importing `Comicarr.py` would start the app or run the preflight, do not import it directly. Instead, keep the helper test limited to data that can be tested without executing application startup, or skip helper-level tests and rely on the manifest drift test plus pip smoke.

**Verify**: `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_dependency_manifests.py -q -p no:cacheprovider` -> all tests pass.

### Step 4: Run a pip install smoke test

Use a disposable virtualenv in `/tmp` to confirm `requirements.txt` can install the modern runtime packages and import the app stack modules.

**Verify**: `python3 -m venv /tmp/comicarr-pip-install-check && /tmp/comicarr-pip-install-check/bin/python -m pip install -r requirements.txt && /tmp/comicarr-pip-install-check/bin/python -c "import fastapi, uvicorn, jwt, sqlalchemy, multipart, cryptography"` -> exit 0.

## Test plan

- New backend unit test: `tests/unit/test_dependency_manifests.py`.
- Cover the specific regression: `requirements.txt` missing runtime dependencies from `pyproject.toml`.
- Optional helper tests should use the current style in `tests/unit/test_system_domain.py`: pytest functions/classes, `MagicMock`/`patch` only when needed, no type hints.

## Done criteria

- [ ] `requirements.txt` contains every runtime dependency declared in `[project].dependencies`.
- [ ] Startup dependency checking handles requirement extras and mapped import names.
- [ ] `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_dependency_manifests.py -q -p no:cacheprovider` exits 0.
- [ ] `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_system_domain.py -q -p no:cacheprovider` exits 0.
- [ ] `./.venv/bin/ruff check --no-cache Comicarr.py tests/unit/test_dependency_manifests.py` exits 0.
- [ ] `./.venv/bin/ruff format --check Comicarr.py tests/unit/test_dependency_manifests.py` exits 0.
- [ ] The pip smoke command exits 0.
- [ ] No files outside the in-scope list are modified.
- [ ] `plans/README.md` status row updated.

## STOP conditions

Stop and report back if:

- `requirements.txt` is no longer intended to support pip users.
- `pyproject.toml` or `requirements.txt` has already been replaced by a generated-file workflow.
- Fixing the startup checker requires changing application startup semantics outside dependency parsing.
- The pip smoke fails because a current dependency cannot be installed from PyPI without changing package versions.

## Maintenance notes

After this lands, dependency changes should update `pyproject.toml`, `requirements.txt`, and the lockfile together. Reviewers should check that `requirements.txt` remains a compatibility mirror, not a second independent source of truth.
