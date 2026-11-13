# Post-processing migration map

This map records the compatibility contract for strangling
`comicarr.postprocessor.PostProcessor` one restart-safe stage at a time. The
legacy class remains the public facade until its callers and operational
recovery paths have migrated.

## Entry points and callers

| Entry point | First-party callers | Observable result |
|---|---|---|
| `PostProcessor.Process()` | `comicarr.process`, `comicarr.app.downloads.service`, tests | queue/API status, library file, issue state, notifications, cleanup |
| `PostProcessor.Process_next()` | `Process()` and focused tests | one resolved issue processed or an error/status string |
| `PostProcessor._process_manga()` | `Process()` and focused tests | chapter file moved, issue state updated, journal advanced |
| Manual folder processing | `comicarr.app.common.filesystem`, `FolderCheck` | eligible files processed without deleting the selected root |

## Inputs, outputs, and collaborators

- Inputs: download name/path, optional issue/comic identity, manual/API/DDL
  mode, queue, and an optional canonical recovery-journal release key.
- Outputs: historical status strings/dicts, queue messages, logs, notifications,
  and mutated instance fields used by later facade stages.
- Filesystem: archive inspection, metadata staging, rename, copy/move, duplicate
  handling, permissions, source/cache cleanup, and optional story-arc copies.
- Persistence: comics, issues, annuals, story arcs, snatched/nzblog rows, weekly
  and one-off history, plus the durable pipeline journal.
- External collaborators: downloader cleanup, metadata tools, pre/post scripts,
  image lookup, notifications, weekly/read-list projection, and runtime locks.
- Mutable runtime state: configuration, API lock, cache/program directories,
  current week/year, and user-visible global messages.

## Failure and recovery contract

The durable journal brackets irreversible work as
`post_processing -> moved -> post_processed`. A primary download must reuse the
canonical release key claimed by the queue consumer. A secondary story-arc copy
must derive its own arc-scoped key. Additive pre-commit journal failures are
logged and do not abort processing; the terminal transition joins the
`nzblog` deletion transaction and must propagate so both changes roll back.
Duplicate or regressing journal writes are monotonic no-ops. Manual processing
may clean the selected file in move mode but must not delete the selected root.

The durable journal/database facts are the recovery source of truth. Cleanup
and notification happen only after durable move/status work; retries detect
completed journal stages rather than repeating irreversible file work.

## Characterization evidence

- `test_pp_idempotency_guard.py`: atomic claim, retry, duplicate, manual, and
  canonical-key threading.
- `test_pp_complete_ordering.py`: move/cleanup ordering and transactional
  journal completion.
- `test_journal_pp_seam.py`: lifecycle, failure, story-arc, one-off, and manga
  paths.
- `test_manga_postprocessor.py`: manga filename, destination, and failure
  behavior.
- `test_placement.py`: the four file-operation modes against the four
  on-existing policies, plus the cross-filesystem and symlink fallbacks.
- `test_pp_placement_sites.py`: what each post-processor site hands the
  placement stage, and what it does when placement fails.
- `test_storyarc_placement.py`: the story-arc directory placement, which had
  no coverage of any kind before the stage existed.

## Extraction sequence

1. Journal transition stage with explicit context and an injectable journal
   adapter; `_journal_release_key()` and `_journal_pp()` remain facade methods.
2. Downloader input-resolution stage with explicit SAB/NZBGet configuration
   and an injectable path probe; `Process()` retains the historical queue-stop
   facade for missing SAB paths.
3. Filesystem operation/result stage, preserving the journal bracket and
   retry rule. **Landed as `comicarr/app/common/placement.py`, not as part of
   `app/downloads/postprocess_pipeline.py`.** Manual import finalization
   (`app/imports/finalization.py`) and story arcs (`app/storyarcs/service.py`)
   both place files, and neither may depend on the downloads package to do it,
   so the stage lives in `app/common/`. An architecture test
   (`tests/unit/test_placement_bracket_boundary.py`) asserts that
   `placement.py` imports nothing from `app/downloads/`, and that the stage is
   journal-blind: the caller owns the `post_processing`/`moved` bracket, which
   is why the bracket and retry rule are preserved by the callers rather than
   by the stage.
