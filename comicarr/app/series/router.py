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

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.exceptions import NotFoundError
from comicarr.app.core.security import COOKIE_NAME, require_api_key, require_session
from comicarr.app.imports import finalization as import_finalization
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


# ---------------------------------------------------------------------------
# Bulk series operations
# ---------------------------------------------------------------------------

MAX_BULK_IDS = 100


def _validate_bulk_ids(request_body):
    """Validate and extract IDs from a bulk operation request body."""
    if not isinstance(request_body, dict):
        return None, JSONResponse(status_code=422, content={"detail": "Request body must be a JSON object"})
    ids = request_body.get("ids")
    if not ids or not isinstance(ids, list):
        return None, JSONResponse(status_code=400, content={"detail": "Missing ids array"})
    if len(ids) > MAX_BULK_IDS:
        return None, JSONResponse(
            status_code=422, content={"detail": "Maximum %d IDs per bulk operation" % MAX_BULK_IDS}
        )
    if not all(isinstance(i, str) and i.strip() for i in ids):
        return None, JSONResponse(status_code=422, content={"detail": "All IDs must be non-empty strings"})
    return ids, None


@router.post("/series/bulk-delete", dependencies=[Depends(require_session)])
def bulk_delete_series(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Delete multiple series at once."""
    ids, error = _validate_bulk_ids(request_body)
    if error:
        return error

    results = []
    for comic_id in ids:
        result = series_service.delete_comic(ctx, comic_id)
        results.append({"id": comic_id, "success": result.get("success", False)})

    succeeded = sum(1 for r in results if r["success"])
    return {"success": succeeded > 0, "deleted": succeeded, "total": len(ids), "results": results}


@router.post("/series/bulk-pause", dependencies=[Depends(require_session)])
def bulk_pause_series(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Pause multiple series at once."""
    ids, error = _validate_bulk_ids(request_body)
    if error:
        return error

    for comic_id in ids:
        series_service.pause_comic(ctx, comic_id)

    return {"success": True, "count": len(ids)}


@router.post("/series/bulk-resume", dependencies=[Depends(require_session)])
def bulk_resume_series(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Resume multiple series at once."""
    ids, error = _validate_bulk_ids(request_body)
    if error:
        return error

    for comic_id in ids:
        series_service.resume_comic(ctx, comic_id)

    return {"success": True, "count": len(ids)}


@router.post("/series/{comic_id}/refresh", dependencies=[Depends(require_session)])
def refresh_series(comic_id: str, ctx: AppContext = Depends(get_context)):
    """Refresh series metadata from provider."""
    result = series_service.refresh_comic(ctx, comic_id)
    if not result["success"]:
        return JSONResponse(status_code=400, content={"detail": result.get("error")})
    return result


def _session_identity(request: Request, username: str):
    """Bind one-shot mutating previews to the authenticated browser session."""
    return request.cookies.get(COOKIE_NAME) or username


@router.get("/series/{comic_id}/search-missing/preview", dependencies=[Depends(require_session)])
def preview_search_all_missing(
    comic_id: str,
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Preview eligible/excluded counts for series-scoped Search all missing."""
    result = series_service.preview_search_all_missing(
        ctx,
        comic_id,
        actor=username,
        session_id=_session_identity(request, username),
    )
    if result.get("success") is False:
        return JSONResponse(status_code=int(result.get("status_code") or 400), content=result)
    return result


@router.post("/series/{comic_id}/search-missing", dependencies=[Depends(require_session)])
async def search_all_missing(
    comic_id: str,
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Queue eligible missing issues once and coalesce a durable search run."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    confirm = bool(body.get("confirm"))
    result = series_service.search_all_missing(
        ctx,
        comic_id,
        audit_identity=username,
        confirm=confirm,
        preview_token=body.get("preview_token") or body.get("previewToken"),
        fingerprint=body.get("fingerprint"),
        session_id=_session_identity(request, username),
    )
    if result.get("success") is False:
        return JSONResponse(status_code=int(result.get("status_code") or 400), content=result)
    return result


# ---------------------------------------------------------------------------
# Issue management
# ---------------------------------------------------------------------------


@router.put("/series/issues/{issue_id}/queue")
def queue_issue(
    issue_id: str,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Mark an issue as Wanted and trigger search."""
    return series_service.queue_issue(ctx, issue_id, audit_identity=username)


@router.put("/series/issues/{issue_id}/unqueue")
def unqueue_issue(
    issue_id: str,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Mark an issue as Skipped."""
    return series_service.unqueue_issue(ctx, issue_id, audit_identity=username)


@router.get("/series/issues/{issue_id}/search-preview", dependencies=[Depends(require_session)])
def preview_wanted_issue_search(
    issue_id: str,
    request: Request,
    username: str = Depends(require_session),
):
    result = series_service.preview_wanted_issue(
        issue_id,
        actor=username,
        session_id=_session_identity(request, username),
    )
    if result.get("success") is False:
        return JSONResponse(status_code=int(result.get("status_code") or 400), content=result)
    return result


@router.post("/series/issues/{issue_id}/search", dependencies=[Depends(require_session)])
async def search_one_wanted_issue(
    issue_id: str,
    request: Request,
    username: str = Depends(require_session),
):
    try:
        body = await request.json()
    except Exception:
        body = {}
    result = series_service.search_wanted_issue(
        issue_id,
        username,
        preview_token=(body or {}).get("preview_token"),
        fingerprint=(body or {}).get("fingerprint"),
        session_id=_session_identity(request, username),
    )
    if result.get("success") is False:
        return JSONResponse(status_code=int(result.get("status_code") or 400), content=result)
    return result


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


def _normalize_match_import_ids(imp_ids):
    """Normalize import IDs while preserving the legacy empty-match response."""
    if isinstance(imp_ids, str):
        imp_ids = imp_ids.split(",")

    normalized = []
    seen = set()
    for imp_id in imp_ids:
        if imp_id is None:
            continue
        imp_id = str(imp_id).strip()
        if imp_id and imp_id not in seen:
            normalized.append(imp_id)
            seen.add(imp_id)
    return normalized


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

    issue_id = request_body.get("issue_id")
    comic_name = request_body.get("comic_name")
    imp_ids = _normalize_match_import_ids(imp_ids)
    if not imp_ids:
        return {
            "success": True,
            "matched": 0,
            "imported": 0,
            "comic_id": comic_id,
            "comic_name": series_queries.get_comic_name(comic_id) or comic_name or "Unknown",
            "moved": 0,
            "archived": 0,
        }

    try:
        result = import_finalization.finalize_manual_match(
            ctx,
            imp_ids,
            comic_id,
            series_name=comic_name,
            fallback_issue_id=issue_id,
        )
    except import_finalization.ImportFinalizationError as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
    return {
        "success": True,
        "matched": result.matched,
        "imported": result.matched,
        "comic_id": result.series_id,
        "comic_name": result.series_name,
        "moved": result.moved,
        "archived": result.archived,
    }


@router.patch("/import/{imp_id}", dependencies=[Depends(require_session)])
def update_import_metadata(
    imp_id: str,
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Update editable metadata for one pending import file."""
    if request_body is None:
        request_body = {}

    if "issue_number" not in request_body:
        return JSONResponse(status_code=400, content={"detail": "Missing issue_number"})

    result = series_service.update_import_metadata(ctx, imp_id, request_body.get("issue_number"))
    if not result.get("success"):
        if result.get("not_found"):
            status = 404
        elif result.get("imported"):
            status = 409
        else:
            status = 400
        return JSONResponse(status_code=status, content={"detail": result.get("error")})
    return result


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


@router.post("/import/manga/scan", dependencies=[Depends(require_session)])
def manga_scan(ctx: AppContext = Depends(get_context)):
    """Trigger a manga library scan."""
    result = series_service.manga_library_scan(ctx)
    if not result["success"]:
        return JSONResponse(status_code=400, content={"detail": result.get("error")})
    return result


@router.get("/import/manga/progress", dependencies=[Depends(require_session)])
def manga_scan_progress(ctx: AppContext = Depends(get_context)):
    """Get manga scan progress."""
    from comicarr import mangasync

    return mangasync.get_scan_progress()


@router.post("/import/manga/confirm", dependencies=[Depends(require_session)])
def manga_scan_confirm(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Confirm and import selected manga from scan results."""
    if request_body is None:
        request_body = {}

    selected_ids = request_body.get("selected_ids", [])
    scan_id = request_body.get("scan_id")

    if not isinstance(selected_ids, list) or not all(isinstance(i, str) for i in selected_ids):
        return JSONResponse(status_code=400, content={"detail": "selected_ids must be a list of strings"})
    if not selected_ids:
        return JSONResponse(status_code=400, content={"detail": "No series selected"})
    if not scan_id or not isinstance(scan_id, str):
        return JSONResponse(status_code=400, content={"detail": "Missing or invalid scan_id"})

    result = series_service.manga_scan_confirm(ctx, selected_ids, scan_id)
    if not result["success"]:
        status = 409 if result.get("stale") else 400
        return JSONResponse(status_code=status, content={"detail": result.get("error")})
    return result


@router.post("/import/comic/scan", dependencies=[Depends(require_session)])
def comic_scan(ctx: AppContext = Depends(get_context)):
    """Trigger a comic library scan."""
    result = series_service.comic_library_scan(ctx)
    if not result["success"]:
        return JSONResponse(status_code=400, content={"detail": result.get("error")})
    return result


@router.get("/import/comic/progress", dependencies=[Depends(require_session)])
def comic_scan_progress(ctx: AppContext = Depends(get_context)):
    """Get comic scan progress."""
    from comicarr import comicsync

    return comicsync.get_scan_progress()


@router.post("/import/comic/confirm", dependencies=[Depends(require_session)])
def comic_scan_confirm(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Confirm and import selected comics from scan results."""
    if request_body is None:
        request_body = {}

    selected_ids = request_body.get("selected_ids", [])
    scan_id = request_body.get("scan_id")

    if not isinstance(selected_ids, list) or not all(isinstance(i, str) for i in selected_ids):
        return JSONResponse(status_code=400, content={"detail": "selected_ids must be a list of strings"})
    if not selected_ids:
        return JSONResponse(status_code=400, content={"detail": "No series selected"})
    if not scan_id or not isinstance(scan_id, str):
        return JSONResponse(status_code=400, content={"detail": "Missing or invalid scan_id"})

    result = series_service.comic_scan_confirm(ctx, selected_ids, scan_id)
    if not result["success"]:
        status = 409 if result.get("stale") else 400
        return JSONResponse(status_code=status, content={"detail": result.get("error")})
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
