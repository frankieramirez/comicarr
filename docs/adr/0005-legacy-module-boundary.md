# ADR-0005: Legacy module boundary and seam modules

**Status:** Accepted
**Date:** 2026-11-13
**Related:** [Foundations plan](../architecture/foundations-plan.md),
[ADR-0003](./0003-attention-module-ownership.md),
[Roadmap: Comicarr 1.0.0](https://github.com/frankieramirez/comicarr/issues/1184)

## Context

About half the backend still lives in root-level `comicarr/*.py` modules
inherited from Mylar3. The roadmap's Foundations milestone is complete when "no
router under `comicarr/app/` imports a legacy module directly". Measured on
2026-11-13, that sentence was already almost true and proved very little:
routers import only `mangasync`, `comicsync`, `getimage` and `readinglist`
beyond shared infrastructure, while services reach into `importer` from six
files, `updater` from four and `search` from three. A rule about routers alone
would let the milestone close with every real crossing still in place.

Three rules were considered:

1. Routers only, as written. Cheap, and it changes nothing.
2. Nothing under `comicarr/app/` imports any root module. Honest, but it makes
   Foundations responsible for `search.py`, `filechecker.py`, `cv.py` and about
   forty other modules, which is most of a rewrite.
3. A named set of legacy modules, each reachable from `comicarr/app/` through
   exactly one seam module. Everything else is baselined and may only shrink.

## Decision

Rule 3.

Root modules fall into three groups. They will be listed by name in
`scripts/check_legacy_seams.py`, a guard this ADR calls for and that is not
written yet:

- **Infrastructure**: `logger`, `db`, `tables`, `config`, `encrypted`,
  `helpers`, `series_kind`. Any code may import these. They are not legacy for
  the purpose of this rule.
- **Foundations legacy**: `importer`, `updater`, `rsscheck`, `weeklypull`,
  `notifiers`, `postprocessor`, `process`, and the scheduler wrappers
  `rsscheckit` and `weeklypullit`. Under `comicarr/app/`, each may be imported
  only by its one seam module, named in the
  [Foundations plan](../architecture/foundations-plan.md).
- **Deferred legacy**: every other root module. Existing imports from
  `comicarr/app/` are recorded in a shrink-only allowlist keyed on
  `(file, module)`. New crossings fail the guard. Foundations has no duty to
  empty this list.

Routers carry a stricter rule: a `router.py` imports no root module outside
Infrastructure. The five crossings that exist today are allowlisted and must
reach zero before Foundations closes.

The guard will be an AST scan under `npm run lint:guards`, in the style of
`check_attention_seam.py`, so function-local imports count. It also catches
attribute access through the package, such as `comicarr.updater.forceRescan`
after a bare `import comicarr`, which is how `app/downloads/service.py` reaches
`updater` and `search` today. A stale allowlist entry fails the guard.

Legacy modules importing each other, and legacy modules importing
`comicarr.app`, are not governed. Those edges disappear as bodies move.

Foundations is complete, for this rule, when the router allowlist is empty and
the Foundations legacy modules are imported from `comicarr/app/` only by their
seam modules. The roadmap sentence stays true as written and no longer passes
by accident.

## Consequences

- The milestone has a check that can fail, and it lives in CI.
- Seam modules become the only place where typed, modern code meets Mylar3
  calling conventions, which is where characterization tests belong.
- Deferred legacy is visible as a number that only goes down, without being
  promised for 1.0.
- A seam is not a rewrite. A module can sit behind its seam, unchanged, for a
  long time. That is accepted: the upgrade promise needs tests and clear
  edges more than it needs new code.
