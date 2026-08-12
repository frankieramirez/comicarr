#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Focused persistence, image, ownership, and compensation tests for Library Chat."""

import asyncio
import io
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text
from starlette.datastructures import UploadFile

import comicarr
from comicarr import db
from comicarr.app.ai import chat_images, chat_store
from comicarr.app.ai.chat_service import stream_turn
from comicarr.app.ai.router import router
from comicarr.app.core.schema import upgrade_database
from comicarr.app.core.security import require_session
from comicarr.tables import ai_chat_messages, metadata


@pytest.fixture
def chat_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    metadata.create_all(db.get_engine())
    yield tmp_path
    db.shutdown_engine()


@pytest.fixture
def production_chat_db(tmp_path, monkeypatch):
    """Schema via the Alembic runner, starting from a pre-library-chat stamp.

    Mirrors upgraded self-hosted installs that still lack ai_chat_* until 0003
    applies — the path that previously left GET /chat/threads returning 500.
    """
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE ai_chat_attachments"))
        conn.execute(text("DROP TABLE ai_chat_messages"))
        conn.execute(text("DROP TABLE ai_chat_threads"))
        conn.execute(text("INSERT INTO mylar_info(DatabaseVersion) VALUES (0)"))
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version(version_num) VALUES ('0002_legacy_adoption')"))
    assert upgrade_database(engine) == "0006_interactive_search_sessions"
    yield tmp_path
    db.shutdown_engine()


def _image_upload(filename="cover.png", size=(3200, 1600), image_format="PNG"):
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[0x010E] = "private metadata"
    Image.new("RGB", size, color="red").save(buffer, format=image_format, exif=exif)
    buffer.seek(0)
    return UploadFile(buffer, filename=filename)


def _create_turn(username, title, thread_id=None):
    thread_id = thread_id or chat_store.new_id()
    thread, message, created = chat_store.create_user_turn(
        username,
        thread_id,
        title,
        [],
        title,
        create_thread=True,
    )
    return thread, message, created


@pytest.mark.asyncio
async def test_images_are_verified_resized_and_reencoded_without_metadata(chat_db):
    records = await chat_images.save_uploads("thread-a", [_image_upload()])

    assert len(records) == 1
    assert (records[0]["width"], records[0]["height"]) == (2048, 1024)
    assert records[0]["media_type"] == "image/webp"
    path = chat_images.resolve_relative_path(records[0]["relative_path"])
    with Image.open(path) as stored:
        assert stored.format == "WEBP"
        assert stored.getexif() == {}
        assert getattr(stored, "n_frames", 1) == 1


@pytest.mark.asyncio
async def test_corrupt_and_excess_images_are_rejected_without_files(chat_db):
    corrupt = UploadFile(io.BytesIO(b"not an image"), filename="bad.png")
    with pytest.raises(chat_images.InvalidChatImage, match="corrupt"):
        await chat_images.save_uploads("thread-a", [corrupt])
    with pytest.raises(chat_images.InvalidChatImage, match="maximum of 4"):
        await chat_images.save_uploads("thread-a", [_image_upload() for _ in range(5)])
    assert not chat_images.attachment_root().exists()


@pytest.mark.asyncio
async def test_spoofed_and_oversized_images_are_rejected(chat_db):
    gif_buffer = io.BytesIO()
    Image.new("RGB", (10, 10), color="red").save(gif_buffer, format="GIF")
    gif_buffer.seek(0)
    spoofed = UploadFile(gif_buffer, filename="looks-like-a-png.png")
    oversized = UploadFile(
        io.BytesIO(b"x" * (chat_images.MAX_IMAGE_BYTES + 1)),
        filename="too-large.png",
    )

    with pytest.raises(chat_images.InvalidChatImage, match="Only JPEG, PNG, and WebP"):
        await chat_images.save_uploads("thread-a", [spoofed])
    with pytest.raises(chat_images.InvalidChatImage, match="10 MB or smaller"):
        await chat_images.save_uploads("thread-a", [oversized])
    assert not chat_images.attachment_root().exists()


def test_attachment_paths_cannot_escape_chat_storage(chat_db):
    with pytest.raises(chat_images.InvalidChatImage, match="Invalid attachment path"):
        chat_images.resolve_relative_path("chat_attachments/../../outside.webp")


