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


def test_raw_downloads_attention_reader_is_removed_but_post_adapters_remain():
    from comicarr.app.downloads.router import router

    routes = {(route.path, method) for route in router.routes for method in (getattr(route, "methods", None) or set())}

    assert ("/api/downloads/needs-attention", "GET") not in routes
    assert ("/api/downloads/needs-attention/batch", "POST") in routes
