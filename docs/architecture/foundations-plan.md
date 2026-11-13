# Foundations plan

The settled approach for the Foundations milestone of the
[1.0 roadmap](https://github.com/frankieramirez/comicarr/issues/1184). Each
section records a decision made on the
[Foundations map](https://github.com/frankieramirez/comicarr/issues/1186) and
links the ticket that holds the reasoning. Budgets and scenario lists here are
targets to build against. Where a number was chosen without a measurement, the
section says so.

## 1. The boundary

Decision: [ADR-0005](../adr/0005-legacy-module-boundary.md)
([ticket](https://github.com/frankieramirez/comicarr/issues/1187)).

`scripts/check_legacy_seams.py` runs under `npm run lint:guards`. Under
`comicarr/app/`, a Foundations legacy module may be imported only by its seam
module. Routers import no root module outside Infrastructure. Everything else
is a shrink-only allowlist.

Router crossings to remove (all five):

| Router | Imports | Goes to |
|---|---|---|
| `app/series/router.py` | `mangasync`, `comicsync` | `app/series/service.py` |
| `app/opds/router.py` | `getimage`, `readinglist` | a new `app/opds/service.py` |
| `app/opds/router.py` | table objects from `tables` | allowed (Infrastructure), no change |

## 2. Seams and order

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1188).

| Order | Legacy module | Lines | Seam module | Shape |
|---|---|---|---|---|
| 1 | `notifiers.py` | 844 | `app/notifications/service.py` | Move. Root file deleted. |
| 2 | `weeklypull.py`, `weeklypullit.py` | 2,077 | `app/weekly/pull.py` | Seam first, bodies later. |
| 3 | `rsscheck.py`, `rsscheckit.py` | 1,821 | `app/search/rss.py` | Seam first, bodies later. |
| 4 | `updater.py` | 2,993 | three seams, below | Seam first, split by job. |
| 5 | `importer.py` | 3,040 | `app/series/add.py` | Seam first, bodies later. |

`updater.py` is three jobs in one file and gets three seams:

- `forceRescan` goes behind `app/series/rescan.py`.
  `app/imports/finalization.py`, `app/metadata/service.py`,
  `app/series/location.py` and `app/downloads/service.py` call the seam.
- `foundsearch` and `nzblog` (snatch bookkeeping) go behind
  `app/downloads/snatch_record.py`.
- `dbUpdate`, `watchlist_updater`, `totals` and the `*_update` pull helpers go
  behind `app/series/refresh.py`.

`importer.py` is Series add, not file import (see `CONTEXT.md`). Its seam
exposes `add_series`, `add_manga`, `refresh_series` and the three worker
queues. `app/imports/` does not own it.

Every module follows the same five steps:

1. Characterization tests for each function `comicarr/app/` calls today.
2. The seam module, with typed functions that delegate to the legacy module.
3. Every caller under `comicarr/app/` switches to the seam, and its allowlist
   entries are deleted in the same change.
4. Bodies move behind the seam one stage at a time, each with its tests.
5. The root module is deleted once nothing imports it.

Foundations requires steps 1 to 3 for all five modules, and steps 4 and 5 for
`notifiers.py`. Steps 4 and 5 for the other four happen as their tests allow
and are not a 1.0 gate. Legacy callers such as `search.py` and
`postprocessor.py` may call a seam; they are not required to.

The order runs smallest and least coupled first. `updater.py` and
`importer.py` call each other, so `updater` goes first: it has the most
callers under `comicarr/app/`, and its seams shrink what `importer` needs.

## 3. Post-processing end state

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1189).
Detail lives in the
[post-processing migration map](postprocessing-migration-map.md#end-state).

The facade is retired when the class `PostProcessor` and the module
`comicarr/process.py` no longer exist, and
`comicarr.app.downloads.postprocessing` is the only way to post-process.
What survives at the root is a plain folder-matching function with a typed
result, sitting behind that one seam.

## 4. Story-arc file handling

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1191).

Story arcs stay frozen. Their file handling splits in two.

**Ported** behind `app/storyarcs/` using `app/common/placement.py`:

- The secondary arc copy made after a library issue is post-processed
  (`COPY2ARCDIR`, `ARC_FILEOPS`, `ARC_FILEOPS_SOFTLINK_RELATIVE`).
- The reading-order filename prefix (`READ2FILENAME`).
- Arc folder naming and location (`STORYARCDIR`, `ARC_FOLDERFORMAT`,
  `STORYARC_LOCATION`), most of which is already in
  `app/storyarcs/service.py`.

These become one function, `copy_issue_to_arc`, called by the post-processing
pipeline with its own arc-scoped journal key, as the journal contract already
requires.

**Kept running, with a deprecation notice** under
[ADR-0006](../adr/0006-deprecation-policy.md):

- `storyarc-oneoff`: downloading an arc issue whose series is not in the
  library, straight into the arc folder. This is the "One-off STORYARC mode"
  in `nzb_or_oneoff_pp` and the arc-only branches of `search.py`.
- `storyarc-folder-match`: recognizing, during a manual folder scan, files
  that belong to a watched arc but to no watched series. This is about 600
  nested lines of `Process()`.

Both have the same replacement, which already exists: **Add missing series**
on the arc adds the series to the library and wants its arc issues, after
which search, download, import and the arc copy all take the normal path.

`in_use()` for `storyarc-oneoff` is true when any `storyarcs` row is `Wanted`
or `Snatched` with no library issue behind it. `storyarc-folder-match` is true
when `STORYARCDIR` is on and at least one arc is watched. Neither is removed
before 1.0. The deprecated code moves, unchanged, into the surviving
folder-matching function and the legacy search module; it is not rewritten.

## 5. First-class test targets

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1192).

A target is first-class when every scenario in its table has a unit test and
at least one integration test that runs through
`tests/integration/test_acquisition_pipeline.py`, from a search result to the
final library state. The tables live in `docs/testing/first-class-targets.md`,
one row per scenario with the test that proves it. A row with no test fails a
guard.

Manga scenarios: bare-number filenames under each `BareNumberMode`;
`v`-prefixed volumes; a volume covering its chapters without marking them
Have; blended-frontier search terms; MangaDex ledger sync healing an empty
ledger; MAL-sourced series; chapter placement and the duplicate guard in
post-processing; manga RSS; add-manga failure narration.

SABnzbd scenarios: handoff verified from SABnzbd's own response; completed
path with and without remote path mapping; missing completed path;
history entry removed before Comicarr reads it; failed download leading to a
retry; category routing; restart mid-download; wrong API key and unreachable
host classified as connection failures.

NZBGet scenarios: append handoff; history polling; destination directory
mapping; par, unpack and health failures mapped to Comicarr's failure
reasons; restart mid-download; authentication failure.

What backs the tests:

- Every pull request: in-process fakes fed by recorded responses, captured
  from real SABnzbd and NZBGet releases with secrets removed.
- Nightly, not gating pull requests: a contract job against real SABnzbd and
  NZBGet containers at pinned versions, with the queue paused. It checks that
  the recorded responses still match what the clients send.

Coverage target for `sabnzbd.py`, `nzbget.py`, `app/manga/` and the handoff,
completed-path and reconcile modules in `app/downloads/` is 80% of lines. The
current figure was not measured when this was written; the first task records
it, and it may not fall.

Any client the Clean slate integration check records as broken adds a
scenario here before it is fixed.

## 6. Upgrade test matrix

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1194).
Research: [Mylar3 fixture databases](../research/2026-11-13-mylar3-fixture-databases.md).

