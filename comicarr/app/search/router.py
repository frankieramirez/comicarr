#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Search domain router — provider search, RSS monitoring.

Depends on series domain for cross-domain lookups (Phase 5).
"""

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import COOKIE_NAME, require_session
from comicarr.app.search import interactive as interactive_search
from comicarr.app.search import service as search_service
from comicarr.app.search.interactive_sessions import (
    InteractiveCandidateConflict,
    InteractiveSearchAuthorizationError,
    InteractiveSearchExpired,
)

router = APIRouter(prefix="/api/search", tags=["search"])


def _session_identity(request: Request, username: str):
    return request.cookies.get(COOKIE_NAME) or username


# ---------------------------------------------------------------------------
# Comic / manga search
# ---------------------------------------------------------------------------


@router.post("/comics", dependencies=[Depends(require_session)])
def search_comics(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Search for comics across ComicVine, Metron, or MangaDex."""
    if request_body is None:
        request_body = {}

    name = request_body.get("name", "")
    if not name:
        return JSONResponse(status_code=400, content={"detail": "Missing search name"})

    result = search_service.find_comic(
        ctx,
        name=name,
        issue=request_body.get("issue"),
        type_=request_body.get("type", "comic"),
        mode=request_body.get("mode", "series"),
        limit=request_body.get("limit"),
        offset=request_body.get("offset"),
        sort=request_body.get("sort"),
        content_type=request_body.get("content_type"),
    )

    if isinstance(result, dict) and "error" in result:
        return JSONResponse(status_code=400, content={"detail": result["error"]})

    return result


@router.post("/manga", dependencies=[Depends(require_session)])
def search_manga(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Search for manga via MangaDex API."""
    if request_body is None:
        request_body = {}

    name = request_body.get("name", "")
    if not name:
        return JSONResponse(status_code=400, content={"detail": "Missing search name"})

    result = search_service.find_manga(
        ctx,
        name=name,
        limit=request_body.get("limit"),
        offset=request_body.get("offset"),
        sort=request_body.get("sort"),
    )

    if isinstance(result, dict) and "error" in result:
        return JSONResponse(status_code=400, content={"detail": result["error"]})

    return result


# ---------------------------------------------------------------------------
# Add comic / manga to library
# ---------------------------------------------------------------------------


@router.post("/add", dependencies=[Depends(require_session)])
def add_comic(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Add a comic to the watchlist."""
    if request_body is None:
        request_body = {}

    comic_id = request_body.get("id") or request_body.get("comic_id")
    if not comic_id:
        return JSONResponse(status_code=400, content={"detail": "Missing comic id"})

    result = search_service.add_comic(ctx, comic_id)
    if not result["success"]:
        return JSONResponse(status_code=500, content={"detail": result.get("error")})
    return result


@router.post("/add-manga", dependencies=[Depends(require_session)])
def add_manga(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Add a manga to the library by MangaDex ID."""
    if request_body is None:
        request_body = {}

    manga_id = request_body.get("id") or request_body.get("manga_id")
    if not manga_id:
        return JSONResponse(status_code=400, content={"detail": "Missing manga id"})

    result = search_service.add_manga(ctx, manga_id)
    if not result["success"]:
        return JSONResponse(status_code=400, content={"detail": result.get("error")})
    return result


# ---------------------------------------------------------------------------
# Force search / RSS
# ---------------------------------------------------------------------------


@router.post("/force", dependencies=[Depends(require_session)])
def force_search(ctx: AppContext = Depends(get_context)):
    """Trigger a full search for all wanted issues."""
    return search_service.force_search(ctx)


@router.post("/rss/force", dependencies=[Depends(require_session)])
def force_rss(ctx: AppContext = Depends(get_context)):
    """Trigger an RSS feed check."""
    result = search_service.force_rss(ctx)
    if not result["success"]:
        return JSONResponse(status_code=500, content={"detail": result.get("error")})
    return result


@router.get("/providers", dependencies=[Depends(require_session)])
def get_provider_stats(ctx: AppContext = Depends(get_context)):
    """Get sanitized provider search statistics."""
    return search_service.get_provider_stats(ctx)


@router.get("/health", dependencies=[Depends(require_session)])
def get_search_health(ctx: AppContext = Depends(get_context)):
    """Get acquisition-route, durable run, worker, and maintenance health."""
    return search_service.get_health(ctx)


@router.post("/interactive", dependencies=[Depends(require_session)], status_code=202)
async def start_interactive_search(
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Start provider collection for one tracked item or a series' missing issues."""

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    # Off the event loop: validation hits the DB and provider plan checks
    # before the collection thread is spawned (#733).
    result = await asyncio.to_thread(
        interactive_search.start_search,
        ctx,
        actor=username,
        browser_session=_session_identity(request, username),
        entity_type=body.get("entity_type"),
        entity_id=body.get("entity_id"),
    )
    if result.get("success") is False:
        return JSONResponse(status_code=int(result.get("status_code") or 400), content=result)
    return result


@router.get("/interactive/{session_id}", dependencies=[Depends(require_session)])
def poll_interactive_search(
    session_id: str,
    request: Request,
    username: str = Depends(require_session),
):
    """Poll sanitized progress and candidates for an owned search session."""

    try:
        return interactive_search.get_search(
            session_id=session_id,
            actor=username,
            browser_session=_session_identity(request, username),
        )
    except InteractiveSearchExpired as e:
        return JSONResponse(status_code=410, content={"detail": str(e), "status": "expired"})
    except InteractiveSearchAuthorizationError:
        return JSONResponse(status_code=404, content={"detail": "Interactive search session not found"})


@router.post(
    "/interactive/{session_id}/candidates/{candidate_id}/grab",
    dependencies=[Depends(require_session)],
)
async def grab_interactive_candidate(
    session_id: str,
    candidate_id: str,
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Safely hand off one owned, freshly revalidated release candidate."""

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        # Off the event loop: revalidation re-runs a provider search and the
        # handoff talks to the download client — minutes, not milliseconds.
        # Running it inline froze every other request (#733).
        result = await asyncio.to_thread(
            interactive_search.grab_candidate,
            ctx,
            session_id=session_id,
            candidate_id=candidate_id,
            actor=username,
            browser_session=_session_identity(request, username),
            override=body.get("override") is True,
        )
    except InteractiveSearchExpired as e:
        return JSONResponse(status_code=410, content={"detail": str(e), "status": "expired"})
    except InteractiveSearchAuthorizationError:
        return JSONResponse(status_code=404, content={"detail": "Release candidate not found"})
    except InteractiveCandidateConflict as e:
        return JSONResponse(status_code=409, content={"detail": str(e), "status": "conflict"})
    if result.get("success") is False:
        return JSONResponse(status_code=int(result.pop("status_code", 409)), content=result)
    return result


@router.get("/runs/{run_id}", dependencies=[Depends(require_session)])
def get_search_run(run_id: str, include_items: bool = True, ctx: AppContext = Depends(get_context)):
    """Poll the terminal outcome of a durable search run."""
    result = search_service.get_run(ctx, run_id, include_items=include_items)
    if result.get("success") is False:
        return JSONResponse(status_code=int(result.get("status_code") or 404), content=result)
    return result


@router.post("/runs/{run_id}/retry", dependencies=[Depends(require_session)])
def retry_search_run(run_id: str, ctx: AppContext = Depends(get_context)):
    """Redrive durable search obligations that missed their queue handoff."""
    result = search_service.retry_run(ctx, run_id)
    if result.get("success") is False and result.get("status_code"):
        return JSONResponse(status_code=int(result["status_code"]), content=result)
    return result
