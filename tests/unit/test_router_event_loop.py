#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Async routes must dispatch blocking service work off the event loop (#733)."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import require_session
from comicarr.app.series import service as series_service
from comicarr.app.series.router import router as series_router
from comicarr.app.storyarcs.router import router as storyarcs_router


def _on_event_loop():
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(series_router)
    app.include_router(storyarcs_router)
    app.dependency_overrides[require_session] = lambda: "alice"
    app.dependency_overrides[get_context] = lambda: AppContext(config=SimpleNamespace())
    return TestClient(app)


def test_search_all_missing_runs_service_off_the_event_loop(client, monkeypatch):
    observed = {}

    def search_all_missing(_ctx, _comic_id, **_kwargs):
        observed["on_event_loop"] = _on_event_loop()
        return {"success": True, "run_id": "run-1"}

    monkeypatch.setattr(series_service, "search_all_missing", search_all_missing)

    response = client.post("/api/series/123/search-missing", json={"confirm": True})

    assert response.status_code == 200
    assert observed["on_event_loop"] is False


def test_search_one_wanted_issue_runs_service_off_the_event_loop(client, monkeypatch):
    observed = {}

    def search_wanted_issue(_issue_id, _actor, **_kwargs):
        observed["on_event_loop"] = _on_event_loop()
        return {"success": True, "run_id": "run-1"}

    monkeypatch.setattr(series_service, "search_wanted_issue", search_wanted_issue)

    response = client.post("/api/series/issues/456/search", json={})

    assert response.status_code == 200
    assert observed["on_event_loop"] is False


def test_generate_story_arc_runs_ai_pipeline_off_the_event_loop(client, monkeypatch):
    from comicarr.app.ai import story_arcs

    observed = {}

    def generate_reading_order(_description):
        observed["on_event_loop"] = _on_event_loop()
        return {"success": True, "issues": [{"series": "X-Men", "issue": "1"}]}

    monkeypatch.setattr(story_arcs, "generate_reading_order", generate_reading_order)
    monkeypatch.setattr(story_arcs, "enrich_with_providers", lambda issues: issues)
    monkeypatch.setattr(story_arcs, "map_to_library", lambda issues: issues)

    response = client.post("/api/storyarcs/generate", json={"description": "Dark Phoenix Saga"})

    assert response.status_code == 200
    assert observed["on_event_loop"] is False


def test_save_generated_arc_runs_service_off_the_event_loop(client, monkeypatch):
    from comicarr.app.ai import story_arcs

    observed = {}

    def save_arc(_arc_name, _issues):
        observed["on_event_loop"] = _on_event_loop()
        return {"success": True}

    monkeypatch.setattr(story_arcs, "save_arc", save_arc)

    response = client.post(
        "/api/storyarcs/generate/save",
        json={"arc_name": "Dark Phoenix Saga", "issues": [{"series": "X-Men", "issue": "1"}]},
    )

    assert response.status_code == 200
    assert observed["on_event_loop"] is False
