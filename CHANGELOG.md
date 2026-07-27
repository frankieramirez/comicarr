# Changelog

## 0.20.0

### Minor Changes

- ea4b9e9: Add a dedicated saved Library Chat workspace with image attachments.
- ea4b9e9: Redesign the chat workspace and move its entry point out of the sidebar navigation. Chat now opens from a pinned "Ask Comicarr" launcher above the account menu (or ⌘⇧K), the workspace gains a grouped and searchable thread rail, a thread header with the answering model, and a calmer transcript, and the dashboard gets an ask bar plus a recent-chats list in place of the command hint card.

### Patch Changes

- ea4b9e9: Report a pull-list outage in plain language instead of dumping raw response
  headers into the log. When the pull-list host is unhealthy, Cloudflare answers
  on its behalf; only one of those replies was recognised, so the rest were
  logged as an unreadable header dump. All of them now explain that the source is
  temporarily unreachable and that the data shown may be stale, including how
  long upstream asked us to wait when it says so.

## 0.19.14

### Patch Changes

- 1f58860: Fix torrents snatched through qBittorrent, Transmission or uTorrent never being
  monitored. They were sent to the client successfully and then left in Snatched
  forever: nothing polled them, post-processing never ran, and a restart could not
  pick them back up. All five torrent clients are now polled through one code
  path, and a client being unreachable is kept distinct from a torrent genuinely
  being gone, so an outage no longer looks like a lost download.

  The auto-snatch worker now also starts for uTorrent, Transmission and
  qBittorrent — and for a local-post-processing-only setup — so the releases those
  clients queue are actually consumed instead of piling up unread. Torrents paused
  for the local post-processing copy are resumed even when the copy fails, the
  on-snatch script keeps firing for the three newly monitored clients, and every
  qBittorrent and uTorrent WebUI call now has a timeout so one hung client can no
  longer stall monitoring for every download.

- b5ec0d4: Fix saving settings failing whenever the RSS check interval or database update
  interval was changed. Both fields were sent under names the configuration did
  not recognise, which rolled back the entire save — every other setting changed
  at the same time was discarded without a visible error.

  Interval changes now also reach the running scheduler, which they never did, so
  a new search or RSS cadence takes effect without a restart. The database update
  interval is a real setting now and survives a restart instead of resetting to 24
  hours.

  Setting an interval to zero and then correcting it no longer leaves that
  background job switched off. Jobs paused deliberately — from the jobs page, or
  by turning RSS off — still stay paused. A database update interval below an
  hour is raised to an hour, the way the search and RSS intervals already were,
  so a negative value can no longer schedule the updater to run without pause.

- 332bab6: Fix MyAnimeList cover art being blocked by the browser security policy. The
  list of hosts trusted to serve cover images and the Content-Security-Policy
  that permits the browser to load them are now derived from one source, so they
  cannot drift apart again.
- 95fba47: Fix MyAnimeList manga series being treated as comics in two places: downloads
  were post-processed down the ComicVine path instead of the manga path, and the
  scheduled chapter check skipped them entirely, so they never picked up new
  chapters. MangaDex-added series now also record their MangaDex id, which the
  "already in library" check on search results depends on.
- 159f47e: Fix bulk actions on the Wanted and Upcoming lists doing nothing. Selecting rows
  never registered, so the action bar reported no selection and Search or Skip ran
  against an empty set.

  Clearing the selection, changing page, or a row disappearing now also unchecks
  the rows, so a later bulk action cannot skip issues you already cleared or that
  are no longer on screen. A bulk Skip or Mark Wanted that fails partway through
  now reports how many issues were applied and keeps only the failures selected,
  instead of reporting a total failure and retrying the ones that succeeded.

- 98cb480: Fix manga post-processing deleting the downloaded file when the file operation
  is set to hardlink or softlink. Both modes are meant to leave the download in
  place; the manga path moved it regardless, so the original was destroyed. It now
  uses the same mode-aware file placement as the rest of post-processing.

  Manga chapters that are already in the library also import correctly again. A
  repack, a manual re-run, or a post-crash retry now replaces the existing file
  under every file operation mode, instead of failing on the hardlink and softlink
  modes and leaving the chapter unimported.

