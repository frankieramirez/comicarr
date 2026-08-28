#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Canonical HTTP interface for Needs attention."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from comicarr.app.attention import (
    PREVIEW_CAP,
    PROBLEM_STATUS,
    ImportSource,
    InvalidAttentionRequest,
    ResolutionRequest,
    Scope,
    read,
    resolve,
)
from comicarr.app.attention._serialization import serialize_view as _serialize_view
from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import require_session

router = APIRouter(prefix="/api/attention", tags=["attention"])


def serialize_view(view):
    """Serialize a domain view; preview policy belongs to the HTTP adapter."""
    return _serialize_view(view, preview_cap=PREVIEW_CAP)


def _scope_from_query(scope_type, scope_id):
    if scope_type is None and scope_id is None:
        return None
    return Scope(type=scope_type or "", id=scope_id or "")


def _item_wire(item):
    return {
        "release_key": item.release_key,
        "ok": item.ok,
        "status": item.status,
        "error": None if item.ok else item.message,
        "status_code": None if item.ok else PROBLEM_STATUS.get(item.problem, 500),
    }


def serialize_report(report):
    """Serialize one-or-many resolution outcomes into the stable wire shape."""
    body = {
        "success": report.success,
        "partial": report.partial,
        "action": report.action,
        "requested": report.requested,
        "processed": report.processed,
        "succeeded": report.succeeded,
        "failed": report.failed,
        "capped": report.capped,
        "skipped_for_cap": report.skipped_for_cap,
        "cap": report.cap,
        "results": [_item_wire(item) for item in report.results],
    }
    if not report.success:
        body["error"] = "No rows could be resolved"
        body["detail"] = body["error"]
    return body


def _resolution_request(body, actor):
    source_body = body.get("import_source")
    if source_body is None:
        source = None
    elif isinstance(source_body, dict):
        unknown = set(source_body) - {"nzb_name", "nzb_folder"}
        if unknown:
            raise InvalidAttentionRequest("unknown import_source fields")
        source = ImportSource(
            nzb_name=source_body.get("nzb_name"),
            nzb_folder=source_body.get("nzb_folder"),
        )
    else:
        raise InvalidAttentionRequest("import_source must be an object")
    return ResolutionRequest(
        action=body.get("action"),
        release_keys=body.get("release_keys") or (),
        actor=actor,
        import_source=source,
    )


@router.get("", dependencies=[Depends(require_session)])
def get_attention(
    scope_type: str | None = Query(None, max_length=32),
    scope_id: str | None = Query(None, max_length=255),
):
    """Return unresolved actionable obligations grouped for operator triage."""
    try:
        view = read(scope=_scope_from_query(scope_type, scope_id))
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return serialize_view(view)


@router.post("/resolve")
def resolve_attention(
    request_body: dict,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Apply one operator action to one or many admitted obligations."""
    try:
        report = resolve(ctx, _resolution_request(request_body, username))
    except InvalidAttentionRequest as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    body = serialize_report(report)
    if report.success:
        return body
    return JSONResponse(status_code=409, content=body)