4. Database reconciliation stage using downloads/series query boundaries.
   **Landed as `PostProcessReconcileStage` in
   `app/downloads/postprocess_pipeline.py`.** It takes a
   `PostProcessPlacedItem` (series, issue, kind: issue, annual or manga, and
   the placed path) and writes through `app/series/queries.py` and
   `app/downloads/queries.py`. For comics and annuals it still runs
   `updater.totals` and `updater.foundsearch`, which the facade passes in so the
   stage imports no legacy module. The facade calls it where the
   inline writes sat, so its position against the journal is unchanged. The
   inherited `snatched` writes do not converge on their own (a NULL `Provider`
   never conflicts), so the stage skips an item whose row already records the
   placed file; a re-run after a restart writes nothing.
5. Cleanup and notification stages after durable completion.
   **Landed as `PostProcessCleanupStage` and `PostProcessNotifyStage` in
   `app/downloads/postprocess_pipeline.py`.** Cleanup takes a
   `PostProcessCleanupContext` and removes download files and folders only
   when `FILE_OPTS` is `move`, keeps the `mega` DDL folder, and empties the
   metadata cache folder only when tagging made one. A cleanup failure is
   narrated and logged, never raised, so it cannot touch the journal or the
   library. The facade still calls it where `tidyup` ran, after `moved`, so
   its order against the journal is unchanged. Notification goes through
   `app/notifications/service.py` and replaces `sendnotify`. It sends only
   when the caller's own `complete()` call wrote `post_processed`, so a
   re-run after a restart sends nothing. The cover reader is passed in by the
   facade, so the stage imports no legacy module.

Each stage must retain focused success, expected-failure, and
side-effect/idempotency coverage before the next extraction begins.

## End state

Decided on the [Foundations map](https://github.com/frankieramirez/comicarr/issues/1189).
"Retiring the facade" means all of the following are true:

- No class named `PostProcessor` exists, and `comicarr/process.py` is deleted.
- `comicarr.app.downloads.postprocessing` is the only entry point. Its `run`
  and `recover` return `PostProcessResult`; the queue messages with
  `mode: stop | fail | outside` are gone.
- The success, failed-download and "outside" retry loop that `process.py` runs
  today lives in `app/downloads/postprocessing.py`.
- What remains at the root is one module-level function in
  `comicarr/postprocessor.py` that matches the files in a folder and returns
  typed matches. A match is one of two kinds: a library issue, or an arc-only
  match for a file that belongs to a watched story arc and to no watched
  series. The pipeline places arc-only matches in the arc folder under an
  arc-scoped journal key, which keeps the deprecated `storyarc-folder-match`
  behavior working. The function moves no files, writes no rows and sends
  nothing. It is a Foundations legacy module with
  `app/downloads/postprocessing.py` as its only seam (ADR-0005).

The folder matcher stays at the root on purpose. It is about 2,900 lines of
inherited matching rules, and moving it under `comicarr/app/` would mean either
rewriting it or weakening the modern lint lane. Neither is worth doing before
1.0.

Stages 1 to 5 above have landed. The sequence continues:

4. Database reconciliation stage (landed, see above).
5. Cleanup and notification stages (landed, see above).
6. Per-item processing: `Process_next` and `_process_manga` become pipeline
   functions in `app/downloads/postprocess_pipeline.py`. The story-arc copy
   becomes `copy_issue_to_arc` in `app/storyarcs/`, called from here with its
   own arc-scoped key.
   `copy_issue_to_arc` (`app/storyarcs/arc_copy.py`) exists and is tested
   against the legacy arc placement; the legacy branch keeps running until
   this step switches the call.
7. Orchestration: the loop in `process.py` moves into
   `app/downloads/postprocessing.py` and `process.py` is deleted.
   `FailedProcessor` is called from there unchanged.
8. Folder matching: the body of `Process()` becomes the typed function
   described above, the class is deleted, and `FolderCheck` calls
   `postprocessing.run`.

The deprecated story-arc paths (`storyarc-oneoff`, `storyarc-folder-match`, see
the [Foundations plan](foundations-plan.md#4-story-arc-file-handling)) travel
inside the folder matcher and the one-off branch unchanged.

An architecture test proves the end state: it fails if `comicarr.postprocessor`
defines `PostProcessor`, if `comicarr/process.py` exists, or if anything under
`comicarr/` other than `app/downloads/postprocessing.py` imports
`comicarr.postprocessor`.

