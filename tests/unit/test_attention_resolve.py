#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Needs attention operator resolution through the public module interface."""

from types import SimpleNamespace

import pytest

import comicarr
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.attention import ResolutionRequest, read, resolve
from comicarr.app.core.context import AppContext
from comicarr.app.downloads import journal
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, issues, metadata, pipeline_journal


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    monkeypatch.setattr(comicarr, "PROVIDER_BLOCKLIST", {}, raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            FAILED_DOWNLOAD_HANDLING=True,
            FAILED_AUTO=False,
            HIGHCOUNT=0,
            DDL_LOCATION=str(tmp_path / "ddl"),
            CACHE_DIR=str(tmp_path / "cache"),
            DESTINATION_DIR=str(tmp_path / "library"),
        ),
        raising=False,
    )
    engine = get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready
    yield
    shutdown_engine()


def _seed_failed_obligation():
    with get_engine().begin() as conn:
        conn.execute(
            comics.insert().values(
                ComicID="C1",
                ComicName="Saga",
                ComicYear="2012",
                Status="Active",
            )
        )
        conn.execute(
            issues.insert().values(
                IssueID="1001",
                ComicID="C1",
                ComicName="Saga",
                Issue_Number="1",
                Status="Failed",
            )
        )

    release_key = "1001|nzbgeek"
    payload = {
        "issueid": "1001",
        "comicid": "C1",
        "comicname": "Saga",
        "issuenumber": "1",
        "provider": "nzbgeek",
        "nzbname": "Saga.001",
    }
    journal.record_transition(
        release_key,
        journal.SNATCHED,
        payload=payload,
        issueid="1001",
        provider="nzbgeek",
        nzbname="Saga.001",
    )
    journal.mark_failed(
        release_key,
        "download_failed_no_auto_handling",
        payload=payload,
        issueid="1001",
        provider="nzbgeek",
    )
    return release_key


def test_operator_can_stop_wanting_one_obligation_through_unified_resolution():
    release_key = _seed_failed_obligation()
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    report = resolve(
        ctx,
        ResolutionRequest(
            action="stop_wanting",
            release_keys=(release_key,),
            actor="operator",
        ),
    )

    assert report.success is True
    assert report.partial is False
    assert report.requested == 1
    assert report.processed == 1
    assert report.succeeded == 1
    assert report.failed == 0
    assert report.results[0].release_key == release_key
    assert report.results[0].ok is True
    assert all(member.release_key != release_key for group in read().groups for member in group.members)


def test_canonical_resolution_route_uses_one_report_for_one_key():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from comicarr.app.attention.router import router
    from comicarr.app.core.context import get_context
    from comicarr.app.core.security import require_session

    release_key = _seed_failed_obligation()
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "operator"
    app.dependency_overrides[get_context] = lambda: ctx

    with TestClient(app) as client:
        response = client.post(
            "/api/attention/resolve",
            json={"action": "stop_wanting", "release_keys": [release_key]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "partial": False,
        "action": "stop_wanting",
        "requested": 1,
        "processed": 1,
        "succeeded": 1,
        "failed": 0,
        "capped": False,
        "skipped_for_cap": 0,
        "cap": 25,
        "results": [
            {
                "release_key": release_key,
                "ok": True,
                "status": "ignored",
                "error": None,
                "status_code": None,
            }
        ],
    }


def test_resolve_attention_requires_session_without_override():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from comicarr.app.attention.router import router
    from comicarr.app.core.context import get_context

    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_context] = lambda: ctx
    # Leave require_session real — missing cookie should 401.

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/attention/resolve",
            json={"action": "stop_wanting", "release_keys": []},
        )

    assert response.status_code == 401


def _canonical_client(ctx):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from comicarr.app.attention.router import router
    from comicarr.app.core.context import get_context
    from comicarr.app.core.security import require_session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "operator"
    app.dependency_overrides[get_context] = lambda: ctx
    return TestClient(app)


def test_canonical_resolution_rejects_non_object_json_with_422():
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    with _canonical_client(ctx) as client:
        response = client.post("/api/attention/resolve", json=["not", "an", "object"])

    assert response.status_code == 422


def test_canonical_resolution_rejects_semantically_invalid_object_with_400():
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    with _canonical_client(ctx) as client:
        response = client.post(
            "/api/attention/resolve",
            json={"action": "nuke", "release_keys": ["missing"]},
        )

    assert response.status_code == 400
    assert "unknown action" in response.json()["detail"].lower()


@pytest.mark.parametrize(
    "release_keys",
    ["one", 42, {"release_key": "one"}, [{"bad": "key"}]],
)
def test_canonical_resolution_rejects_malformed_release_keys_with_400(release_keys):
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    with _canonical_client(ctx) as client:
        response = client.post(
            "/api/attention/resolve",
            json={"action": "stop_wanting", "release_keys": release_keys},
        )

    assert response.status_code == 400
    assert "release_keys" in response.json()["detail"]


def test_canonical_resolution_returns_409_when_no_item_succeeds():
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    with _canonical_client(ctx) as client:
        response = client.post(
            "/api/attention/resolve",
            json={"action": "stop_wanting", "release_keys": ["missing"]},
        )

    assert response.status_code == 409
    assert response.json()["success"] is False
    assert response.json()["failed"] == 1
    assert response.json()["results"][0]["status_code"] == 404


def test_canonical_resolution_returns_200_for_partial_success():
    release_key = _seed_failed_obligation()
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    with _canonical_client(ctx) as client:
        response = client.post(
            "/api/attention/resolve",
            json={
                "action": "stop_wanting",
                "release_keys": [release_key, "missing"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["partial"] is True
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert {item["release_key"] for item in body["results"]} == {release_key, "missing"}


def test_public_resolve_deduplicates_and_trims_release_keys():
    release_key = _seed_failed_obligation()
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})

    report = resolve(
        ctx,
        ResolutionRequest(
            action="stop_wanting",
            release_keys=("  " + release_key + "  ", release_key, "missing"),
            actor="operator",
        ),
    )

    assert report.requested == 2
    assert report.processed == 2
    assert [item.release_key for item in report.results] == [release_key, "missing"]
    assert report.succeeded == 1
    assert report.failed == 1


def test_public_resolve_caps_newest_rows_before_fanout():
    ctx = AppContext(config=comicarr.CONFIG, provider_blocklist={})
    keys = []
    with get_engine().begin() as conn:
        for index in range(27):
            key = "cap-%02d" % index
            keys.append(key)
            conn.execute(
                pipeline_journal.insert().values(
                    release_key=key,
                    issueid="missing-%02d" % index,
                    provider="test",
                    stage="failed",
                    stage_rank=60,
                    updated_date="2026-08-%02d 12:00:00" % (index + 1),
                    fail_reason="download_failed_no_auto_handling",
                )
            )

    report = resolve(
        ctx,
        ResolutionRequest(action="stop_wanting", release_keys=tuple(keys), actor="operator"),
    )

    assert report.requested == 27
    assert report.processed == 25
    assert report.capped is True
    assert report.skipped_for_cap == 2
    assert [item.release_key for item in report.results] == list(reversed(keys[-25:]))
