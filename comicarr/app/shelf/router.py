#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Shelf routes: the print copies an operator owns.

Errors carry a stable ``code`` (and ``field`` where one is at fault) for the
UI to translate; ``detail`` repeats the code.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from comicarr.app.core.security import require_session
from comicarr.app.shelf import service

router = APIRouter(prefix="/api/shelf", tags=["shelf"], dependencies=[Depends(require_session)])


def _error(error: service.CopyError) -> JSONResponse:
    return JSONResponse(status_code=error.status, content=error.as_dict())


@router.get("/copies")
def list_copies(
    comic_id: str | None = Query(None),
    item_id: str | None = Query(None),
    volume_number: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Copies matching every filter given, newest first."""
    return service.list_copies(
        comic_id=comic_id, item_id=item_id, volume_number=volume_number, query=q, limit=limit, offset=offset
    )


@router.post("/copies", status_code=201)
def create_copy(request_body: dict = None):
    """Add one copy of an issue, an annual or a manga volume."""
    try:
        return service.create_copy(request_body or {})
    except service.CopyError as error:
        return _error(error)


@router.patch("/copies/{copy_id}")
def update_copy(copy_id: str, request_body: dict = None):
    """Change a copy's variant, grade, price, storage or notes."""
    try:
        return service.update_copy(copy_id, request_body or {})
    except service.CopyError as error:
        return _error(error)


@router.delete("/copies/{copy_id}", status_code=204)
def delete_copy(copy_id: str):
    try:
        service.delete_copy(copy_id)
    except service.CopyError as error:
        return _error(error)
    return Response(status_code=204)


@router.get("/export.csv")
def export_csv():
    """The whole shelf as a spreadsheet file."""
    return Response(
        service.export_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="comicarr-shelf.csv"', "Cache-Control": "no-store"},
    )


@router.get("/series/{comic_id}")
def series_shelf(comic_id: str):
    """Copy counts for one series: ``issues`` by id and ``volumes`` by number."""
    return service.series_shelf(comic_id)


@router.post("/series/{comic_id}/mark")
def mark_items(comic_id: str, request_body: dict = None):
    """Bulk "Mark on shelf". Body: ``ItemIDs`` and ``VolumeNumbers``."""
    try:
        return service.mark_items(comic_id, request_body or {})
    except service.CopyError as error:
        return _error(error)
