# State machines

Comicarr has about 70 state machines. Most are implicit: a text column, a
module global, or a few `useState` calls whose legal values exist only as
string literals scattered across the code that reads and writes them. This
document records the decision that makes them explicit, the machines covered
so far, and the inventory of the rest.

## 1. Decision

A state machine whose states cross a boundary is declared once, in
`comicarr/app/common/state_machines.py`. "Crosses a boundary" means the state
is stored in a column another module reads, sent over the HTTP API, or
published in an MCP tool schema.

Each entry gives the states as stored, the column, the owning module, how a
move is enforced today, named subsets (terminal, in flight, operator
settable), and the legal transitions where the owner enforces an edge list.

Three gates hold the registry to the rest of the code. All three run in CI.

| Gate | What it catches |
|---|---|
| `tests/unit/test_state_machine_registry.py` | The registry disagrees with the enum, constant or MCP schema that enforces a machine. |
| `python3 scripts/generate_state_types.py --check` (in `npm run lint`) | `frontend/src/types/states.generated.ts` is stale. |
| `npm --prefix frontend run typecheck` (CI frontend jobs) | An issue or series state has no translated label and tone in `frontend/src/lib/statusTone.ts`. |

The registry is not consulted at request time. No write is rejected because
of it, and an unknown state is stored and rendered as before. This follows
ADR-0001: fail open at runtime, gate in CI. A registry that rejected writes
would strand the first writer nobody registered.

The registry does not replace the enums in `acquisition/models.py` or the
constants in `downloads/journal.py`. Those stay where the enforcement is. The
registry is a stdlib-only leaf so the generator can load it on a bare
interpreter, which means it cannot import them; the pin test is the link.

## 2. Changing a state

1. Change the enforcing code: the enum member, the constant, or the writer.
2. Change the entry in `state_machines.py` to match. The pin test fails until
   both agree.
3. Run `npm run lint:fix:generated`. The pre-commit hook does this when the
   registry changes.
4. Fix what `tsc` reports. A new issue or series state needs a tone and a
   Lingui label in `statusTone.ts`.
5. If the state is in an MCP schema, the tool snapshot in
   `tests/contract/mcp_tools.json` changes too. That is a 1.0 contract change.

Stored and wire spellings never change case. `Downloaded` (issue status),
`downloaded` (fulfillment and journal stage) and `Post-Processed` (snatch log)
belong to three different machines.

## 3. Registering a machine

Register a machine when it has an enforcing definition to pin to: an enum, a
constant set, a rank table, or a schema. A machine that exists only as string
literals needs that definition first, in its owning module. Registering it
without one adds a copy that nothing checks.

Add the entry, add a pin test, and set `ts_type` if the frontend reads the
state. Then replace the frontend's hand-written union with the generated one.

## 4. Registered machines

| Machine | Stored in | Enforced by | Frontend type |
|---|---|---|---|
| `series_status` | `comics.Status` | nothing | `SeriesStatus` |
| `issue_status` | `issues.Status`, `annuals.Status` | nothing | `IssueStatus`, `SettableIssueStatus` |
| `acquisition_intent` | `issues.AcquisitionIntent` | enum coercion | `AcquisitionIntent` |
| `fulfillment` | computed | projection | `FulfillmentState` |
| `issue_display_state` | computed | projection | `IssueDisplayState` |
| `search_run_dispatch_state` | `acquisition_runs.dispatch_state` | enum coercion, claim compare-and-swap | `SearchRunDispatchState` |
| `search_run_completion_state` | `acquisition_runs.completion_state` | projection from item counts | `SearchRunCompletionState` |
| `search_run_item_state` | `acquisition_run_items.state` | conditional update, edge list | `SearchRunItemState` |
| `journal_stage` | `pipeline_journal.stage` | monotonic rank compare-and-swap | none |
| `journal_resolution` | `pipeline_journal.status` | conditional update | none |
| `activity_event_status` | `activity_events.status` | validated on insert | `EventStatus` |

`series_status` and `issue_status` are the two with no enforcement at all.
They are registered because every screen and both MCP status tools read them.

## 5. Inventory of unregistered machines

Found by a read-through of the whole codebase on 2026-11-16. Each line names
the state holder and the value set. The "Lead" column records a suspected
defect. A lead marked *read* was checked against the source and not
reproduced; an unmarked lead comes from the sweep alone. Treat every lead as a
place to look, not as a confirmed bug.

### 5.1 Persisted, legacy tables

