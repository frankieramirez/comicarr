#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The process-wide runtime state contract.

``AppContext`` has one owner per process lifecycle.  It is created by
``comicarr.app.core.runtime.create_runtime`` *after* configuration, schema
readiness, and secret setup have completed, and *before* the legacy workers
start.  FastAPI's lifespan only attaches that instance to ``app.state``; it
never rebuilds a snapshot.

Ownership categories and boundaries:

* immutable configuration: paths and ``config`` are fixed after factory
  creation; configuration writes use the existing Config transaction boundary.
* long-lived services: scheduler, provider sessions, crypto, AI clients, and
  the event bus are created once. Lifespan first quiesces scheduler jobs, then
  closes the event bus before draining workers and closing other clients.
* queues and locks: all worker/request-visible queues and locks are carried
  over by identity from the bootstrap context and are never cloned.
* request-visible state: statuses, progress, migration/acquisition gate, and
  lifecycle values are updated under ``runtime_lock``.  Durable
  acquisition decisions remain serialized by ``MaintenanceController``'s
  database transaction/fence before their in-memory projection is updated.
* worker-pool references live on the context only; no field has a
  ``comicarr`` package alias.

Shutdown owner/order is the FastAPI lifespan: quiesce scheduled jobs off the
event loop, close the event bus, signal queues, join workers off the event
loop, close clients, dispose database resources, then mark the context
disposed so no later request can use it. If scheduler quiescence times out,
lifespan leaves runtime resources intact for Comicarr.py's terminal process
exit instead of disposing them underneath a still-running job.

