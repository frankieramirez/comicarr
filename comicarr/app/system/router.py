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

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from comicarr import logger
from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import (
    COOKIE_NAME,
    create_session_token,
    require_session,
    rotate_runtime_jwt_key,
    validate_jwt_token,
)
from comicarr.app.system import service as system_service
from comicarr.app.system import support_bundle as support_bundle_module

router = APIRouter(prefix="/api", tags=["system"])


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


# Login is async so it can await request.json(). The blocking bcrypt
# call (~250ms on NAS ARM hardware) is offloaded to a threadpool via
# asyncio.to_thread so it doesn't block the event loop.
@router.post("/auth/login")
async def login(request: Request, ctx: AppContext = Depends(get_context)):
    """JSON login — returns JWT in HttpOnly cookie."""
    body = await request.json()

    username = body.get("username")
    password = body.get("password")

    if not username or not password:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Missing username or password"},
        )

    # Delegate to service (handles rate limiting, bcrypt, migration)
    # Run in threadpool since verify_login does blocking bcrypt work
    ip = request.client.host if request.client else "unknown"
    result = await asyncio.to_thread(system_service.verify_login, ctx, username, password, ip)

    if not result["success"]:
        return JSONResponse(
            status_code=401,
            content=result,
        )

    # Issue JWT cookie
    login_timeout = getattr(ctx.config, "LOGIN_TIMEOUT", 43800) if ctx.config else 43800
    # Serialize issuance with logout rotation so a successful login can never
    # return a token signed by the just-revoked key.
    with ctx.runtime_lock:
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
def logout(
    ctx: AppContext = Depends(get_context),
    username: str = Depends(require_session),
):
    """Revoke every UI session, then clear this client's JWT cookie."""
    try:
        rotate_runtime_jwt_key(ctx)
    except Exception as e:
        logger.error("[AUTH] Unable to persist logout revocation: %s" % type(e).__name__)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Unable to revoke active sessions"},
        )

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
async def setup(request: Request, ctx: AppContext = Depends(get_context)):
    """First-run credential setup. Only works if no auth is configured."""
    body = await request.json()

    username = body.get("username")
    password = body.get("password")
    setup_token = body.get("setup_token")

    def _run_setup():
        with _setup_lock:
            return system_service.initial_setup(ctx, username, password, setup_token)

    result = await asyncio.to_thread(_run_setup)
    if result["success"]:
        status_code = 200
    elif result.get("error") == system_service.SETUP_PERSISTENCE_ERROR:
        status_code = 500
    else:
        status_code = 400
    return JSONResponse(status_code=status_code, content=result)


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------


@router.get("/events/stream", dependencies=[Depends(require_session)])
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
async def update_config(request: Request, ctx: AppContext = Depends(get_context)):
    """Update configuration key-values."""
    body = await request.json()
    result = await asyncio.to_thread(system_service.update_config, ctx, body)
    if not result["success"]:
        status_code = 500 if result.get("error") == system_service.CONFIG_PERSISTENCE_ERROR else 400
        return JSONResponse(status_code=status_code, content=result)
    return result