| Machine | States | Lead |
|---|---|---|
| `storyarcs.Status` | Wanted, Skipped, Read, Added, Snatched, Downloaded, Archived, NULL | Mixes issue status with reading-list values. Frontend `ArcIssueStatus` lacks Snatched. Frozen feature. |
| `readlist.Status` | Added, Read | None. |
| `weekly.STATUS` | Wanted, Skipped, Snatched, Downloaded, Incomplete, Mismatched, copied issue status | Incomplete and Mismatched have no reader. |
| `snatched.Status` | Snatched, Downloaded, Post-Processed | An append-only log, not a mutable state: Status is part of the key. |
| `failed.Status` | Failed | Readers branch on Good, Retry and Retrysame, which nothing writes. |
| `ddl_info.status` | Queued, Downloading, Completed, Failed, Manual Review | Compare-and-swap claims sit beside unguarded upserts on the same column. |
| `importresults.Status` | Not Imported, Possible Duplicate, Imported, NULL | Possible Duplicate has no reader. Readers disagree on case sensitivity. |
| `jobhistory.status` | Waiting, Running, Paused, Error, Queued, Interrupted; also `DispatchState` values and worker heartbeat words | Three vocabularies share one column. See 5.3, scheduler. |
| `upcoming.Status`, `oneoffhistory.Status`, `provider_searches.active`, `nzblog` row presence | small | None. |

The two registered legacy machines carry the most history:

- `issue_status` is written from about 60 sites. The Wanted-or-Skipped
  decision for a new issue is copied about seven times across the modules split out of
  the old `importer.py` and `updater.py`. In the weekly upcoming update, any status outside five
  named ones is rewritten to Skipped, which includes Ignored
  (`watchlist_match.upcoming_update`, *read*).
- `series_status`: Error is written by `snatch_record.no_searchresults` and read back as
  Loading. The Continuing-or-Ended rule is derived in three places. The
  series header shows Continuing for a series in Loading or Error
  (`frontend/src/pages/SeriesDetailPage.tsx:837-846`, *read*).

### 5.2 Persisted, modern tables

| Machine | States | Lead |
|---|---|---|
| `ai_chat_messages.status` | streaming, complete, error, cancelled | No state predicate on update. Frozen feature. |
| chat action status (JSON in `ai_chat_messages.action`) | pending, processing, partial, confirmed, dismissed, error | An action left in processing after a crash has no recovery path. Frozen feature. |
| `acquisition_search_previews.state` | previewed, accepted; expiry by `expires_at` | None. Compare-and-swap. |
| `interactive_search_sessions.state` | queued, running, complete, failed, ready | `update_search_progress` guards on expiry only and may overwrite complete. Frontend union lacks ready. |
| `interactive_search_candidates.state` | available, unavailable, submitting, submitted, failed, manual_review | None. Compare-and-swap with a lease on `updated_at`. |
| `manga_volumes.Status` | Snatched, Downloaded; Archived read only | None. |
| `acquisition_reconciliation.state` | ready, migrating, pending_preview, failed | Value check only. |
| `acquisition_canary_permits.state` and `.outcome` | waiting_for_drain, authorized, claimed, completed, cancelled, manual_review | Outcome is free text. |
| `acquisition_maintenance.active`, `acquisition_maintenance_leases.released_at` | flag plus epoch; NULL means active | None. Compare-and-swap. |
| `acquisition_repair_runs.state` | previewed, confirmed, waiting_for_drain, applying, canary_complete, needs_review, completed, rollback_waiting_for_drain, rolling_back, rolled_back, rollback_needs_review | Apply and rollback check the state in Python, then update without a state predicate. Frontend terminal set names failed and conflict, which are never written. |
| `acquisition_repair_items.apply_state`, `.rollback_state` | pending, applied or rolled_back, conflict | Read then update with no row lock. |
| `acquisition_repair_series.state`, `acquisition_repair_canaries.state` | eight and three states | Unconditional updates. |

Leads on the registered modern machines:

- `journal_stage`: retention never purges cancelled rows
  (`acquisition/retention.py:148-153`, *read*). Ranks are copied as the literals 20
  and 30 in `activity/producers.py`.
- `search_run_item_state`: `acquisition/maintenance.py:281-290` sets cancelled
  with its own literals, outside `RunLedger`. `series/wanted_groups.py:29-30`
  keeps its own live and trouble sets; sending cancelled to "queued" there is
  deliberate (*read*).
- `activity_event_status`: an unknown status is `action_required` on the
  backend and `normal` in the frontend `severityOf` (*read*).
- `search_run_dispatch_state`: no writer of missed or max_instances was
  found. No frontend code reads the dispatch state, so a run whose dispatch
  failed keeps polling.

### 5.3 In memory

