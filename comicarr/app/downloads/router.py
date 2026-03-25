#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Downloads domain router — history, post-processing, DDL queue.

The densest cross-domain junction. Depends on series (status updates),
metadata (tagging), system (notifications) (Phase 6).
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import require_session
from comicarr.app.downloads import service as dl_service

router = APIRouter(prefix="/api/downloads", tags=["downloads"])


# ---------------------------------------------------------------------------
# History endpoints
# ---------------------------------------------------------------------------

@router.get("/history", dependencies=[Depends(require_session)])
def get_history(
    limit: int = Query(None),
    offset: int = Query(0),
    ctx: AppContext = Depends(get_context),
):
    """Get download history with optional pagination."""
    return dl_service.get_history(ctx, limit=limit, offset=offset)


@router.delete("/history", dependencies=[Depends(require_session)])
def clear_history(
    status_type: str = Query(None, alias="status"),
    ctx: AppContext = Depends(get_context),
):
    """Clear download history, optionally filtered by status."""
    return dl_service.clear_history(ctx, status_type=status_type)


# ---------------------------------------------------------------------------
# Post-processing endpoints
# ---------------------------------------------------------------------------

@router.post("/process", dependencies=[Depends(require_session)])
def force_process(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Queue a download for post-processing.

    Supports both standard API calls and ComicRN/APC compatibility.
    """
    if request_body is None:
        request_body = {}

    nzb_name = request_body.get("nzb_name")
    nzb_folder = request_body.get("nzb_folder")

    if not nzb_name:
        return JSONResponse(status_code=400, content={"detail": "Missing nzb_name"})
    if not nzb_folder:
        return JSONResponse(status_code=400, content={"detail": "Missing nzb_folder"})

    result = dl_service.force_process(
        ctx,
        nzb_name=nzb_name,
        nzb_folder=nzb_folder,
        failed=request_body.get("failed", False),
        issueid=request_body.get("issueid"),
        comicid=request_body.get("comicid"),
        ddl=request_body.get("ddl", False),
        oneoff=request_body.get("oneoff", False),
        apc_version=request_body.get("apc_version"),
        comicrn_version=request_body.get("comicrn_version"),
    )

    if not result["success"]:
        return JSONResponse(status_code=500, content={"detail": result.get("error")})
    return result


@router.post("/process/issue", dependencies=[Depends(require_session)])
def process_issue(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Post-process a specific issue."""
    if request_body is None:
        request_body = {}

    comicid = request_body.get("comicid")
    folder = request_body.get("folder")

    if not comicid:
        return JSONResponse(status_code=400, content={"detail": "Missing comicid"})
    if not folder:
        return JSONResponse(status_code=400, content={"detail": "Missing folder"})

    result = dl_service.process_issue(ctx, comicid, folder, issueid=request_body.get("issueid"))
    if not result["success"]:
        return JSONResponse(status_code=500, content={"detail": result.get("error")})
    return result


# ---------------------------------------------------------------------------
# DDL queue endpoints
# ---------------------------------------------------------------------------

@router.get("/queue", dependencies=[Depends(require_session)])
def get_ddl_queue(ctx: AppContext = Depends(get_context)):
    """Get current DDL download queue."""
    return dl_service.get_ddl_queue(ctx)


@router.post("/{item_id}/requeue", dependencies=[Depends(require_session)])
def requeue_ddl_item(item_id: str, ctx: AppContext = Depends(get_context)):
    """Requeue a failed DDL download."""
    result = dl_service.requeue_ddl_item(ctx, item_id)
    if not result["success"]:
        return JSONResponse(status_code=404, content={"detail": result.get("error")})
    return result


@router.delete("/{item_id}", dependencies=[Depends(require_session)])
def delete_ddl_item(item_id: str, ctx: AppContext = Depends(get_context)):
    """Remove an item from the DDL queue."""
    return dl_service.delete_ddl_item(ctx, item_id)
