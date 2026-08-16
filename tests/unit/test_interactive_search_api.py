#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Collection and polling contracts for issue-scoped Interactive search."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

import comicarr
from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import COOKIE_NAME, require_session
from comicarr.app.search import interactive
from comicarr.app.search.interactive_sessions import create_session, read_session
from comicarr.app.search.router import router
from comicarr.search_filer import ReleaseCandidateEvaluation
from comicarr.tables import interactive_search_sessions, metadata


def _config(**overrides):
    values = {
        "ENABLE_DDL": True,
        "ENABLE_GETCOMICS": True,
        "ENABLE_EXTERNAL_SERVER": False,
        "EXPERIMENTAL": False,
        "NEWZNAB": False,
        "EXTRA_NEWZNABS": [],
        "ENABLE_TORRENT_SEARCH": False,
        "ENABLE_32P": False,
        "ENABLE_PUBLIC": False,
        "ENABLE_TORZNAB": False,
        "EXTRA_TORZNABS": [],
        "PROVIDER_ORDER": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    value = create_engine("sqlite:///%s" % (tmp_path / "interactive-api.db"))
    metadata.create_all(value)
    monkeypatch.setattr(interactive.db, "get_engine", lambda: value)
    monkeypatch.setattr(comicarr, "PROVIDER_BLOCKLIST", [])
    monkeypatch.setattr(interactive.helpers, "block_provider_check", lambda _name: False)
    monkeypatch.setattr(interactive.search_routes, "route_health", lambda _ctx: {"success": True, "routes": {}})
    yield value
    value.dispose()


def _evaluation(title="Candidate"):
    return ReleaseCandidateEvaluation(
        candidate={
            "title": title,
            "provider": "DDL(GetComics)",
            "source_kind": "ddl",
            "published_at": None,
            "size_bytes": None,
            "pack": False,
            "metrics": {},
        },
        verdict={
            "status": "accepted",
            "accepted": True,
            "overrideable": False,
            "reason_code": "accepted.issue",
            "reasons": [{"code": "accepted.issue", "message": "Accepted issue match"}],
            "match_kind": "standard",
        },
        reconstruction_hint={
            "provider_config_id": 200,
            "provider_type": "ddl",
            "provider_item_id": "item-1",
        },
    )


def _handoff_evaluation(title="Candidate"):
    evaluation = _evaluation(title)
    evaluation.legacy_match = {
        "ComicName": "Example",
        "ComicID": "series-1",
        "IssueID": "tracked-1",
        "ComicVolume": None,
        "IssueNumber": "1",
        "IssueDate": "2026-08-11",
        "comyear": "2026",
        "pack": False,
        "pack_numbers": None,
        "pack_issuelist": None,
        "modcomicname": "Example",
        "oneoff": False,
        "nzbprov": "DDL(GetComics)",
        "provider": "DDL(GetComics)",
        "nzbtitle": title,
        "nzbid": "item-1",
        "link": "https://provider.invalid/private",
        "pubdate": None,
        "size": None,
        "tmpprov": "DDL(GetComics)",
        "kind": "ddl",
        "SARC": None,
        "booktype": "Print",
        "IssueArcID": None,
        "newznab": None,
        "torznab": None,
        "downloadit": False,
        "ComicTitle": title,
        "entry": {"id": "item-1", "link": "https://provider.invalid/private"},
        "provider_stat": {"id": 200, "type": "ddl", "active": True, "hits": 0},
    }
    return evaluation


@pytest.fixture
def api_client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "alice"
    app.dependency_overrides[get_context] = lambda: AppContext(config=_config())
    client = TestClient(app)
    client.cookies.set(COOKIE_NAME, "browser-cookie")
    return client


def test_start_endpoint_binds_actor_and_browser_cookie(api_client, monkeypatch):
    captured = {}

    def start(_ctx, **kwargs):
        captured.update(kwargs)
        return {"success": True, "session_id": "opaque", "state": "queued"}

    monkeypatch.setattr(interactive, "start_search", start)

    response = api_client.post(
        "/api/search/interactive",
        json={"entity_type": "annual", "entity_id": "annual-1"},
    )

    assert response.status_code == 202
    assert response.json()["session_id"] == "opaque"
    assert captured == {
        "actor": "alice",
        "browser_session": "browser-cookie",
        "entity_type": "annual",
        "entity_id": "annual-1",
    }


def test_poll_endpoint_never_exposes_private_reconstruction(api_client, monkeypatch):
    monkeypatch.setattr(
        interactive,
        "get_search",
        lambda **_kwargs: {
            "session_id": "opaque",
            "state": "complete",
            "provider_failures": [],
            "candidates": [{"candidate_id": "candidate", "candidate": {"title": "Safe"}}],
        },
    )

    response = api_client.get("/api/search/interactive/opaque")

    assert response.status_code == 200
    assert "reconstruction" not in response.text


def test_grab_endpoint_binds_owner_and_explicit_override(api_client, monkeypatch):
    captured = {}

    def grab(_ctx, **kwargs):
        captured.update(kwargs)
        return {"success": True, "status": "submitted"}

    monkeypatch.setattr(interactive, "grab_candidate", grab)
    response = api_client.post(
        "/api/search/interactive/session-1/candidates/candidate-1/grab",
        json={"override": True},
    )

    assert response.status_code == 200
    assert captured == {
        "session_id": "session-1",
        "candidate_id": "candidate-1",
        "actor": "alice",
        "browser_session": "browser-cookie",
        "override": True,
    }


@pytest.mark.parametrize(
    ("entity_type", "mode"),
    [("issue", "want"), ("annual", "want_ann"), ("story_arc_issue", "story_arc")],
)
def test_start_validates_supported_tracked_items_and_returns_polling_resource(engine, monkeypatch, entity_type, mode):
    monkeypatch.setattr(
        interactive.search,
        "_search_source_for_issue",
        lambda *_args, **_kwargs: ({"ComicID": "series-1", "StoryArcID": "arc-1"}, mode, False),
    )
    if entity_type == "story_arc_issue":
        monkeypatch.setattr(
            interactive.db,
            "select_one",
            lambda _stmt: {"ComicID": "series-1", "StoryArcID": "arc-1"},
        )
    worker = {}

    def capture(target, **kwargs):
        worker.update({"target": target, **kwargs})

    monkeypatch.setattr(interactive, "start_background_thread", capture)

    result = interactive.start_search(
        AppContext(config=_config()),
        actor="alice",
        browser_session="browser-cookie",
        entity_type=entity_type,
        entity_id="tracked-1",
    )

    assert result["success"] is True
    assert result["state"] == "queued"
    assert result["progress"] == {
        "provider_total": 1,
        "provider_completed": 0,
        "current_provider": None,
    }
    assert result["candidates"] == []
    assert worker["target"] is interactive._collect
    assert worker["kwargs"]["entity"]["entity_type"] == entity_type


def test_start_rejects_mismatched_or_missing_entity(engine, monkeypatch):
    monkeypatch.setattr(
        interactive.search,
        "_search_source_for_issue",
        lambda *_args, **_kwargs: ({"ComicID": "series-1"}, "want_ann", False),
    )

    result = interactive.start_search(
        AppContext(config=_config()),
        actor="alice",
        browser_session="browser-cookie",
        entity_type="issue",
        entity_id="tracked-1",
    )

    assert result == {"success": False, "status_code": 404, "error": "Tracked item not found"}


def test_start_reports_blocked_when_no_provider_can_collect(engine, monkeypatch):
    monkeypatch.setattr(
        interactive.search,
        "_search_source_for_issue",
        lambda *_args, **_kwargs: ({"ComicID": "series-1"}, "want", False),
    )

    result = interactive.start_search(
        AppContext(config=_config(ENABLE_DDL=False, ENABLE_GETCOMICS=False)),
        actor="alice",
        browser_session="browser-cookie",
        entity_type="issue",
        entity_id="tracked-1",
    )

    assert result["status_code"] == 409
    assert result["status"] == "blocked"


def test_start_exposes_sanitized_route_health_block(engine, monkeypatch):
    monkeypatch.setattr(
        interactive.search,
        "_search_source_for_issue",
        lambda *_args, **_kwargs: ({"ComicID": "series-1"}, "want", False),
    )
    monkeypatch.setattr(
        interactive.search_routes,
        "route_health",
        lambda _ctx: {
            "success": False,
            "error": "client_not_ready",
            "routes": {"nzb": {"ready": False, "reason": "client_not_ready"}},
        },
    )

    result = interactive.start_search(
        AppContext(config=_config()),
        actor="alice",
        browser_session="browser-cookie",
        entity_type="issue",
        entity_id="tracked-1",
    )

    assert result["status_code"] == 409
    assert result["error"] == "client_not_ready"
    assert result["routes"]["nzb"]["reason"] == "client_not_ready"


def test_worker_collects_every_evaluation_without_auto_snatch(engine, monkeypatch):
    pending = interactive.create_pending_session(
        engine,
        actor="alice",
        browser_session="browser-cookie",
        entity_type="issue",
        entity_id="tracked-1",
        series_id="series-1",
        provider_total=2,
    )
    calls = []

    def manual_search(**kwargs):
        calls.append(kwargs)
        interactive.search_filer._INTERACTIVE_COLLECTOR.get()["evaluations"]([_evaluation("First")])
        interactive.search_filer.report_provider_complete("DDL(GetComics)")
        interactive.search_filer.report_provider_failure(
            "Indexer",
            "request_error",
            "https://user:pass@example.invalid/api?apikey=secret",
        )
        interactive.search_filer.report_provider_complete("Indexer")
        return []

    monkeypatch.setattr(interactive.search, "searchforissue", manual_search)

    interactive._collect(
        session_id=pending["session_id"],
        entity={"entity_type": "issue", "entity_id": "tracked-1", "series_id": "series-1"},
        initial_failures=[],
        provider_total=2,
    )

    result = read_session(
        engine,
        session_id=pending["session_id"],
        actor="alice",
        browser_session="browser-cookie",
    )
    assert calls == [{"issueid": "tracked-1", "manual": True, "entity_type": "issue"}]
    assert result["state"] == "complete"
    assert result["progress"]["provider_completed"] == 2
    assert result["candidates"][0]["candidate"]["title"] == "First"
    assert result["provider_failures"][0]["code"] == "request_error"
    assert "secret" not in str(result)
    assert "https://" not in str(result)


def test_worker_failure_is_terminal_and_credential_safe(engine, monkeypatch):
    pending = interactive.create_pending_session(
        engine,
        actor="alice",
        browser_session="browser-cookie",
        entity_type="issue",
        entity_id="tracked-1",
        provider_total=1,
    )
    monkeypatch.setattr(
        interactive.search,
        "searchforissue",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("https://host/api?token=secret")),
    )

    interactive._collect(
        session_id=pending["session_id"],
        entity={"entity_type": "issue", "entity_id": "tracked-1", "series_id": "series-1"},
        initial_failures=[],
        provider_total=1,
    )

    with engine.connect() as conn:
        row = conn.execute(select(interactive_search_sessions)).mappings().one()
    assert row["state"] == "failed"
    assert "secret" not in row["provider_failures_json"]
    assert "https://" not in row["provider_failures_json"]


