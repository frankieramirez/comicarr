# Plan 005: Clear runtime dependency audit findings

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report - do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b6d743ea..HEAD -- pyproject.toml requirements.txt uv.lock Comicarr.py tests`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M-L
- **Risk**: MED
- **Depends on**: plans/001-sync-python-dependency-manifests.md
- **Category**: security
- **Planned at**: commit `b6d743ea`, 2026-07-07

## Why this matters

The JavaScript production dependency audit was clean, but the Python environment audit found runtime advisories in packages used by authentication, FastAPI request handling, image processing, and outbound HTTP. Most should be straightforward lockfile upgrades, but `urllib3` is explicitly pinned below 2 and needs compatibility work rather than a blind bump. This plan creates a controlled dependency upgrade with tests and an audit gate.

## Current state

- `pyproject.toml` - runtime dependency constraints.
- `requirements.txt` - pip compatibility constraints; plan 001 should make it mirror runtime dependencies.
- `uv.lock` - locked package versions.
- `comicarr/app/core/security.py` - imports PyJWT for session tokens.
- `comicarr/app/main.py` - FastAPI/Starlette app and static file serving.
- `comicarr/getimage.py` and `comicarr/app/metadata/service.py` - use Pillow for local and remote images.
- Many modules use `requests`, which depends on `urllib3`.

Relevant excerpts:

```text
pyproject.toml:13-35
"cryptography>=46.0.5",
"fastapi>=0.115.0",
...
"PyJWT>=2.8.0",
"python-multipart>=0.0.9",
...
"requests[socks]>=2.22.0",
...
"urllib3<2",
"uvicorn[standard]>=0.30.0",
```

```text
requirements.txt:21-25
requests[socks]>=2.22.0
...
urllib3<2
```

```text
uv.lock:563-564
name = "cryptography"
version = "46.0.5"
```

```text
uv.lock:1044-1045
name = "pillow"
version = "12.1.0"
```

```text
uv.lock:1400-1401
name = "pyjwt"
version = "2.12.1"
```

```text
uv.lock:1537-1538
name = "python-multipart"
version = "0.0.22"
```

```text
uv.lock:1863-1864
name = "starlette"
version = "1.0.0"
```

```text
uv.lock:1993-1994
name = "urllib3"
version = "1.26.20"
```

Advisor audit note from 2026-07-07:

- `npm audit --omit=dev --audit-level=high` was clean in both root and `frontend/`.
- `uv tool run pip-audit --path .venv/lib/python3.12/site-packages --progress-spinner off` reported 40 known vulnerabilities across 10 packages. Runtime packages called out by the report included `cryptography`, `idna`, `pillow`, `PyJWT`, `python-multipart`, `requests`, `starlette`, and `urllib3`. `pytest`/`pygments` findings were dev-tooling only and lower priority.

Repo conventions to match:

- Do not manually bump project versions; release automation handles versions.
- Keep `requirements.txt`, `pyproject.toml`, and `uv.lock` consistent after plan 001.
- Use `uv` for lockfile work.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install baseline | `uv sync --extra dev` | exit 0 |
| Upgrade targeted packages | `uv lock --upgrade-package cryptography --upgrade-package idna --upgrade-package pillow --upgrade-package PyJWT --upgrade-package python-multipart --upgrade-package requests --upgrade-package starlette` | exit 0 |
| Sync upgraded env | `uv sync --extra dev` | exit 0 |
| Runtime audit | `SITE=$(.venv/bin/python -c "import site; print(site.getsitepackages()[0])"); uv tool run pip-audit --path "$SITE" --progress-spinner off` | no advisories for runtime packages listed in this plan |
| Backend tests | `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit -q -p no:cacheprovider` | all unit tests pass |
| Integration tests | `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/integration -q -p no:cacheprovider` | all pass, or STOP on environmental blocker |
| Backend lint | `./.venv/bin/ruff check --no-cache comicarr/` | exit 0 |
| Frontend audit check | `cd frontend && npm audit --omit=dev --audit-level=high` | `found 0 vulnerabilities` |

## Scope

**In scope**:

- `pyproject.toml`
- `requirements.txt`
- `uv.lock`
- Minimal source/test changes required for dependency compatibility

**Out of scope**:

- Project version bumps
- Frontend dependency upgrades, unless the clean npm audit becomes dirty while executing this plan
- Refactoring HTTP clients or image processing architecture
- Ignoring vulnerabilities without a written maintainer decision

## Git workflow

- Branch: `chore/update-runtime-dependencies`
- Commit message style: `chore: update audited runtime dependencies`
- Do not push or open a PR unless instructed.

## Steps

### Step 1: Re-run the audit from a fresh synced environment

Run `uv sync --extra dev`, then run the runtime audit command from this plan. Capture the current package findings in your working notes or PR description, not in source files.

**Verify**: The audit output still includes at least one of the runtime packages listed in this plan. If it is already clean, skip to the done criteria and mark this plan fixed independently.

### Step 2: Upgrade straightforward runtime packages

Run targeted `uv lock --upgrade-package` for the non-`urllib3` packages listed in the command table. Then run `uv sync --extra dev`.

Do not loosen all constraints broadly. Keep changes focused on the audited packages and their resolver-selected transitive dependencies.

**Verify**: `uv sync --extra dev` exits 0 and `git diff -- pyproject.toml uv.lock requirements.txt` shows only dependency-related changes.

### Step 3: Handle the `urllib3<2` compatibility cap deliberately

The project currently pins `urllib3<2` in both `pyproject.toml` and `requirements.txt`. Try removing or relaxing that cap only after plan 001 has aligned `requirements.txt`.

Required approach:

- First change `pyproject.toml` and `requirements.txt` to allow the fixed `urllib3` line selected by the live audit report.
- Run `uv lock`.
- If the resolver reports that a runtime dependency such as `cfscrape` requires `urllib3<2`, STOP and report the conflicting package and constraint. Do not pin a vulnerable version silently.
- If the resolver succeeds, run the tests in this plan and fix only direct compatibility issues caused by the upgrade.

**Verify**: `uv lock && uv sync --extra dev` exits 0, or the STOP condition is met with resolver output.

### Step 4: Run behavioral checks

Run the backend unit and integration commands. Pay attention to authentication/session tests, image metadata tests, and any tests that exercise outbound HTTP mocks.

**Verify**: Both pytest commands in this plan exit 0.

### Step 5: Re-run dependency audits

Run the runtime Python audit and the frontend production audit. If the Python audit still reports dev-only packages, document them separately and do not block this runtime plan on them. If it reports any of the runtime packages listed in this plan, continue upgrading or STOP if blocked by resolver compatibility.

**Verify**: Runtime audit has no advisories for `cryptography`, `idna`, `pillow`, `PyJWT`, `python-multipart`, `requests`, `starlette`, or `urllib3`; frontend production audit remains clean.

## Test plan

- Full backend unit suite.
- Backend integration suite.
- Dependency audits before and after.
- Any source compatibility fixes need a focused regression test near the affected code.

## Done criteria

- [ ] `pyproject.toml`, `requirements.txt`, and `uv.lock` agree on the upgraded dependency set.
- [ ] Runtime Python audit no longer reports advisories for the runtime packages listed in this plan, or a resolver-blocking package is documented as BLOCKED.
- [ ] `urllib3<2` is removed/relaxed if compatible, or the exact blocker is documented.
- [ ] Backend unit and integration tests pass.
- [ ] `./.venv/bin/ruff check --no-cache comicarr/` exits 0.
- [ ] Frontend production npm audit remains clean.
- [ ] No files outside the in-scope list are modified unless required for a direct compatibility fix.
- [ ] `plans/README.md` status row updated.

## STOP conditions

Stop and report back if:

- Plan 001 has not landed, because `requirements.txt` is not yet a trustworthy install source.
- The resolver cannot satisfy a fixed `urllib3` because a runtime dependency pins `<2`.
- A dependency upgrade requires broad source refactors outside compatibility fixes.
- A package no longer supports Python 3.10, which the repo currently supports.

## Maintenance notes

Add a recurring dependency-audit check only after this plan is clean; otherwise it will create noisy known-failing CI. Reviewers should separate runtime vulnerability fixes from dev-tool-only findings.
