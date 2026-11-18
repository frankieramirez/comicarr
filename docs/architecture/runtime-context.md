# Runtime context ownership

`AppContext` is the one runtime owner for a Comicarr process. It is created
once by `comicarr.app.core.runtime.create_runtime()` after `comicarr.initialize`
has loaded configuration, applied schema readiness checks, and decrypted or
generated startup secrets. `Comicarr.py` creates it before `comicarr.start()`
can start a scheduler or worker. FastAPI lifespan attaches that existing
instance to `app.state.ctx`; it does not construct a second view.

## Ownership contract

| State category | Examples | Creation/writer | Reader/shutdown owner | Identity rule |
| --- | --- | --- | --- | --- |
| Immutable configuration | paths, `config`, build metadata | startup configuration | routes/services; no disposal | fixed after factory creation |
| Long-lived services | scheduler, CV session/cache, Metron, AI bundle, event bus, background-worker registry | runtime factory; event loop is attached in lifespan | workers/routes; lifespan quiesces jobs, closes the event bus, then closes clients after drain | one instance per process |
| Queues and locks | `ddl_queued`, all work queues, search/API/DDL locks, acquisition resume lock | bootstrap context; the factory carries them over | workers, scheduler, routes; lifespan signals queues then drains pools | must be the exact same object, never a copy |
| Request-visible state | scheduler status, setup/JWT state, import progress, version state | migrated services write with `set_runtime_field()` | system/API readers; discarded with process | `set_runtime_field()` serializes writes with `runtime_lock` |
| Durable-acquisition projection | schema readiness, maintenance block reason, migration reconciliation | `MaintenanceController` database transactions/fences, then runtime projection | startup diagnostics and acquisition workers | durable DB fence is authoritative; context is its live projection |

### Complete field classification

- Immutable configuration: `prog_dir`, `data_dir`, `db_file`, `config`.
- Long-lived services: `scheduler`, `event_bus`, `cv_session`,
  `cv_rate_limiter`, `cv_cache`, `metron_api`, `fernet`, `ai_client`,
  `ai_async_client`, `ai_circuit_breaker`, `ai_rate_limiter`,
  `background_workers`.
- Locks: `runtime_lock`, `init_lock`, `search_lock`, `api_lock`, `ddl_lock`,
  `acquisition_resume_lock`.
- Queues: `snatched_queue`, `nzb_queue`, `pp_queue`, `search_queue`,
  `ddl_queue`, `return_nzb_queue`, `add_list`, `issue_watch_list`,
  `refresh_queue`.
- Worker-pool references: `sn_pool`, `nzb_pool`, `search_pool`,
  `pp_pool`, `ddl_pool`, `mass_add_pool`, `mass_refresh_pool`.
- Mutable process state: `comic_sort`, `publisher_imprints`,
  `provider_blocklist`, `ddl_queued`, `ddl_stuck_notified`,
  `pack_issueids_dont_queue`, `folder_cache`, `check_folder_cache`,
  `force_status`, `update_value`, `provider_status`.
- Scheduler/request status: `monitor_status`, `search_status`, `rss_status`,
  `weekly_status`, `version_status`, `updater_status`, `importinbox_status`,
  `weekly_manual_next_run`, `import_status`, `import_files`,
  `import_totalfiles`, `import_cid_count`, `import_parsed_count`,
  `import_failure_count`, `import_lock`, `import_button`.
- Auth/session state: `download_apikey`, `sse_key`, `setup_token`,
  `jwt_secure_dir`, `jwt_secret_key`, `jwt_generation`. Logout rotates the
  persisted JWT key and the in-memory signing authority under `runtime_lock`;
  token issuance holds the same lock.
- Provider/version state: `backend_status_ws`, `backend_status_cv`,
  `current_version`, `current_version_name`, `current_release_name`,
  `latest_version`, `commits_behind`, `install_type`, `current_branch`.
- Lifecycle state: `signal`, `started`, `start_up`, `disposed`.
- Durable-acquisition projection: `db_empty`, `acquisition_schema_ready`,
  `acquisition_schema_version`, `acquisition_schema_error`,
  `acquisition_workers_blocked`, `acquisition_block_reason`,
  `migration_in_progress`, `migration_status`, `migration_current_table`,
  `migration_tables_complete`, `migration_tables_total`, `migration_error`,
  `migration_reconciliation`.

## Lifecycle