@router.post("/config/api-key/regenerate")
async def regenerate_api_key(
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Regenerate and persist the API key."""
    ip = request.client.host if request.client else "unknown"
    result = await asyncio.to_thread(system_service.regenerate_api_key, ctx, username, ip)
    if not result["success"]:
        return JSONResponse(status_code=500, content=result)
    return result


@router.put("/config/providers", dependencies=[Depends(require_session)])
async def update_providers(request: Request, ctx: AppContext = Depends(get_context)):
    """Update Newznab/Torznab provider configuration.

    Object-payload ``verify`` and ``enabled`` must be JSON booleans when present.
    """
    body = await request.json()
    result = await asyncio.to_thread(system_service.update_providers, ctx, body)
    if not result["success"]:
        status_code = 500 if result.get("error") == system_service.PROVIDER_CONFIG_PERSISTENCE_ERROR else 400
        return JSONResponse(status_code=status_code, content=result)
    return result


@router.get("/config/providers", dependencies=[Depends(require_session)])
def get_providers(ctx: AppContext = Depends(get_context)):
    """Return provider identities and enablement without credentials."""
    return system_service.get_provider_config(ctx)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.post("/system/shutdown", dependencies=[Depends(require_session)])
def shutdown_system(ctx: AppContext = Depends(get_context)):
    """Initiate graceful shutdown."""
    import os
    import signal

    from comicarr.app.core.runtime import set_runtime_field

    set_runtime_field(ctx, "signal", "shutdown")
    if ctx.event_bus:
        ctx.event_bus.publish_sync("shutdown", {"message": "Now shutting down system."})
    os.kill(os.getpid(), signal.SIGTERM)
    return {"success": True, "message": "Shutdown initiated"}


@router.post("/system/restart", dependencies=[Depends(require_session)])
def restart_system(ctx: AppContext = Depends(get_context)):
    """Initiate graceful restart."""
    import os
    import signal

    from comicarr.app.core.runtime import set_runtime_field

    set_runtime_field(ctx, "signal", "restart")
    if ctx.event_bus:
        ctx.event_bus.publish_sync("restart", {"message": "Now restarting system."})
    os.kill(os.getpid(), signal.SIGTERM)
    return {"success": True, "message": "Restart initiated"}


@router.get("/system/version")
def get_version(ctx: AppContext = Depends(get_context)):
    """Return version information."""
    return system_service.get_version_info(ctx)


@router.get("/system/release-notes", dependencies=[Depends(require_session)])
def get_release_notes(
    after: str,
    through: str,
    ctx: AppContext = Depends(get_context),
):
    """Return structured release notes for the open-closed semver range.

    Query params:
      after   — exclusive lower bound (typically last_seen / current when behind)
      through — inclusive upper bound (typically current install or latest remote)

    Sections are newest-first. Source is local CHANGELOG.md under PROG_DIR;
    when the operator is behind, notes for the notified remote release may
    come from the body already cached by the update check (no second fetch).
    """
    after = (after or "").strip()
    through = (through or "").strip()
    if not after or not through:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "after and through query params are required"},
        )
    return system_service.get_release_notes(ctx, after=after, through=through)


@router.get("/system/whats-new/archive", dependencies=[Depends(require_session)])
def get_whats_new_archive(ctx: AppContext = Depends(get_context)):
    """Permanent Settings → About What's new archive.

    Sections are newest-first, floored at the pending range when unread so
    modal overflow is never shorter than this list, and padded toward ~10
    historical rows when quiet (#451 / #474).
    """
    return system_service.get_whats_new_archive(ctx)


@router.post("/system/whats-new/dismiss", dependencies=[Depends(require_session)])
def dismiss_whats_new(ctx: AppContext = Depends(get_context)):
    """Acknowledge post-upgrade notes — LAST_SEEN_VERSION = current.

    Used by the modal "Got it" and About "Mark as read". Does not run on
    overflow navigation alone.
    """
    result = system_service.dismiss_whats_new(ctx)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    return result


@router.post("/system/version/check", dependencies=[Depends(require_session)])
def check_version_now(ctx: AppContext = Depends(get_context)):
    """Force a single release check (ignores automatic-check off).

    Used by Settings → About → Updates "Check now". Off for automatic checks
    means no unsolicited traffic, not refusal of an operator-initiated check.
    """
    return system_service.force_version_check(ctx)


@router.get("/system/logs", dependencies=[Depends(require_session)])
def get_logs(
    lines: int = Query(
        system_service.DEFAULT_LOG_LINES,
        ge=1,
        le=system_service.MAX_LOG_LINES,
        description="How many trailing lines of comicarr.log to return.",
    ),
    ctx: AppContext = Depends(get_context),
):
    """Return the tail of the current log file plus the effective log level."""
    return system_service.get_recent_logs(ctx, lines=lines)


@router.get("/system/jobs", dependencies=[Depends(require_session)])
def get_jobs(include_acquisition: bool = True, ctx: AppContext = Depends(get_context)):
    """Return scheduled job information."""
    return system_service.get_job_info(ctx, include_acquisition=include_acquisition)


# ---------------------------------------------------------------------------
# Startup diagnostics & migration endpoints
# ---------------------------------------------------------------------------


@router.get("/system/diagnostics", dependencies=[Depends(require_session)])
def get_startup_diagnostics(include_acquisition: bool = True, ctx: AppContext = Depends(get_context)):
    """Return startup diagnostics (db empty, migration dismissed)."""
    return system_service.get_startup_diagnostics(ctx, include_acquisition=include_acquisition)


@router.post("/system/migration/preview", dependencies=[Depends(require_session)])
async def preview_migration(request: Request, ctx: AppContext = Depends(get_context)):
    """Validate a Mylar3 source path and return preview data."""
    body = await request.json()
    path = body.get("path", "")
    result = await asyncio.to_thread(system_service.preview_migration, ctx, path)
    if result.get("success") is False:
        return JSONResponse(status_code=400, content=result)
    return result


@router.post("/system/migration/start", dependencies=[Depends(require_session)])
async def start_migration(request: Request, ctx: AppContext = Depends(get_context)):
    """Start a migration in a background thread."""
    body = await request.json()
    path = body.get("path", "")
    result = await asyncio.to_thread(system_service.start_migration, ctx, path)
    if result.get("success") is False:
        return JSONResponse(status_code=int(result.get("status_code") or 400), content=result)
    return result


@router.get("/system/migration/progress", dependencies=[Depends(require_session)])
def get_migration_progress(ctx: AppContext = Depends(get_context)):
    """Return current migration progress."""
    return system_service.get_migration_progress(ctx)


@router.post("/system/acquisition/reconciliation/ready", dependencies=[Depends(require_session)])
async def mark_reconciliation_ready(
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Explicitly resume acquisition after the operator records reconciliation."""
    body = await request.json()
    if not isinstance(body, dict):
        body = {}
    result = await asyncio.to_thread(
        system_service.mark_reconciliation_ready,
        ctx,
        actor=username,
        reason=body.get("reason"),
    )
    return _repair_response(result)


@router.post("/system/acquisition/maintenance/abort", dependencies=[Depends(require_session)])
async def abort_acquisition_maintenance(
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Audit and release a drained fence that an operator has abandoned."""
    body = await request.json()
    if not isinstance(body, dict):
        body = {}
    result = await asyncio.to_thread(
        system_service.abort_acquisition_maintenance,
        ctx,
        actor=username,
        reason=body.get("reason"),
    )
    return _repair_response(result)


# ---------------------------------------------------------------------------
# Acquisition repair — owner session only (never API-key)
# ---------------------------------------------------------------------------


def _session_identity(request: Request, username: str):
    """Bind repair tokens to the current browser session cookie."""
    return request.cookies.get(COOKIE_NAME) or username


def _repair_response(result):
    if result.get("success") is False:
        return JSONResponse(status_code=int(result.get("status_code") or 400), content=result)
    return result


@router.post("/system/acquisition/repair/preview", dependencies=[Depends(require_session)])
async def preview_acquisition_repair(
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Create a read-only series repair preview and one-shot confirmation token."""
    body = await request.json()
    series_id = body.get("series_id") or body.get("comic_id")
    if not series_id:
        return JSONResponse(status_code=400, content={"success": False, "error": "series_id is required"})
    result = await asyncio.to_thread(
        system_service.preview_acquisition_repair,
        ctx,
        series_id,
        actor=username,
        session_id=_session_identity(request, username),
    )
    return _repair_response(result)


@router.post("/system/acquisition/repair/{run_id}/confirm", dependencies=[Depends(require_session)])
async def confirm_acquisition_repair(
    run_id: str,
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Freeze the immutable repair manifest with the one-shot preview token."""
    body = await request.json()
    result = await asyncio.to_thread(
        system_service.confirm_acquisition_repair,
        ctx,
        run_id,
        actor=username,
        session_id=_session_identity(request, username),
        preview_token=body.get("preview_token") or body.get("token"),
        fingerprint=body.get("fingerprint"),
        selected_optional_keys=body.get("selected_optional_keys") or body.get("selectedOptionalKeys") or (),
        canary_entity_key=body.get("canary_entity_key") or body.get("canaryEntityKey"),
    )
    return _repair_response(result)


@router.post("/system/acquisition/repair/{run_id}/apply", dependencies=[Depends(require_session)])
async def apply_acquisition_repair(
    run_id: str,
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Apply a confirmed repair manifest under the maintenance fence."""
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    if not isinstance(body, dict):
        body = {}
    result = await asyncio.to_thread(
        system_service.apply_acquisition_repair,
        ctx,
        run_id,
        actor=username,
        session_id=_session_identity(request, username),
        max_items=body.get("max_items"),
        canary_only=bool(body.get("canary_only") or body.get("canaryOnly")),
    )
    return _repair_response(result)


@router.get("/system/acquisition/repair/{run_id}", dependencies=[Depends(require_session)])
def get_acquisition_repair_run(
    run_id: str,
    request: Request,
    include_items: bool = True,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Poll a repair run owned by the current session."""
    result = system_service.get_acquisition_repair_run(
        ctx,
        run_id,
        actor=username,
        session_id=_session_identity(request, username),
        include_items=include_items,
    )
    return _repair_response(result)


@router.post("/system/acquisition/repair/{run_id}/rollback", dependencies=[Depends(require_session)])
async def rollback_acquisition_repair(
    run_id: str,
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Conditionally roll back applied repair values that have not drifted."""
    body = await request.json()
    reason = body.get("reason")
    if not reason:
        return JSONResponse(status_code=400, content={"success": False, "error": "reason is required"})
    result = await asyncio.to_thread(
        system_service.rollback_acquisition_repair,
        ctx,
        run_id,
        actor=username,
        session_id=_session_identity(request, username),
        reason=reason,
    )
    return _repair_response(result)


@router.post("/system/acquisition/repair/{run_id}/canary", dependencies=[Depends(require_session)])
async def authorize_acquisition_canary(
    run_id: str,
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Authorize exactly one named downloader handoff while fenced."""
    body = await request.json()
    release_key = body.get("release_key") or body.get("releaseKey")
    route = body.get("route")
    if not release_key or not route:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "release_key and route are required"},
        )
    result = await asyncio.to_thread(
        system_service.authorize_acquisition_canary,
        ctx,
        run_id,
        actor=username,
        session_id=_session_identity(request, username),
        release_key=release_key,
        route=route,
    )
    return _repair_response(result)


@router.get("/system/acquisition/canary/{permit_id}", dependencies=[Depends(require_session)])
def get_acquisition_canary(
    permit_id: str,
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Poll the single permitted external handoff."""
    return _repair_response(
        system_service.get_acquisition_canary(
            ctx,
            permit_id,
            actor=username,
            session_id=_session_identity(request, username),
        )
    )


@router.post("/system/acquisition/canary/{permit_id}/release", dependencies=[Depends(require_session)])
async def release_acquisition_canary(
    permit_id: str,
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Release maintenance after the canary has been inspected."""
    body = await request.json()
    reason = body.get("reason")
    if not reason:
        return JSONResponse(status_code=400, content={"success": False, "error": "reason is required"})
    result = await asyncio.to_thread(
        system_service.release_acquisition_canary,
        ctx,
        permit_id,
        actor=username,
        session_id=_session_identity(request, username),
        reason=reason,
    )
    return _repair_response(result)


# ---------------------------------------------------------------------------
# Support bundle
# ---------------------------------------------------------------------------


@router.post("/system/support-bundle", dependencies=[Depends(require_session)])
def create_support_bundle(ctx: AppContext = Depends(get_context)):
    """Generate and download a Support bundle ZIP (session-authenticated only)."""
    try:
        artifact = support_bundle_module.generate_support_bundle(ctx)
    except support_bundle_module.SupportBundleInProgress:
        body = support_bundle_module.error_body("support_bundle_in_progress")
        return JSONResponse(
            status_code=409,
            content=body,
            headers={"Retry-After": "2"},
        )
    except support_bundle_module.SupportBundleUnavailable:
        return JSONResponse(
            status_code=503,
            content=support_bundle_module.error_body("support_bundle_unavailable"),
        )
    except support_bundle_module.SupportBundleValidationFailed:
        return JSONResponse(
            status_code=500,
            content=support_bundle_module.error_body("support_bundle_validation_failed"),
        )
    except support_bundle_module.SupportBundleError as exc:
        status = 503 if exc.code == "support_bundle_unavailable" else 500
        return JSONResponse(status_code=status, content=support_bundle_module.error_body(exc.code))
    except Exception as e:
        logger.error("[SUPPORT-BUNDLE] unexpected adapter failure: %s" % type(e).__name__)
        return JSONResponse(
            status_code=500,
            content=support_bundle_module.error_body("support_bundle_generation_failed"),
        )

    return Response(
        content=artifact.content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
            "X-Comicarr-Support-Bundle-Contract": str(artifact.contract_version),
            "X-Comicarr-Support-Bundle-Status": artifact.status,
        },
    )