def test_grab_refinds_exact_candidate_handoffs_once_and_replays(engine, monkeypatch):
    created = create_session(
        engine,
        actor="alice",
        browser_session="browser-cookie",
        entity_type="issue",
        entity_id="tracked-1",
        series_id="series-1",
        evaluations=[_handoff_evaluation()],
    )
    candidate_id = created["candidates"][0]["candidate_id"]
    monkeypatch.setattr(
        interactive,
        "_resolve_entity",
        lambda entity_type, entity_id: (
            {"entity_type": entity_type, "entity_id": entity_id, "series_id": "series-1"},
            None,
        ),
    )
    monkeypatch.setattr(interactive, "_candidate_eligibility", lambda _entity: {"status": True})
    searches = []

    def manual_search(**kwargs):
        searches.append(kwargs)
        interactive.search_filer._INTERACTIVE_COLLECTOR.get()["evaluations"]([_handoff_evaluation()])
        return []

    monkeypatch.setattr(interactive.search, "searchforissue", manual_search)
    handoffs = []

    def verify(matches, info):
        handoffs.append((matches, info))
        info["foundc"] = {
            "status": True,
            "info": {"journal_release_key": "release-1", "journal_managed": True},
        }
        return info

    monkeypatch.setattr(interactive.search, "verification", verify)
    kwargs = {
        "session_id": created["session_id"],
        "candidate_id": candidate_id,
        "actor": "alice",
        "browser_session": "browser-cookie",
    }

    first = interactive.grab_candidate(AppContext(config=_config()), **kwargs)
    replay = interactive.grab_candidate(AppContext(config=_config()), **kwargs)

    assert first == {
        "status": "submitted",
        "candidate_id": candidate_id,
        "journal_release_key": "release-1",
        "journal_managed": True,
        "success": True,
        "idempotent": False,
    }
    assert replay["success"] is True
    assert replay["idempotent"] is True
    assert len(searches) == 1
    assert len(handoffs) == 1
    assert handoffs[0][0][0]["downloadit"] is True


