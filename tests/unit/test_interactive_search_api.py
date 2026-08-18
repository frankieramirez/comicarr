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


def _missing_items():
    return [
        {"entity_type": "issue", "entity_id": "i1", "issue_number": "1"},
        {"entity_type": "issue", "entity_id": "i2", "issue_number": "2"},
        {"entity_type": "issue", "entity_id": "i3", "issue_number": "3"},
        {"entity_type": "issue", "entity_id": "i10", "issue_number": "10"},
    ]


def _pack_evaluation(title="Example 001-010"):
    evaluation = _evaluation(title)
    evaluation.candidate["pack"] = True
    evaluation.verdict.update(
        {
            "reason_code": "accepted.pack",
            "reasons": [{"code": "accepted.pack", "message": "Accepted pack match"}],
            "match_kind": "pack",
        }
    )
    evaluation.legacy_match = {
        "ComicName": "Example",
        "ComicID": "series-1",
        "IssueID": "i1",
        "IssueNumber": "1",
        "pack": True,
        "pack_numbers": "1-10",
        "pack_issuelist": {
            "valid": True,
            "issues": [
                {"issueid": "i1", "issuenumber": "1"},
                {"issueid": "i2", "issuenumber": "2"},
                {"issueid": "i3", "issuenumber": "3"},
                {"issueid": "owned-4", "issuenumber": "4"},
            ],
        },
        "nzbprov": "DDL(GetComics)",
        "provider": "DDL(GetComics)",
        "nzbtitle": title,
        "nzbid": "pack-1",
        "link": "https://provider.invalid/pack",
        "entry": {"id": "pack-1"},
        "provider_stat": {"id": 200, "type": "ddl", "active": True, "hits": 0},
        "comyear": "2026",
        "downloadit": False,
        "oneoff": False,
        "SARC": None,
        "IssueArcID": None,
        "ComicTitle": title,
        "tmpprov": "DDL(GetComics)",
        "kind": "ddl",
        "booktype": "Print",
        "newznab": None,
        "torznab": None,
        "pubdate": None,
        "size": None,
        "modcomicname": title,
        "ComicVolume": None,
        "IssueDate": "2026-08-11",
    }
    evaluation.reconstruction_hint = {
        "provider_config_id": 200,
        "provider_type": "ddl",
        "provider_item_id": "pack-1",
    }
    return evaluation


def test_start_accepts_series_with_eligible_missing_issues(engine, monkeypatch):
    monkeypatch.setattr(
        interactive.db,
        "select_one",
        lambda _stmt: {"ComicID": "series-1", "ComicName": "Example"},
    )
    monkeypatch.setattr(interactive, "_series_missing_items", lambda *_args, **_kwargs: _missing_items())
    worker = {}
    monkeypatch.setattr(
        interactive, "start_background_thread", lambda target, **kwargs: worker.update({"target": target, **kwargs})
    )

    result = interactive.start_search(
        AppContext(config=_config()),
        actor="alice",
        browser_session="browser-cookie",
        entity_type="series",
        entity_id="series-1",
    )

    assert result["success"] is True
    assert result["entity_type"] == "series"
    assert result["entity_id"] == "series-1"
    assert result["state"] == "queued"
    assert worker["target"] is interactive._collect
    assert [item["entity_id"] for item in worker["kwargs"]["entity"]["targets"]] == [
        "i1",
        "i10",
        "i2",
        "i3",
    ]
    assert worker["kwargs"]["provider_total"] == result["progress"]["provider_total"] == 4


def test_start_rejects_series_with_no_eligible_missing_issues(engine, monkeypatch):
    monkeypatch.setattr(
        interactive.db,
        "select_one",
        lambda _stmt: {"ComicID": "series-1", "ComicName": "Example"},
    )
    monkeypatch.setattr(interactive, "_series_missing_items", lambda *_args, **_kwargs: [])

    result = interactive.start_search(
        AppContext(config=_config()),
        actor="alice",
        browser_session="browser-cookie",
        entity_type="series",
        entity_id="series-1",
    )

    assert result == {
        "success": False,
        "status_code": 409,
        "status": "blocked",
        "error": "No eligible missing issues remain to search",
    }


def test_start_rejects_unknown_series(engine, monkeypatch):
    monkeypatch.setattr(interactive.db, "select_one", lambda _stmt: None)

    result = interactive.start_search(
        AppContext(config=_config()),
        actor="alice",
        browser_session="browser-cookie",
        entity_type="series",
        entity_id="missing",
    )

    assert result == {"success": False, "status_code": 404, "error": "Tracked item not found"}


