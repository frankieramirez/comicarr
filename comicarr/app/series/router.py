#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Series domain router — comic CRUD, issue management, imports.

The core domain. Largest route count but well-understood patterns
established by Phases 1-3 (Phase 4).
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.exceptions import NotFoundError
from comicarr.app.core.security import require_api_key, require_session
from comicarr.app.series import queries as series_queries
from comicarr.app.series import service as series_service

router = APIRouter(prefix="/api", tags=["series"])


# ---------------------------------------------------------------------------
# Series CRUD
# ---------------------------------------------------------------------------

@router.get("/series", dependencies=[Depends(require_session)])
def list_series(
    limit: int = Query(None),
    offset: int = Query(0),
    ctx: AppContext = Depends(get_context),
):
    """List all comic series in the library."""
    return series_service.list_comics(ctx, limit=limit, offset=offset)


@router.get("/series/{comic_id}", dependencies=[Depends(require_session)])
def get_series(comic_id: str, ctx: AppContext = Depends(get_context)):
    """Get a single series with its issues and annuals."""
    result = series_service.get_comic_detail(ctx, comic_id)
    if not result["comic"]:
        raise NotFoundError("Comic not found: %s" % comic_id)
    return result


@router.post("/series", dependencies=[Depends(require_session)])
def add_series(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Add a comic to the watchlist."""
    if request_body is None:
        request_body = {}

    comic_id = request_body.get("id") or request_body.get("comic_id")
    if not comic_id:
        return JSONResponse(status_code=400, content={"detail": "Missing comic id"})

    result = series_service.add_comic(ctx, comic_id)
    if not result["success"]:
        return JSONResponse(status_code=500, content={"detail": result.get("error")})
    return result


@router.delete("/series/{comic_id}", dependencies=[Depends(require_session)])
def delete_series(
    comic_id: str,
    directory: bool = Query(False),
    ctx: AppContext = Depends(get_context),
):
    """Delete a comic series with optional directory deletion."""
    result = series_service.delete_comic(ctx, comic_id, delete_directory=directory)
    if not result["success"]:
        status = 404 if "not found" in result.get("error", "").lower() else 500
        return JSONResponse(status_code=status, content={"detail": result.get("error")})
    return result


@router.put("/series/{comic_id}/pause", dependencies=[Depends(require_session)])
def pause_series(comic_id: str, ctx: AppContext = Depends(get_context)):
    """Pause a comic series."""
    return series_service.pause_comic(ctx, comic_id)


@router.put("/series/{comic_id}/resume", dependencies=[Depends(require_session)])
def resume_series(comic_id: str, ctx: AppContext = Depends(get_context)):
    """Resume a comic series."""
    return series_service.resume_comic(ctx, comic_id)


@router.post("/series/{comic_id}/refresh", dependencies=[Depends(require_session)])
def refresh_series(comic_id: str, ctx: AppContext = Depends(get_context)):
    """Refresh series metadata from provider."""
    result = series_service.refresh_comic(ctx, comic_id)
    if not result["success"]:
        return JSONResponse(status_code=400, content={"detail": result.get("error")})
    return result


# ---------------------------------------------------------------------------
# Issue management
# ---------------------------------------------------------------------------

@router.put("/series/issues/{issue_id}/queue", dependencies=[Depends(require_session)])
def queue_issue(issue_id: str, ctx: AppContext = Depends(get_context)):
    """Mark an issue as Wanted and trigger search."""
    return series_service.queue_issue(ctx, issue_id)


@router.put("/series/issues/{issue_id}/unqueue", dependencies=[Depends(require_session)])
def unqueue_issue(issue_id: str, ctx: AppContext = Depends(get_context)):
    """Mark an issue as Skipped."""
    return series_service.unqueue_issue(ctx, issue_id)


@router.get("/wanted", dependencies=[Depends(require_session)])
def get_wanted(
    limit: int = Query(None),
    offset: int = Query(0),
    story_arcs: bool = Query(False, alias="story_arcs"),
    ctx: AppContext = Depends(get_context),
):
    """Get all wanted issues with optional story arcs and annuals."""
    return series_service.get_wanted(ctx, limit=limit, offset=offset, include_story_arcs=story_arcs)


# ---------------------------------------------------------------------------
# Import management
# ---------------------------------------------------------------------------

@router.get("/import", dependencies=[Depends(require_session)])
def get_import_pending(
    limit: int = Query(50),
    offset: int = Query(0),
    include_ignored: bool = Query(False, alias="include_ignored"),
    ctx: AppContext = Depends(get_context),
):
    """Get pending import files grouped by series."""
    return series_service.get_import_pending(ctx, limit=limit, offset=offset, include_ignored=include_ignored)


@router.post("/import/match", dependencies=[Depends(require_session)])
def match_import(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Manually match import files to a comic series."""
    if request_body is None:
        request_body = {}

    imp_ids = request_body.get("imp_ids", [])
    comic_id = request_body.get("comic_id")

    if not imp_ids:
        return JSONResponse(status_code=400, content={"detail": "Missing imp_ids"})
    if not comic_id:
        return JSONResponse(status_code=400, content={"detail": "Missing comic_id"})

    # Support both list and comma-separated string
    if isinstance(imp_ids, str):
        imp_ids = [iid.strip() for iid in imp_ids.split(",") if iid.strip()]

    issue_id = request_body.get("issue_id")
    return series_service.match_import(ctx, imp_ids, comic_id, issue_id=issue_id)


@router.post("/import/ignore", dependencies=[Depends(require_session)])
def ignore_import(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Mark import files as ignored or unignored."""
    if request_body is None:
        request_body = {}

    imp_ids = request_body.get("imp_ids", [])
    if not imp_ids:
        return JSONResponse(status_code=400, content={"detail": "Missing imp_ids"})

    if isinstance(imp_ids, str):
        imp_ids = [iid.strip() for iid in imp_ids.split(",") if iid.strip()]

    ignore = request_body.get("ignore", True)
    return series_service.ignore_import(ctx, imp_ids, ignore=ignore)


@router.delete("/import", dependencies=[Depends(require_session)])
def delete_import(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Delete import records."""
    if request_body is None:
        request_body = {}

    imp_ids = request_body.get("imp_ids", [])
    if not imp_ids:
        return JSONResponse(status_code=400, content={"detail": "Missing imp_ids"})

    if isinstance(imp_ids, str):
        imp_ids = [iid.strip() for iid in imp_ids.split(",") if iid.strip()]

    return series_service.delete_import(ctx, imp_ids)


@router.post("/import/refresh", dependencies=[Depends(require_session)])
def refresh_import(ctx: AppContext = Depends(get_context)):
    """Trigger an import directory scan."""
    result = series_service.refresh_import(ctx)
    if not result["success"]:
        return JSONResponse(status_code=400, content={"detail": result.get("error")})
    return result


# ---------------------------------------------------------------------------
# REST-compat endpoints (migrated from legacy /rest mount)
# ---------------------------------------------------------------------------

@router.get("/watchlist", dependencies=[Depends(require_api_key("full"))])
def rest_watchlist():
    """Return all comics enriched with havetotals data.

    Migrated from REST.Watchlist — authenticates via X-Api-Key header.
    """
    return series_service.havetotals()


@router.get("/comics", dependencies=[Depends(require_api_key("full"))])
def rest_comics():
    """Return all comics with every column.

    Migrated from REST.Comics — authenticates via X-Api-Key header.
    """
    return series_queries.list_comics_full()


@router.get("/comic/{comic_id}", dependencies=[Depends(require_api_key("full"))])
def rest_comic(comic_id: str):
    """Return a single comic with all columns.

    Migrated from REST.Comic (no nested path) — authenticates via X-Api-Key header.
    """
    match = series_queries.get_comic_full(comic_id)
    if match:
        return match
    return {"error": "No Comic with that ID"}


@router.get("/comic/{comic_id}/issues", dependencies=[Depends(require_api_key("full"))])
def rest_comic_issues(comic_id: str):
    """Return all issues for a comic.

    Migrated from REST.Comic with issuemode='issues'.
    """
    return series_queries.get_issues_full(comic_id)


@router.get("/comic/{comic_id}/issue/{issue_id}", dependencies=[Depends(require_api_key("full"))])
def rest_comic_issue(comic_id: str, issue_id: str):
    """Return a single issue by comic and issue ID.

    Migrated from REST.Comic with issuemode='issue' and issue_id.
    """
    return series_queries.get_issue_full(comic_id, issue_id)
