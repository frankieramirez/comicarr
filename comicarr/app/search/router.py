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

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import require_session
from comicarr.app.search import service as search_service

router = APIRouter(prefix="/api/search", tags=["search"])


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
    """Get provider search statistics."""
    return search_service.get_provider_stats(ctx)
