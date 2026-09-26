#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

import comicarr
from comicarr import db
from comicarr.app.ai import actions as chat_actions
from comicarr.app.ai import chat_store
from comicarr.app.ai.chat_service import stream_turn
from comicarr.app.ai.router import router
from comicarr.app.core.context import get_context
from comicarr.app.core.security import require_session
from comicarr.tables import annuals, issues, metadata


@pytest.fixture
def chat_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    metadata.create_all(db.get_engine())
    yield tmp_path
    db.shutdown_engine()


def _add_series_row(comic_id="1000", name="Injustice: Gods Among Us", year="2013"):
    db.upsert(
        "comics",
        {"ComicID": comic_id, "ComicName": name, "ComicYear": year, "Status": "Active"},
        {"ComicID": comic_id},
    )


def _add_issue(issue_id, comic_id="1000", number="1", status="Skipped", intent=None, comic_name=None):
    db.upsert(
        "issues",
        {
            "IssueID": issue_id,
            "ComicID": comic_id,
            "ComicName": comic_name or "Injustice: Gods Among Us",
            "Issue_Number": number,
            "Status": status,
            "AcquisitionIntent": intent,
        },
        {"IssueID": issue_id},
    )


def _add_annual(issue_id, comic_id="1000", number="Annual 1", status=None, intent=None):
    db.upsert(
        "annuals",
        {
            "IssueID": issue_id,
            "ComicID": comic_id,
            "ComicName": "Injustice: Gods Among Us",
            "Issue_Number": number,
            "Status": status,
            "AcquisitionIntent": intent,
            "Deleted": 0,
        },
        {"IssueID": issue_id},
    )


def _set_issue_status(issue_id, status, intent=None):
    db.upsert("issues", {"Status": status, "AcquisitionIntent": intent}, {"IssueID": issue_id})


def _issue_status(issue_id):
    row = db.select_one(select(issues.c.Status, issues.c.AcquisitionIntent).where(issues.c.IssueID == issue_id))
    return (row["Status"], row["AcquisitionIntent"]) if row else None


def _annual_status(issue_id):
    row = db.select_one(select(annuals.c.Status, annuals.c.AcquisitionIntent).where(annuals.c.IssueID == issue_id))
    return (row["Status"], row["AcquisitionIntent"]) if row else None


def test_mark_issues_prepare_lists_only_markable_rows(chat_db):
    _add_series_row()
    _add_issue("i1", number="1", status=None)
    _add_issue("i2", number="2", status="Downloaded")
    _add_issue("i3", number="3", status="Wanted")
    _add_issue("i4", number="4", status="Skipped", intent="ignored")
    _add_annual("a1", status=None)

    ctx = SimpleNamespace(config=SimpleNamespace(ANNUALS_ON=True))
    proposal = chat_actions.prepare_action(
        "mark_issues",
        {"series_name": "Injustice", "status": "Wanted", "scope": "all"},
        ctx,
    )

    assert proposal["status"] == "pending"
    assert proposal["preview"]["comic_id"] == "1000"
    assert proposal["preview"]["target_status"] == "Wanted"
    assert proposal["preview"]["count"] == 2
    assert {item["issue_id"] for item in proposal["preview"]["issues"]} == {"i1", "a1"}


def test_mark_issues_prepare_annual_scope_and_no_match(chat_db):
    _add_series_row()
    _add_issue("i1", status=None)
    _add_annual("a1", status=None)

    ctx = SimpleNamespace(config=SimpleNamespace(ANNUALS_ON=True))
    annuals_only = chat_actions.prepare_action(
        "mark_issues",
        {"series_name": "Injustice", "status": "Skipped", "scope": "annuals"},
        ctx,
    )
    assert annuals_only["status"] == "pending"
    assert [item["issue_id"] for item in annuals_only["preview"]["issues"]] == ["a1"]

    missing = chat_actions.prepare_action("mark_issues", {"series_name": "Nonexistent", "status": "Wanted"}, ctx)
    assert missing["status"] == "error"

    bad_status = chat_actions.prepare_action("mark_issues", {"series_name": "Injustice", "status": "Deleted"}, ctx)
    assert bad_status["status"] == "error"

    nothing = chat_actions.prepare_action(
        "mark_issues",
        {"series_name": "Injustice", "status": "Wanted", "scope": "annuals"},
        SimpleNamespace(config=SimpleNamespace(ANNUALS_ON=False)),
    )
    assert nothing["status"] == "error"


