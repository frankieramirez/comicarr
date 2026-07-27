#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""SQLAlchemy Core persistence for private Library Chat conversations."""

import base64
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, delete, func, insert, or_, select, update

from comicarr import db
from comicarr.tables import ai_chat_attachments as attachments
from comicarr.tables import ai_chat_messages as messages
from comicarr.tables import ai_chat_threads as threads

MAX_CONTEXT_MESSAGES = 20


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _id():
    return uuid.uuid4().hex


def _next_seq(conn, thread_id):
    """Next position in a thread, assigned inside the caller's transaction."""
    current = conn.execute(
        select(func.coalesce(func.max(messages.c.seq), 0)).where(messages.c.thread_id == thread_id)
    ).scalar()
    return (current or 0) + 1


def new_id():
    """Return an opaque identifier suitable for a new chat record."""
    return _id()


def _attachment_dict(row):
    return {
        "id": row["id"],
        "filename": row["filename"],
        "media_type": row["media_type"],
        "byte_size": row["byte_size"],
        "width": row["width"],
        "height": row["height"],
        "url": "/api/ai/chat/threads/%s/attachments/%s" % (row["thread_id"], row["id"]),
    }


def _message_dict(row, message_attachments=None):
    result = {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "role": row["role"],
        "content": row["content"],
        "status": row["status"],
        "attachments": [_attachment_dict(item) for item in (message_attachments or [])],
        "created_at": row["created_at"],
    }
    if row.get("results"):
        try:
            result["results"] = json.loads(row["results"])
        except (TypeError, ValueError):
            result["results"] = None
    return result


def _summary_stmt(username):
    message_count = (
        select(func.count()).select_from(messages).where(messages.c.thread_id == threads.c.id).scalar_subquery()
    )
    return select(
        threads.c.id,
        threads.c.title,
        threads.c.created_at,
        threads.c.updated_at,
        message_count.label("message_count"),
    ).where(threads.c.username == username)


def _summary(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "message_count": row["message_count"],
    }


def _encode_cursor(row):
    value = json.dumps([row["updated_at"], row["id"]], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode_cursor(cursor):
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, str) for item in value):
            raise ValueError
        return value[0], value[1]
    except Exception as e:
        raise ValueError("Invalid cursor") from e


def list_threads(username, cursor=None, limit=20):
    limit = max(1, min(int(limit), 50))
    stmt = _summary_stmt(username)
    decoded = _decode_cursor(cursor)
    if decoded:
        updated_at, thread_id = decoded
        stmt = stmt.where(
            or_(
                threads.c.updated_at < updated_at,
                and_(threads.c.updated_at == updated_at, threads.c.id < thread_id),
            )
        )
    rows = db.select_all(stmt.order_by(threads.c.updated_at.desc(), threads.c.id.desc()).limit(limit + 1))
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "threads": [_summary(row) for row in rows],
        "next_cursor": _encode_cursor(rows[-1]) if has_more else None,
    }


def get_thread(username, thread_id):
    row = db.select_one(_summary_stmt(username).where(threads.c.id == thread_id).limit(1))
    if row is None:
        return None
    message_rows = db.select_all(
        select(messages).where(messages.c.thread_id == thread_id).order_by(messages.c.created_at, messages.c.seq)
    )
    attachment_rows = db.select_all(
        select(attachments).where(attachments.c.thread_id == thread_id).order_by(attachments.c.created_at)
    )
    by_message = {}
    for attachment in attachment_rows:
        by_message.setdefault(attachment["message_id"], []).append(attachment)
    detail = _summary(row)
    detail["messages"] = [_message_dict(message, by_message.get(message["id"])) for message in message_rows]
    return detail


def owns_thread(username, thread_id):
    return (
        db.select_one(select(threads.c.id).where(threads.c.id == thread_id, threads.c.username == username).limit(1))
        is not None
    )


def rename_thread(username, thread_id, title):
    now = _now()
    clean_title = " ".join(title.split())[:80]
    if not clean_title:
        raise ValueError("title must not be empty")
    with db._db_lock, db.get_engine().begin() as conn:
        result = conn.execute(
            update(threads)
            .where(threads.c.id == thread_id, threads.c.username == username)
            .values(title=clean_title, updated_at=now)
        )
        if result.rowcount != 1:
            return None
    row = db.select_one(_summary_stmt(username).where(threads.c.id == thread_id).limit(1))
    return _summary(row) if row else None


