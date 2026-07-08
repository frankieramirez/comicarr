# Plan 004: Make integration and browser regressions visible in CI

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report - do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b6d743ea..HEAD -- .github/workflows/test.yml .github/workflows/ci.yml README.md`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S-M
- **Risk**: LOW
- **Depends on**: plans/001-sync-python-dependency-manifests.md
- **Category**: tests
- **Planned at**: commit `b6d743ea`, 2026-07-07

## Why this matters

The project has integration and Playwright tests, but the workflow can still report success when those checks fail or never run on pull requests. That is risky for restart recovery, setup, and frontend/backend integration paths where unit tests are not enough. Once the pip dependency baseline is fixed, CI should make these regressions visible before merge.

## Current state

- `.github/workflows/test.yml` - backend unit tests are required, but integration tests are non-blocking.
- `.github/workflows/test.yml` - E2E runs only on pushes to main/master and is non-blocking.
- `.github/workflows/test.yml` - summary job only depends on backend and frontend unit jobs.
- `.github/workflows/ci.yml` - separate lint/build workflow already gates frontend and backend lint.

Relevant excerpts:

```text
test.yml:46-49
- name: Run integration tests
  run: |
    pytest tests/integration -v ...
  continue-on-error: true # Integration tests may have more dependencies
```

```text
test.yml:106-110
e2e-tests:
  needs: [backend-tests, frontend-tests]
  if: github.event_name == 'push' && ...
```

```text
test.yml:155-163
- name: Wait for backend to be ready
  ...
  continue-on-error: true
- name: Run E2E tests
  ...
  continue-on-error: true # E2E tests may need more setup
```

```text
test.yml:183-196
test-summary:
  needs: [backend-tests, frontend-tests]
  ...
  if backend-tests or frontend-tests failed, exit 1
```

Repo conventions to match:

- Workflows use GitHub Actions YAML with `actions/checkout`, `actions/setup-python`, and `actions/setup-node`.
- Node version is 22 in frontend workflows.
- Python test matrix covers 3.10, 3.11, and 3.12.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| YAML syntax smoke | `./.venv/bin/python - <<'PY'\nfrom pathlib import Path\np = Path('.github/workflows/test.yml')\ntext = p.read_text()\nassert 'backend-tests:' in text\nassert 'frontend-tests:' in text\nassert 'test-summary:' in text\nprint('workflow text loaded')\nPY` | prints `workflow text loaded` |
| Backend unit tests | `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit -q -p no:cacheprovider` | all unit tests pass |
| Backend integration tests | `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/integration -q -p no:cacheprovider` | all integration tests pass, or STOP if they require unavailable local services |
| Frontend tests | `cd frontend && npm run test:run` | all pass |
| Frontend typecheck | `cd frontend && npm run typecheck` | exit 0 |

## Scope

**In scope**:

- `.github/workflows/test.yml`
- `.github/workflows/ci.yml` only if a shared dependency or naming cleanup is required
- `README.md` only if CI badges or documented checks need correction

**Out of scope**:

- Rewriting the CI system
- Fixing test failures in product code
- Adding new Playwright tests
- Dependency manifest fixes; plan 001 must land first
- Dependency upgrades; plan 005 owns those

## Git workflow

- Branch: `ci/gate-integration-e2e`
- Commit message style: `ci: gate on integration and e2e tests`
- Do not push or open a PR unless instructed.

## Steps

### Step 1: Make backend integration tests blocking

In `.github/workflows/test.yml`, remove `continue-on-error: true` from the integration test step. Keep the integration command itself unchanged unless it fails because the install baseline from plan 001 changed the supported install command.

**Verify**: `rg -n "Run integration tests|continue-on-error" .github/workflows/test.yml` -> the integration step no longer has `continue-on-error: true`.

### Step 2: Run E2E on pull requests and make readiness failures blocking

Change the `e2e-tests` job so it runs for pull requests as well as pushes to main/master. Remove `continue-on-error: true` from the backend readiness step.

If the full Playwright suite is too slow for every PR, do not silently keep it non-blocking. Instead, split a small required smoke project or job and leave the larger suite scheduled or main-only. The required smoke must still launch the backend and run at least one browser assertion.

**Verify**: `rg -n "e2e-tests|github.event_name|continue-on-error" .github/workflows/test.yml` -> E2E is not restricted to push-only and readiness is not marked continue-on-error.

### Step 3: Make E2E failures affect the summary job

Update `test-summary` so it has `needs: [backend-tests, frontend-tests, e2e-tests]` or equivalent. Its shell check must fail when `needs.e2e-tests.result` is `failure`.

If E2E is skipped for a legitimate event, the summary should allow `skipped` only for that event. Do not allow `failure`.

**Verify**: `rg -n "needs\\.e2e-tests|e2e-tests" .github/workflows/test.yml` -> the summary references E2E.

### Step 4: Make CI install commands consistent with plan 001

Because this workflow currently runs both `pip install -r requirements.txt` and `pip install -e ".[dev]"`, confirm that remains intentional after plan 001. If the repo standard is now `uv sync --extra dev`, update only if the maintainer has already adopted uv in CI elsewhere. Otherwise keep pip and rely on plan 001's corrected requirements.

**Verify**: `rg -n "pip install -r requirements.txt|uv sync" .github/workflows/test.yml` -> install method is consistent and intentional.

## Test plan

- Local unit/integration/frontend test commands listed above.
- Workflow text greps for the specific gating conditions.
- Final validation happens in GitHub Actions on the PR; if the first CI run exposes real test failures, fix or split those tests rather than re-adding `continue-on-error`.

## Done criteria

- [ ] Backend integration test step is blocking.
- [ ] Backend readiness for E2E is blocking.
- [ ] At least a required E2E smoke path runs on pull requests.
- [ ] Summary job fails when required E2E fails.
- [ ] Local unit, integration, frontend test commands either pass or any environmental blocker is documented before PR.
- [ ] No files outside the in-scope list are modified.
- [ ] `plans/README.md` status row updated.

## STOP conditions

Stop and report back if:

- Plan 001 has not landed and CI install still fails because `requirements.txt` is incomplete.
- Existing integration or E2E tests are red for product reasons unrelated to workflow gating.
- E2E requires secrets or external services unavailable to pull requests from forks.

## Maintenance notes

Reviewers should reject any future use of `continue-on-error` for required correctness checks unless paired with a separate blocking smoke check that covers the same risk class.