Comicarr adopted Alembic between v0.19.4 and v0.20.0, so the matrix is keyed
on schema revision, not version number.

| Row | Source | Schema at source | Path exercised |
|---|---|---|---|
| Fresh | empty database | none | base to head |
| Pre-Alembic | Comicarr v0.19.4 | no `alembic_version` | legacy adoption, then head |
| 0.2x | Comicarr v0.20.0 | `0003_library_chat` | upgrade |
| 0.3x | Comicarr v0.30.0 | `0007_interactive_search_progress` | upgrade |
| 0.4x | Comicarr v0.40.0 | `0009_chat_actions` | upgrade |
| 0.5x | Comicarr v0.50.7 | `0014_import_issue_readiness` | upgrade |
| Mylar3 old | Mylar3 v0.4.0 | no `mylar_info` | Mylar import |
| Mylar3 mid | Mylar3 v0.6.9 | `mylar_info` present | Mylar import |
| Mylar3 current | Mylar3 v0.8.3 | current | Mylar import |

Fixtures are synthetic and committed as SQL text, with the script that
rebuilds them. Each holds the same small library: a few comic series, one
manga series, issues in every status, an annual, a story arc, and snatched,
failed and weekly rows. No one's real library is used.

- Alembic-era rows are built by upgrading an empty database to the source
  revision and seeding it. That is only valid while landed migrations never
  change, so a guard pins the checksum of every landed revision file.