def test_grab_fails_closed_when_candidate_identity_changes(engine, monkeypatch):
    created = create_session(
        engine,
        actor="alice",
        browser_session="browser-cookie",
        entity_type="issue",
        entity_id="tracked-1",
        evaluations=[_handoff_evaluation()],
    )
    monkeypatch.setattr(
        interactive,
        "_resolve_entity",
        lambda entity_type, entity_id: (
            {"entity_type": entity_type, "entity_id": entity_id, "series_id": "series-1"},
            None,
        ),
    )
    monkeypatch.setattr(interactive, "_candidate_eligibility", lambda _entity: {"status": True})

    def changed_search(**_kwargs):
        changed = _handoff_evaluation()
        changed.legacy_match["nzbid"] = "different-item"
        changed.reconstruction_hint["provider_item_id"] = "different-item"
        interactive.search_filer._INTERACTIVE_COLLECTOR.get()["evaluations"]([changed])
        return []

    monkeypatch.setattr(interactive.search, "searchforissue", changed_search)
    result = interactive.grab_candidate(
        AppContext(config=_config()),
        session_id=created["session_id"],
        candidate_id=created["candidates"][0]["candidate_id"],
        actor="alice",
        browser_session="browser-cookie",
    )

    assert result["success"] is False
    assert result["code"] == "candidate_changed"


