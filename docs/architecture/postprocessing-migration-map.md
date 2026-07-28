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
5. Cleanup and notification stages after durable completion.

Each stage must retain focused success, expected-failure, and
side-effect/idempotency coverage before the next extraction begins.
