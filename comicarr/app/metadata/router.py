#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Metadata domain router — comic search, metadata lookup, metatag operations.

Low cross-domain dependency, well-bounded. Validates the domain pattern.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse, Response

from comicarr import logger
from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.exceptions import NotFoundError
from comicarr.app.core.security import require_session
from comicarr.app.metadata import service as metadata_service
from comicarr.app.metadata.image_fetch import fetch_allowed_image

router = APIRouter(prefix="/api/metadata", tags=["metadata"])


@router.post("/search", dependencies=[Depends(require_session)])
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

    result = metadata_service.search_comics(
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


@router.post("/search/manga", dependencies=[Depends(require_session)])
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

    result = metadata_service.search_manga(
        ctx,
        name=name,
        limit=request_body.get("limit"),
        offset=request_body.get("offset"),
        sort=request_body.get("sort"),
    )

    if isinstance(result, dict) and "error" in result:
        return JSONResponse(status_code=400, content={"detail": result["error"]})

    return result


@router.get("/comic/{comic_id}", dependencies=[Depends(require_session)])
def get_comic_info(comic_id: str, ctx: AppContext = Depends(get_context)):
    """Get comic metadata from database."""
    result = metadata_service.get_comic_info(ctx, comic_id)
    if result is None:
        raise NotFoundError("No comic found with ID: %s" % comic_id)
    return result


@router.get("/issue/{issue_id}", dependencies=[Depends(require_session)])
def get_issue_info(issue_id: str, ctx: AppContext = Depends(get_context)):
    """Get issue metadata from database."""
    result = metadata_service.get_issue_info(ctx, issue_id)
    if result is None:
        raise NotFoundError("No issue found with ID: %s" % issue_id)
    return result


@router.get("/art/{comic_id}", dependencies=[Depends(require_session)])
def get_artwork(comic_id: str, ctx: AppContext = Depends(get_context)):
    """Get or cache comic cover artwork. Returns the image file."""
    image_path = metadata_service.get_artwork(ctx, comic_id)
    if image_path is None:
        raise NotFoundError("No artwork found for comic: %s" % comic_id)
    return FileResponse(image_path, media_type="image/jpeg")


@router.get("/image-proxy", dependencies=[Depends(require_session)])
def image_proxy(url: str = Query(..., description="External image URL to proxy")):
    """Proxy external cover images to avoid CORS issues.

    Only allows requests to known metadata CDNs (shared allowlist with get_artwork).
    """
    result = fetch_allowed_image(url)
    if result is None:
        from comicarr.app.metadata.image_fetch import is_allowed_image_url

        if not is_allowed_image_url(url):
            return JSONResponse({"error": "Domain not allowed"}, status_code=403)
        logger.error("[IMAGE-PROXY] Failed to fetch %s" % url)
        return JSONResponse({"error": "Failed to fetch image"}, status_code=502)

    content, content_type = result
    return Response(content=content, media_type=content_type)


@router.get("/series-image/{series_id}", dependencies=[Depends(require_session)])
def get_series_image(series_id: str, ctx: AppContext = Depends(get_context)):
    """Get cover image URL for a Metron series (lazy loading)."""
    image_url = metadata_service.get_series_image(ctx, series_id)
    return {"image": image_url}


@router.post("/metatag", dependencies=[Depends(require_session)])
def metatag_issue(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Tag metadata for a single issue."""
    if request_body is None:
        request_body = {}

    issue_id = request_body.get("issue_id")
    comic_id = request_body.get("comic_id")

    if not issue_id:
        return JSONResponse(status_code=400, content={"detail": "Missing issue_id"})

    result = metadata_service.manual_metatag(ctx, issue_id, comic_id)
    if not result["success"]:
        return JSONResponse(status_code=500, content={"detail": result.get("error", "Metatag failed")})
    return result


@router.post("/metatag/bulk", dependencies=[Depends(require_session)])
def metatag_bulk(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Tag metadata for multiple issues in a series."""
    if request_body is None:
        request_body = {}

    comic_id = request_body.get("comic_id")
    issue_ids = request_body.get("issue_ids", [])

    if not comic_id:
        return JSONResponse(status_code=400, content={"detail": "Missing comic_id"})
    if not issue_ids:
        return JSONResponse(status_code=400, content={"detail": "Missing issue_ids"})

    if isinstance(issue_ids, str):
        issue_ids = [iid.strip() for iid in issue_ids.split(",") if iid.strip()]

    result = metadata_service.bulk_metatag(ctx, comic_id, issue_ids)
    if not result["success"]:
        return JSONResponse(status_code=500, content={"detail": result.get("error", "Bulk metatag failed")})
    return result


@router.post("/metatag/group", dependencies=[Depends(require_session)])
def metatag_group(
    request_body: dict = None,
    ctx: AppContext = Depends(get_context),
):
    """Tag metadata for all issues in a series."""
    if request_body is None:
        request_body = {}

    comic_id = request_body.get("comic_id")
    if not comic_id:
        return JSONResponse(status_code=400, content={"detail": "Missing comic_id"})

    result = metadata_service.group_metatag(ctx, comic_id)
    if not result["success"]:
        return JSONResponse(status_code=500, content={"detail": result.get("error", "Group metatag failed")})
    return result
