#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Unit tests for AI library-based series recommendations (#914)."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from comicarr.app.ai import recommendations as recs
from comicarr.app.ai.rate_limiter import AIRateLimiter
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
    rate_limiter.reserve_request.return_value = True
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
    with patch.object(recs, "_invalidate_cache"), pytest.raises(recs.RecommendationGenerationError):
        recs.generate_recommendations()


def test_recommendations_respects_circuit_breaker_and_rate_limit(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)

    ctx.ai_circuit_breaker.allow_request.return_value = False
    with patch.object(recs, "_invalidate_cache"), pytest.raises(recs.RecommendationGenerationError):
        recs.generate_recommendations(collection_patterns=_patterns())

    ctx.ai_circuit_breaker.allow_request.return_value = True
    ctx.ai_rate_limiter.reserve_request.return_value = False
    with patch.object(recs, "_invalidate_cache"), pytest.raises(recs.RecommendationGenerationError) as failure:
        recs.generate_recommendations(collection_patterns=_patterns())
    assert failure.value.status_code == 429


def test_recommendations_returns_fresh_cache_without_llm_call(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)
    cached = [{"comic_name": "Absolute Wonder Woman", "comicid": "4050-999", "reason": "same line"}]

    with (
        patch.object(recs, "_get_cached_recommendations", return_value=cached),
        patch.object(recs.ai_queries, "get_library_comic_ids", return_value=set()),
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
        patch.object(recs.ai_queries, "get_library_comic_ids", return_value=set()),
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
    ]
    ctx.ai_circuit_breaker.record_success.assert_called_once()
    cache_recs.assert_called_once_with(recommendations)
    log_activity.assert_called_once()


def test_recommendations_llm_failure_records_breaker_and_raises(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)

    with (
        patch.object(recs, "_get_cached_recommendations", return_value=None),
        patch.object(recs, "request_structured", side_effect=ValueError("bad json")),
        patch.object(recs.ai_service, "log_activity") as log_activity,
    ):
        with pytest.raises(recs.RecommendationGenerationError):
            recs.generate_recommendations(collection_patterns=_patterns())

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


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [(503, "Recommendation generation unavailable"), (429, "AI request or token limit reached")],
)
def test_refresh_reports_failure_without_replacing_cards(status_code, expected_error):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "alice"

    with (
        patch.object(
            recs,
            "generate_recommendations",
            side_effect=recs.RecommendationGenerationError("private provider detail", status_code=status_code),
        ),
        TestClient(app) as client,
    ):
        response = client.post("/api/ai/recommendations/refresh")

    assert response.status_code == status_code
    assert response.json() == {"error": expected_error}


def test_refresh_reserves_rpm_before_dispatch_sequentially(monkeypatch):
    ctx = _make_context()
    ctx.ai_rate_limiter = AIRateLimiter(rpm_limit=1, daily_token_limit=1000)
    monkeypatch.setattr(core_runtime, "_runtime", ctx)
    result = SeriesRecommendations(recommendations=[])

    with (
        patch.object(recs, "request_structured", return_value=result) as request,
        patch.object(recs, "_cache_recommendations"),
        patch.object(recs, "_invalidate_cache") as invalidate,
        patch.object(recs.ai_service, "log_activity"),
    ):
        assert recs.generate_recommendations(force=True, collection_patterns=_patterns()) == []
        with pytest.raises(recs.RecommendationGenerationError) as failure:
            recs.generate_recommendations(force=True, collection_patterns=_patterns())

    assert failure.value.status_code == 429
    assert ctx.ai_rate_limiter.today_requests == 1
    request.assert_called_once()
    invalidate.assert_not_called()


def test_refresh_reserves_rpm_before_dispatch_concurrently(monkeypatch):
    ctx = _make_context()
    ctx.ai_rate_limiter = AIRateLimiter(rpm_limit=1, daily_token_limit=1000)
    monkeypatch.setattr(core_runtime, "_runtime", ctx)
    start = Barrier(3)

    def run():
        start.wait()
        try:
            recs.generate_recommendations(force=True, collection_patterns=_patterns())
            return 200
        except recs.RecommendationGenerationError as e:
            return e.status_code

    with (
        patch.object(recs, "request_structured", return_value=SeriesRecommendations(recommendations=[])) as request,
        patch.object(recs, "_cache_recommendations"),
        patch.object(recs, "_invalidate_cache"),
        patch.object(recs.ai_service, "log_activity"),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        first, second = pool.submit(run), pool.submit(run)
        start.wait()
        assert sorted((first.result(), second.result())) == [200, 429]

    assert ctx.ai_rate_limiter.today_requests == 1
    request.assert_called_once()


def test_parse_failure_charges_response_usage(monkeypatch):
    ctx = _make_context()
    ctx.ai_rate_limiter = AIRateLimiter(rpm_limit=2, daily_token_limit=20)
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=4),
        choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))],
    )
    ctx.ai_client.chat.completions.create.return_value = response
    monkeypatch.setattr(core_runtime, "_runtime", ctx)

    with (
        patch.object(recs, "_invalidate_cache"),
        patch.object(recs.ai_service, "log_activity") as log_activity,
        pytest.raises(recs.RecommendationGenerationError),
    ):
        recs.generate_recommendations(force=True, collection_patterns=_patterns())

    assert ctx.ai_rate_limiter.today_requests == 1
    assert ctx.ai_rate_limiter.today_tokens == 11
    assert log_activity.call_args.kwargs["prompt_tokens"] == 7
    assert log_activity.call_args.kwargs["completion_tokens"] == 4


