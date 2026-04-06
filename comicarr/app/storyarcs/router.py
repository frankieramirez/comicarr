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

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from comicarr.app.core.exceptions import NotFoundError
from comicarr.app.core.security import require_session
from comicarr.app.storyarcs import service as arc_service

router = APIRouter(prefix="/api", tags=["storyarcs"])


# ---------------------------------------------------------------------------
# Story arc endpoints
# ---------------------------------------------------------------------------


@router.post("/storyarcs/generate", dependencies=[Depends(require_session)])
async def generate_story_arc(request: Request):
    """Generate a reading order from a natural language arc description using AI."""
    from comicarr.app.ai import story_arcs

    body = await request.json()
    description = body.get("description", "")

    if not description or len(description.strip()) < 3:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Description must be at least 3 characters"},
        )

    # Generate reading order via AI
    result = story_arcs.generate_reading_order(description)
    if not result["success"]:
        return JSONResponse(content=result)

    # Enrich with provider data (ComicVine match)
    issues = story_arcs.enrich_with_providers(result["issues"])

    # Map against user's library
    issues = story_arcs.map_to_library(issues)

    return JSONResponse(content={"success": True, "issues": issues, "description": description})


@router.post("/storyarcs/generate/save", dependencies=[Depends(require_session)])
async def save_generated_arc(request: Request):
    """Save a previously generated reading order to the storyarcs table."""
    from comicarr.app.ai import story_arcs

    body = await request.json()
    arc_name = body.get("arc_name", "")
    issues = body.get("issues", [])

    if not arc_name or not issues:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "arc_name and issues are required"},
        )

    result = story_arcs.save_arc(arc_name, issues)
    return JSONResponse(content=result)


@router.get("/storyarcs", dependencies=[Depends(require_session)])
def list_story_arcs(
    custom_only: bool = Query(False, alias="customOnly"),
):
    """List all tracked story arcs with aggregated stats."""
    return arc_service.list_arcs(custom_only=custom_only)


@router.get("/storyarcs/{arc_id}", dependencies=[Depends(require_session)])
def get_story_arc(arc_id: str):
    """Get a single story arc with all issues in reading order."""
    result = arc_service.get_arc_detail(arc_id)
    if result is None:
        raise NotFoundError("Story arc not found")
    return result


@router.delete("/storyarcs/{arc_id}", dependencies=[Depends(require_session)])
def delete_story_arc(arc_id: str):
    """Delete an entire story arc."""
    return arc_service.delete_arc(arc_id)


@router.put(
    "/storyarcs/{arc_id}/issues/{issue_arc_id}/status",
    dependencies=[Depends(require_session)],
)
def set_arc_issue_status(
    arc_id: str,
    issue_arc_id: str,
    request_body: dict = None,
):
    """Set the status of an individual arc issue."""
    if request_body is None:
        request_body = {}

    status = request_body.get("status", "")
    if not status:
        return JSONResponse(status_code=400, content={"detail": "Missing status"})

    result = arc_service.set_issue_status(issue_arc_id, status)
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
):
    """Remove a single issue from a story arc (soft-delete)."""
    return arc_service.delete_arc_issue(issue_arc_id)


@router.post("/storyarcs/{arc_id}/want-all", dependencies=[Depends(require_session)])
def want_all_arc_issues(arc_id: str):
    """Mark all non-downloaded arc issues as Wanted and trigger search."""
    return arc_service.want_all_issues(arc_id)


@router.post("/storyarcs/{arc_id}/refresh", dependencies=[Depends(require_session)])
def refresh_story_arc(arc_id: str):
    """Refresh a story arc from ComicVine."""
    result = arc_service.refresh_arc(arc_id)
    if not result["success"]:
        return JSONResponse(status_code=404, content={"detail": result.get("error")})
    return result


# ---------------------------------------------------------------------------
# Reading list endpoints
# ---------------------------------------------------------------------------


@router.get("/readlist", dependencies=[Depends(require_session)])
def get_readlist():
    """Get all reading list entries."""
    return arc_service.get_readlist()


@router.post("/readlist", dependencies=[Depends(require_session)])
def add_to_readlist(
    request_body: dict = None,
):
    """Add an issue to the reading list."""
    if request_body is None:
        request_body = {}

    issue_id = request_body.get("issue_id")
    if not issue_id:
        return JSONResponse(status_code=400, content={"detail": "Missing issue_id"})

    return arc_service.add_to_readlist(issue_id)


@router.delete("/readlist/{issue_id}", dependencies=[Depends(require_session)])
def remove_from_readlist(issue_id: str):
    """Remove an issue from the reading list."""
    return arc_service.remove_from_readlist(issue_id)


@router.delete("/readlist", dependencies=[Depends(require_session)])
def clear_read_issues():
    """Remove all issues marked as Read from the reading list."""
    return arc_service.clear_read_issues()


# ---------------------------------------------------------------------------
# Upcoming endpoints
# ---------------------------------------------------------------------------


@router.get("/upcoming", dependencies=[Depends(require_session)])
def get_upcoming(
    include_downloaded: bool = Query(False, alias="include_downloaded_issues"),
):
    """Get upcoming issues for the current week."""
    return arc_service.get_upcoming(include_downloaded=include_downloaded)