- 117321b: Fix the version and update-available information never changing after startup.
  The scheduled version check wrote to a copy of the state that the API does not
  read, so a new release was never reported once the process was running. The
  branch name, which nothing ever set, is now reported too. A version check that
  fails to reach GitHub now keeps the last known result instead of reporting
  "up to date".

## 0.19.13

### Patch Changes

- 544eb20: Fix MAL manga series: rescan no longer crashes on chapters without dates, Refresh routes `mal-` IDs through the MAL importer instead of ComicVine, and MAL cover images now display (CSP allowlist plus local cover caching).

## 0.19.12

### Patch Changes

- d692778: Prevent manual imports from overwriting files created during finalization.

## 0.19.11

### Patch Changes

- 7d1c77a: Fix Library pagination controls resetting to the first page.

## 0.19.10

### Patch Changes

- ecf8b0c: Fix Library filters (empty dropdowns, double chevrons, broken search) and unify view toggle, search, and filter chips into one action bar.

## 0.19.9

### Patch Changes

- ad8a35a: Restore legacy MyAnimeList manga covers by normalizing provider image URLs to the MAL CDN.

## 0.19.8

### Patch Changes

- b56f7dc: Restore manga covers and chapter rows when adding MAL series, and fix library inbox matching so scanned manga files can be processed.

## 0.19.7

### Patch Changes

- fd4af61: Show live library, API, and download queue status in the application top bar.

## 0.19.6

### Patch Changes

- ac143fa: Improve the application error recovery screen with clearer guidance and reload controls.

## 0.19.5

### Patch Changes

- 3d626f0: Revoke all active UI sessions durably on logout while preserving the current session when secure key rotation fails.
- 2f59687: Persist additional Newznab and Torznab credentials transactionally with encrypted API keys and truthful save failures, while scrubbing provider secrets from diagnostics and retained config backups.
- 64aea8c: Keep clients, database connections, and runtime context open for terminal process exit when a scheduler job or worker remains alive after its bounded shutdown drain.
- 61249df: Harden bundled downloader integrations and package vendor clients under Comicarr's supported namespace.
- 5bd9fdf: Fix modern backend correctness hazards and enforce a strict lint ratchet for active application code.
- 0433c04: Reject empty, multiple, partial, unknown, and structurally spoofed Alembic revision states before schema mutation, and verify legacy adoption across every supported database dialect.

## 0.19.4

### Patch Changes

- 2e0b8da: Fix library scan reconciliation so detected files are recorded on their issues, and sort matched scan results before unmatched folders.

## 0.19.3

### Patch Changes

- 743a908: Fix library scans so existing comic series are reconciled instead of reported as unmatched.

## 0.19.2

### Patch Changes

- 59fd790: Make library scan progress and import confirmation visible across the Dashboard and Import pages.
- d5d338f: Keep search route loading visible, harden health diagnostics, and allow a single Wanted issue to be searched without forcing the backlog.
- 0f19c09: Reconcile scanned comic folders with existing series and show the outcome in Import.

## 0.19.1

### Patch Changes

- 5816867: Prioritize operator-requested searches over restart recovery, ensure configured Torznab providers are searched, and expose safe provider-attempt diagnostics.

## 0.19.0

### Minor Changes

- b95001e: Restore reliable comic acquisition and recovery: durable search/refresh workers, reservation-before-submit handoffs, acquisition run ledgers, route health, evidence-driven repair, and server-side Search all missing. Add an operator recovery runbook; the current canary permit authorizes or cancels one exact handoff, while a future persisted-candidate executor is required before it can prove a full production canary.

## 0.18.9

### Patch Changes

- 7157998: Restore current operational dashboard data and add a safe, observable weekly release refresh.

## 0.18.8

### Patch Changes

