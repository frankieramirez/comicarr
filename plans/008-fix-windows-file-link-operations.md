# Plan 008: Fix Windows hardlink and softlink file operations

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report - do not improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b6d743ea..HEAD -- comicarr/app/common/filesystem.py tests/unit/test_app_core.py tests/unit`
> If any in-scope file changed since this plan was written, compare the "Current state" excerpts against the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW-MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `b6d743ea`, 2026-07-07

## Why this matters

The Windows branch of `file_ops()` calls literal `mklink` command strings that do not interpolate source and destination paths. The softlink branch also raises before its fallback copy code, so a failed link can leave the source moved and the intended link missing. Windows users who configure hardlink or softlink post-processing can get a logged success without a link, or worse, a lossy move.

## Current state

- `comicarr/app/common/filesystem.py` - file operation helper extracted from legacy helpers.
- `tests/unit/test_app_core.py` - already contains `TestCommonFilesystem` for filesystem utility tests.

Relevant excerpts:

```text
filesystem.py:66-80
def file_ops(path, dst, arc=False, one_off=False, multiple=False, file_opts=None, ...):
    """Perform file copy/move/link operations.
    Takes config values as parameters to stay free of global state.
    """
```

```text
filesystem.py:112-123
elif any([action_op == "hardlink", action_op == "softlink"]):
    if os_detect is None or "windows" not in os_detect.lower():
        if action_op == "hardlink":
            ...
            os.link(path, dst)
```

```text
filesystem.py:217-220
if file_opts == "hardlink":
    try:
        os.system(r"mklink /H dst path")
        log.debug("Successfully hardlinked file [" + dst + " --> " + path + "]")
```

```text
filesystem.py:233-241
elif file_opts == "softlink":
    try:
        shutil.move(path, dst)
        ...
        os.system(r"mklink dst path")
        ...
    except OSError as e:
        raise e
```

Repo conventions to match:

- Use the existing function signature and return `True`/`False` behavior.
- Keep broad `except Exception as e` style with contextual logs where this module already uses it.
- Avoid type hints.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused tests | `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_app_core.py::TestCommonFilesystem -q -p no:cacheprovider` | all filesystem tests pass |
| Backend lint | `./.venv/bin/ruff check --no-cache comicarr/app/common/filesystem.py tests/unit/test_app_core.py` | exit 0 |
| Format check | `./.venv/bin/ruff format --check comicarr/app/common/filesystem.py tests/unit/test_app_core.py` | exit 0 |

## Scope

**In scope**:

- `comicarr/app/common/filesystem.py`
- `tests/unit/test_app_core.py` or `tests/unit/test_filesystem.py` if you choose a separate focused file

**Out of scope**:

- Rewriting all post-processing file operations
- Changing non-Windows behavior except to share a helper safely
- Adding platform-specific CI runners
- Changing caller semantics in `helpers.py` or postprocessor modules

## Git workflow

- Branch: `fix/windows-file-link-ops`
- Commit message style: `fix: correct Windows file link operations`
- Do not push or open a PR unless instructed.

## Steps

### Step 1: Remove literal `mklink` shell calls

Replace the Windows hardlink branch with `os.link(path, dst)`, matching the non-Windows behavior. Python's `os.link` supports Windows hard links and avoids shell quoting problems.

Do not use `os.system`, `subprocess` shell strings, or literal command placeholders. If a Windows-specific fallback is truly required, use structured APIs and check return codes.

**Verify**: `rg -n "mklink|os\\.system" comicarr/app/common/filesystem.py` -> no matches for this code path.

### Step 2: Make Windows softlink behavior match non-Windows behavior

For the Windows softlink branch, use `os.symlink()` with the same path direction as the non-Windows branch:

- For non-arc behavior, move `path` to `dst`, remove stale `path` if it exists, then create the symlink at `path` pointing to `dst`.
- Respect relative softlink behavior if the relevant config flag is in effect.
- If symlink creation fails, log a warning and copy from `dst` back to `path`, matching the existing fallback intent.
- Remove the unreachable `raise e`.

Be careful with operation order: do not delete the only existing file before a recoverable copy fallback exists.

**Verify**: `./.venv/bin/ruff check --no-cache comicarr/app/common/filesystem.py` -> `All checks passed!`.

### Step 3: Add mocked Windows-path tests

Add tests under `TestCommonFilesystem` in `tests/unit/test_app_core.py`, or create `tests/unit/test_filesystem.py` with the GPL header.

Test cases:

- Windows hardlink calls `os.link(path, dst)` and returns `True`.
- Windows hardlink falls back to copy and returns `True` on a cross-device style `OSError`, if you preserve that fallback.
- Windows softlink calls `shutil.move(path, dst)`, then `os.symlink(dst, path)` for absolute links.
- Windows softlink failure copies `dst` back to `path` and returns `True`/`False` according to copy outcome.
- No test should require a real Windows host; patch `os.link`, `os.symlink`, `shutil.move`, `shutil.copy`, `os.path.lexists`, and `os.remove`.

**Verify**: `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest tests/unit/test_app_core.py::TestCommonFilesystem -q -p no:cacheprovider` -> all pass.

## Test plan

- Mocked unit tests for Windows hardlink and softlink paths.
- Existing path traversal tests in `TestCommonFilesystem`.
- No real filesystem symlink privileges required in CI.

## Done criteria

- [ ] Windows hardlink branch no longer uses literal `mklink` strings.
- [ ] Windows softlink branch no longer has unreachable fallback code.
- [ ] Link operations check Python exceptions/return behavior instead of assuming shell success.
- [ ] Mocked Windows tests cover success and fallback paths.
- [ ] Focused tests and ruff commands pass.
- [ ] No files outside the in-scope list are modified.
- [ ] `plans/README.md` status row updated.

## STOP conditions

Stop and report back if:

- A caller depends on the current reversed `dst -> path` logging/path direction in a way that conflicts with the non-Windows branch.
- Real Windows behavior requires elevated symlink privileges that cannot be represented by a safe fallback.
- Fixing this requires changing postprocessor archive semantics outside `file_ops()`.

## Maintenance notes

Reviewers should check path direction carefully. The safest implementation is the one that makes Windows and non-Windows branches share code or helper functions instead of maintaining divergent logic.