1. `comicarr.initialize()` establishes config, schema/migration state, and
   secrets. A schema or maintenance failure closes the acquisition gate but
   still permits authenticated diagnostics.
2. `create_runtime()` copies the bootstrap context exactly once, shallowly,
   so every object keeps its identity. It also builds the AI
   client bundle and loads the persisted JWT signing key at this lifecycle
   boundary.
3. `comicarr.start(runtime)` rejects a missing or divergent context before
   starting scheduler/worker activity. Worker pool references are written
   on that context so the shutdown owner sees the same pools.
4. FastAPI lifespan stores that instance on `app.state.ctx`, sets the event-bus
   loop, and re-reads the durable acquisition gate.
5. Lifespan shutdown quiesces running scheduler jobs off the event loop,
   closes the event bus to reject late publications, signals queues, joins
   registered worker pools and finite background workers off the event loop,
   closes external clients, disposes the database, then marks the context
   disposed. Scheduler and worker drains recheck liveness and report every
   live or uncertain owner. If any owner remains, one preservation path leaves
   clients, the database, and the context intact for Comicarr.py's terminal
   exit rather than disposing them underneath live work. `get_context()` fails
   closed only after normal teardown.

## Transitional boundary

The system router, acquisition maintenance gate, `weeklypullit` state writer,
and the bounded AI runtime consumers are the first migrated ownership boundary.
`tests/unit/test_runtime_context.py` keeps an explicit allowlist for direct
`comicarr.<UPPERCASE>` accesses in those files; it is empty. The larger
`app/system/service.py` scheduler surface and non-selected domains remain
documented compatibility consumers until their coherent ownership waves,
rather than being silently rewritten in this change.

## Retiring the package globals (#1478)

`runtime.current()` is the accessor that replaces a `comicarr.X` global. It
never raises: before `create_runtime()` it returns a module-level bootstrap
`AppContext`, and afterwards the factory context. Code that may run during
start-up, a CLI entry point, or a unit test reads and writes through it
without caring which phase it runs in. `get_runtime()` stays the accessor for
code where running before start-up is a bug.

Each retirement slice moved one group of globals in a single change: every
reader and writer switched to `runtime.current().<field>`, the global was
deleted, and its name joined `RETIRED_GLOBALS` in
`scripts/check_retired_globals.py` so it cannot return. The factory used to
adopt each remaining global and project it back onto the package; with the
last projected group retired, `create_runtime()` is now a plain shallow copy
of the bootstrap context (`dataclasses.replace`), and nothing on `AppContext`
has a `comicarr` alias.

Retired so far: scheduler status and schedule stamps (`*_status`,
`force_status`, `weekly_manual_next_run`, `sched_*_last`; #1539) and the work
queues (`*_queue`, `add_list`, `issue_watch_list`), process locks
(`init_lock`, `api_lock`, `search_lock`, `ddl_lock`, `acquisition_resume_lock`)
and worker-pool references (`*_pool`; #1540), the install paths
(`prog_dir`, `data_dir`, `db_file`), version and install state
(`install_type`, `current_*`, `latest_version`, `update_*`), metadata and
provider sessions (`cv_*`, `metron_api`, `provider_*`, `backend_status_*`;
#1541), the configuration object (`config`; #1542), the scheduler, AI
clients, DDL and folder-cache state, import progress, first-run secrets, and
the lifecycle and acquisition gate state (`signal`, `started`, `start_up`,
`db_empty`, `acquisition_*`, `migration_*`), and the download-client route
flags (`use_*`) and the search, pull-list and provider state (`keys_32p`,
`search_tier_date`, `pull*`, `current_weeknumber`, `current_year`, `reqs`,
`db_backfill`), and maintenance-mode progress (`maintenance`,
`maintenance_update`, `maintenance_db_*`; #1543). Values that never changed after start-up became module
constants beside their readers instead: `ISSUE_EXCEPTIONS`
(`app/common/numbers.py`), `IMPRINT_MAPPING` (`app/metadata/cv.py`), `GC_URL`
(`app/downloads/getcomics.py`), `DEMURL` and `WWTURL` (`app/search/service.py`). The bootstrap context
builds the process's one scheduler
(`comicarr/app/core/scheduler.py`); `runtime.new_bootstrap()` gives a test a
fresh one.

`tests/fixtures/upgrade_matrix/build.py` drives historical Comicarr and Mylar3
release trees, where these globals are the old releases' real API, so the guard
exempts the runtime-field names in that file only.