def test_series_worker_searches_gap_starts_and_annotates_pack_coverage(engine, monkeypatch):
    pending = interactive.create_pending_session(
        engine,
        actor="alice",
        browser_session="browser-cookie",
        entity_type="series",
        entity_id="series-1",
        series_id="series-1",
        provider_total=1,
    )
    searched = []

    def _single(title, item_id):
        evaluation = _evaluation(title)
        evaluation.reconstruction_hint = {
            "provider_config_id": 200,
            "provider_type": "ddl",
            "provider_item_id": item_id,
        }
        return evaluation

    def manual_search(**kwargs):
        searched.append(kwargs)
        evaluations = [_pack_evaluation(), _single("Example 001", "item-1")]
        if kwargs["issueid"] == "i10":
            evaluations = [_single("Example 010", "item-10")]
        interactive.search_filer._INTERACTIVE_COLLECTOR.get()["evaluations"](evaluations)
        interactive.search_filer.report_provider_complete("DDL(GetComics)")
        return []

    monkeypatch.setattr(interactive.search, "searchforissue", manual_search)

    interactive._collect(
        session_id=pending["session_id"],
        entity={
            "entity_type": "series",
            "entity_id": "series-1",
            "series_id": "series-1",
            "missing": _missing_items(),
            "targets": [
                {"entity_type": "issue", "entity_id": "i1", "issue_number": "1"},
                {"entity_type": "issue", "entity_id": "i10", "issue_number": "10"},
            ],
        },
        initial_failures=[],
        provider_total=1,
    )

    result = read_session(
        engine,
        session_id=pending["session_id"],
        actor="alice",
        browser_session="browser-cookie",
    )
    assert [call["issueid"] for call in searched] == ["i1", "i10"]
    assert all(call["manual"] is True for call in searched)
    assert result["state"] == "complete"
    pack = next(candidate for candidate in result["candidates"] if candidate["candidate"]["pack"])
    assert pack["satisfies"] == [
        {"entity_type": "issue", "entity_id": "i1", "issue_number": "1"},
        {"entity_type": "issue", "entity_id": "i2", "issue_number": "2"},
        {"entity_type": "issue", "entity_id": "i3", "issue_number": "3"},
    ]
    titles = [candidate["candidate"]["title"] for candidate in result["candidates"]]
    assert titles[0] == "Example 001-010"
    assert "Example 001" in titles
    assert "Example 010" in titles
    assert titles.count("Example 001-010") == 1


def test_series_grab_revalidates_against_the_pack_anchor_issue(engine, monkeypatch):
    pack = _pack_evaluation()
    pack.satisfies = [
        {"entity_type": "issue", "entity_id": "i1", "issue_number": "1"},
        {"entity_type": "issue", "entity_id": "i2", "issue_number": "2"},
    ]
    created = create_session(
        engine,
        actor="alice",
        browser_session="browser-cookie",
        entity_type="series",
        entity_id="series-1",
        series_id="series-1",
        evaluations=[pack],
    )
    resolved = []

    def resolve(entity_type, entity_id):
        resolved.append((entity_type, entity_id))
        return {"entity_type": entity_type, "entity_id": entity_id, "series_id": "series-1"}, None

    monkeypatch.setattr(interactive, "_resolve_entity", resolve)
    monkeypatch.setattr(interactive, "_candidate_eligibility", lambda _entity: {"status": True})
    searches = []

    def manual_search(**kwargs):
        searches.append(kwargs)
        interactive.search_filer._INTERACTIVE_COLLECTOR.get()["evaluations"]([_pack_evaluation()])
        return []

    monkeypatch.setattr(interactive.search, "searchforissue", manual_search)

    def verify(matches, info):
        info["foundc"] = {"status": True, "info": {"journal_release_key": "pack-release", "journal_managed": True}}
        return info

    monkeypatch.setattr(interactive.search, "verification", verify)

    result = interactive.grab_candidate(
        AppContext(config=_config()),
        session_id=created["session_id"],
        candidate_id=created["candidates"][0]["candidate_id"],
        actor="alice",
        browser_session="browser-cookie",
    )

    assert result["success"] is True
    assert result["status"] == "submitted"
    assert ("issue", "i1") in resolved
    assert ("series", "series-1") not in resolved
    assert searches == [{"issueid": "i1", "manual": True, "entity_type": "issue"}]