def delete_thread(username, thread_id):
    with db._db_lock, db.get_engine().begin() as conn:
        owned = conn.execute(
            select(threads.c.id).where(threads.c.id == thread_id, threads.c.username == username)
        ).first()
        if owned is None:
            return None
        paths = list(
            conn.execute(select(attachments.c.relative_path).where(attachments.c.thread_id == thread_id)).scalars()
        )
        conn.execute(delete(attachments).where(attachments.c.thread_id == thread_id))
        conn.execute(delete(messages).where(messages.c.thread_id == thread_id))
        conn.execute(delete(threads).where(threads.c.id == thread_id))
    return paths


def create_user_turn(username, thread_id, content, image_records, title, create_thread=False):
    now = _now()
    message_id = _id()
    created_thread = False
    with db._db_lock, db.get_engine().begin() as conn:
        if not create_thread:
            thread = conn.execute(
                select(threads.c.id).where(threads.c.id == thread_id, threads.c.username == username)
            ).first()
            if thread is None:
                return None, None, False
        else:
            conn.execute(
                insert(threads).values(
                    id=thread_id,
                    username=username,
                    title=title,
                    created_at=now,
                    updated_at=now,
                )
            )
            created_thread = True

        conn.execute(
            insert(messages).values(
                id=message_id,
                thread_id=thread_id,
                role="user",
                content=content,
                status="complete",
                results=None,
                prompt_tokens=0,
                completion_tokens=0,
                created_at=now,
                seq=_next_seq(conn, thread_id),
            )
        )
        for record in image_records:
            conn.execute(
                insert(attachments).values(
                    id=record["id"],
                    thread_id=thread_id,
                    message_id=message_id,
                    filename=record["filename"],
                    media_type=record["media_type"],
                    byte_size=record["byte_size"],
                    width=record["width"],
                    height=record["height"],
                    relative_path=record["relative_path"],
                    created_at=now,
                )
            )
        conn.execute(update(threads).where(threads.c.id == thread_id).values(updated_at=now))

    row = db.select_one(_summary_stmt(username).where(threads.c.id == thread_id).limit(1))
    thread = _summary(row)
    message = _message_dict(
        {
            "id": message_id,
            "thread_id": thread_id,
            "role": "user",
            "content": content,
            "status": "complete",
            "results": None,
            "created_at": now,
        },
        [
            {
                **record,
                "thread_id": thread_id,
                "message_id": message_id,
            }
            for record in image_records
        ],
    )
    return thread, message, created_thread


def add_assistant_message(
    username,
    thread_id,
    content,
    result_data=None,
    status="complete",
    prompt_tokens=0,
    completion_tokens=0,
    parent_message_id=None,
):
    now = _now()
    message_id = _id()
    with db._db_lock, db.get_engine().begin() as conn:
        owned = conn.execute(
            select(threads.c.id).where(threads.c.id == thread_id, threads.c.username == username)
        ).first()
        if owned is None:
            return None
        conn.execute(
            insert(messages).values(
                id=message_id,
                thread_id=thread_id,
                parent_message_id=parent_message_id,
                role="assistant",
                content=content,
                status=status,
                results=json.dumps(result_data) if result_data is not None else None,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                created_at=now,
                seq=_next_seq(conn, thread_id),
            )
        )
        conn.execute(update(threads).where(threads.c.id == thread_id).values(updated_at=now))
    row = db.select_one(select(messages).where(messages.c.id == message_id))
    return _message_dict(row)


