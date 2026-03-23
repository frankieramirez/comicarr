---
title: "fix: Add missing db.rawdb compatibility shim"
type: fix
status: active
date: 2026-03-23
---

# fix: Add missing db.rawdb compatibility shim

## Overview

The Upcoming Releases page (and likely many other pages) crashes with a 500 Internal Server Error:

```
AttributeError: module 'comicarr.db' has no attribute 'rawdb'
```

The traceback shows `webserve.py:4040` in `fly_me_to_the_moon()` calling `db.rawdb.select_all(...)`, but `rawdb` was never defined in the refactored `db.py`.

## Problem Statement

When `db.py` was refactored for multi-database support (commit `3df729cb`, PR #45), the module-level `rawdb` object was replaced with standalone functions (`raw_select_all`, `raw_select_one`). However, `webserve.py` was not updated — it still references `db.rawdb.select_all()` (105 occurrences) and `db.rawdb.select_one()` (77 occurrences). This breaks **every page** that queries the database via these methods, not just Upcoming Releases.

## Proposed Solution

Add a lightweight compatibility shim object `rawdb` to `comicarr/db.py` that delegates to the existing module-level functions. This is the safest fix because:

1. **Minimal change** — one small class + one module variable, no changes to 182 call sites
2. **Zero risk of breaking working code** — all existing `raw_select_all`/`raw_select_one` callers are unaffected
3. **Consistent with existing pattern** — `db.py` already has a `DBConnection` deprecation shim

### Implementation

Add to `comicarr/db.py` after the `raw_execute` function (around line 221):

```python
# comicarr/db.py (after raw_execute, ~line 221)

class _RawDBShim:
    """Compatibility shim so ``db.rawdb.select_all(...)`` and
    ``db.rawdb.select_one(...)`` keep working during migration.

    .. deprecated::
        Use ``db.raw_select_all()`` / ``db.raw_select_one()`` directly.
    """
    select_all = staticmethod(raw_select_all)
    select_one = staticmethod(raw_select_one)

rawdb = _RawDBShim()
```

That's it. No changes to `webserve.py` needed for the fix itself.

## Acceptance Criteria

- [ ] `db.rawdb.select_all(sql, args)` delegates to `db.raw_select_all(sql, args)`
- [ ] `db.rawdb.select_one(sql, args)` delegates to `db.raw_select_one(sql, args)`
- [ ] Upcoming Releases page loads without 500 error
- [ ] Other pages using `db.rawdb` (Series, Wanted, Story Arcs, etc.) also work
- [ ] Existing `db.raw_select_all()` / `db.raw_select_one()` callers unaffected

## Files to Change

| File | Change |
|------|--------|
| `comicarr/db.py` | Add `_RawDBShim` class and `rawdb` module attribute (~6 lines) |

## Context

- `webserve.py` has **182 total references** to `db.rawdb` (105 `select_all`, 77 `select_one`)
- Only `webserve.py` uses the `db.rawdb` pattern — no other files are affected
- A future cleanup PR could replace all `db.rawdb.select_all` → `db.raw_select_all` and remove the shim, but that's a larger refactor and not needed for the fix

## Sources

- Error traceback: `webserve.py:4040` → `fly_me_to_the_moon` → `db.rawdb.select_all`
- Root cause: PR #45 (`3df729cb`) refactored `db.py` without updating `webserve.py` callers
- Similar pattern: `DBConnection` deprecation shim already exists in `db.py:350`
