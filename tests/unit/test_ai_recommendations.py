#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Unit tests for AI library-based series recommendations (#914)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from comicarr.app.ai import recommendations as recs
from comicarr.app.ai.router import router
from comicarr.app.ai.schemas import SeriesRecommendations
from comicarr.app.core import runtime as core_runtime
from comicarr.app.core.context import AppContext
from comicarr.app.core.security import require_session


@pytest.fixture(autouse=True)
def _clear_runtime(monkeypatch):
    monkeypatch.setattr(core_runtime, "_runtime", None)
    yield
    monkeypatch.setattr(core_runtime, "_runtime", None)


def _make_context():
    config = SimpleNamespace(
        AI_BASE_URL="https://ai.example.test/v1",
        AI_API_KEY="test-key",
        AI_MODEL="test-model",
        AI_TIMEOUT=30,
        AI_DAILY_TOKEN_LIMIT=1000,
        AI_RPM_LIMIT=12,
    )
    circuit_breaker = MagicMock()
    circuit_breaker.allow_request.return_value = True
    circuit_breaker.state = "closed"
    rate_limiter = MagicMock()
    rate_limiter.can_request.return_value = True
    rate_limiter.today_tokens = 24
    rate_limiter.today_requests = 3
    return AppContext(
        config=config,
        ai_client=MagicMock(name="ai_client"),
        ai_circuit_breaker=circuit_breaker,
        ai_rate_limiter=rate_limiter,
        event_bus=MagicMock(name="event_bus"),
    )


def _patterns():
    return {
        "series_count": 3,
        "top_publishers": ["DC"],
        "avg_completion": 50.0,
        "monitored_series": ["Absolute Batman", "Injustice", "Saga"],
    }


def test_recommendations_unavailable_before_runtime_initialization():
    assert recs.generate_recommendations() == []


def test_recommendations_respects_circuit_breaker_and_rate_limit(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)

    ctx.ai_circuit_breaker.allow_request.return_value = False
    assert recs.generate_recommendations(collection_patterns=_patterns()) == []

    ctx.ai_circuit_breaker.allow_request.return_value = True
    ctx.ai_rate_limiter.can_request.return_value = False
    assert recs.generate_recommendations(collection_patterns=_patterns()) == []


def test_recommendations_returns_fresh_cache_without_llm_call(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)
    cached = [{"comic_name": "Absolute Wonder Woman", "reason": "same line"}]

    with (
        patch.object(recs, "_get_cached_recommendations", return_value=cached),
        patch.object(recs, "request_structured") as request,
    ):
        assert recs.generate_recommendations(collection_patterns=_patterns()) == cached

    request.assert_not_called()


def test_recommendations_force_bypasses_cache(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)
    result = SeriesRecommendations(recommendations=[])

    with (
        patch.object(recs, "_get_cached_recommendations", return_value=[{"comic_name": "stale"}]) as get_cache,
        patch.object(recs, "_cache_recommendations"),
        patch.object(recs, "request_structured", return_value=result) as request,
        patch.object(recs.ai_service, "log_activity"),
    ):
        assert recs.generate_recommendations(force=True, collection_patterns=_patterns()) == []

    get_cache.assert_not_called()
    request.assert_called_once()


def test_recommendations_resolves_picks_and_skips_tracked_matches(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)
    result = SeriesRecommendations(
        recommendations=[
            {
                "comic_name": "Absolute Wonder Woman",
                "publisher": "DC",
                "reason": "You have Absolute Batman, so try the same line",
                "because_of": "Absolute Batman",
            },
            {
                "comic_name": "Injustice 2",
                "publisher": "DC",
                "reason": "Sequel to a series you track",
                "because_of": "Injustice",
            },
            {
                "comic_name": "Unknown Series",
                "publisher": None,
                "reason": "Deep cut",
                "because_of": None,
            },
        ]
    )

    def fake_find(ctx, name, **kwargs):
        if name == "Absolute Wonder Woman":
            return {
                "results": [
                    {
                        "name": "Absolute Wonder Woman",
                        "comicid": "4050-999",
                        "comicyear": "2024",
                        "issues": 12,
                        "publisher": "DC Comics",
                        "comicimage": "https://img/aww.jpg",
                        "in_library": False,
                    }
                ]
            }
        if name == "Injustice 2":
            return {"results": [{"name": "Injustice", "comicid": "4050-1", "in_library": True}]}
        return {"error": "Search returned no results"}

    with (
        patch.object(recs, "_get_cached_recommendations", return_value=None),
        patch.object(recs, "_cache_recommendations") as cache_recs,
        patch.object(recs, "request_structured", return_value=result),
        patch.object(recs.search_service, "find_comic", side_effect=fake_find) as find,
        patch.object(recs.ai_service, "log_activity") as log_activity,
    ):
        recommendations = recs.generate_recommendations(collection_patterns=_patterns())

    assert find.call_count == 3
    assert recommendations == [
        {
            "comic_name": "Absolute Wonder Woman",
            "publisher": "DC Comics",
            "reason": "You have Absolute Batman, so try the same line",
            "because_of": "Absolute Batman",
            "comicid": "4050-999",
            "comicyear": "2024",
            "issues": 12,
            "comicimage": "https://img/aww.jpg",
        },
        {
            "comic_name": "Injustice 2",
            "publisher": "DC",
            "reason": "Sequel to a series you track",
            "because_of": "Injustice",
            "comicid": None,
            "comicyear": None,
            "issues": None,
            "comicimage": None,
        },
        {
            "comic_name": "Unknown Series",
            "publisher": None,
            "reason": "Deep cut",
            "because_of": None,
            "comicid": None,
            "comicyear": None,
            "issues": None,
            "comicimage": None,
        },
    ]
    ctx.ai_circuit_breaker.record_success.assert_called_once()
    cache_recs.assert_called_once_with(recommendations)
    log_activity.assert_called_once()


def test_recommendations_llm_failure_records_breaker_and_returns_empty(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)

    with (
        patch.object(recs, "_get_cached_recommendations", return_value=None),
        patch.object(recs, "request_structured", side_effect=ValueError("bad json")),
        patch.object(recs.ai_service, "log_activity") as log_activity,
    ):
        assert recs.generate_recommendations(collection_patterns=_patterns()) == []

    ctx.ai_circuit_breaker.record_failure.assert_called_once()
    log_activity.assert_called_once()


def test_recommendations_empty_library_returns_empty(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)

    with patch.object(recs, "request_structured") as request:
        assert recs.generate_recommendations(collection_patterns={"monitored_series": []}) == []

    request.assert_not_called()


def test_recommendations_routes_serve_cache_and_refresh():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "alice"

    cached = [{"comic_name": "Absolute Wonder Woman", "comicid": "4050-999"}]
    with (
        patch.object(recs, "get_cached_recommendations", return_value=cached),
        patch.object(recs, "generate_recommendations", return_value=cached) as generate,
        TestClient(app) as client,
    ):
        response = client.get("/api/ai/recommendations")
        assert response.status_code == 200
        assert response.json() == {"recommendations": cached}

        refresh = client.post("/api/ai/recommendations/refresh")
        assert refresh.status_code == 200
        assert refresh.json() == {"recommendations": cached}

    generate.assert_called_once_with(force=True)