@pytest.mark.asyncio
async def test_animated_images_are_rejected_explicitly(chat_db):
    buffer = io.BytesIO()
    frames = [Image.new("RGB", (10, 10), color=color) for color in ("red", "blue")]
    frames[0].save(buffer, format="WEBP", save_all=True, append_images=frames[1:], duration=100, loop=0)
    buffer.seek(0)

    with pytest.raises(chat_images.InvalidChatImage, match="Animated images"):
        await chat_images.save_uploads("thread-a", [UploadFile(buffer, filename="animated.webp")])
    assert not chat_images.attachment_root().exists()


@pytest.mark.asyncio
async def test_images_over_explicit_pixel_budget_are_rejected(chat_db, monkeypatch):
    monkeypatch.setattr(chat_images, "MAX_IMAGE_PIXELS", 100)

    with pytest.raises(chat_images.InvalidChatImage, match="dimensions are too large"):
        await chat_images.save_uploads("thread-a", [_image_upload(size=(20, 20))])

    assert not chat_images.attachment_root().exists()


def test_chat_schema_declares_migration_indexes_and_usage_columns():
    assert {index.name for index in metadata.tables["ai_chat_threads"].indexes} == {"ai_chat_threads_owner_updated"}
    assert {index.name for index in metadata.tables["ai_chat_messages"].indexes} == {"ai_chat_messages_thread_created"}
    assert {index.name for index in metadata.tables["ai_chat_attachments"].indexes} == {
        "ai_chat_attachments_message",
        "ai_chat_attachments_thread_created",
    }
    assert ai_chat_messages.c.prompt_tokens.server_default.arg == "0"
    assert ai_chat_messages.c.completion_tokens.server_default.arg == "0"
    assert ai_chat_messages.c.parent_message_id.nullable is True


def test_threads_are_private_paginated_and_return_message_contract(chat_db):
    first, first_message, created = _create_turn("alice", "First thread")
    second, _, _ = _create_turn("alice", "Second thread")
    _create_turn("bob", "Bob's thread")

    assert created is True
    assert first_message == {
        "id": first_message["id"],
        "thread_id": first["id"],
        "role": "user",
        "content": "First thread",
        "status": "complete",
        "attachments": [],
        "created_at": first_message["created_at"],
    }
    page = chat_store.list_threads("alice", limit=1)
    assert len(page["threads"]) == 1
    assert page["next_cursor"]
    next_page = chat_store.list_threads("alice", cursor=page["next_cursor"], limit=1)
    assert {page["threads"][0]["id"], next_page["threads"][0]["id"]} == {first["id"], second["id"]}
    assert chat_store.get_thread("bob", first["id"]) is None
    assert chat_store.rename_thread("bob", first["id"], "stolen") is None
    assert chat_store.delete_thread("bob", first["id"]) is None


