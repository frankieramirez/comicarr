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
* queues and locks: all worker/request-visible queues and locks are adopted by
  identity from the legacy runtime.  The compatibility bridge may expose the
  same object to an unmigrated caller, but it must never clone one.
* request-visible state: statuses, progress, migration/acquisition gate, and
  lifecycle values are updated through the runtime bridge's lock.  Durable
  acquisition decisions remain serialized by ``MaintenanceController``'s
  database transaction/fence before their in-memory projection is updated.
* legacy compatibility state: worker-pool references and scalar aliases stay
  projected into ``comicarr`` temporarily for legacy engines.  Context is the
  canonical writer for migrated code; the projection is not a second owner.

Shutdown owner/order is the FastAPI lifespan: quiesce scheduled jobs off the
event loop, close the event bus, signal queues, join workers off the event
loop, close clients, dispose database resources, then mark the context
disposed so no later request can use it. If scheduler quiescence times out,
lifespan leaves runtime resources intact for Comicarr.py's terminal process
exit instead of disposing them underneath a still-running job.

Type annotations are an explicit exception to the project's "no type hints"
rule — structured shared-state objects where types genuinely pay for themselves.
"""

import queue
import threading
from dataclasses import dataclass, field

from fastapi import Request

from comicarr.app.core.workers import BackgroundWorkerRegistry


@dataclass
class AppContext:
    # Immutable after init — paths and config
    prog_dir: str = ""
    data_dir: str = ""
    db_file: str = ""
    config: object = None  # comicarr.config.Config instance
    jwt_secure_dir: str = None

    # Scheduler
    scheduler: object = None  # BackgroundScheduler

    # Thread-safe locks. ``runtime_lock`` serializes context/legacy projection
    # writes; the acquired queue and domain locks retain their legacy locking
    # semantics and identities.
    runtime_lock: object = field(default_factory=threading.RLock)
    init_lock: threading.Lock = field(default_factory=threading.Lock)
    search_lock: object = None  # ThreadSafeLock
    api_lock: object = None  # ThreadSafeLock
    ddl_lock: object = None  # ThreadSafeLock
    acquisition_resume_lock: object = None  # threading.Lock

    # Work queues (inter-thread communication)
    snatched_queue: queue.Queue = field(default_factory=queue.Queue)
    nzb_queue: queue.Queue = field(default_factory=queue.Queue)
    pp_queue: queue.Queue = field(default_factory=queue.Queue)
    search_queue: queue.Queue = field(default_factory=queue.Queue)
    ddl_queue: queue.Queue = field(default_factory=queue.Queue)
    return_nzb_queue: queue.Queue = field(default_factory=queue.Queue)
    add_list: queue.Queue = field(default_factory=queue.Queue)
    issue_watch_list: queue.Queue = field(default_factory=queue.Queue)
    refresh_queue: queue.Queue = field(default_factory=queue.Queue)

    # Worker references. These stay compatibility-projected while the legacy
    # worker bootstrap is being strangled; the objects themselves are shared.
    sn_pool: object = None
    nzb_pool: object = None
    search_pool: object = None
    pp_pool: object = None
    ddl_pool: object = None
    mass_add_pool: object = None
    mass_refresh_pool: object = None
    background_workers: object = field(default_factory=BackgroundWorkerRegistry)

    # SSE
    event_bus: object = None  # EventBus instance

    # Provider clients
    cv_session: object = None  # requests.Session
    cv_rate_limiter: object = None
    cv_cache: object = None
    metron_api: object = None
    fernet: object = None  # Fernet instance

    # AI integration
    ai_client: object = None  # OpenAI sync client
    ai_async_client: object = None  # AsyncOpenAI async client
    ai_circuit_breaker: object = None  # CircuitBreaker instance
    ai_rate_limiter: object = None  # AIRateLimiter instance

    # In-memory state (migrated from globals)
    comic_sort: object = None  # COMICSORT
    publisher_imprints: dict = field(default_factory=dict)
    provider_blocklist: list = field(default_factory=list)
    ddl_queued: set = field(default_factory=set)
    ddl_stuck_notified: set = field(default_factory=set)
    pack_issueids_dont_queue: dict = field(default_factory=dict)
    folder_cache: object = None
    check_folder_cache: object = None

    # Scheduler status (read by frontend)
    monitor_status: str = "Waiting"
    search_status: str = "Waiting"
    rss_status: str = "Waiting"
    weekly_status: str = "Waiting"
    version_status: str = "Waiting"
    updater_status: str = "Waiting"
    force_status: dict = field(default_factory=dict)
    importinbox_status: str = "Waiting"
    weekly_manual_next_run: object = None

    # Import progress tracking
    import_status: str = None
    import_files: int = 0
    import_totalfiles: int = 0
    import_cid_count: int = 0
    import_parsed_count: int = 0
    import_failure_count: int = 0
    import_lock: bool = False
    import_button: bool = False

    # Mutable auth state (ephemeral, NOT on config)
    sse_key: str = None
    setup_token: str = None

    # JWT signing authority. The secure directory is immutable after init;
    # the active key is rotated under ``runtime_lock``.
    jwt_secret_key: bytes = None
    jwt_generation: int = 0

    # Backend status
    backend_status_ws: str = "up"
    backend_status_cv: str = "up"
    provider_status: dict = field(default_factory=dict)

    # Version info
    current_version: str = None
    current_version_name: str = None
    current_release_name: str = None
    latest_version: str = None
    update_state: str = None
    update_reason: str = None
    install_type: str = None
    current_branch: str = None

    # Misc runtime state
    signal: str = None
    started: bool = False
    start_up: bool = True
    update_value: dict = field(default_factory=dict)

    # Database/acquisition runtime projection. Durable maintenance state is
    # owned by the database fence; these fields expose its latest safe view.
    db_empty: bool = False
    acquisition_schema_ready: bool = False
    acquisition_schema_version: int = 0
    acquisition_schema_error: str = None
    acquisition_workers_blocked: bool = True
    acquisition_block_reason: str = "schema_unavailable"

    # Migration status is request-visible and projected for legacy callers.
    migration_in_progress: bool = False
    migration_status: str = "idle"
    migration_current_table: str = ""
    migration_tables_complete: int = 0
    migration_tables_total: int = 0
    migration_error: str = None
    migration_reconciliation: object = None

    # Lifecycle terminal state. Accessors reject a disposed context rather
    # than allowing a request/background callback to touch closed resources.
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
