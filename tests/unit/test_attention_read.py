#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Needs-attention read-interface and canonical HTTP tests."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.tables import metadata, pipeline_journal


@pytest.fixture
def attention_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _journal(**overrides):
    row = {
        "release_key": "rk-1",
        "issueid": "iss-1",
        "provider": "DDL",
        "stage": "failed",
        "stage_rank": 60,
        "updated_date": "2026-07-10 12:00:00",
        "status": None,
        "fail_reason": "submission_rejected",
        "payload_json": json.dumps({"comicid": "42", "comicname": "Saga"}),
    }
    row.update(overrides)
    return row


def test_read_returns_one_consistent_view_of_actionable_obligations(attention_db):
    from comicarr.app.attention import AttentionGroup, AttentionMember, AttentionView, read

    with attention_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(release_key="actionable-1", issueid="iss-1"),
                _journal(release_key="actionable-2", issueid="iss-2"),
                _journal(release_key="self-reconciled", issueid="iss-3", fail_reason="download_gone"),
                _journal(release_key="resolved", issueid="iss-4", status="retried"),
            ],
        )

    view = read()

    assert isinstance(view, AttentionView)
    assert view.total == 1
    assert view.member_total == 2
    assert len(view.groups) == 1
    assert isinstance(view.groups[0], AttentionGroup)
    assert isinstance(view.groups[0].members[0], AttentionMember)
    assert view.groups[0].group_key == "42|submission_rejected"
    assert {member.release_key for member in view.groups[0].members} == {
        "actionable-1",
        "actionable-2",
    }


def test_read_accepts_positional_scope_and_filters_before_grouping(attention_db):
    from comicarr.app.attention import Scope, read

    with attention_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(release_key="in-scope", issueid="iss-1"),
                _journal(release_key="out-of-scope", issueid="iss-2"),
            ],
        )

    view = read(Scope(type="issue", id="iss-1"))

    assert view.member_total == 1
    assert [member.release_key for member in view.groups[0].members] == ["in-scope"]


def test_sql_admission_and_is_actionable_agree_on_token_shapes(attention_db):
    from comicarr.app.attention import read
    from comicarr.app.attention._policy import is_actionable

    with attention_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                _journal(release_key="suffixed-flat", issueid="iss-1", fail_reason="download_gone:pruned"),
                _journal(release_key="bare-composite", issueid="iss-2", fail_reason="immutable_payload_conflict"),
            ],
        )

    view = read()

    assert view.total == 0
    assert view.member_total == 0
    assert len(view.groups) == 0
    assert is_actionable("download_gone:pruned") is False
    assert is_actionable("immutable_payload_conflict") is False


def test_read_rejects_scope_with_none_id(attention_db):
    from comicarr.app.attention import Scope, read

    with pytest.raises(ValueError, match="provided together"):
        read(scope=Scope(type="series", id=None))


def test_canonical_get_serializes_the_attention_view(attention_db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from comicarr.app.attention.router import router
    from comicarr.app.core.security import require_session

    with attention_db.begin() as conn:
        conn.execute(insert(pipeline_journal), [_journal(release_key="actionable")])

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "operator"

    with TestClient(app) as client:
        response = client.get("/api/attention")

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "group_key": "42|submission_rejected",
                "comicid": "42",
                "series_label": "Saga",
                "base_reason": "submission_rejected",
                "reason_phrase": "the downloader rejected the submission",
                "member_count": 1,
                "newest_updated_at": "2026-07-10 12:00:00",
                "oldest_updated_at": "2026-07-10 12:00:00",
                "members": [
                    {
                        "release_key": "actionable",
                        "issue_label": "Saga",
                        "issueid": "iss-1",
                        "stage": "failed",
                        "available_actions": ["retry", "stop_wanting"],
                        "updated_date": "2026-07-10 12:00:00",
                    }
                ],
                "stage": "failed",
                "available_actions": ["retry", "stop_wanting"],
            }
        ],
        "causes": [
            {
                "cause_key": "submission_rejected|failed",
                "base_reason": "submission_rejected",
                "reason_phrase": "the downloader rejected the submission",
                "headline": "The downloader rejected these submissions",
                "hint": None,
                "icon": "failed",
                "fix": None,
                "stage": "failed",
                "available_actions": ["retry", "stop_wanting"],
                "series_count": 1,
                "member_count": 1,
                "newest_updated_at": "2026-07-10 12:00:00",
                "series": [
                    {
                        "group_key": "42|submission_rejected",
                        "comicid": "42",
                        "series_label": "Saga",
                        "member_count": 1,
                        "issue_labels": ["Saga"],
                    }
                ],
                "release_keys": ["actionable"],
            }
        ],
        "total": 1,
        "member_total": 1,
        "preview_cap": 5,
    }