def test_grab_requires_and_revalidates_explicit_candidate_override(engine, monkeypatch):
    rejected = _evaluation("Candidate REPACK")
    rejected.verdict.update(
        {
            "status": "rejected",
            "accepted": False,
            "overrideable": True,
            "reason_code": "ignored.search_word",
            "match_kind": "none",
        }
    )
    created = create_session(
        engine,
        actor="alice",
        browser_session="browser-cookie",
        entity_type="issue",
        entity_id="tracked-1",
        evaluations=[rejected],
    )
    candidate_id = created["candidates"][0]["candidate_id"]
    monkeypatch.setattr(
        interactive,
        "_resolve_entity",
        lambda entity_type, entity_id: (
            {"entity_type": entity_type, "entity_id": entity_id, "series_id": "series-1"},
            None,
        ),
    )
    monkeypatch.setattr(interactive, "_candidate_eligibility", lambda _entity: {"status": True})
    kwargs = {
        "session_id": created["session_id"],
        "candidate_id": candidate_id,
        "actor": "alice",
        "browser_session": "browser-cookie",
    }

    required = interactive.grab_candidate(AppContext(config=_config()), **kwargs)
    assert required["code"] == "override_required"

    reasons = []

    def revalidate(_entity, *, override_reason=None):
        reasons.append(override_reason)
        return [_handoff_evaluation("Candidate REPACK")], []

    monkeypatch.setattr(interactive, "_revalidate_candidate", revalidate)

    def verify(_matches, info):
        info["foundc"] = {"status": True, "info": {"journal_release_key": "release-override"}}
        return info

    monkeypatch.setattr(interactive.search, "verification", verify)
    result = interactive.grab_candidate(AppContext(config=_config()), override=True, **kwargs)

    assert result["status"] == "submitted"
    assert reasons == ["ignored.search_word"]
