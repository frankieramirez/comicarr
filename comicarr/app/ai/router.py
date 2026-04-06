#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
AI domain router — status, connection testing, activity feed.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from comicarr.app.ai import service as ai_service
from comicarr.app.core.security import require_session

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status", dependencies=[Depends(require_session)])
async def ai_status():
    """Return AI configuration and usage status."""
    status = ai_service.get_ai_status()
    return JSONResponse(content=status)


@router.post("/test", dependencies=[Depends(require_session)])
async def ai_test(request: Request):
    """Test an AI connection with provided credentials."""
    body = await request.json()
    base_url = body.get("base_url", "")
    api_key = body.get("api_key", "")
    model = body.get("model", "")

    if not base_url or not api_key or not model:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "base_url, api_key, and model are required"},
        )

    result = ai_service.test_connection(base_url, api_key, model)
    return JSONResponse(content=result)


@router.get("/activity", dependencies=[Depends(require_session)])
async def ai_activity(limit: int = 50, offset: int = 0):
    """Return AI activity feed entries."""
    entries = ai_service.get_activity(limit=limit, offset=offset)
    return JSONResponse(content={"entries": entries})
