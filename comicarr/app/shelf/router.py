#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Shelf routes: the print copies an operator owns or wants.

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
    state: str | None = Query(None),
    item_kind: str | None = Query(None),
    item_id: str | None = Query(None),
    storage: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Copies matching every filter given, newest first."""
    try:
        return service.list_copies(
            comic_id=comic_id,
            state=state,
            item_kind=item_kind,
            item_id=item_id,
            storage=storage,
            query=q,
            limit=limit,
            offset=offset,
        )
    except service.CopyError as error:
        return _error(error)


@router.post("/copies", status_code=201)
def create_copy(request_body: dict = None):
    """Add one copy of an issue, an annual or a manga volume."""
    try:
        return service.create_copy(request_body or {})
    except service.CopyError as error:
        return _error(error)


@router.get("/copies/{copy_id}")
def get_copy(copy_id: str):
    copy = service.get_copy(copy_id)
    if copy is None:
        return _error(service.CopyError("copy_not_found", status=404))
    return copy


@router.patch("/copies/{copy_id}")
def update_copy(copy_id: str, request_body: dict = None):
    """Change a copy's state, variant, grade, price, storage or notes."""
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


@router.post("/series/{comic_id}/mark")
def mark_items(comic_id: str, request_body: dict = None):
    """Bulk "Mark on shelf" / "Add to wishlist". Body: ``State`` and ``items``."""
    body = request_body or {}
    try:
        return service.mark_items(comic_id, body.get("State"), body.get("items"))
    except service.CopyError as error:
        return _error(error)


@router.get("/series/{comic_id}")
def series_shelf(comic_id: str):
    """Per-item copy counts for one series, keyed ``issue:ID``, ``annual:ID`` or ``volume:N``."""
    return service.series_shelf(comic_id)


@router.get("/summary")
def summary():
    """Totals across the whole shelf. Money is per currency, in cents."""
    return service.summary()


@router.get("/storage")
def storage_places():
    """Storage names in use, most recently used first."""
    return {"results": service.storage_places()}