def test_series_worker_scales_the_blocked_provider_offset_across_targets(engine, monkeypatch):
    initial_failures = [
        {"provider": "Indexer", "code": "temporarily_blocked", "detail": "Provider is temporarily blocked"}
    ]
    targets = [
        {"entity_type": "issue", "entity_id": "i1", "issue_number": "1"},
        {"entity_type": "issue", "entity_id": "i10", "issue_number": "10"},
    ]
    # Two planned providers over two targets, one of them blocked before the
    # worker starts, so provider_total is len(plan) * len(targets).
    provider_total = 2 * len(targets)
    pending = interactive.create_pending_session(
        engine,
        actor="alice",
        browser_session="browser-cookie",
        entity_type="series",
        entity_id="series-1",
        series_id="series-1",
        provider_total=provider_total,
        provider_failures=initial_failures,
    )
    reported = []

    def manual_search(**kwargs):
        evaluation = _evaluation("Example %s" % kwargs["issueid"])
        evaluation.reconstruction_hint = {
            "provider_config_id": 200,
            "provider_type": "ddl",
            "provider_item_id": "item-%s" % kwargs["issueid"],
        }
        interactive.search_filer._INTERACTIVE_COLLECTOR.get()["evaluations"]([evaluation])
        interactive.search_filer.report_provider_complete("DDL(GetComics)")
        reported.append(
            read_session(
                engine,
                session_id=pending["session_id"],
                actor="alice",
                browser_session="browser-cookie",
            )["progress"]["provider_completed"]
        )
        return []

    monkeypatch.setattr(interactive.search, "searchforissue", manual_search)

    interactive._collect(
        session_id=pending["session_id"],
        entity={
            "entity_type": "series",
            "entity_id": "series-1",
            "series_id": "series-1",
            "missing": _missing_items(),
            "targets": targets,
        },
        initial_failures=initial_failures,
        provider_total=provider_total,
    )

    result = read_session(
        engine,
        session_id=pending["session_id"],
        actor="alice",
        browser_session="browser-cookie",
    )
    # One blocked provider over two targets occupies two of the four slots, so
    # the first target finishing reports 1 + 2 and not the unscaled 1 + 1.
    assert reported == [3, 4]
    assert result["state"] == "complete"
    assert result["progress"]["provider_total"] == provider_total
    assert result["progress"]["provider_completed"] == provider_total


def test_series_worker_marks_the_session_failed_when_every_target_fails(engine, monkeypatch):
    initial_failures = [
        {"provider": "Indexer", "code": "temporarily_blocked", "detail": "Provider is temporarily blocked"}
    ]
    targets = [
        {"entity_type": "issue", "entity_id": "i1", "issue_number": "1"},
        {"entity_type": "issue", "entity_id": "i10", "issue_number": "10"},
    ]
    provider_total = 2 * len(targets)
    pending = interactive.create_pending_session(
        engine,
        actor="alice",
        browser_session="browser-cookie",
        entity_type="series",
        entity_id="series-1",
        series_id="series-1",
        provider_total=provider_total,
        provider_failures=initial_failures,
    )
    monkeypatch.setattr(
        interactive.search,
        "searchforissue",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("https://host/api?token=secret")),
    )

    interactive._collect(
        session_id=pending["session_id"],
        entity={
            "entity_type": "series",
            "entity_id": "series-1",
            "series_id": "series-1",
            "missing": _missing_items(),
            "targets": targets,
        },
        initial_failures=initial_failures,
        provider_total=provider_total,
    )

    result = read_session(
        engine,
        session_id=pending["session_id"],
        actor="alice",
        browser_session="browser-cookie",
    )
    assert result["state"] == "failed"
    assert result["candidates"] == []
    assert [failure["code"] for failure in result["provider_failures"]] == [
        "temporarily_blocked",
        "collection_failed",
        "collection_failed",
    ]
    # No provider ever completed, so only the blocked provider slots count.
    assert result["progress"]["provider_completed"] == 2
    assert "secret" not in str(result)
    assert "https://" not in str(result)


def test_series_grab_rejects_a_candidate_without_a_tracked_anchor(engine, monkeypatch):
    pack = _pack_evaluation()
    pack.satisfies = []
    created = create_session(
        engine,
        actor="alice",
        browser_session="browser-cookie",
        entity_type="series",
        entity_id="series-1",
        series_id="series-1",
        evaluations=[pack],
    )
    searches = []
    monkeypatch.setattr(interactive.search, "searchforissue", lambda **kwargs: searches.append(kwargs) or [])
    monkeypatch.setattr(interactive, "_candidate_eligibility", lambda _entity: {"status": True})

    result = interactive.grab_candidate(
        AppContext(config=_config()),
        session_id=created["session_id"],
        candidate_id=created["candidates"][0]["candidate_id"],
        actor="alice",
        browser_session="browser-cookie",
    )

    assert result["success"] is False
    assert result["status_code"] == 409
    assert result["status"] == "blocked"
    assert result["error"] == "Release candidate has no tracked issue to grab against"
    assert searches == []
