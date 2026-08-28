#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
FastAPI application — lifespan, router composition, static file serving.
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from apscheduler.schedulers.base import SchedulerNotRunningError
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from comicarr.app.core.events import EventBus
from comicarr.app.core.exceptions import register_exception_handlers
from comicarr.app.core.middleware import (
    CSRFMiddleware,
    SecurityHeadersMiddleware,
    SetupGateMiddleware,
)
from comicarr.app.core.runtime import (
    POOL_CONTEXT_FIELDS,
    get_runtime,
    set_runtime_acquisition_status,
    set_runtime_field,
)

SHUTDOWN_DRAIN_TIMEOUT = 30.0

SCHEDULER_DRAIN_TIMEOUT = 30.0

_WORKER_POOLS = tuple(POOL_CONTEXT_FIELDS)


@dataclass(frozen=True)
class DrainResult:
    """Post-drain owners that can still touch shared runtime resources."""

    live_owners: tuple[str, ...] = ()

    @property
    def all_stopped(self):
        return not self.live_owners


def _drain_worker_pools(timeout, ctx=None):
    """Bounded join of every live worker pool — runs OFF the event loop.

    Relocated from queue_schedule()'s shutdown branch. Each pool gets a
    bounded ``join(timeout)``; an unjoined pool is left for the terminal
    hard-kill backstop (a worker wedged in native code must never hang
    termination forever). An AssertionError from a join is swallowed here so
    it can NOT short-circuit to process exit (the removed
    ``except AssertionError: os._exit(0)`` landmine). Every pool is checked
    again after its join; uncertain or live owners keep shared resources open
    for the terminal process-exit path.
    """
    import threading

    import comicarr
    from comicarr import logger

    deadline = time.monotonic() + timeout
    live_owners = []
    registry = getattr(ctx, "background_workers", None) if ctx is not None else None

    def _record_live_owner(pool_attr, reason):
        if pool_attr not in live_owners:
            live_owners.append(pool_attr)
        logger.warn("[SHUTDOWN] Worker pool %s remains live or uncertain after drain: %s" % (pool_attr, reason))

    for pool_attr in _WORKER_POOLS:
        pool = getattr(ctx, POOL_CONTEXT_FIELDS[pool_attr], None) if ctx is not None else None
        if pool is None:
            pool = getattr(comicarr, pool_attr, None)
        if pool is None:
            continue
        try:
            if pool.is_alive() is False:
                continue
        except Exception as e:
            _record_live_owner(pool_attr, "initial liveness check failed: %s" % e)
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _record_live_owner(pool_attr, "shared drain deadline exhausted")
            continue
        try:
            pool.join(remaining)
        except AssertionError as e:
            logger.warn("[SHUTDOWN] AssertionError joining %s: %s" % (pool_attr, e))
        except Exception as e:
            logger.error("[SHUTDOWN] Error joining %s: %s" % (pool_attr, e))

        try:
            still_alive = pool.is_alive() is not False
        except Exception as e:
            _record_live_owner(pool_attr, "post-join liveness check failed: %s" % e)
            continue
        if still_alive:
            _record_live_owner(pool_attr, "still alive after bounded join")
        else:
            logger.fdebug("[SHUTDOWN] Drained worker pool %s" % pool_attr)

    registered_workers = registry.close() if registry is not None else ()
    for worker in registered_workers:
        owner = "background:%s" % worker.name
        if worker is threading.current_thread():
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _record_live_owner(owner, "shared drain deadline exhausted")
            continue
        try:
            worker.join(remaining)
        except Exception as e:
            logger.error("[SHUTDOWN] Error joining %s: %s" % (owner, e))
        if worker.is_alive():
            _record_live_owner(owner, "still alive after bounded join")
        else:
            logger.fdebug("[SHUTDOWN] Drained %s" % owner)

    return DrainResult(tuple(live_owners))


async def _drain_scheduler(loop, drain_executor, scheduler):
    """Bound scheduler drain and report whether it can still own resources."""

    from comicarr import logger

    if not scheduler:
        return DrainResult()
    try:
        scheduler_shutdown = loop.run_in_executor(drain_executor, lambda: scheduler.shutdown(wait=True))
        await asyncio.wait_for(asyncio.shield(scheduler_shutdown), timeout=SCHEDULER_DRAIN_TIMEOUT)
        if getattr(scheduler, "running", True) is not False:
            logger.error("[SHUTDOWN] APScheduler liveness remains active or uncertain after shutdown")
            return DrainResult(("APScheduler",))
        logger.info("[SHUTDOWN] APScheduler stopped and running jobs drained")
        return DrainResult()
    except asyncio.TimeoutError:
        logger.error("[SHUTDOWN] Scheduler drain timed out; APScheduler remains a live owner")
    except SchedulerNotRunningError:
        logger.info("[SHUTDOWN] APScheduler was already stopped")
        return DrainResult()
    except Exception as e:
        logger.error("[SHUTDOWN] Error stopping scheduler; APScheduler liveness is uncertain: %s" % e)
    return DrainResult(("APScheduler",))


