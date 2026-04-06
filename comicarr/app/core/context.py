#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
AppContext — typed dataclass replacing 130+ module-level globals.

Created once at startup via FastAPI's lifespan, stored on app.state,
and injected into routes via Depends(get_context).

Type annotations are an explicit exception to the project's "no type hints"
rule — structured shared-state objects where types genuinely pay for themselves.
"""

import queue
import threading
from dataclasses import dataclass, field

from fastapi import Request


@dataclass
class AppContext:
    # Immutable after init — paths and config
    prog_dir: str = ""
    data_dir: str = ""
    db_file: str = ""
    config: object = None  # comicarr.config.Config instance

    # Scheduler
    scheduler: object = None  # BackgroundScheduler

    # Thread-safe locks
    init_lock: threading.Lock = field(default_factory=threading.Lock)
    search_lock: object = None  # ThreadSafeLock
    api_lock: object = None  # ThreadSafeLock
    ddl_lock: object = None  # ThreadSafeLock

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
    download_apikey: str = None
    sse_key: str = None
    setup_token: str = None

    # JWT
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
    commits_behind: int = None
    install_type: str = None
    current_branch: str = None

    # Misc runtime state
    signal: str = None
    started: bool = False
    start_up: bool = True
    update_value: dict = field(default_factory=dict)


def get_context(request: Request) -> AppContext:
    """FastAPI dependency — injects the application context."""
    return request.app.state.ctx
