#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
FastAPI application — lifespan, router composition, WSGI bridge.

During the Strangler Fig transition, CherryPy is mounted as a WSGI
sub-application. New FastAPI routes take priority; unmatched requests
fall through to CherryPy.
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from comicarr.app.core.context import AppContext
from comicarr.app.core.events import EventBus
from comicarr.app.core.exceptions import register_exception_handlers
from comicarr.app.core.middleware import (
    CSRFMiddleware,
    SecurityHeadersMiddleware,
    SetupGateMiddleware,
)
from comicarr.app.core.security import generate_ephemeral_key, load_or_create_jwt_key


def _build_context_from_globals():
    """Bridge: populate AppContext from existing comicarr.__init__ globals.

    This is the transition layer. As domains migrate, they'll read from
    AppContext instead of comicarr.VARIABLE. Eventually the globals go away.
    """
    import comicarr

    ctx = AppContext(
        prog_dir=comicarr.PROG_DIR or "",
        data_dir=comicarr.DATA_DIR or "",
        db_file=comicarr.DB_FILE or "",
        config=comicarr.CONFIG,
        scheduler=comicarr.SCHED,
        init_lock=comicarr.INIT_LOCK,
        search_lock=comicarr.SEARCHLOCK,
        api_lock=comicarr.APILOCK,
        ddl_lock=comicarr.DDL_LOCK,
        snatched_queue=comicarr.SNATCHED_QUEUE,
        nzb_queue=comicarr.NZB_QUEUE,
        pp_queue=comicarr.PP_QUEUE,
        search_queue=comicarr.SEARCH_QUEUE,
        ddl_queue=comicarr.DDL_QUEUE,
        return_nzb_queue=comicarr.RETURN_THE_NZBQUEUE,
        add_list=comicarr.ADD_LIST,
        issue_watch_list=comicarr.ISSUE_WATCH_LIST,
        refresh_queue=comicarr.REFRESH_QUEUE,
        cv_session=comicarr.CV_SESSION,
        cv_rate_limiter=comicarr.CV_RATE_LIMITER,
        cv_cache=comicarr.CV_CACHE,
        metron_api=comicarr.METRON_API,
        comic_sort=comicarr.COMICSORT,
        publisher_imprints=comicarr.PUBLISHER_IMPRINTS or {},
        provider_blocklist=comicarr.PROVIDER_BLOCKLIST or [],
        ddl_queued=set(comicarr.DDL_QUEUED) if comicarr.DDL_QUEUED else set(),
        ddl_stuck_notified=comicarr.DDL_STUCK_NOTIFIED or set(),
        pack_issueids_dont_queue=comicarr.PACK_ISSUEIDS_DONT_QUEUE or {},
        folder_cache=comicarr.FOLDER_CACHE,
        check_folder_cache=comicarr.CHECK_FOLDER_CACHE,
        monitor_status=comicarr.MONITOR_STATUS or "Waiting",
        search_status=comicarr.SEARCH_STATUS or "Waiting",
        rss_status=comicarr.RSS_STATUS or "Waiting",
        weekly_status=comicarr.WEEKLY_STATUS or "Waiting",
        version_status=comicarr.VERSION_STATUS or "Waiting",
        updater_status=comicarr.UPDATER_STATUS or "Waiting",
        force_status=comicarr.FORCE_STATUS or {},
        import_status=comicarr.IMPORT_STATUS,
        import_files=comicarr.IMPORT_FILES or 0,
        import_totalfiles=comicarr.IMPORT_TOTALFILES or 0,
        import_cid_count=comicarr.IMPORT_CID_COUNT or 0,
        import_parsed_count=comicarr.IMPORT_PARSED_COUNT or 0,
        import_failure_count=comicarr.IMPORT_FAILURE_COUNT or 0,
        import_lock=comicarr.IMPORTLOCK or False,
        import_button=comicarr.IMPORTBUTTON or False,
        download_apikey=comicarr.DOWNLOAD_APIKEY,
        sse_key=comicarr.SSE_KEY or generate_ephemeral_key(),
        setup_token=comicarr.SETUP_TOKEN,
        backend_status_ws=comicarr.BACKENDSTATUS_WS or "up",
        backend_status_cv=comicarr.BACKENDSTATUS_CV or "up",
        provider_status=comicarr.PROVIDER_STATUS or {},
        current_version=comicarr.CURRENT_VERSION,
        current_version_name=comicarr.CURRENT_VERSION_NAME,
        current_release_name=comicarr.CURRENT_RELEASE_NAME,
        latest_version=comicarr.LATEST_VERSION,
        commits_behind=comicarr.COMMITS_BEHIND,
        install_type=comicarr.INSTALL_TYPE,
        current_branch=comicarr.CURRENT_BRANCH,
        signal=comicarr.SIGNAL,
        started=comicarr.started,
        start_up=comicarr.START_UP,
        update_value=comicarr.UPDATE_VALUE or {},
    )

    # JWT key — separate from Fernet master key
    secure_dir = getattr(comicarr.CONFIG, "SECURE_DIR", None) if comicarr.CONFIG else None
    if secure_dir:
        ctx.jwt_secret_key = load_or_create_jwt_key(secure_dir)
    else:
        # Fallback for development/testing — generate ephemeral key
        ctx.jwt_secret_key = os.urandom(32)

    return ctx


