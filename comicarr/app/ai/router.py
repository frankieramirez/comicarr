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
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from comicarr.app.ai import chat_images, chat_store
from comicarr.app.ai import service as ai_service
from comicarr.app.ai.chat import stream_chat_response
from comicarr.app.ai.chat_service import get_thread_lock, release_thread_lock, stream_turn
from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import require_session

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status", dependencies=[Depends(require_session)])
async def ai_status():
    """Return AI configuration and usage status."""
    status = ai_service.get_ai_status()
    return JSONResponse(content=status)


@router.post("/test", dependencies=[Depends(require_session)])
async def ai_test(request: Request, ctx: AppContext = Depends(get_context)):
    """Test an AI connection with provided credentials."""
    body = await request.json()
    base_url = body.get("base_url", "")
    api_key = body.get("api_key", "")
    model = body.get("model", "")

    # Fall back to saved API key if user didn't provide a new one
    if not api_key and ctx.config:
        api_key = getattr(ctx.config, "AI_API_KEY", "") or ""

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
            if event.get("type") != "usage":
                yield json.dumps(event)

    return EventSourceResponse(generator(), media_type="text/event-stream")


@router.get("/chat/threads")
async def chat_threads(
    cursor: str | None = None,
    limit: int = 20,
    username: str = Depends(require_session),
):
    """List the current user's chat threads using a stable cursor."""
    try:
        result = chat_store.list_threads(username, cursor=cursor, limit=limit)
    except (TypeError, ValueError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return JSONResponse(content=result)


@router.get("/chat/threads/{thread_id}")
async def chat_thread_detail(thread_id: str, username: str = Depends(require_session)):
    """Return one owned thread and its persisted messages."""
    thread = chat_store.get_thread(username, thread_id)
    if thread is None:
        return JSONResponse(status_code=404, content={"error": "Chat thread not found"})
    return JSONResponse(content=thread)


@router.patch("/chat/threads/{thread_id}")
async def chat_thread_update(request: Request, thread_id: str, username: str = Depends(require_session)):
    """Rename one owned chat thread."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})
    if not isinstance(body, dict) or not isinstance(body.get("title"), str):
        return JSONResponse(status_code=400, content={"error": "title is required"})
    try:
        thread = chat_store.rename_thread(username, thread_id, body["title"])
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    if thread is None:
        return JSONResponse(status_code=404, content={"error": "Chat thread not found"})
    return JSONResponse(content=thread)


@router.delete("/chat/threads/{thread_id}")
async def chat_thread_delete(thread_id: str, username: str = Depends(require_session)):
    """Delete one owned thread and its attachment files."""
    async with get_thread_lock(thread_id):
        if not chat_store.owns_thread(username, thread_id):
            return JSONResponse(status_code=404, content={"error": "Chat thread not found"})
        try:
            quarantine = chat_images.quarantine_thread(thread_id)
        except OSError:
            return JSONResponse(status_code=500, content={"error": "Could not remove chat attachments"})
        try:
            paths = chat_store.delete_thread(username, thread_id)
        except Exception:
            chat_images.restore_quarantine(quarantine)
            raise
        if paths is None:
            chat_images.restore_quarantine(quarantine)
            return JSONResponse(status_code=404, content={"error": "Chat thread not found"})
        if not chat_images.delete_quarantine(quarantine):
            return JSONResponse(
                status_code=500, content={"error": "Chat was deleted but attachment cleanup must be retried"}
            )
        release_thread_lock(thread_id)
    return JSONResponse(content={"success": True})


@router.get("/chat/threads/{thread_id}/attachments/{attachment_id}")
async def chat_attachment(
    thread_id: str,
    attachment_id: str,
    username: str = Depends(require_session),
):
    """Serve an attachment only when it belongs to the authenticated user."""
    attachment = chat_store.get_attachment(username, thread_id, attachment_id)
    if attachment is None:
        return JSONResponse(status_code=404, content={"error": "Attachment not found"})
    try:
        path = chat_images.resolve_relative_path(attachment["relative_path"])
    except chat_images.InvalidChatImage:
        return JSONResponse(status_code=404, content={"error": "Attachment not found"})
    if not path.is_file():
        return JSONResponse(status_code=404, content={"error": "Attachment not found"})
    return FileResponse(path, media_type=attachment["media_type"], filename=attachment["filename"])


@router.post("/chat/turns/stream")
async def chat_turn_stream(
    request: Request,
    username: str = Depends(require_session),
    ctx: AppContext = Depends(get_context),
):
    """Persist and stream one text/image chat turn from multipart form data."""
    content_length = request.headers.get("content-length")
    max_request_bytes = chat_images.MAX_IMAGES * chat_images.MAX_IMAGE_BYTES + 1024 * 1024
    if content_length:
        try:
            if int(content_length) > max_request_bytes:
                return JSONResponse(status_code=413, content={"error": "Chat image upload is too large"})
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "Invalid Content-Length header"})
    try:
        # Starlette caps each part at 1 MB by default, which would reject a valid
        # chat image long before save_uploads can report the real 10 MB limit.
        form = await request.form(
            max_files=chat_images.MAX_IMAGES,
            max_fields=3,
            max_part_size=chat_images.MAX_IMAGE_BYTES + 1,
        )
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid multipart form data"})

    thread_id = str(form.get("thread_id") or "").strip() or None
    retry_message_id = str(form.get("retry_message_id") or "").strip() or None
    content = str(form.get("content") or "").strip()
    uploads = list(form.getlist("images[]")) + list(form.getlist("images"))
    uploads = [upload for upload in uploads if getattr(upload, "filename", None)]
    if not retry_message_id and not content and not uploads:
        return JSONResponse(status_code=400, content={"error": "content or at least one image is required"})
    if len(uploads) > chat_images.MAX_IMAGES:
        return JSONResponse(status_code=400, content={"error": "A maximum of 4 images is allowed"})

    async def generator():
        try:
            async for event in stream_turn(
                username,
                thread_id,
                content,
                uploads,
                ctx,
                retry_message_id=retry_message_id,
            ):
                yield json.dumps(event)
        except chat_images.InvalidChatImage as e:
            yield json.dumps({"type": "error", "code": "invalid_image", "content": str(e), "retryable": False})
            yield json.dumps({"type": "done", "message": None})
        except Exception:
            yield json.dumps(
                {
                    "type": "error",
                    "code": "internal_error",
                    "content": "Something went wrong. Please try again.",
                    "retryable": True,
                }
            )
            yield json.dumps({"type": "done", "message": None})

    return EventSourceResponse(generator(), media_type="text/event-stream")


@router.get("/suggestions", dependencies=[Depends(require_session)])
async def ai_suggestions():
    """Return cached AI-generated pull list suggestions."""
    from comicarr.app.ai.pull_list import get_cached_suggestions

    suggestions = get_cached_suggestions()
    return JSONResponse(content={"suggestions": suggestions})