| Machine | Holder | Lead |
|---|---|---|
| Process lifecycle | `comicarr.SIGNAL`, `started`, `_INITIALIZED`, `ctx.disposed` | Nothing writes the `update` signal. |
| Lifespan drain | `app/main.py` lifespan | None. |
| Scheduler job status | `*_STATUS` globals, `jobhistory.status` | Startup routes rows to globals by substring of the job name. Some paths never clear Running (`rsscheckit.py`, `versioncheckit.py`, `folder_monitor.py`). |
| Acquisition worker gate | `ACQUISITION_*` globals | `refresh_runtime_state` may clear a block that `start()` set after skipping the workers. |
| Setup gate | `ctx.setup_token` plus stored credentials | Two sources of truth. |
| Login lockout, password format | `security.py` limiter | MCP key failures share the UI login limiter. |
| Post-processing result | `postprocessing.py` | Lock contention, journal unavailable and maintenance all report "busy"; callers match on detail text. |
| Recovery probe verdict | `recovery_classify.py` | Any raw probe state that matches no branch falls through to GONE, which marks the row failed (`:704-756`, *read*). Whether an unknown raw state can arrive was not shown. |
| SABnzbd and NZBGet status mapping | `sabnzbd.py`, `nzbget.py` | If-chains over client strings with an else branch. |
| DDL queue membership | `DDL_LOCK`, `DDL_QUEUED` | Membership is removed at a dozen sites, not in one `finally`. |
| Search lock | `SEARCHLOCK` | The queueing branch releases the lock without acquiring it (`search.py:2777-2780`, *read*). |
| Provider blocklist, route readiness | `PROVIDER_BLOCKLIST`, `search/health.py` | A list is mutated while iterated. |
| Mylar3 migration progress | `MIGRATION_*` globals | The in-progress flag is set only after the quiescence wait. |
| Library scans | `importinbox.py`, `app/series/comicsync.py`, `mangasync.py` | One machine copied three times. |
| Import finalization phase | `imports/finalization.py` | None. |
| AI circuit breaker | `ai/circuit_breaker.py` | Half-open admits every request. Frozen feature. |
| EventBus, MCP session | `core/events.py`, `mcp/server.py` | Publishes before the loop is set are dropped. |

### 5.4 Frontend

Backend mirrors not yet generated: `ArcIssueStatus`, `BandStage`,
`ChatActionStatus`, `UpdateState`, `WeeklyLibraryState`, `WantedBucket`,
`SearchMissingResult.status`, the interactive search session and candidate
unions, and the repair state sets in `AcquisitionHealthTab.tsx`. Each needs a
backend definition before it can be registered (section 3).

UI-flow machines, each a cluster of `useState` values or a ladder over query
flags: onboarding and migration, import row save state, support bundle
download, server-events connection, status bar API state, auth context, the
search-missing dialog, weekly refresh, series add button, interactive release
search, connection tests in Settings.

Leads:

- Many surfaces render a state they do not recognise as the raw backend word.
  Only `statusTone.ts` is now compile-checked against the registry.
  `ActivityPage.tsx`, `lib/releaseState.ts`, `wantedColumns.tsx` and
  `AcquisitionHealthTab.tsx` keep their own ladders.
- The status bar derives online from the last successful response and ignores
  `isError`, so it can read online while the API is down
  (`frontend/src/components/layout/AppStatusBar.tsx:50-54`).
- "Check now" shows a success toast for an unrecognised `update_state`
  (`frontend/src/components/settings/AboutTab.tsx:41-45`, *read*).
  `UpdateState` ends in `| string`, which removes the
  compiler's help.
- Several components pass translated text back in as a state key
  (`SeriesDetailPage.tsx:84,127`, `ArcIssueTable.tsx:49`,
  `SeriesTable.tsx:493`). This breaks when a second locale ships.

## 6. Order of work

Ranked by what an operator stands to lose, then by how cheaply the registry
can cover it.

1. Recovery probe verdict. Make the raw probe states a closed set and send an
   unknown one to UNKNOWN, which leaves the journal stage alone, not to GONE,
   which marks the row failed.
2. Scheduler job status. One vocabulary per column, and Running cleared in a
   `finally`.
3. `ddl_info.status` and the interactive search states. Define the constants
   in the owning module, register them, generate the frontend unions.
4. `acquisition_repair_runs.state`. Put the state predicate in the UPDATE.
5. `issue_status` writers. Route the copied Wanted-or-Skipped decision
   through one function. This is the largest and can start now that
   `importer.py` is split up (#1464).
6. Frontend ladders. Point `ActivityPage`, `releaseState` and
   `wantedColumns` at generated types so an unknown state is a compile error.
