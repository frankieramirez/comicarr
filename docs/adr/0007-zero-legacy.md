# ADR-0007: Zero legacy before 1.0

**Status:** Accepted
**Date:** 2026-11-16
**Amends:** [ADR-0005](./0005-legacy-module-boundary.md)
**Related:** [#1402](https://github.com/frankieramirez/comicarr/issues/1402),
[ADR-0006](./0006-deprecation-policy.md),
[Foundations plan](../architecture/foundations-plan.md),
[Vendor dependencies](../architecture/vendor-dependencies.md)

## Context

ADR-0005 put every Foundations legacy module behind one seam and baselined the
rest. It said a module "can sit behind its seam, unchanged, for a long time".
Foundations closed on that basis. On 2026-11-16, the package root still held:

- 57 modules besides `__init__.py`, 44.6k lines. 42 of them came from Mylar3,
  some renamed (`PostProcessor` to `postprocessor`, `Failed` to `failed`,
  `cmtagmylar` to `cmtag`, `librarysync` to `comicsync`). The other 16 were
  written for Comicarr but never moved under `app/`.
- `comicarr/_vendor/`, 15.7k lines of copied third-party code.
- `comicarr/downloaders/` and `comicarr/torrent/`.
- 608 reads of `comicarr.UPPER_CASE` module globals under `comicarr/app/`.

Comicarr 1.0 should not ship with half its backend in that shape.

## Decision

**End state.** `comicarr/` holds `__init__.py` and `app/`, and nothing else.
`comicarr/__init__.py` holds no module globals and no scheduler; runtime
state lives on `AppContext` ([runtime context](../architecture/runtime-context.md)).
`comicarr/_vendor/` does not exist. This is a 1.0 gate.

ADR-0005's "Deferred legacy" group stops being an accepted end state. Its
seams and allowlists stay as they are, and they empty as modules move.

**What moves, and what stays.** Behavior stays, quirks included, and so do
these compatibility contracts: INI keys, the database schema, the Mylar3-style
`/api?cmd=` subset Prowlarr uses, and Mylar3 migration. Only the code's
location and shape change. A move PR changes behavior only where its
description says so.

**Vendored libraries** are replaced by a maintained PyPI package where one
exists (qBittorrent, Deluge, Transmission, ComicTagger's `comicapi`).
Otherwise they are replaced by first-party code written from the protocol
(rTorrent XML-RPC, bencode), as #1229 and #1230 did for uTorrent and Mega.

**Dead integrations.** An integration whose remote site no longer works is a
broken feature, so ADR-0006's rule that nothing deprecated before 1.0 is
removed before 1.0 does not cover it. It is removed rather than ported. Its
removal still gets a deprecation registry entry, whose `in_use()` reads the
old setting, and a changeset that says why.

**Guard.** `scripts/check_root_modules.py`, under `npm run lint:guards`,
lists every module and package at the package root and every vendor root,
each with the issue that retires it. All three lists only shrink. A new entry
on disk fails, and so does a listed name that is gone.

**Order.** The order runs from least coupled to most, and the download path
goes last. Phases, sizes and tickets are on
[#1402](https://github.com/frankieramirez/comicarr/issues/1402):

| Phase | Scope | Issues |
|---|---|---|
| 0 | This ADR and the guard | #1403 |
| 1 | Dead integrations out; seedbox SFTP and scheduler wrappers in | #1404, #1405 |
| 2 | Comicarr-written root modules move | #1406 to #1408 |
| 3 | Vendored libraries replaced | #1409 to #1414 |
| 4 | Metadata and library helpers move | #1415 to #1419 |
| 5 | `updater`, `importer`, `comicsync` bodies | #1420 |
| 6 | Weekly pull and RSS bodies | #1421 |
| 7 | Search, file checker, post-processing, Usenet clients, GetComics | #1422 |
| 8 | Infrastructure modules and module globals | #1423 |

**Download path.** Phases 6 and 7 rewrite how issues are found, downloaded and
post-processed. They start only after the current fixes on that path are
verified on a real install. Each of their modules ships in its own release and
is verified end to end before the next one starts. Every body move is
preceded by characterization tests unless tests already pin it.

## Consequences

- The number of root modules, packages and vendor roots is printed by
  `npm run lint:guards` and only goes down.
- ADR-0005's Infrastructure group also moves (phase 8), so in the end no root
  module is "free to import".
- Swapping vendored libraries for packages adds runtime dependencies.
  `uv lock --check` and the wheel smoke build cover them.
- The work is large: about 43 pull requests. Phases 1 to 4 are independent
  and can run in parallel; phases 5 to 8 run in order.