def test_token_budget_blocks_next_refresh(monkeypatch):
    ctx = _make_context()
    ctx.ai_rate_limiter = AIRateLimiter(rpm_limit=2, daily_token_limit=10)
    monkeypatch.setattr(core_runtime, "_runtime", ctx)

    def response_with_usage(**kwargs):
        kwargs["on_response"](SimpleNamespace(usage=SimpleNamespace(prompt_tokens=8, completion_tokens=3)), "prompt")
        return SeriesRecommendations(recommendations=[])

    with (
        patch.object(recs, "request_structured", side_effect=response_with_usage) as request,
        patch.object(recs, "_cache_recommendations"),
        patch.object(recs.ai_service, "log_activity"),
    ):
        assert recs.generate_recommendations(force=True, collection_patterns=_patterns()) == []
        with pytest.raises(recs.RecommendationGenerationError) as failure:
            recs.generate_recommendations(force=True, collection_patterns=_patterns())

    assert failure.value.status_code == 429
    assert ctx.ai_rate_limiter.today_tokens == 11
    request.assert_called_once()


def test_missing_provider_usage_charges_conservative_estimate(monkeypatch):
    ctx = _make_context()
    ctx.ai_rate_limiter = AIRateLimiter(rpm_limit=2, daily_token_limit=5000)
    ctx.ai_client.chat.completions.create.return_value = SimpleNamespace(
        usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"recommendations": []}'))],
    )
    monkeypatch.setattr(core_runtime, "_runtime", ctx)

    with (
        patch.object(recs, "_cache_recommendations"),
        patch.object(recs.ai_service, "log_activity") as log_activity,
    ):
        assert recs.generate_recommendations(force=True, collection_patterns=_patterns()) == []

    assert ctx.ai_rate_limiter.today_tokens > len('{"recommendations": []}')
    assert log_activity.call_args.kwargs["prompt_tokens"] > 0
    assert log_activity.call_args.kwargs["completion_tokens"] == len('{"recommendations": []}')


def test_provider_outage_fails_generation_without_caching(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)
    previous = [{"comic_name": "Previous pick", "comicid": "4050-old"}]
    persisted = {"recommendations": previous}
    result = SeriesRecommendations(
        recommendations=[{"comic_name": "Absolute Wonder Woman", "publisher": "DC", "reason": "same line"}]
    )
    with (
        patch.object(recs, "request_structured", return_value=result),
        patch.object(recs.search_service, "find_comic", side_effect=TimeoutError("provider down")),
        patch.object(recs, "_cache_recommendations") as cache,
        patch.object(recs, "_invalidate_cache", side_effect=lambda: persisted.clear()) as invalidate,
        patch.object(recs, "_get_cached_recommendations", side_effect=lambda: persisted.get("recommendations")),
        patch.object(recs.ai_queries, "get_library_comic_ids", return_value=set()),
        patch.object(recs.ai_service, "log_activity"),
    ):
        with pytest.raises(recs.RecommendationGenerationError):
            recs.generate_recommendations(force=True, collection_patterns=_patterns())
        assert recs.get_cached_recommendations() == previous
    cache.assert_not_called()
    invalidate.assert_not_called()
    ctx.ai_circuit_breaker.record_failure.assert_not_called()
    ctx.ai_circuit_breaker.record_success.assert_called_once()


def test_ambiguous_same_title_needs_publisher_and_year():
    ctx = _make_context()
    candidates = [
        {"name": "The Flash", "comicid": "4050-1", "publisher": "DC Comics", "comicyear": "1987", "in_library": False},
        {"name": "The Flash", "comicid": "4050-2", "publisher": "DC Comics", "comicyear": "2016", "in_library": False},
    ]
    with patch.object(recs.search_service, "find_comic", return_value={"results": candidates}):
        assert (
            recs._resolve_series(ctx, SimpleNamespace(comic_name="The Flash", publisher="DC", comicyear=None)) is None
        )
        match = recs._resolve_series(ctx, SimpleNamespace(comic_name="The Flash", publisher="DC", comicyear="2016"))
    assert match["comicid"] == "4050-2"


def test_cached_cards_exclude_newly_tracked_series(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)
    cached = [
        {"comic_name": "The Flash", "comicid": "4050-1"},
        {"comic_name": "Wonder Woman", "comicid": "4050-2"},
    ]
    with (
        patch.object(recs, "_get_cached_recommendations", return_value=cached),
        patch.object(recs.ai_queries, "get_library_comic_ids", return_value={"4050-1"}) as get_ids,
    ):
        assert recs.get_cached_recommendations() == [cached[1]]
    get_ids.assert_called_once_with({"4050-1", "4050-2"})
