#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Story Arcs domain router — arc CRUD, reading list, upcoming endpoints.

Small, well-bounded, minimal cross-domain dependencies (Phase 3).
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.exceptions import NotFoundError
from comicarr.app.core.security import require_session
from comicarr.app.storyarcs import service as arc_service

router = APIRouter(prefix="/api", tags=["storyarcs"])


# ---------------------------------------------------------------------------
# Story arc endpoints
# ---------------------------------------------------------------------------


@router.get("/storyarcs", dependencies=[Depends(require_session)])
def list_story_arcs(
    custom_only: bool = Query(False, alias="customOnly"),
    ctx: AppContext = Depends(get_context),
):
    """List all tracked story arcs with aggregated stats."""
    return arc_service.list_arcs(ctx, custom_only=custom_only)


@router.get("/storyarcs/{arc_id}", dependencies=[Depends(require_session)])
def get_story_arc(arc_id: str, ctx: AppContext = Depends(get_context)):
    """Get a single story arc with all issues in reading order."""
    result = arc_service.get_arc_detail(ctx, arc_id)
    if result is None:
        raise NotFoundError("Story arc not found")
    return result


@router.delete("/storyarcs/{arc_id}", dependencies=[Depends(require_session)])
def delete_story_arc(arc_id: str, ctx: AppContext = Depends(get_context)):
    """Delete an entire story arc."""
    return arc_service.delete_arc(ctx, arc_id)


@router.put(
    "/storyarcs/{arc_id}/issues/{issue_arc_id}/status",
    dependencies=[Depends(require_session)],
)
def set_arc_issue_status(
    arc_id: str,
    issue_arc_id: str,
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Set the status of an individual arc issue."""
    if request_body is None:
        request_body = {}

    status = request_body.get("status", "")
    if not status:
        return JSONResponse(status_code=400, content={"detail": "Missing status"})

    result = arc_service.set_issue_status(ctx, issue_arc_id, status)
    if not result["success"]:
        return JSONResponse(status_code=400, content={"detail": result.get("error")})
    return result


@router.delete(
    "/storyarcs/{arc_id}/issues/{issue_arc_id}",
    dependencies=[Depends(require_session)],
)
def delete_arc_issue(
    arc_id: str,
    issue_arc_id: str,
    ctx: AppContext = Depends(get_context),
):
    """Remove a single issue from a story arc (soft-delete)."""
    return arc_service.delete_arc_issue(ctx, issue_arc_id)


@router.post("/storyarcs/{arc_id}/want-all", dependencies=[Depends(require_session)])
def want_all_arc_issues(arc_id: str, ctx: AppContext = Depends(get_context)):
    """Mark all non-downloaded arc issues as Wanted and trigger search."""
    return arc_service.want_all_issues(ctx, arc_id)


@router.post("/storyarcs/{arc_id}/refresh", dependencies=[Depends(require_session)])
def refresh_story_arc(arc_id: str, ctx: AppContext = Depends(get_context)):
    """Refresh a story arc from ComicVine."""
    result = arc_service.refresh_arc(ctx, arc_id)
    if not result["success"]:
        return JSONResponse(status_code=404, content={"detail": result.get("error")})
    return result


# ---------------------------------------------------------------------------
# Reading list endpoints
# ---------------------------------------------------------------------------


@router.get("/readlist", dependencies=[Depends(require_session)])
def get_readlist(ctx: AppContext = Depends(get_context)):
    """Get all reading list entries."""
    return arc_service.get_readlist(ctx)


@router.post("/readlist", dependencies=[Depends(require_session)])
def add_to_readlist(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Add an issue to the reading list."""
    if request_body is None:
        request_body = {}

    issue_id = request_body.get("issue_id")
    if not issue_id:
        return JSONResponse(status_code=400, content={"detail": "Missing issue_id"})

    return arc_service.add_to_readlist(ctx, issue_id)


@router.delete("/readlist/{issue_id}", dependencies=[Depends(require_session)])
def remove_from_readlist(issue_id: str, ctx: AppContext = Depends(get_context)):
    """Remove an issue from the reading list."""
    return arc_service.remove_from_readlist(ctx, issue_id)


@router.delete("/readlist", dependencies=[Depends(require_session)])
def clear_read_issues(ctx: AppContext = Depends(get_context)):
    """Remove all issues marked as Read from the reading list."""
    return arc_service.clear_read_issues(ctx)


# ---------------------------------------------------------------------------
# Upcoming endpoints
# ---------------------------------------------------------------------------


@router.get("/upcoming", dependencies=[Depends(require_session)])
def get_upcoming(
    include_downloaded: bool = Query(False, alias="include_downloaded_issues"),
    ctx: AppContext = Depends(get_context),
):
    """Get upcoming issues for the current week."""
    return arc_service.get_upcoming(ctx, include_downloaded=include_downloaded)