def _shutdown_executors(drain_executor, executor):
    """Release shutdown executors exactly once on either terminal path."""

    from comicarr import logger

    try:
        drain_executor.shutdown(wait=False)
    except Exception as e:
        logger.error("[SHUTDOWN] Error shutting down drain executor: %s" % e)

    try:
        executor.shutdown(wait=False)
        logger.info("[SHUTDOWN] ThreadPoolExecutor shutdown requested without waiting")
    except Exception as e:
        logger.error("[SHUTDOWN] Error shutting down executor: %s" % e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan — startup and shutdown."""
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=20)
    loop.set_default_executor(executor)

    ctx = get_runtime()

    event_bus = ctx.event_bus or EventBus()
    event_bus.set_loop(loop)
    ctx.event_bus = event_bus

    app.state.ctx = ctx

    try:
        from comicarr.app.acquisition.maintenance import refresh_runtime_state

        app.state.acquisition_maintenance = refresh_runtime_state(ctx.config).as_dict()
    except Exception:
        import comicarr

        set_runtime_acquisition_status(
            workers_blocked=True,
            block_reason="maintenance_gate_unavailable",
        )
        app.state.acquisition_maintenance = {
            "blocked": True,
            "reason": "maintenance_gate_unavailable",
            "schema_ready": bool(getattr(comicarr, "ACQUISITION_SCHEMA_READY", False)),
        }

    from comicarr import logger

    yield

    import comicarr
    from comicarr import logger

    logger.info("[SHUTDOWN] FastAPI lifespan shutdown starting...")

    drain_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="shutdown-drain")

    scheduler_result = await _drain_scheduler(loop, drain_executor, ctx.scheduler)

    if ctx.event_bus:
        try:
            ctx.event_bus.close()
        except Exception as e:
            logger.error("[SHUTDOWN] Error closing event bus: %s" % e)

    worker_result = DrainResult()
    if scheduler_result.all_stopped:
        for q in [
            ctx.snatched_queue,
            ctx.nzb_queue,
            ctx.pp_queue,
            ctx.search_queue,
            ctx.ddl_queue,
            ctx.add_list,
            ctx.refresh_queue,
        ]:
            try:
                q.put("exit")
            except Exception:
                pass

        try:
            worker_result = await loop.run_in_executor(
                drain_executor,
                _drain_worker_pools,
                SHUTDOWN_DRAIN_TIMEOUT,
                ctx,
            )
            if worker_result.all_stopped:
                logger.info("[SHUTDOWN] Worker drain complete; all pools stopped")
        except Exception as e:
            logger.error("[SHUTDOWN] Error during worker drain; liveness is uncertain: %s" % e)
            worker_result = DrainResult(("worker-pool-state",))

    live_owners = scheduler_result.live_owners + worker_result.live_owners
    if live_owners:
        logger.error(
            "[SHUTDOWN] Preserving runtime resources for terminal process exit; live owners: %s"
            % ", ".join(live_owners)
        )
        _shutdown_executors(drain_executor, executor)
        return

    if ctx.ai_async_client:
        try:
            await ctx.ai_async_client.close()
            logger.info("[SHUTDOWN] AI async client closed")
        except Exception as e:
            logger.error("[SHUTDOWN] Error closing AI client: %s" % e)

    if ctx.ai_client:
        try:
            ctx.ai_client.close()
            logger.info("[SHUTDOWN] AI sync client closed")
        except Exception as e:
            logger.error("[SHUTDOWN] Error closing AI sync client: %s" % e)

    if ctx.cv_session:
        try:
            ctx.cv_session.close()
            logger.info("[SHUTDOWN] CV session closed")
        except Exception:
            pass

    try:
        from comicarr import db

        engine = db.get_engine()
        if engine:
            engine.dispose()
            logger.info("[SHUTDOWN] Database engine disposed")
    except Exception as e:
        logger.error("[SHUTDOWN] Error disposing database: %s" % e)

    _shutdown_executors(drain_executor, executor)

    signal = comicarr.SIGNAL or ctx.signal or "shutdown"
    set_runtime_field(ctx, "signal", signal)
    set_runtime_field(ctx, "disposed", True, project_legacy=False)

    logger.info("[SHUTDOWN] FastAPI lifespan shutdown complete")


def create_app():
    """Factory function — creates and configures the FastAPI application."""
    app = FastAPI(
        title="Comicarr",
        description="Automated Comic Book Manager",
        lifespan=lifespan,
    )

    app.add_middleware(SetupGateMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    register_exception_handlers(app)

    @app.get("/api/health")
    async def health_check():
        return JSONResponse(content={"status": "ok"})

    from comicarr.app.activity.router import router as activity_router
    from comicarr.app.ai.router import router as ai_router
    from comicarr.app.attention.router import router as attention_router
    from comicarr.app.dashboard.router import router as dashboard_router
    from comicarr.app.downloads.router import router as downloads_router
    from comicarr.app.metadata.router import router as metadata_router
    from comicarr.app.opds.router import router as opds_router
    from comicarr.app.search.router import router as search_router
    from comicarr.app.series.router import router as series_router
    from comicarr.app.storyarcs.router import router as storyarcs_router
    from comicarr.app.system.router import router as system_router
    from comicarr.app.weekly.router import router as weekly_router

    app.include_router(system_router)
    app.include_router(ai_router)
    app.include_router(attention_router)
    app.include_router(activity_router)
    app.include_router(dashboard_router)
    app.include_router(weekly_router)
    app.include_router(metadata_router)
    app.include_router(storyarcs_router)
    app.include_router(series_router)
    app.include_router(search_router)
    app.include_router(downloads_router)
    app.include_router(opds_router)

    frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if frontend_dist.is_dir():

        class CachedStaticFiles(StaticFiles):
            async def get_response(self, path, scope):
                try:
                    response = await super().get_response(path, scope)
                except HTTPException as ex:
                    if ex.status_code == 404:
                        response = await super().get_response("index.html", scope)
                        response.headers["Cache-Control"] = "no-cache"
                        return response
                    raise
                if path.startswith("assets/"):
                    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                else:
                    response.headers["Cache-Control"] = "no-cache"
                return response

        app.mount("/", CachedStaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()