def update_assistant_message(
    username,
    message_id,
    content,
    result_data=None,
    status="complete",
    prompt_tokens=0,
    completion_tokens=0,
):
    """Finalize an owned provisional assistant message in place."""
    now = _now()
    with db._db_lock, db.get_engine().begin() as conn:
        owned = conn.execute(
            select(messages.c.thread_id)
            .join(threads, threads.c.id == messages.c.thread_id)
            .where(
                messages.c.id == message_id,
                messages.c.role == "assistant",
                threads.c.username == username,
            )
        ).first()
        if owned is None:
            return None
        conn.execute(
            update(messages)
            .where(messages.c.id == message_id)
            .values(
                content=content,
                status=status,
                results=json.dumps(result_data) if result_data is not None else None,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )
        conn.execute(update(threads).where(threads.c.id == owned[0]).values(updated_at=now))
    row = db.select_one(select(messages).where(messages.c.id == message_id))
    return _message_dict(row)


def get_context_messages(username, thread_id):
    owned = db.select_one(select(threads.c.id).where(threads.c.id == thread_id, threads.c.username == username))
    if owned is None:
        return None
    recent = db.select_all(
        select(messages)
        .where(messages.c.thread_id == thread_id, messages.c.status == "complete")
        .order_by(messages.c.created_at.desc(), messages.c.seq.desc())
        .limit(MAX_CONTEXT_MESSAGES)
    )
    recent.reverse()
    attachment_rows = db.select_all(
        select(attachments.c.message_id, attachments.c.filename)
        .where(attachments.c.message_id.in_([row["id"] for row in recent]))
        .order_by(attachments.c.created_at)
    )
    filenames_by_message = {}
    for attachment in attachment_rows:
        filenames_by_message.setdefault(attachment["message_id"], []).append(attachment["filename"])

    context = []
    for row in recent:
        content = row["content"]
        filenames = filenames_by_message.get(row["id"], [])
        if filenames:
            attachment_note = "[Attached images: %s]" % ", ".join(filenames)
            content = "\n".join(part for part in (content, attachment_note) if part)
        context.append({"role": row["role"], "content": content})
    return context


def get_retry_turn(username, thread_id, message_id):
    """Return an owned persisted user turn and its stored image records."""
    stmt = (
        select(messages)
        .join(threads, threads.c.id == messages.c.thread_id)
        .where(
            messages.c.id == message_id,
            messages.c.thread_id == thread_id,
            messages.c.role == "user",
            threads.c.username == username,
        )
        .limit(1)
    )
    row = db.select_one(stmt)
    if row is None:
        return None

    latest_user = db.select_one(
        select(messages.c.id)
        .where(messages.c.thread_id == thread_id, messages.c.role == "user")
        .order_by(messages.c.created_at.desc(), messages.c.seq.desc())
        .limit(1)
    )
    if latest_user is None or latest_user["id"] != message_id:
        return None

    completed_reply = db.select_one(
        select(messages.c.id)
        .where(
            messages.c.thread_id == thread_id,
            messages.c.role == "assistant",
            messages.c.status == "complete",
            messages.c.seq > row["seq"],
        )
        .limit(1)
    )
    if completed_reply is not None:
        return None

    image_records = db.select_all(
        select(attachments).where(attachments.c.message_id == message_id).order_by(attachments.c.created_at)
    )
    return _message_dict(row, image_records), image_records


def get_attachment(username, thread_id, attachment_id):
    stmt = (
        select(attachments)
        .join(threads, threads.c.id == attachments.c.thread_id)
        .where(
            attachments.c.id == attachment_id,
            attachments.c.thread_id == thread_id,
            threads.c.username == username,
        )
        .limit(1)
    )
    return db.select_one(stmt)


def compensate_user_turn(username, thread_id, message_id, assistant_message_id=None):
    """Remove a rejected image turn and return its relative image paths."""
    with db._db_lock, db.get_engine().begin() as conn:
        owned = conn.execute(
            select(threads.c.id).where(threads.c.id == thread_id, threads.c.username == username)
        ).first()
        if owned is None:
            return []
        paths = list(
            conn.execute(
                select(attachments.c.relative_path).where(
                    attachments.c.thread_id == thread_id,
                    attachments.c.message_id == message_id,
                )
            ).scalars()
        )
        conn.execute(
            delete(attachments).where(
                attachments.c.thread_id == thread_id,
                attachments.c.message_id == message_id,
            )
        )
        conn.execute(
            delete(messages).where(
                messages.c.id == message_id,
                messages.c.thread_id == thread_id,
                messages.c.role == "user",
            )
        )
        conn.execute(
            delete(messages).where(
                messages.c.thread_id == thread_id,
                messages.c.role == "assistant",
                messages.c.parent_message_id == message_id,
            )
        )
        if assistant_message_id:
            conn.execute(
                delete(messages).where(
                    messages.c.id == assistant_message_id,
                    messages.c.thread_id == thread_id,
                    messages.c.role == "assistant",
                )
            )
        remaining = conn.execute(
            select(func.count()).select_from(messages).where(messages.c.thread_id == thread_id)
        ).scalar()
        if remaining == 0:
            conn.execute(delete(threads).where(threads.c.id == thread_id))
    return paths