def test_add_series_prepare_returns_trimmed_candidates(chat_db, monkeypatch):
    def fake_find_comic(ctx, name, **_kwargs):
        assert name == "Wonder Woman"
        return {
            "results": [
                {
                    "comicid": "86313",
                    "comicname": "Absolute Wonder Woman",
                    "comicyear": "2024",
                    "publisher": "DC Comics",
                    "issues": 12,
                    "image": "https://example.test/cover.jpg",
                    "extra": "ignored",
                },
                {"comicid": "2", "comicname": "Wonder Woman", "in_library": True},
            ]
        }

    monkeypatch.setattr("comicarr.app.search.service.find_comic", fake_find_comic)
    proposal = chat_actions.prepare_action("add_series", {"query": "Wonder Woman"}, SimpleNamespace())

    assert proposal["status"] == "pending"
    candidates = proposal["preview"]["candidates"]
    assert candidates[0]["comicid"] == "86313"
    assert candidates[0]["name"] == "Absolute Wonder Woman"
    assert "extra" not in candidates[0]
    assert candidates[1]["in_library"] is True


def test_add_series_prepare_surfaces_provider_failure(chat_db, monkeypatch):
    monkeypatch.setattr(
        "comicarr.app.search.service.find_comic",
        lambda *_a, **_k: {"error": "Search returned no results"},
    )
    proposal = chat_actions.prepare_action("add_series", {"query": "nope"}, SimpleNamespace())
    assert proposal["status"] == "error"


def test_mark_issues_confirm_applies_and_queues_wanted(chat_db, monkeypatch):
    _add_series_row()
    _add_issue("i1", number="1", status=None)
    _add_issue("i2", number="2", status="Skipped")
    enqueued = []
    monkeypatch.setattr(
        "comicarr.app.search.commands.enqueue_search_command",
        lambda values, **kwargs: enqueued.append(values),
    )

    ctx = SimpleNamespace(config=SimpleNamespace(ANNUALS_ON=False))
    proposal = chat_actions.prepare_action("mark_issues", {"series_name": "Injustice", "status": "wanted"}, ctx)
    assert proposal["status"] == "pending"

    result = chat_actions.confirm_action(proposal, {}, ctx, "alice")

    assert result["success"] is True
    assert result["applied"] == 2
    assert _issue_status("i1") == ("Wanted", "wanted")
    assert _issue_status("i2") == ("Wanted", "wanted")
    assert {item["issueid"] for item in enqueued} == {"i1", "i2"}
    assert all(item["entity_type"] == "issue" for item in enqueued)


def test_mark_issues_confirm_skips_stale_rows(chat_db, monkeypatch):
    _add_series_row()
    _add_issue("i1", number="1", status=None)
    _add_issue("i2", number="2", status=None)
    monkeypatch.setattr("comicarr.app.search.commands.enqueue_search_command", lambda *a, **k: None)

    ctx = SimpleNamespace(config=SimpleNamespace(ANNUALS_ON=False))
    proposal = chat_actions.prepare_action("mark_issues", {"series_name": "Injustice", "status": "Wanted"}, ctx)
    _set_issue_status("i2", "Downloaded")

    result = chat_actions.confirm_action(proposal, {}, ctx, "alice")

    assert result["success"] is True
    assert result["applied"] == 1
    assert result["stale"] == 1
    assert _issue_status("i1")[0] == "Wanted"
    assert _issue_status("i2")[0] == "Downloaded"


def test_mark_issues_confirm_skipped_annual(chat_db):
    _add_series_row()
    _add_annual("a1", status="Wanted", intent="wanted")

    ctx = SimpleNamespace(config=SimpleNamespace(ANNUALS_ON=True))
    proposal = chat_actions.prepare_action(
        "mark_issues", {"series_name": "Injustice", "status": "Skipped", "scope": "annuals"}, ctx
    )
    result = chat_actions.confirm_action(proposal, {}, ctx, "alice")

    assert result["success"] is True
    assert result["applied"] == 1
    assert _annual_status("a1") == ("Skipped", "skipped")


def test_add_series_confirm_requires_a_listed_candidate(chat_db, monkeypatch):
    added = []
    monkeypatch.setattr(
        "comicarr.app.search.service.add_comic",
        lambda ctx, comic_id: added.append(comic_id) or {"success": True, "comicid": comic_id},
    )
    proposal = {
        "action_id": "add_series",
        "status": "pending",
        "preview": {"candidates": [{"comicid": "86313", "name": "Absolute Wonder Woman"}]},
    }

    refused = chat_actions.confirm_action(proposal, {"comicid": "999"}, SimpleNamespace(), "alice")
    assert refused["success"] is False
    assert added == []

    result = chat_actions.confirm_action(proposal, {"comicid": "86313"}, SimpleNamespace(), "alice")
    assert result["success"] is True
    assert added == ["86313"]