- 476e5bd: Fix scheduled updates for manga libraries, rebuild Activity with searchable sortable paginated tables, show accurate live queue counts and relative activity times, and add a dashboard library-scan action.

## 0.18.7

### Patch Changes

- 860faea: Show the real app version in the sidebar, login screen, and onboarding welcome step instead of a hardcoded 0.15 / v0.15.1 badge.

## 0.18.6

### Patch Changes

- 0450b4a: Keep server-sent event streams responsive under burst traffic by replacing stale queued updates without emitting event-loop errors.
- 2de9e62: Deduplicate legacy database rows across migration batches and report target constraint conflicts as failed migrations.
- a9df84e: Fix AI library completion filters so percentage queries work on SQLite and preserve inclusive bounds, ordering, and limits.
- 8f8fd4e: Validate and persist reconstructable direct-download jobs, keep malformed jobs from stopping the worker, and hold the GetComics download lock through archive publication.
- cd53fb6: Keep provider downloads inside Comicarr's configured directories, publish completed files atomically, and reject remote ZIP archives that would expand beyond safe resource limits.
- d8a05f1: Validate series directories against configured library roots and preserve database records when directory removal fails.
- e1cbccf: Repair atomic upserts on legacy SQLite databases with an isolated safety snapshot and transactional unique indexes that preserve historical null or empty-key rows.
- ee651ca: Persist config changes through a shared transaction boundary, encrypt secrets before disk writes, preserve private file permissions, and report storage failures without committing runtime config state.
- 7298807: Stop logging 32P runtime credentials and scrub previously written credential lines from support carepackages.

## 0.18.5

### Patch Changes

- 027d784: Harden artwork cache paths and cover image fetches against path traversal and SSRF (allowlisted hosts, no redirects, size and content-type caps).
- 37ff1f7: Fix Discord and sibling webhook notifiers so successful deliveries are reported correctly and network errors return false instead of raising.

## 0.18.4

### Patch Changes

- 2ef88d3: Fix API key regeneration persistence, secret redaction handling, dependency floors, and E2E regression coverage.

## 0.18.3

### Patch Changes

- 2a6b0db: Fix manual import matching so selected files are finalized before pending import rows are marked imported.

## 0.18.2

### Patch Changes

