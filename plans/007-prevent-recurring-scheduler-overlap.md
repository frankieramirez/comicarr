# Plan 007: Prevent recurring scheduler jobs from overlapping themselves

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report - do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b6d743ea..HEAD -- comicarr/__init__.py tests/unit`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `b6d743ea`, 2026-07-07

## Why this matters

Recurring jobs such as search, RSS, DB update, folder monitor, and import scanning mutate shared queues, caches, and globals. The scheduler currently allows three concurrent instances by default, and the recurring jobs do not override that. If one run is slow because of provider latency or filesystem work, another copy can start and amplify duplicate work or race shared state.

## Current state

- `comicarr/__init__.py` - global APScheduler configuration and recurring job registration.
- `tests/unit` - no direct test currently asserts recurring job scheduler options.

Relevant excerpts:

```text
__init__.py:322-330
SCHED = BackgroundScheduler(
    {
        ...
        "apscheduler.job_defaults.coalesce": "true",
        "apscheduler.job_defaults.max_instances": "3",
        "apscheduler.timezone": "UTC",
    }
)
```

```text
__init__.py:814-821
UPDATER_SCHEDULER = SCHED.add_job(
    func=updater.watchlist_updater,
    id="dbupdater",
    ...
    trigger=IntervalTrigger(...),
)
```

```text
__init__.py:824-880
SCHED.add_job(... id="search" ...)
SCHED.add_job(... id="weekly" ...)
SCHED.add_job(... id="rss" ...)
SCHED.add_job(... id="version" ...)
SCHED.add_job(... id="monitor" ...)
SCHED.add_job(... id="importinbox" ...)
```

Repo conventions to match:

- `comicarr/__init__.py` is legacy global-state code; keep the change minimal.
- Avoid broad scheduler rewrites.
- Use `logger` only if new logging is necessary; this plan should not need new logs.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused scheduler test | `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_scheduler_configuration.py -q -p no:cacheprovider` | new tests pass |
| Existing shutdown test | `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_shutdown_drain.py -q -p no:cacheprovider` | all pass |
| Backend lint | `./.venv/bin/ruff check --no-cache comicarr/__init__.py tests/unit/test_scheduler_configuration.py` | exit 0 |
| Format check | `./.venv/bin/ruff format --check comicarr/__init__.py tests/unit/test_scheduler_configuration.py` | exit 0 |

## Scope

**In scope**:

- `comicarr/__init__.py`
- `tests/unit/test_scheduler_configuration.py` (create)

**Out of scope**:

- Changing scheduler persistence or job stores
- Changing intervals or job functions
- Changing queue processing logic
- Making one-shot/manual jobs single-instance unless directly required

## Git workflow

- Branch: `fix/prevent-scheduler-overlap`
- Commit message style: `fix: prevent recurring scheduler job overlap`
- Do not push or open a PR unless instructed.

## Steps

### Step 1: Add a small recurring-job helper

In `comicarr/__init__.py`, add a small private helper near scheduler setup or job registration, for example `_add_recurring_job(**kwargs)`, that delegates to `SCHED.add_job` with:

- `max_instances=1`
- `coalesce=True`

Keep it narrow. Do not change job IDs, triggers, args, or pause behavior.

If a helper is too invasive for this file, set `max_instances=1` and `coalesce=True` explicitly on each recurring `SCHED.add_job` call listed in this plan.

**Verify**: `./.venv/bin/ruff check --no-cache comicarr/__init__.py` -> `All checks passed!`.

### Step 2: Apply single-instance behavior to recurring jobs

Apply the helper or explicit keyword args to these jobs:

- `dbupdater`
- `search`
- `weekly`
- `rss`
- `version`
- `monitor`
- `importinbox`

Do not change the global scheduler default from `max_instances=3` unless you confirm no other code depends on it. Per-job settings are safer and more reviewable.

**Verify**: `rg -n "max_instances=1|_add_recurring_job" comicarr/__init__.py` -> shows every recurring job is covered.

### Step 3: Add a unit test for scheduler options

Create `tests/unit/test_scheduler_configuration.py`.

Recommended approach:

- If you added a helper, test it with a fake scheduler object whose `add_job` records kwargs.
- Assert the helper passes `max_instances=1` and `coalesce=True`.
- Add a source-level safeguard test that reads `comicarr/__init__.py` and asserts each recurring job ID is near a `max_instances=1` call or is registered through the helper. This is acceptable here because importing and running `start()` would be too broad for a unit test.

Keep tests simple and deterministic.

**Verify**: `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_scheduler_configuration.py -q -p no:cacheprovider` -> all pass.

## Test plan

- New focused scheduler configuration test.
- Existing shutdown drain tests to ensure scheduler lifecycle assumptions did not regress.
- No integration test required unless the helper changes `start()` semantics beyond keyword args.

## Done criteria

- [ ] Each recurring job listed in this plan has `max_instances=1` and `coalesce=True`.
- [ ] Job IDs, intervals, pause calls, functions, and args remain unchanged.
- [ ] Focused scheduler test passes.
- [ ] `tests/unit/test_shutdown_drain.py` still passes.
- [ ] Ruff check and format check pass.
- [ ] No files outside the in-scope list are modified.
- [ ] `plans/README.md` status row updated.

## STOP conditions

Stop and report back if:

- A documented product decision requires overlapping any listed recurring job.
- A recurring job intentionally uses `max_instances>1` for throughput and has locking that was not visible during this audit.
- Testing requires starting the real scheduler or running provider/network work.

## Maintenance notes

If future recurring jobs are added, reviewers should require the same single-instance policy unless the PR explains why overlap is safe.