def test_thread_list_route_returns_empty_and_populated_after_production_upgrade(production_chat_db):
    """#409: upgraded installs must list threads without 500 on ordinary page loads."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "alice"

    with TestClient(app) as client:
        empty = client.get("/api/ai/chat/threads?limit=30")
        assert empty.status_code == 200
        assert empty.json() == {"threads": [], "next_cursor": None}

        thread, _, _ = _create_turn("alice", "Saved chat")
        populated = client.get("/api/ai/chat/threads?limit=30")
        assert populated.status_code == 200
        body = populated.json()
        assert body["next_cursor"] is None
        assert len(body["threads"]) == 1
        assert body["threads"][0]["id"] == thread["id"]
        assert body["threads"][0]["title"] == "Saved chat"
        assert body["threads"][0]["message_count"] == 1


def test_only_twenty_recent_messages_are_sent_to_provider(chat_db):
    thread, _, _ = _create_turn("alice", "message 0")
    for index in range(1, 25):
        chat_store.add_assistant_message("alice", thread["id"], "message %d" % index)

    context = chat_store.get_context_messages("alice", thread["id"])
    assert len(context) == 20
    assert context[0]["content"] == "message 5"
    assert context[-1]["content"] == "message 24"


def test_messages_stay_ordered_when_timestamps_tie(chat_db, monkeypatch):
    # A coarse platform clock hands every insert the same created_at; ordering
    # must still follow insertion rather than the random message id.
    monkeypatch.setattr(chat_store, "_now", lambda: "2026-01-01T00:00:00.000000+00:00")
    thread, _, _ = _create_turn("alice", "message 0")
    for index in range(1, 6):
        chat_store.add_assistant_message("alice", thread["id"], "message %d" % index)

    detail = chat_store.get_thread("alice", thread["id"])
    assert [message["content"] for message in detail["messages"]] == ["message %d" % i for i in range(6)]
    context = chat_store.get_context_messages("alice", thread["id"])
    assert [message["content"] for message in context] == ["message %d" % i for i in range(6)]


@pytest.mark.asyncio
async def test_uploaded_filenames_are_stripped_of_paths_and_control_characters(chat_db):
    records = await chat_images.save_uploads(
        "thread-safe",
        [_image_upload(filename='C:\\Users\\reader\\co"ver\r\n.png', size=(10, 10))],
    )
    assert records[0]["filename"] == "co_ver__.png"

    long_name = "a" * 400 + ".png"
    records = await chat_images.save_uploads("thread-long", [_image_upload(filename=long_name, size=(10, 10))])
    assert len(records[0]["filename"]) == chat_images.MAX_FILENAME_LENGTH


@pytest.mark.asyncio
async def test_prior_images_are_represented_by_filename_in_context(chat_db):
    thread_id = chat_store.new_id()
    records = await chat_images.save_uploads(thread_id, [_image_upload(filename="private-cover.png", size=(10, 10))])
    thread, _, _ = chat_store.create_user_turn(
        "alice",
        thread_id,
        "",
        records,
        "private-cover.png",
        create_thread=True,
    )
    chat_store.add_assistant_message("alice", thread["id"], "It is a red cover.")

    context = chat_store.get_context_messages("alice", thread["id"])

    assert context == [
        {"role": "user", "content": "[Attached images: private-cover.png]"},
        {"role": "assistant", "content": "It is a red cover."},
    ]


def test_thread_detail_and_rename_routes_return_direct_contracts(chat_db):
    thread, _, _ = _create_turn("alice", "Original")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "alice"

    with TestClient(app) as client:
        detail = client.get("/api/ai/chat/threads/%s" % thread["id"])
        assert detail.status_code == 200
        assert detail.json()["id"] == thread["id"]
        assert detail.json()["messages"][0]["content"] == "Original"

        renamed = client.patch("/api/ai/chat/threads/%s" % thread["id"], json={"title": "Renamed"})
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Renamed"
        assert "messages" not in renamed.json()


@pytest.mark.asyncio
async def test_vision_rejection_compensates_persisted_turn_and_file(chat_db):
    provider_request = {}

    class RejectingCompletions:
        async def create(self, **kwargs):
            provider_request.update(kwargs)
            raise RuntimeError("This model does not support image inputs")

    ctx = SimpleNamespace(
        ai_async_client=SimpleNamespace(chat=SimpleNamespace(completions=RejectingCompletions())),
        config=SimpleNamespace(AI_MODEL="text-only"),
        ai_circuit_breaker=None,
        ai_rate_limiter=None,
    )
    events = [event async for event in stream_turn("alice", None, "describe this", [_image_upload()], ctx)]

    assert [event["type"] for event in events] == ["thread", "user_message", "error", "done"]
    assert events[2]["code"] == "vision_unsupported"
    current_turn = provider_request["messages"][-1]["content"]
    assert current_turn[0] == {
        "type": "text",
        "text": "describe this\n[Attached images: cover.png]",
    }
    assert current_turn[1]["type"] == "image_url"
    assert current_turn[1]["image_url"]["url"].startswith("data:image/webp;base64,")
    assert chat_store.list_threads("alice")["threads"] == []
    assert not any(chat_images.attachment_root().rglob("*.webp"))


@pytest.mark.asyncio
async def test_successful_turn_stream_persists_assistant_results(chat_db, monkeypatch):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"pattern_id":"search_series","parameters":{"query":"Batman"}}\nFound one.'
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=4, completion_tokens=3),
    )

    class SuccessfulCompletions:
        async def create(self, **_kwargs):
            return response

    monkeypatch.setattr("comicarr.app.ai.chat.execute_pattern", lambda *_args: [{"ComicID": "batman"}])
    monkeypatch.setattr("comicarr.app.ai.service.log_activity", lambda **_kwargs: None)
    ctx = SimpleNamespace(
        ai_async_client=SimpleNamespace(chat=SimpleNamespace(completions=SuccessfulCompletions())),
        config=SimpleNamespace(AI_MODEL="vision"),
        ai_circuit_breaker=None,
        ai_rate_limiter=None,
    )

    events = [event async for event in stream_turn("alice", None, "find Batman", [], ctx)]

    assert [event["type"] for event in events] == ["thread", "user_message", "results", "text", "done"]
    assistant = events[-1]["message"]
    assert events[2]["message_id"] == assistant["id"]
    assert events[3]["message_id"] == assistant["id"]
    assert assistant["content"] == "Found one."
    assert assistant["results"] == [{"ComicID": "batman"}]
    stored = db.select_one(ai_chat_messages.select().where(ai_chat_messages.c.id == assistant["id"]))
    assert stored["prompt_tokens"] == 4
    assert stored["completion_tokens"] == 3
    detail = chat_store.get_thread("alice", assistant["thread_id"])
    assert detail["messages"][-1] == assistant


@pytest.mark.asyncio
async def test_query_failure_persists_error_turn_with_provider_text(chat_db, monkeypatch):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"pattern_id":"search_series","parameters":{"query":"Batman"}}\nTry another query.'
                )
            )
        ],
        usage=None,
    )

    class SuccessfulCompletions:
        async def create(self, **_kwargs):
            return response

    def fail_query(*_args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("comicarr.app.ai.chat.execute_pattern", fail_query)
    monkeypatch.setattr("comicarr.app.ai.service.log_activity", lambda **_kwargs: None)
    ctx = SimpleNamespace(
        ai_async_client=SimpleNamespace(chat=SimpleNamespace(completions=SuccessfulCompletions())),
        config=SimpleNamespace(AI_MODEL="vision"),
        ai_circuit_breaker=None,
        ai_rate_limiter=None,
    )

    events = [event async for event in stream_turn("alice", None, "find Batman", [], ctx)]

    assert [event["type"] for event in events] == ["thread", "user_message", "error", "text", "done"]
    assert events[2]["code"] == "query_error"
    assistant = events[-1]["message"]
    assert assistant["status"] == "error"
    assert assistant["content"] == "Failed to query your library. Please try rephrasing.\n\nTry another query."


@pytest.mark.asyncio
async def test_cancelled_provider_call_persists_cancelled_assistant(chat_db):
    started = asyncio.Event()

    class BlockingCompletions:
        async def create(self, **_kwargs):
            started.set()
            await asyncio.Event().wait()

    ctx = SimpleNamespace(
        ai_async_client=SimpleNamespace(chat=SimpleNamespace(completions=BlockingCompletions())),
        config=SimpleNamespace(AI_MODEL="slow-model"),
        ai_circuit_breaker=None,
        ai_rate_limiter=None,
    )
    turn = stream_turn("alice", None, "wait for it", [], ctx)
    thread_event = await anext(turn)
    await anext(turn)
    provider_task = asyncio.create_task(anext(turn))
    await started.wait()
    provider_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await provider_task
    await turn.aclose()

    detail = chat_store.get_thread("alice", thread_event["thread"]["id"])
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][-1]["status"] == "cancelled"
    assert detail["messages"][-1]["content"] == ""
    stored = db.select_one(ai_chat_messages.select().where(ai_chat_messages.c.id == detail["messages"][-1]["id"]))
    assert stored["prompt_tokens"] == 0


@pytest.mark.asyncio
async def test_retry_reuses_owned_user_turn_and_stored_images(chat_db, monkeypatch):
    thread_id = chat_store.new_id()
    image_records = await chat_images.save_uploads(thread_id, [_image_upload(size=(10, 10))])
    thread, user_message, _ = chat_store.create_user_turn(
        "alice",
        thread_id,
        "describe it",
        image_records,
        "describe it",
        create_thread=True,
    )
    provider_request = {}
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="A red square."))],
        usage=SimpleNamespace(prompt_tokens=8, completion_tokens=3),
    )

    class SuccessfulCompletions:
        async def create(self, **kwargs):
            provider_request.update(kwargs)
            return response

    monkeypatch.setattr("comicarr.app.ai.service.log_activity", lambda **_kwargs: None)
    ctx = SimpleNamespace(
        ai_async_client=SimpleNamespace(chat=SimpleNamespace(completions=SuccessfulCompletions())),
        config=SimpleNamespace(AI_MODEL="vision"),
        ai_circuit_breaker=None,
        ai_rate_limiter=None,
    )

    events = [
        event
        async for event in stream_turn(
            "alice",
            thread["id"],
            "describe it",
            [],
            ctx,
            retry_message_id=user_message["id"],
        )
    ]

    assert [event["type"] for event in events] == ["user_message", "text", "done"]
    detail = chat_store.get_thread("alice", thread["id"])
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert provider_request["messages"][-1]["content"][1]["image_url"]["url"].startswith("data:image/webp;base64,")


@pytest.mark.asyncio
async def test_retry_rejects_changed_content_or_wrong_owner_without_duplicate(chat_db):
    thread, user_message, _ = _create_turn("alice", "original")
    ctx = SimpleNamespace()

    changed = [
        event
        async for event in stream_turn(
            "alice",
            thread["id"],
            "changed",
            [],
            ctx,
            retry_message_id=user_message["id"],
        )
    ]
    wrong_owner = [
        event
        async for event in stream_turn(
            "bob",
            thread["id"],
            "original",
            [],
            ctx,
            retry_message_id=user_message["id"],
        )
    ]
    changed_images = [
        event
        async for event in stream_turn(
            "alice",
            thread["id"],
            "original",
            [_image_upload(size=(10, 10))],
            ctx,
            retry_message_id=user_message["id"],
        )
    ]

    assert changed[0]["code"] == "retry_mismatch"
    assert wrong_owner[0]["code"] == "retry_mismatch"
    assert changed_images[0]["code"] == "retry_mismatch"
    assert len(chat_store.get_thread("alice", thread["id"])["messages"]) == 1


@pytest.mark.asyncio
async def test_retry_rejects_user_turn_that_already_has_completed_reply(chat_db):
    thread, user_message, _ = _create_turn("alice", "original")
    chat_store.add_assistant_message("alice", thread["id"], "already answered")

    events = [
        event
        async for event in stream_turn(
            "alice",
            thread["id"],
            "original",
            [],
            SimpleNamespace(),
            retry_message_id=user_message["id"],
        )
    ]

    assert events[0]["code"] == "retry_mismatch"
    assert len(chat_store.get_thread("alice", thread["id"])["messages"]) == 2


@pytest.mark.asyncio
async def test_retry_vision_rejection_removes_all_attempts_for_user_turn(chat_db):
    thread_id = chat_store.new_id()
    records = await chat_images.save_uploads(thread_id, [_image_upload(size=(10, 10))])
    thread, user_message, _ = chat_store.create_user_turn(
        "alice",
        thread_id,
        "describe it",
        records,
        "describe it",
        create_thread=True,
    )
    chat_store.add_assistant_message(
        "alice",
        thread_id,
        "First attempt failed.",
        status="error",
        parent_message_id=user_message["id"],
    )

    class RejectingCompletions:
        async def create(self, **_kwargs):
            raise RuntimeError("Only text input is supported")

    ctx = SimpleNamespace(
        ai_async_client=SimpleNamespace(chat=SimpleNamespace(completions=RejectingCompletions())),
        config=SimpleNamespace(AI_MODEL="text-only"),
        ai_circuit_breaker=None,
        ai_rate_limiter=None,
    )

    events = [
        event
        async for event in stream_turn(
            "alice",
            thread["id"],
            "describe it",
            [],
            ctx,
            retry_message_id=user_message["id"],
        )
    ]

    assert [event["type"] for event in events] == ["user_message", "error", "done"]
    assert events[1]["code"] == "vision_unsupported"
    assert chat_store.get_thread("alice", thread["id"]) is None
    assert not any(chat_images.attachment_root().rglob("*.webp"))


@pytest.mark.asyncio
async def test_attachment_route_enforces_thread_owner(chat_db):
    thread_id = chat_store.new_id()
    records = await chat_images.save_uploads(thread_id, [_image_upload(size=(10, 10))])
    thread, message, _ = chat_store.create_user_turn(
        "alice",
        thread_id,
        "cover",
        records,
        "cover",
        create_thread=True,
    )
    attachment = message["attachments"][0]
    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[require_session] = lambda: "bob"
    with TestClient(app) as client:
        response = client.get(attachment["url"])
        assert response.status_code == 404

    app.dependency_overrides[require_session] = lambda: "alice"
    with TestClient(app) as client:
        response = client.get(attachment["url"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"