Type annotations are an explicit exception to the project's "no type hints"
rule — structured shared-state objects where types genuinely pay for themselves.
"""

import platform
import queue
import threading
from dataclasses import dataclass, field

from fastapi import Request

from comicarr.app.core.locks import ThreadSafeLock
from comicarr.app.core.workers import BackgroundWorkerRegistry
from comicarr.app.search.queue import FairSearchQueue


@dataclass
class AppContext:
    # None until Comicarr.py resolves them, as the package globals were.
    prog_dir: str = None
    data_dir: str = None
    db_file: str = None
    config: object = None
    jwt_secure_dir: str = None

    scheduler: object = None

    runtime_lock: object = field(default_factory=threading.RLock)
    init_lock: threading.Lock = field(default_factory=threading.Lock)
    search_lock: object = field(default_factory=ThreadSafeLock)
    api_lock: object = field(default_factory=ThreadSafeLock)
    ddl_lock: object = field(default_factory=ThreadSafeLock)
    acquisition_resume_lock: object = field(default_factory=threading.Lock)

    snatched_queue: queue.Queue = field(default_factory=queue.Queue)
    nzb_queue: queue.Queue = field(default_factory=queue.Queue)
    pp_queue: queue.Queue = field(default_factory=queue.Queue)
    search_queue: object = field(default_factory=FairSearchQueue)
    ddl_queue: queue.Queue = field(default_factory=queue.Queue)
    return_nzb_queue: queue.Queue = field(default_factory=queue.Queue)
    add_list: queue.Queue = field(default_factory=queue.Queue)
    issue_watch_list: queue.Queue = field(default_factory=queue.Queue)
    refresh_queue: queue.Queue = field(default_factory=queue.Queue)

    sn_pool: object = None
    nzb_pool: object = None
    search_pool: object = None
    pp_pool: object = None
    ddl_pool: object = None
    mass_add_pool: object = None
    mass_refresh_pool: object = None
    background_workers: object = field(default_factory=BackgroundWorkerRegistry)

    event_bus: object = None

    cv_session: object = None
    cv_rate_limiter: object = None
    cv_cache: object = None
    cv_headers: dict = None
    cv_url: str = None
    # Request timeout (seconds) for ComicVine calls. The CV_TIMEOUT setting
    # has never been wired to it; this keeps the long-standing fixed value.
    cv_timeout: int = 30
    metron_api: object = None
    fernet: object = None

    ai_client: object = None
    ai_async_client: object = None
    ai_circuit_breaker: object = None
    ai_rate_limiter: object = None

    comic_sort: object = None
    publisher_imprints: dict = field(default_factory=dict)
    provider_blocklist: list = field(default_factory=list)
    provider_start_id: int = 0
    # Which download client each route hands off to, derived from config.
    use_sabnzbd: bool = False
    use_nzbget: bool = False
    use_blackhole: bool = False
    use_rtorrent: bool = False
    use_deluge: bool = False
    use_transmission: bool = False
    use_qbittorrent: bool = False
    use_utorrent: bool = False
    use_watchdir: bool = False
    # Search, pull-list and provider state the engines share.
    keys_32p: dict = None
    wwt_cf_cookievalue: object = None
    search_tier_date: str = None
    pullnew: str = None
    pullbyfile: bool = False
    current_weeknumber: str = None
    current_year: str = None
    db_backfill: bool = False
    reqs: dict = field(default_factory=dict)
    # Maintenance mode (the --maintenance CLI and pending database conversions).
    maintenance: bool = False
    maintenance_update: list = field(default_factory=list)
    maintenance_db_total: int = 0
    maintenance_db_count: int = 0
    # Process and command-line state, set by Comicarr.py and initialize().
    full_path: str = None
    args: list = field(default_factory=list)
    config_file: str = None
    daemon: bool = False
    pidfile: str = None
    createpid: bool = False
    sys_encoding: str = None
    os_detect: str = field(default_factory=platform.system)
    user_agent: str = None
    umask: int = None
    ddl_queued: set = field(default_factory=set)
    ddl_stuck_notified: set = field(default_factory=set)
    pack_issueids_dont_queue: dict = field(default_factory=dict)
    folder_cache: object = None
    check_folder_cache: object = None

    monitor_status: str = "Waiting"
    search_status: str = "Waiting"
    rss_status: str = "Waiting"
    weekly_status: str = "Waiting"
    version_status: str = "Waiting"
    updater_status: str = "Waiting"
    manga_sync_status: str = "Waiting"
    force_status: dict = field(default_factory=dict)
    importinbox_status: str = "Waiting"
    weekly_manual_next_run: object = None
    # Last-run timestamps the scheduler restores at start-up (epoch seconds).
    sched_rss_last: object = None
    sched_weekly_last: object = None
    sched_monitor_last: object = None
    sched_search_last: object = None
    sched_version_last: object = None
    sched_dbupdate_last: object = None
    sched_manga_sync_last: object = None

    import_status: str = None
    import_files: int = 0
    import_totalfiles: int = 0
    import_cid_count: int = 0
    import_parsed_count: int = 0
    import_failure_count: int = 0
    import_lock: bool = False
    import_button: bool = False

    sse_key: str = None
    setup_token: str = None

    jwt_secret_key: bytes = None
    jwt_generation: int = 0

    backend_status_ws: str = "up"
    backend_status_cv: str = "up"
    provider_status: dict = field(default_factory=dict)

    current_version: str = None
    current_version_name: str = None
    current_release_name: str = None
    latest_version: str = None
    update_state: str = None
    update_reason: str = None
    install_type: str = None
    current_branch: str = None

    signal: str = None
    started: bool = False
    start_up: bool = True
    update_value: dict = field(default_factory=dict)

    db_empty: bool = False
    acquisition_schema_ready: bool = False
    acquisition_schema_version: int = 0
    acquisition_schema_error: str = "acquisition schema has not been verified"
    acquisition_workers_blocked: bool = True
    acquisition_block_reason: str = "schema_unavailable"

    migration_in_progress: bool = False
    migration_status: str = "idle"
    migration_current_table: str = ""
    migration_tables_complete: int = 0
    migration_tables_total: int = 0
    migration_error: str = None
    migration_reconciliation: object = None

    disposed: bool = False


def get_context(request: Request) -> AppContext:
    """FastAPI dependency — injects the application context."""
    try:
        ctx = request.app.state.ctx
    except AttributeError as e:
        from comicarr.app.core.runtime import RuntimeNotInitializedError

        raise RuntimeNotInitializedError("Runtime context is not initialized") from e
    if ctx is None or getattr(ctx, "disposed", False):
        from comicarr.app.core.runtime import RuntimeNotInitializedError

        raise RuntimeNotInitializedError("Runtime context is not initialized or has been disposed")
    return ctx
