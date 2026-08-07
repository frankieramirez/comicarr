#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Single-shot creation and temporary legacy projection for ``AppContext``.

The factory deliberately *adopts* initialized legacy objects.  In particular,
queues, locks, sets, dictionaries, scheduler, and client instances are passed
to ``AppContext`` by reference.  No mutable object is copied during this
transition: unmigrated legacy code and migrated context consumers therefore
observe the same state until the legacy aliases can be removed.
"""

import os
import threading

from comicarr.app.core.context import AppContext
from comicarr.app.core.events import EventBus
from comicarr.app.core.security import generate_ephemeral_key, load_or_create_jwt_key


class RuntimeNotInitializedError(RuntimeError):
    """Raised when code attempts to use runtime state outside its lifecycle."""


# The factory lock makes normal startup single-shot even if a future bootstrap
# path races with a server/lifespan integration test. The singleton is private;
# consumers use get_runtime(), FastAPI's get_context(), or an explicit ctx.
_runtime_lock = threading.Lock()
_runtime = None
_UNSET = object()


# ``AppContext`` fields that still need a temporary legacy projection. Mutable
# entries in this map always point to the exact same object. Scalar projections
# are written through set_runtime_field under ctx.runtime_lock so migrated code
# has one writer while old engines are drained.
_CONTEXT_TO_LEGACY = {
    "prog_dir": "PROG_DIR",
    "data_dir": "DATA_DIR",
    "db_file": "DB_FILE",
    "config": "CONFIG",
    "scheduler": "SCHED",
    "init_lock": "INIT_LOCK",
    "search_lock": "SEARCHLOCK",
    "api_lock": "APILOCK",
    "ddl_lock": "DDL_LOCK",
    "acquisition_resume_lock": "ACQUISITION_RESUME_LOCK",
    "snatched_queue": "SNATCHED_QUEUE",
    "nzb_queue": "NZB_QUEUE",
    "pp_queue": "PP_QUEUE",
    "search_queue": "SEARCH_QUEUE",
    "ddl_queue": "DDL_QUEUE",
    "return_nzb_queue": "RETURN_THE_NZBQUEUE",
    "add_list": "ADD_LIST",
    "issue_watch_list": "ISSUE_WATCH_LIST",
    "refresh_queue": "REFRESH_QUEUE",
    "sn_pool": "SNPOOL",
    "nzb_pool": "NZBPOOL",
    "search_pool": "SEARCHPOOL",
    "pp_pool": "PPPOOL",
    "ddl_pool": "DDLPOOL",
    "mass_add_pool": "MASS_ADD",
    "mass_refresh_pool": "MASS_REFRESH",
    "cv_session": "CV_SESSION",
    "cv_rate_limiter": "CV_RATE_LIMITER",
    "cv_cache": "CV_CACHE",
    "metron_api": "METRON_API",
    "ai_client": "AI_CLIENT",
    "ai_async_client": "AI_ASYNC_CLIENT",
    "ai_circuit_breaker": "AI_CIRCUIT_BREAKER",
    "ai_rate_limiter": "AI_RATE_LIMITER",
    "comic_sort": "COMICSORT",
    "publisher_imprints": "PUBLISHER_IMPRINTS",
    "provider_blocklist": "PROVIDER_BLOCKLIST",
    "ddl_queued": "DDL_QUEUED",
    "ddl_stuck_notified": "DDL_STUCK_NOTIFIED",
    "pack_issueids_dont_queue": "PACK_ISSUEIDS_DONT_QUEUE",
    "folder_cache": "FOLDER_CACHE",
    "check_folder_cache": "CHECK_FOLDER_CACHE",
    "monitor_status": "MONITOR_STATUS",
    "search_status": "SEARCH_STATUS",
    "rss_status": "RSS_STATUS",
    "weekly_status": "WEEKLY_STATUS",
    "version_status": "VERSION_STATUS",
    "updater_status": "UPDATER_STATUS",
    "force_status": "FORCE_STATUS",
    "importinbox_status": "IMPORTINBOX_STATUS",
    "weekly_manual_next_run": "WEEKLY_MANUAL_NEXT_RUN",
    "import_status": "IMPORT_STATUS",
    "import_files": "IMPORT_FILES",
    "import_totalfiles": "IMPORT_TOTALFILES",
    "import_cid_count": "IMPORT_CID_COUNT",
    "import_parsed_count": "IMPORT_PARSED_COUNT",
    "import_failure_count": "IMPORT_FAILURE_COUNT",
    "import_lock": "IMPORTLOCK",
    "import_button": "IMPORTBUTTON",
    "sse_key": "SSE_KEY",
    "setup_token": "SETUP_TOKEN",
    "backend_status_ws": "BACKENDSTATUS_WS",
    "backend_status_cv": "BACKENDSTATUS_CV",
    "provider_status": "PROVIDER_STATUS",
    "current_version": "CURRENT_VERSION",
    "current_version_name": "CURRENT_VERSION_NAME",
    "current_release_name": "CURRENT_RELEASE_NAME",
    "latest_version": "LATEST_VERSION",
    "update_state": "UPDATE_STATE",
    "update_reason": "UPDATE_REASON",
    "install_type": "INSTALL_TYPE",
    "current_branch": "CURRENT_BRANCH",
    "signal": "SIGNAL",
    "started": "started",
    "start_up": "START_UP",
    "update_value": "UPDATE_VALUE",
    "db_empty": "DB_EMPTY",
    "acquisition_schema_ready": "ACQUISITION_SCHEMA_READY",
    "acquisition_schema_version": "ACQUISITION_SCHEMA_VERSION",
    "acquisition_schema_error": "ACQUISITION_SCHEMA_ERROR",
    "acquisition_workers_blocked": "ACQUISITION_WORKERS_BLOCKED",
    "acquisition_block_reason": "ACQUISITION_BLOCK_REASON",
    "migration_in_progress": "MIGRATION_IN_PROGRESS",
    "migration_status": "MIGRATION_STATUS",
    "migration_current_table": "MIGRATION_CURRENT_TABLE",
    "migration_tables_complete": "MIGRATION_TABLES_COMPLETE",
    "migration_tables_total": "MIGRATION_TABLES_TOTAL",
    "migration_error": "MIGRATION_ERROR",
    "migration_reconciliation": "MIGRATION_RECONCILIATION",
}


# Keep the legacy worker names and their canonical context fields in one
# ordered mapping. Startup stores these identities here and lifespan drains
# them in this same order.
POOL_CONTEXT_FIELDS = {
    "SNPOOL": "sn_pool",
    "NZBPOOL": "nzb_pool",
    "SEARCHPOOL": "search_pool",
    "PPPOOL": "pp_pool",
    "DDLPOOL": "ddl_pool",
    "MASS_ADD": "mass_add_pool",
    "MASS_REFRESH": "mass_refresh_pool",
}


def _legacy_value(comicarr, field, default=None):
    """Read an initialized legacy value without fabricating a mutable default."""
    return getattr(comicarr, _CONTEXT_TO_LEGACY[field], default)


def _adopt_legacy_runtime():
    """Build context kwargs from existing process objects, preserving identity."""
    import comicarr

    return {
        field: _legacy_value(comicarr, field)
        for field in _CONTEXT_TO_LEGACY
        if field
        not in {
            "sse_key",
            "ai_client",
            "ai_async_client",
            "ai_circuit_breaker",
            "ai_rate_limiter",
        }
    }


def _initialize_ai_clients(ctx):
    """Create one AI client bundle at the runtime lifecycle boundary.

    Canonical consumers read this context bundle. Remaining legacy aliases
    receive these same instances through the temporary bridge below.
    """
    ai_config = ctx.config
    if not ai_config or not getattr(ai_config, "AI_BASE_URL", None) or not getattr(ai_config, "AI_API_KEY", None):
        return

    from comicarr import logger
    from comicarr.app.ai.circuit_breaker import CircuitBreaker
    from comicarr.app.ai.client import create_ai_clients
    from comicarr.app.ai.rate_limiter import AIRateLimiter

    sync_client, async_client = create_ai_clients(ai_config)
    if not sync_client:
        return

    ctx.ai_client = sync_client
    ctx.ai_async_client = async_client
    ctx.ai_circuit_breaker = CircuitBreaker(
        threshold=getattr(ai_config, "AI_CIRCUIT_THRESHOLD", 5),
        cooldown=getattr(ai_config, "AI_CIRCUIT_COOLDOWN", 300),
    )
    ctx.ai_rate_limiter = AIRateLimiter(
        rpm_limit=getattr(ai_config, "AI_RPM_LIMIT", 20),
        daily_token_limit=getattr(ai_config, "AI_DAILY_TOKEN_LIMIT", 100000),
    )
    logger.info("[AI] Client initialized: %s" % getattr(ai_config, "AI_BASE_URL", ""))


def _project_context(ctx):
    """Expose context values to remaining legacy engines without copying them."""
    import comicarr

    for field, legacy_name in _CONTEXT_TO_LEGACY.items():
        if field == "disposed":
            continue
        setattr(comicarr, legacy_name, getattr(ctx, field))


def create_runtime():
    """Create and return the single canonical process runtime.

    Configuration must already exist. This intentionally fails closed rather
    than constructing an incomplete context that could let workers run before
    schema/secret setup finishes.
    """
    global _runtime

    with _runtime_lock:
        if _runtime is not None:
            return _runtime

        import comicarr

        if getattr(comicarr, "CONFIG", None) is None:
            raise RuntimeNotInitializedError(
                "Runtime context cannot be created before configuration, schema, and secret initialization"
            )

        ctx = AppContext(**_adopt_legacy_runtime())
        ctx.sse_key = getattr(comicarr, "SSE_KEY", None) or generate_ephemeral_key()
        ctx.event_bus = EventBus()

        secure_dir = getattr(ctx.config, "SECURE_DIR", None)
        ctx.jwt_secure_dir = secure_dir
        ctx.jwt_secret_key = load_or_create_jwt_key(secure_dir) if secure_dir else os.urandom(32)
        _initialize_ai_clients(ctx)
        _project_context(ctx)
        _runtime = ctx
        return ctx


def get_runtime():
    """Return the initialized process runtime or fail clearly before startup."""
    if _runtime is None:
        raise RuntimeNotInitializedError("Runtime context is not initialized")
    if _runtime.disposed:
        raise RuntimeNotInitializedError("Runtime context has been disposed")
    return _runtime


def get_runtime_if_initialized():
    """Best-effort compatibility helper for legacy code that runs pre-factory."""
    return _runtime


def set_runtime_field(ctx, field, value, *, project_legacy=True):
    """Write a canonical field and, while needed, its legacy projection.

    This is intentionally the only bridge used by migrated lifecycle/system/
    acquisition writers. Mutable values are assigned by identity; no clone or
    value snapshot is produced.
    """
    if ctx is None:
        raise RuntimeNotInitializedError("Runtime context is not initialized")
    if ctx.disposed:
        raise RuntimeNotInitializedError("Runtime context has been disposed")

    with ctx.runtime_lock:
        setattr(ctx, field, value)
        if project_legacy:
            legacy_name = _CONTEXT_TO_LEGACY.get(field)
            if legacy_name:
                import comicarr

                setattr(comicarr, legacy_name, value)
    return value


def set_runtime_acquisition_status(
    *,
    schema_ready=_UNSET,
    schema_version=_UNSET,
    schema_error=_UNSET,
    workers_blocked=_UNSET,
    block_reason=_UNSET,
):
    """Project durable acquisition status into context when it already exists.

    Schema setup runs before runtime creation, so pre-factory calls keep the
    existing globals authoritative. Once the factory exists, all values are
    updated under the runtime lock and projected to legacy callers.
    """
    import comicarr

    ctx = get_runtime_if_initialized()
    values = {
        "acquisition_schema_ready": schema_ready,
        "acquisition_schema_version": schema_version,
        "acquisition_schema_error": schema_error,
        "acquisition_workers_blocked": workers_blocked,
        "acquisition_block_reason": block_reason,
    }
    for field, value in values.items():
        if value is _UNSET:
            continue
        if ctx is None:
            legacy_name = _CONTEXT_TO_LEGACY[field]
            setattr(comicarr, legacy_name, value)
        else:
            set_runtime_field(ctx, field, value)
