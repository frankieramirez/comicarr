#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
System domain router — auth, SSE, config, admin endpoints.

Auth and SSE are prerequisites for every other domain, so they
migrate first (Phase 1).
"""

import asyncio
import json
import threading

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import (
    COOKIE_NAME,
    create_session_token,
    require_session,
    validate_jwt_token,
)
from comicarr.app.system import service as system_service

router = APIRouter(prefix="/api", tags=["system"])


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

# Login MUST be sync def — bcrypt takes ~250ms on NAS ARM hardware.
# If async def, it blocks the entire event loop. FastAPI runs sync
# handlers in a threadpool where threading.Lock is safe.
@router.post("/auth/login")
def login(request: Request, ctx: AppContext = Depends(get_context)):
    """JSON login — returns JWT in HttpOnly cookie."""
    import asyncio
    loop = asyncio.get_event_loop()
    # Read body synchronously (we're in a threadpool)
    body = asyncio.run_coroutine_threadsafe(request.json(), loop).result(timeout=5)

    username = body.get("username")
    password = body.get("password")

    if not username or not password:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Missing username or password"},
        )

    # Delegate to service (handles rate limiting, bcrypt, migration)
    ip = request.client.host if request.client else "unknown"
    result = system_service.verify_login(ctx, username, password, ip)

    if not result["success"]:
        return JSONResponse(
            status_code=401,
            content=result,
        )

    # Issue JWT cookie
    login_timeout = getattr(ctx.config, "LOGIN_TIMEOUT", 43800) if ctx.config else 43800
    token = create_session_token(username, ctx.jwt_secret_key, ctx.jwt_generation, login_timeout)

    enable_https = getattr(ctx.config, "ENABLE_HTTPS", False) if ctx.config else False
    response = JSONResponse(content={"success": True, "username": username})
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=enable_https,
        samesite="strict",
        max_age=2_628_000,  # 30 days
    )
    return response


@router.post("/auth/logout")
def logout(response: Response, username: str = Depends(require_session)):
    """Clear the JWT session cookie."""
    response = JSONResponse(content={"success": True})
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/auth/check-session")
def check_session(request: Request, ctx: AppContext = Depends(get_context)):
    """Check if user has a valid JWT session."""
    token = request.cookies.get(COOKIE_NAME)
    if token:
        username = validate_jwt_token(token, ctx.jwt_secret_key, ctx.jwt_generation)
        if username:
            return {"success": True, "authenticated": True, "username": username}
    return {"success": True, "authenticated": False}


@router.get("/auth/check-setup")
def check_setup(ctx: AppContext = Depends(get_context)):
    """Check if initial setup is needed."""
    needs_setup = not getattr(ctx.config, "HTTP_USERNAME", None) or not getattr(ctx.config, "HTTP_PASSWORD", None)
    return {"success": True, "needs_setup": needs_setup}


_setup_lock = threading.Lock()


@router.post("/auth/setup")
def setup(request: Request, ctx: AppContext = Depends(get_context)):
    """First-run credential setup. Only works if no auth is configured."""
    import asyncio
    loop = asyncio.get_event_loop()
    body = asyncio.run_coroutine_threadsafe(request.json(), loop).result(timeout=5)

    username = body.get("username")
    password = body.get("password")
    setup_token = body.get("setup_token")

    with _setup_lock:
        result = system_service.initial_setup(ctx, username, password, setup_token)
        status_code = 200 if result["success"] else 400
        return JSONResponse(status_code=status_code, content=result)


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------

@router.get("/events/stream")
async def event_stream(request: Request, ctx: AppContext = Depends(get_context)):
    """Server-Sent Events stream. Uses sse-starlette for proper keepalive."""
    if ctx.event_bus is None:
        return JSONResponse(status_code=503, content={"detail": "EventBus not initialized"})

    sub_id, queue = ctx.event_bus.subscribe()
    seq = 0

    async def generator():
        nonlocal seq
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    seq += 1
                    yield ServerSentEvent(
                        data=json.dumps(event.payload),
                        event=event.event_type,
                        id=str(seq),
                    )
                except asyncio.TimeoutError:
                    # Keep connection alive — sse-starlette sends pings
                    continue
        except asyncio.CancelledError:
            pass
        finally:
            ctx.event_bus.unsubscribe(sub_id)

    return EventSourceResponse(generator(), ping=15)


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------

@router.get("/config", dependencies=[Depends(require_session)])
def get_config(ctx: AppContext = Depends(get_context)):
    """Return current configuration (safe subset)."""
    return system_service.get_safe_config(ctx)


@router.put("/config", dependencies=[Depends(require_session)])
def update_config(request: Request, ctx: AppContext = Depends(get_context)):
    """Update configuration key-values."""
    import asyncio
    loop = asyncio.get_event_loop()
    body = asyncio.run_coroutine_threadsafe(request.json(), loop).result(timeout=5)
    result = system_service.update_config(ctx, body)
    return result


@router.put("/config/providers", dependencies=[Depends(require_session)])
def update_providers(request: Request, ctx: AppContext = Depends(get_context)):
    """Update Newznab/Torznab provider configuration."""
    import asyncio
    loop = asyncio.get_event_loop()
    body = asyncio.run_coroutine_threadsafe(request.json(), loop).result(timeout=5)
    result = system_service.update_providers(ctx, body)
    return result


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@router.post("/system/shutdown", dependencies=[Depends(require_session)])
def shutdown_system(ctx: AppContext = Depends(get_context)):
    """Initiate graceful shutdown."""
    ctx.signal = "shutdown"
    import comicarr
    comicarr.SIGNAL = "shutdown"
    if ctx.event_bus:
        ctx.event_bus.publish_sync("shutdown", {"message": "Now shutting down system."})
    return {"success": True, "message": "Shutdown initiated"}


@router.post("/system/restart", dependencies=[Depends(require_session)])
def restart_system(ctx: AppContext = Depends(get_context)):
    """Initiate graceful restart."""
    ctx.signal = "restart"
    import comicarr
    comicarr.SIGNAL = "restart"
    if ctx.event_bus:
        ctx.event_bus.publish_sync("restart", {"message": "Now restarting system."})
    return {"success": True, "message": "Restart initiated"}


@router.get("/system/version")
def get_version(ctx: AppContext = Depends(get_context)):
    """Return version information."""
    return system_service.get_version_info(ctx)


@router.get("/system/logs", dependencies=[Depends(require_session)])
def get_logs(ctx: AppContext = Depends(get_context)):
    """Return recent log entries."""
    return system_service.get_recent_logs(ctx)


@router.get("/system/jobs", dependencies=[Depends(require_session)])
def get_jobs(ctx: AppContext = Depends(get_context)):
    """Return scheduled job information."""
    return system_service.get_job_info(ctx)


# ---------------------------------------------------------------------------
# Startup diagnostics & migration endpoints
# ---------------------------------------------------------------------------

@router.get("/system/diagnostics", dependencies=[Depends(require_session)])
def get_startup_diagnostics(ctx: AppContext = Depends(get_context)):
    """Return startup diagnostics (db empty, migration dismissed)."""
    return system_service.get_startup_diagnostics(ctx)


@router.post("/system/migration/preview", dependencies=[Depends(require_session)])
def preview_migration(request: Request, ctx: AppContext = Depends(get_context)):
    """Validate a Mylar3 source path and return preview data."""
    import asyncio
    loop = asyncio.get_event_loop()
    body = asyncio.run_coroutine_threadsafe(request.json(), loop).result(timeout=5)
    path = body.get("path", "")
    result = system_service.preview_migration(ctx, path)
    if result.get("success") is False:
        return JSONResponse(status_code=400, content=result)
    return result


@router.post("/system/migration/start", dependencies=[Depends(require_session)])
def start_migration(request: Request, ctx: AppContext = Depends(get_context)):
    """Start a migration in a background thread."""
    import asyncio
    loop = asyncio.get_event_loop()
    body = asyncio.run_coroutine_threadsafe(request.json(), loop).result(timeout=5)
    path = body.get("path", "")
    result = system_service.start_migration(ctx, path)
    if result.get("success") is False:
        return JSONResponse(status_code=400, content=result)
    return result


@router.get("/system/migration/progress", dependencies=[Depends(require_session)])
def get_migration_progress(ctx: AppContext = Depends(get_context)):
    """Return current migration progress."""
    return system_service.get_migration_progress(ctx)
