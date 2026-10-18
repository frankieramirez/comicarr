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
from starlette.responses import FileResponse

from comicarr.app.core.security import require_session
from comicarr.app.downloads import service as dl_service

router = APIRouter(prefix="/api/downloads", tags=["downloads"])


@router.get("/history", dependencies=[Depends(require_session)])
def get_history(
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str = Query(None, max_length=200),
    status: str = Query(None, max_length=50),
    sort: str = Query("date"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
):
    """Get searchable, sortable download history."""
    return dl_service.get_history(
        limit=limit,
        offset=offset,
        search=q,
        status=status,
        sort=sort,
        order=order,
    )


@router.delete("/history", dependencies=[Depends(require_session)])
def clear_history(
    status_type: str = Query(None, alias="status"),
):
    """Clear download history, optionally filtered by status."""
    return dl_service.clear_history(status_type=status_type)


@router.post("/process", dependencies=[Depends(require_session)])
def force_process(
    request_body: dict = None,
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
        return JSONResponse(status_code=result.get("status_code", 500), content={"detail": result.get("error")})
    return result


@router.post("/process/issue", dependencies=[Depends(require_session)])
def process_issue(
    request_body: dict = None,
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

    result = dl_service.process_issue(comicid, folder, issueid=request_body.get("issueid"))
    if not result["success"]:
        return JSONResponse(status_code=result.get("status_code", 500), content={"detail": result.get("error")})
    return result


@router.get("/queue", dependencies=[Depends(require_session)])
def get_ddl_queue(
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str = Query(None, max_length=200),
    status: str = Query(None, max_length=50),
    sort: str = Query("updated"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
):
    """Get the searchable, sortable active DDL download queue."""
    return dl_service.get_ddl_queue(
        limit=limit,
        offset=offset,
        search=q,
        status=status,
        sort=sort,
        order=order,
    )


@router.post("/{item_id}/requeue", dependencies=[Depends(require_session)])
def requeue_ddl_item(item_id: str):
    """Requeue a failed DDL download."""
    result = dl_service.requeue_ddl_item(item_id)
    if not result["success"]:
        if result.get("not_found"):
            status_code = 404
        elif result.get("validation_error"):
            status_code = 400
        elif result.get("handoff_error"):
            status_code = 503
        else:
            status_code = 500
        return JSONResponse(status_code=status_code, content={"detail": result.get("error")})
    return result


@router.post("/ddl", dependencies=[Depends(require_session)])
def queue_ddl_download(
    request_body: dict = None,
):
    """Queue a direct download link for processing."""
    if request_body is None:
        request_body = {}

    result = dl_service.queue_ddl_download(request_body)
    if not result["success"]:
        if result.get("validation_error"):
            status_code = 400
        elif result.get("handoff_error"):
            status_code = 503
        else:
            status_code = 500
        return JSONResponse(status_code=status_code, content={"detail": result.get("error")})
    return result


@router.delete("/{item_id}", dependencies=[Depends(require_session)])
def delete_ddl_item(item_id: str):
    """Remove an item from the DDL queue."""
    return dl_service.delete_ddl_item(item_id)


@router.get("/file/{issue_id}", dependencies=[Depends(require_session)])
def download_file(issue_id: str):
    """Serve a downloaded issue file.

    Looks up the file location from the database, validates the path
    is within allowed directories, and streams the file.
    """
    import comicarr
    from comicarr.app.common.library_roots import is_servable_library_file

    pathfile, filename = dl_service.get_issue_file_path(issue_id)
    if pathfile is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "File not found for issue: %s" % issue_id},
        )

    if not is_servable_library_file(pathfile, comicarr.CONFIG):
        return JSONResponse(
            status_code=403,
            content={"detail": "File path outside allowed directories"},
        )

    return FileResponse(
        path=pathfile,
        filename=filename,
        media_type="application/octet-stream",
    )