def test_unknown_action_is_an_error_proposal(chat_db):
    proposal = chat_actions.prepare_action("delete_everything", {}, SimpleNamespace())
    assert proposal["status"] == "error"
    result = chat_actions.confirm_action(proposal, {}, SimpleNamespace(), "alice")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_action_proposal_streams_and_persists_on_message(chat_db, monkeypatch):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"action_id":"mark_issues","parameters":{"series_name":"Injustice","status":"Wanted"}}\nWant them all?'
                )
            )
        ],
        usage=None,
    )

    class SuccessfulCompletions:
        async def create(self, **_kwargs):
            return response

    _add_series_row()
    _add_issue("i1", status=None)
    monkeypatch.setattr("comicarr.app.ai.service.log_activity", lambda **_kwargs: None)
    ctx = SimpleNamespace(
        ai_async_client=SimpleNamespace(chat=SimpleNamespace(completions=SuccessfulCompletions())),
        config=SimpleNamespace(AI_MODEL="test-model", ANNUALS_ON=False),
        ai_circuit_breaker=None,
        ai_rate_limiter=None,
    )

    events = [event async for event in stream_turn("alice", None, "want all of Injustice", [], ctx)]

    assert [event["type"] for event in events] == ["thread", "user_message", "action", "text", "done"]
    action_event = events[2]["action"]
    assert action_event["action_id"] == "mark_issues"
    assert action_event["status"] == "pending"
    assert action_event["preview"]["count"] == 1

    assistant = events[-1]["message"]
    assert assistant["action"]["action_id"] == "mark_issues"
    detail = chat_store.get_thread("alice", assistant["thread_id"])
    assert detail["messages"][-1]["action"]["preview"]["issues"][0]["issue_id"] == "i1"


def _client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "alice"
    app.dependency_overrides[get_context] = lambda: SimpleNamespace(config=SimpleNamespace(AI_MODEL="test-model"))
    return TestClient(app)


def test_confirm_and_dismiss_routes_transition_owned_actions(chat_db, monkeypatch):
    thread, _, _ = chat_store.create_user_turn(
        "alice", chat_store.new_id(), "want them", [], "want them", create_thread=True
    )
    assistant = chat_store.add_assistant_message("alice", thread["id"], "Sure.")
    chat_store.update_assistant_message(
        "alice",
        assistant["id"],
        "Sure.",
        action_data={
            "action_id": "mark_issues",
            "status": "pending",
            "preview": {
                "comic_id": "1000",
                "target_status": "Skipped",
                "scope": "issues",
                "issues": [{"issue_id": "i1", "kind": "issue", "number": "1"}],
            },
        },
    )
    _add_series_row()
    _add_issue("i1", status="Wanted", intent="wanted")

    with _client() as client:
        missing = client.post("/api/ai/chat/actions/confirm", json={"thread_id": thread["id"], "message_id": "nope"})
        assert missing.status_code == 404

        confirmed = client.post(
            "/api/ai/chat/actions/confirm",
            json={"thread_id": thread["id"], "message_id": assistant["id"]},
        )
        assert confirmed.status_code == 200
        body = confirmed.json()["action"]
        assert body["status"] == "confirmed"
        assert body["result"]["applied"] == 1
        assert _issue_status("i1") == ("Skipped", "skipped")

        replayed = client.post(
            "/api/ai/chat/actions/confirm",
            json={"thread_id": thread["id"], "message_id": assistant["id"]},
        )
        assert replayed.status_code == 200
        assert replayed.json()["action"]["status"] == "confirmed"

        stored = chat_store.get_thread("alice", thread["id"])["messages"][-1]
        assert stored["action"]["status"] == "confirmed"


def test_confirm_route_rejects_other_users_actions(chat_db):
    thread, _, _ = chat_store.create_user_turn("alice", chat_store.new_id(), "mine", [], "mine", create_thread=True)
    assistant = chat_store.add_assistant_message("alice", thread["id"], "Sure.")
    chat_store.update_assistant_message(
        "alice",
        assistant["id"],
        "Sure.",
        action_data={"action_id": "mark_issues", "status": "pending", "preview": {}},
    )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "bob"

    with TestClient(app) as client:
        denied = client.post(
            "/api/ai/chat/actions/dismiss",
            json={"thread_id": thread["id"], "message_id": assistant["id"]},
        )
        assert denied.status_code == 404


def test_dismiss_marks_pending_proposal(chat_db):
    thread, _, _ = chat_store.create_user_turn(
        "alice", chat_store.new_id(), "skip it", [], "skip it", create_thread=True
    )
    assistant = chat_store.add_assistant_message("alice", thread["id"], "Ok.")
    chat_store.update_assistant_message(
        "alice",
        assistant["id"],
        "Ok.",
        action_data={"action_id": "add_series", "status": "pending", "preview": {"candidates": []}},
    )

    with _client() as client:
        dismissed = client.post(
            "/api/ai/chat/actions/dismiss",
            json={"thread_id": thread["id"], "message_id": assistant["id"]},
        )
        assert dismissed.status_code == 200
        assert dismissed.json()["action"]["status"] == "dismissed"

        confirmed = client.post(
            "/api/ai/chat/actions/confirm",
            json={"thread_id": thread["id"], "message_id": assistant["id"]},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["action"]["status"] == "dismissed"