- b29dad4: Fix manual import matching so selected manga imports are finalized and stale pending import records can be ignored or deleted from the review table.

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.18.1](https://github.com/frankieramirez/comicarr/compare/v0.18.0...v0.18.1) (2026-06-09)

### Bug Fixes

- address open GitHub issues [#149](https://github.com/frankieramirez/comicarr/issues/149), [#150](https://github.com/frankieramirez/comicarr/issues/150), [#158](https://github.com/frankieramirez/comicarr/issues/158), [#159](https://github.com/frankieramirez/comicarr/issues/159) ([#161](https://github.com/frankieramirez/comicarr/issues/161)) ([b4bbc97](https://github.com/frankieramirez/comicarr/commit/b4bbc978e5907466ccef17572fb3609baea402ff))

## [0.18.0](https://github.com/frankieramirez/comicarr/compare/v0.17.1...v0.18.0) (2026-05-17)

### Features

- Restart-durable download/post-process pipeline ([#156](https://github.com/frankieramirez/comicarr/issues/156)) ([49b569f](https://github.com/frankieramirez/comicarr/commit/49b569fe37970862c61408836bc43dce2c0456fd))

## [0.17.1](https://github.com/frankieramirez/comicarr/compare/v0.17.0...v0.17.1) (2026-04-20)

### Bug Fixes

- Render issue rows on series detail page ([#141](https://github.com/frankieramirez/comicarr/issues/141)) ([ba24726](https://github.com/frankieramirez/comicarr/commit/ba247265a9a4f7dad0a8767be56201b3646aabd0))

## [0.17.0](https://github.com/frankieramirez/comicarr/compare/v0.16.0...v0.17.0) (2026-04-19)

### Features

- Align library, releases, and wanted tables with redesign ([#139](https://github.com/frankieramirez/comicarr/issues/139)) ([4993293](https://github.com/frankieramirez/comicarr/commit/4993293c9956277704f17bdd2a4160eb6d4d94eb))

## [0.16.0](https://github.com/frankieramirez/comicarr/compare/v0.15.1...v0.16.0) (2026-04-19)

### Features

- Major frontend redesign ([#137](https://github.com/frankieramirez/comicarr/issues/137)) ([255438c](https://github.com/frankieramirez/comicarr/commit/255438c9794787cfbd260c167d4a4c3398b9181c))

## [0.15.1](https://github.com/frankieramirez/comicarr/compare/v0.15.0...v0.15.1) (2026-04-15)

### Bug Fixes

- Resolve library pagination not responding to clicks ([#135](https://github.com/frankieramirez/comicarr/issues/135)) ([db39a8b](https://github.com/frankieramirez/comicarr/commit/db39a8ba8cb30a0486fb9c7080540efd4b3a3fcd))

## [0.15.0](https://github.com/frankieramirez/comicarr/compare/v0.14.0...v0.15.0) (2026-04-14)

### Features

- Add list/grid view toggle to library page ([#133](https://github.com/frankieramirez/comicarr/issues/133)) ([7c76e2b](https://github.com/frankieramirez/comicarr/commit/7c76e2bc3cfbbd2747c336b97a351872657a3e99))

## [0.14.0](https://github.com/frankieramirez/comicarr/compare/v0.13.0...v0.14.0) (2026-04-14)

### Features

- Restructure information architecture for modern UX ([#131](https://github.com/frankieramirez/comicarr/issues/131)) ([896c788](https://github.com/frankieramirez/comicarr/commit/896c788107d4e48742e5253d9eb6398c233db79e))

## [0.13.0](https://github.com/frankieramirez/comicarr/compare/v0.12.2...v0.13.0) (2026-04-14)

### Features

- Persist Series page table state in URL via nuqs ([#129](https://github.com/frankieramirez/comicarr/issues/129)) ([80c1777](https://github.com/frankieramirez/comicarr/commit/80c17773bc8e593076fc0df6863f61b91de6cc07))

## [0.12.2](https://github.com/frankieramirez/comicarr/compare/v0.12.1...v0.12.2) (2026-04-07)

### Code Refactoring

- Redesign Import Management into Library Scan + Import Inbox ([#117](https://github.com/frankieramirez/comicarr/issues/117)) ([a2533ef](https://github.com/frankieramirez/comicarr/commit/a2533efb15e19cf8d744e06cdfbb27cd4cd99696))

## [0.12.1](https://github.com/frankieramirez/comicarr/compare/v0.12.0...v0.12.1) (2026-04-07)

### Bug Fixes

- Manga import chapter population, cover caching, and series bulk actions ([#115](https://github.com/frankieramirez/comicarr/issues/115)) ([39636de](https://github.com/frankieramirez/comicarr/commit/39636de83ded726118b3a65fc8527959624ce895))

## [0.12.0](https://github.com/frankieramirez/comicarr/compare/v0.11.1...v0.12.0) (2026-04-07)

### Features

- Add MyAnimeList as primary manga metadata provider ([#113](https://github.com/frankieramirez/comicarr/issues/113)) ([5a68333](https://github.com/frankieramirez/comicarr/commit/5a68333540a8d13a5339440f38aaba9819705882))

## [0.11.1](https://github.com/frankieramirez/comicarr/compare/v0.11.0...v0.11.1) (2026-04-07)

### Bug Fixes

- Make Import page scan cards symmetrical (Comic + Manga side-by-side) ([#111](https://github.com/frankieramirez/comicarr/issues/111)) ([4fedd0b](https://github.com/frankieramirez/comicarr/commit/4fedd0b2c3c720fe7038aec2cb3d5e3ff0e4b586))

## [0.11.0](https://github.com/frankieramirez/comicarr/compare/v0.10.4...v0.11.0) (2026-04-06)

### Features

- Elevate manga to first-class citizen with full parity ([#110](https://github.com/frankieramirez/comicarr/issues/110)) ([ec68bbb](https://github.com/frankieramirez/comicarr/commit/ec68bbb9e1678e2d87d13d6ba1df4293d65035f1))

### Bug Fixes

- Add error fallback for broken images in Recent Downloads ([#108](https://github.com/frankieramirez/comicarr/issues/108)) ([8c63f74](https://github.com/frankieramirez/comicarr/commit/8c63f747a118bb921c0e7d41dd0243af2716497b))

## [0.10.4](https://github.com/frankieramirez/comicarr/compare/v0.10.3...v0.10.4) (2026-04-06)

### Bug Fixes

- Resolve broken dashboard images and AI banner issues ([#106](https://github.com/frankieramirez/comicarr/issues/106)) ([8010da1](https://github.com/frankieramirez/comicarr/commit/8010da1524f9722fac65466d655cc3f19e128ee4))

## [0.10.3](https://github.com/frankieramirez/comicarr/compare/v0.10.2...v0.10.3) (2026-04-06)

### Bug Fixes

- Clean up 9 frontend ESLint warnings for zero-warning baseline ([#96](https://github.com/frankieramirez/comicarr/issues/96)) ([a547170](https://github.com/frankieramirez/comicarr/commit/a54717026c83e2f6689d790f122d6f157be99386))

## [0.10.2](https://github.com/frankieramirez/comicarr/compare/v0.10.1...v0.10.2) (2026-04-06)

### Bug Fixes

- Resolve startup errors in git detection and job scheduler ([#103](https://github.com/frankieramirez/comicarr/issues/103)) ([c5dcb6b](https://github.com/frankieramirez/comicarr/commit/c5dcb6b3e9d27eff5bd4808c4795ec4ce582fd8e))

## [0.10.1](https://github.com/frankieramirez/comicarr/compare/v0.10.0...v0.10.1) (2026-04-06)

### Bug Fixes

- Replace MySQL-only right/concat with SQLite-compatible substr ([#101](https://github.com/frankieramirez/comicarr/issues/101)) ([4cd03a5](https://github.com/frankieramirez/comicarr/commit/4cd03a5c55541aaa5ce841595c43ab96caacec04))

## [0.10.0](https://github.com/frankieramirez/comicarr/compare/v0.9.8...v0.10.0) (2026-04-06)

### Features

- BYOK AI Suite — LLM-Powered Intelligence Layer ([#99](https://github.com/frankieramirez/comicarr/issues/99)) ([1e8e501](https://github.com/frankieramirez/comicarr/commit/1e8e5018b9e0509ca87c7f73f11a4cf1f3852253))

## [0.9.8](https://github.com/frankieramirez/comicarr/compare/v0.9.7...v0.9.8) (2026-04-05)

### Bug Fixes

- Remove deprecated Vitest 4 poolOptions config ([#95](https://github.com/frankieramirez/comicarr/issues/95)) ([ed5b56d](https://github.com/frankieramirez/comicarr/commit/ed5b56dd73baa0ee36ab524e155663e81d59da65))

## [0.9.7](https://github.com/frankieramirez/comicarr/compare/v0.9.6...v0.9.7) (2026-03-25)

### Bug Fixes

- Resolve settings page showing empty pre-filled values ([#84](https://github.com/frankieramirez/comicarr/issues/84)) ([cabc4bc](https://github.com/frankieramirez/comicarr/commit/cabc4bc75b9a75dbb925b393732c6b20bf614f9b))

## [0.9.6](https://github.com/frankieramirez/comicarr/compare/v0.9.5...v0.9.6) (2026-03-25)

### Bug Fixes

- Constrain search result hover cards to prevent viewport overflow ([#81](https://github.com/frankieramirez/comicarr/issues/81)) ([b8e0362](https://github.com/frankieramirez/comicarr/commit/b8e036211671da2ddf763bf83e17f66fed11e45a))

## [0.9.5](https://github.com/frankieramirez/comicarr/compare/v0.9.4...v0.9.5) (2026-03-25)

### Bug Fixes

- Skip unexpanded git export-subst placeholders in version display ([#79](https://github.com/frankieramirez/comicarr/issues/79)) ([4322e01](https://github.com/frankieramirez/comicarr/commit/4322e0107823d1e8edf578d922a1b0b2d7267ee2))

## [0.9.4](https://github.com/frankieramirez/comicarr/compare/v0.9.3...v0.9.4) (2026-03-25)

### Bug Fixes

- Resolve asyncio.get_event_loop() errors in all system router endpoints ([#77](https://github.com/frankieramirez/comicarr/issues/77)) ([5965606](https://github.com/frankieramirez/comicarr/commit/596560658d09fdb6d97237a2edbe82eeded4f2d2))

## [0.9.3](https://github.com/frankieramirez/comicarr/compare/v0.9.2...v0.9.3) (2026-03-25)

### Bug Fixes

- Resolve UnboundLocalError in job_management and KeyError in DDL health check ([#75](https://github.com/frankieramirez/comicarr/issues/75)) ([a649d50](https://github.com/frankieramirez/comicarr/commit/a649d509452dae57c16f995a051a5bd82e92e97d))

## [0.9.2](https://github.com/frankieramirez/comicarr/compare/v0.9.1...v0.9.2) (2026-03-25)

### Bug Fixes

- Remove leftover CherryPy dependencies blocking Docker startup ([#73](https://github.com/frankieramirez/comicarr/issues/73)) ([c51526e](https://github.com/frankieramirez/comicarr/commit/c51526e30fabeaf9482e22b957e5586f92aff224))

## [0.9.1](https://github.com/frankieramirez/comicarr/compare/v0.9.0...v0.9.1) (2026-03-25)

### Bug Fixes

- Include version in settings page config response ([#69](https://github.com/frankieramirez/comicarr/issues/69)) ([f59c89b](https://github.com/frankieramirez/comicarr/commit/f59c89b3d2bce81df233e989708f9543ad5f79b4))

## [0.9.0](https://github.com/frankieramirez/comicarr/compare/v0.8.0...v0.9.0) (2026-03-25)

### Features

- FastAPI migration with vertical domain decomposition ([07f79ad](https://github.com/frankieramirez/comicarr/commit/07f79ad07158f19a9b9f1bf035dc327381ce04ad))

## [0.8.0](https://github.com/frankieramirez/comicarr/compare/v0.7.0...v0.8.0) (2026-03-24)

### Features

- Enrich search results with additional API metadata ([#65](https://github.com/frankieramirez/comicarr/issues/65)) ([e7fd739](https://github.com/frankieramirez/comicarr/commit/e7fd7395160aebc24a0abd098daf42fe43a574ff))

## [0.7.0](https://github.com/frankieramirez/comicarr/compare/v0.6.0...v0.7.0) (2026-03-24)

### Features

- Add content source toggles for comic-only or manga-only experience ([#63](https://github.com/frankieramirez/comicarr/issues/63)) ([d214139](https://github.com/frankieramirez/comicarr/commit/d2141394ea41689270aa8696a59a399a1f859320))

## [0.6.0](https://github.com/frankieramirez/comicarr/compare/v0.5.0...v0.6.0) (2026-03-24)

### Features

- Migrate all tables to DataTable component with OpenStatus data-table ([#62](https://github.com/frankieramirez/comicarr/issues/62)) ([f92ee50](https://github.com/frankieramirez/comicarr/commit/f92ee50f60e70f4f1591794d960462b5b26d8adb))

### Bug Fixes

- resolve weekly table KeyError and add version display to Settings ([#60](https://github.com/frankieramirez/comicarr/issues/60)) ([5662361](https://github.com/frankieramirez/comicarr/commit/5662361ac0f32aea98ed9c6660e7be1f92d0e9ca))

## [0.5.0](https://github.com/frankieramirez/comicarr/compare/v0.4.4...v0.5.0) (2026-03-24)

### Features

- Build complete Story Arcs frontend and fix backend gaps ([#58](https://github.com/frankieramirez/comicarr/issues/58)) ([6868e74](https://github.com/frankieramirez/comicarr/commit/6868e74b705019697df91c236c0e057850bae90c))

## [0.4.4](https://github.com/frankieramirez/comicarr/compare/v0.4.3...v0.4.4) (2026-03-24)

### Bug Fixes

- replace broken db.rawdb calls with direct raw_select_all/raw_select_one ([#56](https://github.com/frankieramirez/comicarr/issues/56)) ([d1a7429](https://github.com/frankieramirez/comicarr/commit/d1a7429b9c6d17e73091bf94014da37d7003a704))

## [0.4.3](https://github.com/frankieramirez/comicarr/compare/v0.4.2...v0.4.3) (2026-03-23)

### Bug Fixes

- dark mode issues in settings and remove placeholder UI ([#54](https://github.com/frankieramirez/comicarr/issues/54)) ([069f57e](https://github.com/frankieramirez/comicarr/commit/069f57e4955c28899d909a4957a3482f9612781e))

## [0.4.2](https://github.com/frankieramirez/comicarr/compare/v0.4.1...v0.4.2) (2026-03-23)

### Bug Fixes

- run uv lock in Docker build to handle version bumps ([27b610d](https://github.com/frankieramirez/comicarr/commit/27b610d2ca42316577ccc8ba1b2b67bfee44ad1b))

## [0.4.1](https://github.com/frankieramirez/comicarr/compare/v0.4.0...v0.4.1) (2026-03-23)

### Bug Fixes

- sync uv.lock and prevent stale lockfile on release ([#51](https://github.com/frankieramirez/comicarr/issues/51)) ([0efcc3e](https://github.com/frankieramirez/comicarr/commit/0efcc3e3c2d2bbb95c42ab24a47bfa8a6ec8457d))

## [0.4.0](https://github.com/frankieramirez/comicarr/compare/v0.3.0...v0.4.0) (2026-03-23)

### Features

- Automate releases with release-please ([#47](https://github.com/frankieramirez/comicarr/issues/47)) ([12adb79](https://github.com/frankieramirez/comicarr/commit/12adb79b4347b59f7bd583fb7b6fb11ff47ed005))

### Bug Fixes

- Metron search missing cover images + API hardening ([#48](https://github.com/frankieramirez/comicarr/issues/48)) ([639c9d3](https://github.com/frankieramirez/comicarr/commit/639c9d39a394fbbdebf4c7c3f0d1d6bb1195c4cd))

## [0.1.0] - 2026-03-21

### Added

- Modern React 19 frontend with Tailwind CSS 4, replacing the legacy jQuery/Bootstrap UI
- Real-time updates via Server-Sent Events (SSE)
- Dark and light theme support with system preference detection
- Smart search with parallel pagination and result caching
- Server-side search sorting with mode-aware controls
- Weekly pull list tracking up to 4 weeks ahead
- Story arc management with lazy loading
- Direct download support for Mega, MediaFire, and Pixeldrain
- Multi-stage Docker build with non-root user and dynamic PUID/PGID support
- GitHub Actions CI/CD: linting, testing (Python 3.10-3.12 matrix), and automated releases to GHCR
- Multi-architecture Docker images (amd64, arm64)
- Comprehensive test suite with unit, integration, and E2E tests

### Changed

- Rebranded from Mylar3 to Comicarr throughout the codebase
- Switched to `uv` for Python dependency management
- Upgraded to Python 3.12 runtime in Docker
- Upgraded to Node.js 22 for frontend builds
- Improved search performance with parallel provider queries
- Enhanced API key and credential handling — secrets are redacted in logs and CarePackage exports

### Fixed

- API key plaintext logging vulnerability
- SABnzbd integration regression
- ComicVine result display when MangaDex is disabled
- Various startup and configuration issues

### Attribution

Comicarr is built on the foundation of [Mylar3](https://github.com/mylar3/mylar3), created by the Mylar3 team. The original project provided the robust backend for comic management, downloading, and post-processing.
