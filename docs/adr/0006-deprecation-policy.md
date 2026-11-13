# ADR-0006: How a feature is deprecated

**Status:** Accepted
**Date:** 2026-11-13
**Related:** [Foundations plan](../architecture/foundations-plan.md),
[Roadmap: Comicarr 1.0.0](https://github.com/frankieramirez/comicarr/issues/1184)

## Context

The roadmap promises that working features stay, and that a feature is removed
only when it is broken beyond repair or cannot legally ship, and only after a
deprecation notice. Nothing defined what a notice is, where an operator sees
it, or how long it runs. Foundations is the first milestone that needs one, for
parts of story-arc file handling.

Operators of a self-hosted app rarely read release notes before upgrading. A
notice that lives only in a changelog reaches the people who needed it least.
A banner shown to everyone trains people to ignore banners.

## Decision

One shared mechanism, one registry.

**Registry.** To be built: `comicarr/app/system/deprecations.py` does not
exist yet. It will hold one entry per
deprecated feature: a stable id, a plain-language name, the release that
announced it, the earliest release that may remove it, what to use instead, a
docs link, and an `in_use()` predicate that reads configuration and the
database to say whether this install relies on the feature.

**Where a notice appears.**

1. A changeset in the release that announces it, so it shows in the release
   notes and in the in-app What's New.
2. A "Deprecations" page on comicarr.com, one section per registry entry.
3. Activity, Health view: a row per entry whose `in_use()` is true. Installs
   that do not use the feature see nothing.
4. One warning in the log at startup per entry in use. It is a warning, so it
   is visible at log level 0.

No new SSE event type is added. The Health view reads the registry through the
existing system endpoint.

**Window.**

- Nothing deprecated before 1.0.0 is removed before 1.0.0.
- After 1.0.0, a removal ships only in a major release, and at least 90 days
  and two minor releases after the notice.
- Exception: code that cannot legally ship. It is replaced where a replacement
  is practical. Where it is not, the feature is removed after a notice in at
  least one prior release, and the changeset says why.

**Deprecated is not frozen, and frozen is not deprecated.** Built-in AI and
story arcs as a whole are frozen: they keep working and get no new features,
and have no removal date. Only registry entries are deprecated.

## Consequences

- An operator learns about a deprecation in the app, only if it affects them.
- Every removal can be traced to a registry entry with dates.
- `in_use()` predicates are code that must be written and tested per entry.
- The existing `--quiet` and `--verbose` flag messages predate this policy.
  They move into the registry when the roadmap decides their fate.