- The pre-Alembic row is generated once from the v0.19.4 tag.
- Mylar3 rows are generated from Mylar3's own `dbcheck()` at each tag.
- Each Comicarr row also carries a `config.ini` from that era.

Dialects: every row runs on SQLite on every pull request. Fresh, 0.2x, 0.5x
and Mylar3 current also run against PostgreSQL and MySQL in the existing
dialect job.

A row passes when all of these hold:

1. The upgrade finishes, the revision equals head, and `alembic check`
   reports no drift.
2. Row counts are preserved for every migrated table.
3. Seeded statuses, wanted flags and file locations are unchanged.
4. The app boots on the result with the maintenance gate released.
5. The series list and one series detail return the seeded data.
6. The era's `config.ini` loads, saves and reloads with no key lost.
7. Running the upgrade a second time changes nothing.

When a release changes the schema head, the release it supersedes becomes a
new row.

## 7. Benchmark and budget

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1195).

The library is generated from a fixed seed: 400 series (350 comic, 50 manga)
with a long tail, 20,000 issues, 15,000 zero-byte files with realistic names,
2,000 wanted issues, 50 story arcs and 5,000 history rows. SQLite is the
measured database.

| Operation | Ceiling |
|---|---|
| Library list API | 500 ms |
| Series detail API, 500-issue series | 500 ms |
| Wanted API | 500 ms |
| Dashboard API | 500 ms |
| Startup to ready | 15 s |
| Full library rescan | 5 min |
| Weekly pull match | 60 s |
| Release evaluation, 200 candidates for one issue | 2 s |
| Schema upgrade of the 0.2x row at this size | 60 s |

These ceilings were chosen as what an operator would tolerate, before any
measurement. The first benchmark task measures each one. A ceiling the
current code cannot meet is reported, not quietly raised.

Two checks, because wall-clock time on shared runners is noisy:

- Every pull request: a query-count budget per endpoint on a small library.
  Statement counts are deterministic, so this can gate merges, and it catches
  the usual cause of a slow page.
- Nightly, on release pull requests and on demand: the wall-clock run above,
  median of five after a warm-up. It fails only on a ceiling. A slowdown of
  more than 25% against the committed baseline file is reported as a warning.

The roadmap reconsiders Rust only if "the benchmark misses its budget". That
means a ceiling still missed after one focused optimization pass in Python.

## 8. Mega and uTorrent

Decision: [ticket](https://github.com/frankieramirez/comicarr/issues/1197).
Research: [replacements](../research/2026-11-13-mega-utorrent-replacements.md).
Detail lives in [vendor dependencies](vendor-dependencies.md#selected-direction).

Both features stay. Both vendored trees are replaced by small first-party
modules written from the public protocol descriptions, and the vendored
directories are deleted. No deprecation notice is needed.

## Continuous integration cost

- Every pull request: the seam guard, query-count budgets, and the SQLite
  upgrade matrix.
- Existing dialect job: four upgrade rows on PostgreSQL and MySQL.
- Nightly: the wall-clock benchmark and the SABnzbd and NZBGet contract job.
