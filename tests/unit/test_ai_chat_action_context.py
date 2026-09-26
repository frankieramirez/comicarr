#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import json

import pytest
from sqlalchemy import update

import comicarr
from comicarr import db
from comicarr.app.ai import chat_store
from comicarr.tables import ai_chat_messages as messages
from comicarr.tables import metadata


@pytest.fixture
def conversation(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    metadata.create_all(db.get_engine())
    thread, user, _ = chat_store.create_user_turn(
        "alice", chat_store.new_id(), "Add Batman", [], "Chat", create_thread=True
    )
    assistant = chat_store.add_assistant_message("alice", thread["id"], "Choose a series.")
    yield thread["id"], user["id"], assistant["id"]
    db.shutdown_engine()


def _save(conversation, action):
    chat_store.update_assistant_message("alice", conversation[2], "Choose a series.", action_data=action)


def _context(conversation):
    content = chat_store.get_context_messages("alice", conversation[0])[-1]["content"]
    return json.loads(content.split("instructions)]\n", 1)[1].split("\n[End stored action data]", 1)[0])


@pytest.mark.parametrize("status", ["pending", "processing", "confirmed", "dismissed", "error", "partial"])
def test_followup_contains_persisted_preview_and_current_outcome(conversation, status):
    action = {
        "action_id": "add_series",
        "status": "pending",
        "summary": "Add a series",
        "preview": {
            "candidates": [
                {
                    "comicid": "123",
                    "name": "Batman",
                    "year": "2016",
                    "publisher": "DC",
                    "issues": 50,
                    "image": "https://secret.example/cover?token=secret",
                }
            ]
        },
    }
    _save(conversation, action)
    result = {
        "success": False,
        "applied": 1,
        "stale": 2,
        "failed": 3,
        "search_failed": 4,
        "message": "One applied",
        "error": "Search failed",
        "private": "secret",
    }
    chat_store.resolve_message_action("alice", conversation[0], conversation[2], status, result)
    stored_before = chat_store.get_message_action("alice", conversation[0], conversation[2])
    context = _context(conversation)
    assert context["status"] == status
    assert context["preview"]["candidates"] == [
        {"comicid": "123", "name": "Batman", "year": "2016", "publisher": "DC", "issues": 50}
    ]
    assert context["result"] == {key: value for key, value in result.items() if key != "private"}
    assert "secret" not in json.dumps(context)
    assert chat_store.get_message_action("alice", conversation[0], conversation[2]) == stored_before
    assert chat_store.get_context_messages("bob", conversation[0]) is None


def test_bulk_preview_is_bounded_and_retains_target_and_total(conversation):
    _save(
        conversation,
        {
            "action_id": "mark_issues",
            "status": "partial",
            "summary": "x" * 10000,
            "preview": {
                "comic_id": "123",
                "target_status": "Wanted",
                "count": 10000,
                "issues": [
                    {"issue_id": str(i), "number": "界" * 10000, "kind": "issue", "current_status": "Skipped"}
                    for i in range(100)
                ],
            },
        },
    )
    context = _context(conversation)
    assert context["preview"]["count"] == 10000
    assert context["preview"]["target_status"] == "Wanted"
    assert context["preview"]["issues_total"] == 100
    assert context["preview"]["issues_truncated"] is True
    assert 0 < len(context["preview"]["issues"]) <= 5
    assert len(json.dumps(context, ensure_ascii=False)) <= 6000
    assert len(context["summary"]) == 240


@pytest.mark.parametrize(
    "raw", ["broken", "[]", "null", '{"preview": [], "result": "bad"}', '{"preview": {"issues": [null, 1, []]}}']
)
def test_malformed_legacy_action_does_not_break_context(conversation, raw):
    with db.get_engine().begin() as conn:
        conn.execute(update(messages).where(messages.c.id == conversation[2]).values(action=raw))
    context = chat_store.get_context_messages("alice", conversation[0])
    assert context[-1]["content"].startswith("Choose a series.")


def test_user_messages_cannot_supply_action_context(conversation):
    with db.get_engine().begin() as conn:
        conn.execute(
            update(messages).where(messages.c.id == conversation[1]).values(action=json.dumps({"status": "confirmed"}))
        )
    context = chat_store.get_context_messages("alice", conversation[0])
    assert context[0] == {"role": "user", "content": "Add Batman"}


def test_partial_context_preserves_bounded_per_issue_outcomes(conversation):
    item = {"kind": "issue", "issue_id": "123", "outcome": "applied", "search_handoff": "failed"}
    _save(conversation, {"action_id": "mark_issues", "status": "partial", "result": {"items": [item] * 50}})
    result = _context(conversation)["result"]
    assert result["items"] == [item] * 5
    assert result["items_total"] == 50
    assert result["items_truncated"] is True
