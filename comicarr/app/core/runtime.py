#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Single-shot creation of the process ``AppContext``, and its bootstrap.

Every piece of process state lives on ``AppContext``; nothing is stored on the
``comicarr`` package. Before ``create_runtime`` runs, ``current()`` returns a
bootstrap context that start-up code writes into. The factory copies that
context field by field, so queues, locks, sets, dictionaries, the scheduler
and client instances keep their identity across the hand-over.
"""

import dataclasses
import os
import threading

from comicarr.app.core.context import AppContext
from comicarr.app.core.events import EventBus
from comicarr.app.core.scheduler import build_scheduler
from comicarr.app.core.security import generate_ephemeral_key, load_or_create_jwt_key


class RuntimeNotInitializedError(RuntimeError):
    """Raised when code attempts to use runtime state outside its lifecycle."""


_runtime_lock = threading.Lock()
_runtime = None
_UNSET = object()


def new_bootstrap():
    """Return a fresh pre-factory context with the process's real scheduler."""
    return AppContext(scheduler=build_scheduler())


# The context that exists before ``create_runtime`` runs. Module-level code,
# CLI entry points and unit tests read and write runtime state through
# ``current()`` without waiting for the factory, so a value set during
# start-up is never lost: the factory carries every field over.
_bootstrap = new_bootstrap()

# The worker-pool references a shutdown drain joins.
POOL_FIELDS = (
    "sn_pool",
    "nzb_pool",
    "search_pool",
    "pp_pool",
    "ddl_pool",
    "mass_add_pool",
    "mass_refresh_pool",
)


def _initialize_ai_clients(ctx):
    """Create one AI client bundle at the runtime lifecycle boundary.

    Consumers read this bundle from the runtime context.
    """
    ai_config = ctx.config
    if not ai_config or not getattr(ai_config, "AI_BASE_URL", None) or not getattr(ai_config, "AI_API_KEY", None):
        return

    from comicarr.app.ai.circuit_breaker import CircuitBreaker
    from comicarr.app.ai.client import create_ai_clients
    from comicarr.app.ai.rate_limiter import AIRateLimiter
    from comicarr.app.core import logger

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

        if _bootstrap.config is None:
            raise RuntimeNotInitializedError(
                "Runtime context cannot be created before configuration, schema, and secret initialization"
            )

        # A shallow copy: every mutable value keeps its identity.
        ctx = dataclasses.replace(_bootstrap)
        ctx.sse_key = ctx.sse_key or generate_ephemeral_key()
        ctx.event_bus = EventBus()

        secure_dir = getattr(ctx.config, "SECURE_DIR", None)
        ctx.jwt_secure_dir = secure_dir
        ctx.jwt_secret_key = load_or_create_jwt_key(secure_dir) if secure_dir else os.urandom(32)
        _initialize_ai_clients(ctx)
        _runtime = ctx
        return ctx


def get_runtime():
    """Return the initialized process runtime or fail clearly before startup."""
    if _runtime is None:
        raise RuntimeNotInitializedError("Runtime context is not initialized")
    if _runtime.disposed:
        raise RuntimeNotInitializedError("Runtime context has been disposed")
    return _runtime


def current():
    """Return the runtime context, before or after the factory has run.

    This is the accessor for process state. It never raises: before
    ``create_runtime`` it returns the bootstrap context, which the factory
    carries over, so a reader never has to care which phase of start-up it
    runs in. Use ``get_runtime`` instead where running before start-up is a
    bug.
    """
    ctx = _runtime
    return _bootstrap if ctx is None else ctx


def get_runtime_if_initialized():
    """Return the factory runtime, or None before ``create_runtime`` runs."""
    return _runtime


def set_runtime_field(ctx, field, value):
    """Write one field of a live runtime context under its lock.

    Mutable values are assigned by identity; no clone or value snapshot is
    produced.
    """
    if ctx is None:
        raise RuntimeNotInitializedError("Runtime context is not initialized")
    if ctx.disposed:
        raise RuntimeNotInitializedError("Runtime context has been disposed")

    with ctx.runtime_lock:
        setattr(ctx, field, value)
    return value


def set_runtime_acquisition_status(
    *,
    schema_ready=_UNSET,
    schema_version=_UNSET,
    schema_error=_UNSET,
    workers_blocked=_UNSET,
    block_reason=_UNSET,
):
    """Record durable acquisition status on the runtime context.

    Schema setup runs before the factory, so early calls write the bootstrap
    context, which the factory carries over.
    """
    ctx = current()
    values = {
        "acquisition_schema_ready": schema_ready,
        "acquisition_schema_version": schema_version,
        "acquisition_schema_error": schema_error,
        "acquisition_workers_blocked": workers_blocked,
        "acquisition_block_reason": block_reason,
    }
    with ctx.runtime_lock:
        for field, value in values.items():
            if value is not _UNSET:
                setattr(ctx, field, value)
