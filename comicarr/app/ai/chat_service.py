#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Application service for persistent Library Chat turns."""

import asyncio

from comicarr.app.ai import chat_images, chat_store
from comicarr.app.ai.chat import stream_chat_response

_thread_locks = {}


def get_thread_lock(thread_id):
    return _thread_locks.setdefault(thread_id, asyncio.Lock())


def release_thread_lock(thread_id):
    """Forget a deleted thread's lock so the map does not grow for the process's life."""
    _thread_locks.pop(thread_id, None)


def normalize_title(content, image_records):
    title = " ".join(content.split())[:80]
    if title:
        return title
    if image_records:
        return " ".join(image_records[0]["filename"].split())[:80] or "Image"
    return "New chat"


async def stream_turn(username, thread_id, content, uploads, ctx, retry_message_id=None):
    """Serialize turns within an existing thread and stream their events."""
    if not thread_id:
        async for event in _stream_turn(username, thread_id, content, uploads, ctx, retry_message_id):
            yield event
        return

    lock = get_thread_lock(thread_id)
    async with lock:
        async for event in _stream_turn(username, thread_id, content, uploads, ctx, retry_message_id):
            yield event


async def _stream_turn(username, thread_id, content, uploads, ctx, retry_message_id=None):
    """Persist a user turn, stream the provider response, then persist it."""
    if retry_message_id:
        retry_turn = chat_store.get_retry_turn(username, thread_id, retry_message_id) if thread_id else None
        if uploads or retry_turn is None or content != retry_turn[0]["content"]:
            yield {
                "type": "error",
                "code": "retry_mismatch",
                "content": "The saved message no longer matches this retry.",
                "retryable": False,
            }
            yield {"type": "done", "message": None}
            return
        user_message, image_records = retry_turn
        thread = chat_store.get_thread(username, thread_id)
        created = False
    else:
        create_thread = not thread_id
        if create_thread:
            thread_id = chat_store.new_id()

        image_records = await chat_images.save_uploads(thread_id, uploads)
        try:
            thread, user_message, created = chat_store.create_user_turn(
                username,
                thread_id,
                content,
                image_records,
                normalize_title(content, image_records),
                create_thread=create_thread,
            )
        except Exception:
            chat_images.delete_paths(item["relative_path"] for item in image_records)
            raise

    if thread is None:
        chat_images.delete_paths(item["relative_path"] for item in image_records)
        yield {"type": "error", "code": "thread_not_found", "content": "Chat thread not found.", "retryable": False}
        yield {"type": "done", "message": None}
        return

    if created:
        yield {"type": "thread", "thread": {key: value for key, value in thread.items() if key != "messages"}}
    yield {"type": "user_message", "message": user_message}
    assistant_message = chat_store.add_assistant_message(
        username,
        thread_id,
        "",
        status="streaming",
        parent_message_id=user_message["id"],
    )
    assistant_message_id = assistant_message["id"]

    context_messages = chat_store.get_context_messages(username, thread_id)
    data_urls = [chat_images.as_data_url(item["relative_path"]) for item in image_records]
    text_parts = []
    result_data = None
    provider_error = None
    query_error = None
    prompt_tokens = 0
    completion_tokens = 0
    try:
        async for event in stream_chat_response(context_messages, ctx, current_turn_images=data_urls):
            event_type = event.get("type")
            if event_type == "usage":
                prompt_tokens = event.get("prompt_tokens", 0) or 0
                completion_tokens = event.get("completion_tokens", 0) or 0
            elif event_type == "text":
                text_parts.append(event.get("content", ""))
                yield {**event, "message_id": assistant_message_id}
            elif event_type == "results":
                result_data = event.get("data", [])
                yield {**event, "message_id": assistant_message_id}
            elif event_type == "error":
                error_event = {
                    "type": "error",
                    "code": event.get("code", "provider_error"),
                    "content": event.get("content", "Something went wrong. Please try again."),
                    "retryable": event.get("retryable", True),
                }
                if error_event["code"] == "query_error":
                    query_error = error_event
                    yield error_event
                else:
                    provider_error = error_event
                    if provider_error["code"] != "vision_unsupported":
                        yield provider_error
    except (asyncio.CancelledError, GeneratorExit):
        chat_store.update_assistant_message(
            username,
            assistant_message_id,
            "".join(text_parts),
            result_data=result_data,
            status="cancelled",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        raise

    if provider_error:
        if provider_error["code"] == "vision_unsupported":
            paths = chat_store.compensate_user_turn(
                username,
                thread_id,
                user_message["id"],
                assistant_message_id,
            )
            chat_images.delete_paths(paths)
            yield provider_error
        else:
            chat_store.update_assistant_message(
                username,
                assistant_message_id,
                provider_error["content"],
                status="error",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        yield {"type": "done", "message": None}
        return

    assistant_content = "".join(text_parts)
    if query_error:
        assistant_content = "\n\n".join(part for part in (query_error["content"], assistant_content) if part)
    assistant_message = chat_store.update_assistant_message(
        username,
        assistant_message_id,
        assistant_content,
        result_data=result_data,
        status="error" if query_error else "complete",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    yield {"type": "done", "message": assistant_message}