def _mount_cherrypy_wsgi(app):
    """Mount CherryPy as a WSGI sub-application under /legacy.

    During the Strangler Fig transition, unmatched FastAPI routes
    fall through to CherryPy via this bridge.
    """
    try:
        import cherrypy
        from a2wsgi import WSGIMiddleware

        cherrypy_wsgi_app = cherrypy.tree
        app.mount("/legacy", WSGIMiddleware(cherrypy_wsgi_app))
    except Exception:
        pass  # CherryPy not initialized yet or not available


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan — startup and shutdown."""
    # --- Startup ---
    loop = asyncio.get_running_loop()

    # Set thread pool to 20 during transition (matching APScheduler pool)
    loop.set_default_executor(ThreadPoolExecutor(max_workers=20))

    # Build context from existing globals
    ctx = _build_context_from_globals()

    # Set up EventBus with the running event loop
    event_bus = EventBus()
    event_bus.set_loop(loop)
    ctx.event_bus = event_bus

    # Store context on app.state for dependency injection
    app.state.ctx = ctx

    # Mount CherryPy WSGI bridge
    _mount_cherrypy_wsgi(app)

    yield

    # --- Shutdown ---
    import comicarr
    from comicarr import logger

    logger.info("[SHUTDOWN] FastAPI lifespan shutdown starting...")

    # 1. Stop APScheduler
    if ctx.scheduler:
        try:
            ctx.scheduler.shutdown(wait=False)
            logger.info("[SHUTDOWN] APScheduler stopped")
        except Exception as e:
            logger.error("[SHUTDOWN] Error stopping scheduler: %s" % e)

    # 2. Signal queue consumer threads to stop
    for q in [ctx.snatched_queue, ctx.nzb_queue, ctx.pp_queue,
              ctx.search_queue, ctx.ddl_queue]:
        try:
            q.put("exit")
        except Exception:
            pass

    # 3. Close provider sessions
    if ctx.cv_session:
        try:
            ctx.cv_session.close()
            logger.info("[SHUTDOWN] CV session closed")
        except Exception:
            pass

    # 4. Dispose database engine
    try:
        from comicarr import db
        engine = db.get_engine()
        if engine:
            engine.dispose()
            logger.info("[SHUTDOWN] Database engine disposed")
    except Exception as e:
        logger.error("[SHUTDOWN] Error disposing database: %s" % e)

    # 5. Propagate shutdown signal to legacy system
    comicarr.SIGNAL = "shutdown"

    logger.info("[SHUTDOWN] FastAPI lifespan shutdown complete")


def create_app():
    """Factory function — creates and configures the FastAPI application."""
    app = FastAPI(
        title="Comicarr",
        description="Automated Comic Book Manager",
        lifespan=lifespan,
    )

    # Register middleware (order matters — outermost first)
    app.add_middleware(SetupGateMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    # Register domain exception handlers
    register_exception_handlers(app)

    # Health check — available before any domain routers
    @app.get("/api/health")
    async def health_check():
        return JSONResponse(content={"status": "ok"})

    # Domain routers
    from comicarr.app.metadata.router import router as metadata_router
    from comicarr.app.search.router import router as search_router
    from comicarr.app.series.router import router as series_router
    from comicarr.app.storyarcs.router import router as storyarcs_router
    from comicarr.app.system.router import router as system_router
    app.include_router(system_router)
    app.include_router(metadata_router)
    app.include_router(storyarcs_router)
    app.include_router(series_router)
    app.include_router(search_router)

    return app


# Module-level app instance for uvicorn to import
app = create_app()