def test_get_attention_requires_session_without_override():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from comicarr.app.attention.router import router
    from comicarr.app.core.context import AppContext, get_context

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_context] = lambda: AppContext()
    # Leave require_session real — missing cookie should 401.

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/attention")

    assert response.status_code == 401


def test_downloads_and_activity_attention_adapters_are_removed():
    """ADR-0003: the six compatibility routes left in 0.49.x; /api/attention owns the queue."""
    from comicarr.app.activity.router import router as activity_router
    from comicarr.app.downloads.router import router as downloads_router

    routes = {
        (route.path, method)
        for router in (activity_router, downloads_router)
        for route in router.routes
        for method in (getattr(route, "methods", None) or set())
    }

    assert ("/api/downloads/needs-attention", "GET") not in routes
    assert ("/api/activity/band", "GET") not in routes
    assert not any("needs-attention" in path for path, _method in routes)


def test_view_folds_series_groups_into_causes(attention_db):
    """The dashboard's "Needs you" rows: one row per cause, every series it touches."""
    from comicarr.app.attention import PREVIEW_CAP, read
    from comicarr.app.attention._serialization import serialize_view

    def saga(**kw):
        return _journal(payload_json=json.dumps({"comicid": "42", "comicname": "Saga"}), **kw)

    def batman(**kw):
        return _journal(payload_json=json.dumps({"comicid": "7", "comicname": "Batman"}), **kw)

    with attention_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal),
            [
                saga(release_key="s-1", issueid="s1", fail_reason="invalid_postprocess_command"),
                saga(release_key="s-2", issueid="s2", fail_reason="invalid_postprocess_command"),
                batman(release_key="b-1", issueid="b1", fail_reason="invalid_postprocess_command:exit 2"),
                batman(release_key="b-2", issueid="b2", fail_reason="submission_rejected"),
            ],
        )

    body = serialize_view(read(), preview_cap=PREVIEW_CAP)
    assert body["total"] == 3
    causes = body["causes"]
    assert [cause["base_reason"] for cause in causes] == ["invalid_postprocess_command", "submission_rejected"]

    misconfigured = causes[0]
    assert misconfigured["headline"] == "Post-processing is misconfigured"
    assert misconfigured["fix"] == {"label": "Open post-processing", "href": "/settings?section=media"}
    assert misconfigured["series_count"] == 2
    assert misconfigured["member_count"] == 3
    assert [series["series_label"] for series in misconfigured["series"]] == ["Saga", "Batman"]
    assert sorted(misconfigured["release_keys"]) == ["b-1", "s-1", "s-2"]
    assert misconfigured["available_actions"] == ["retry", "stop_wanting"]

    rejected = causes[1]
    assert rejected["headline"] == "The downloader rejected these submissions"
    assert rejected["fix"] is None
    assert rejected["release_keys"] == ["b-2"]
    # Totals across causes equal the series view's member total.
    assert sum(cause["member_count"] for cause in causes) == body["member_total"]


def test_unmapped_reason_cause_falls_back_to_its_phrase(attention_db):
    from comicarr.app.attention import PREVIEW_CAP, read
    from comicarr.app.attention._serialization import serialize_view

    with attention_db.begin() as conn:
        conn.execute(insert(pipeline_journal), [_journal(fail_reason="postprocess_error")])

    (cause,) = serialize_view(read(), preview_cap=PREVIEW_CAP)["causes"]
    assert cause["headline"] == "Post-processing failed"
    assert cause["hint"] is None
