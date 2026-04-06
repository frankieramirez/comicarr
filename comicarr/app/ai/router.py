#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
AI domain router — status, connection testing, activity feed, library chat.
"""

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from comicarr.app.ai import service as ai_service
from comicarr.app.ai.chat import stream_chat_response
from comicarr.app.core.context import AppContext, get_context
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


@router.post("/chat/stream", dependencies=[Depends(require_session)])
async def chat_stream(request: Request, ctx: AppContext = Depends(get_context)):
    """Stream a chat response via Server-Sent Events.

    Expects JSON body: {"messages": [{"role": "user", "content": "..."}]}
    Yields SSE events with type: text | results | error | done.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON body"},
        )

    messages = body.get("messages", [])
    if not messages or not isinstance(messages, list):
        return JSONResponse(
            status_code=400,
            content={"error": "messages array is required"},
        )

    # Validate message structure
    for msg in messages:
        if not isinstance(msg, dict):
            return JSONResponse(
                status_code=400,
                content={"error": "Each message must be an object with role and content"},
            )
        if msg.get("role") not in ("user", "assistant"):
            return JSONResponse(
                status_code=400,
                content={"error": "Message role must be 'user' or 'assistant'"},
            )
        if not msg.get("content"):
            return JSONResponse(
                status_code=400,
                content={"error": "Message content must not be empty"},
            )

    # Cap conversation length to prevent abuse
    if len(messages) > 20:
        messages = messages[-20:]

    async def generator():
        async for event in stream_chat_response(messages, ctx):
            yield json.dumps(event)

    return EventSourceResponse(generator(), media_type="text/event-stream")


@router.get("/suggestions", dependencies=[Depends(require_session)])
async def ai_suggestions():
    """Return cached AI-generated pull list suggestions."""
    from comicarr.app.ai.pull_list import get_cached_suggestions

    suggestions = get_cached_suggestions()
    return JSONResponse(content={"suggestions": suggestions})
