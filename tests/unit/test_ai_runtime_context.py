#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Canonical runtime ownership tests for the bounded AI consumer wave."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from comicarr.app.ai import service as ai_service
from comicarr.app.ai.parsing import ai_parse_filename
from comicarr.app.ai.pull_list import generate_suggestions
from comicarr.app.ai.runtime import get_ai_runtime
from comicarr.app.ai.schemas import PullSuggestions, ReadingOrder
from comicarr.app.ai.story_arcs import generate_reading_order
from comicarr.app.core import runtime as core_runtime
from comicarr.app.core.context import AppContext


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


def test_ai_runtime_is_unavailable_before_context_initialization():
    assert get_ai_runtime() is None
    assert ai_parse_filename("uninitialized.cbz") is None
    assert generate_suggestions(weekly_data=[{"COMIC": "Batman", "ISSUE": "1"}]) == []
    assert generate_reading_order("Knightfall") == {
        "success": False,
        "error": "AI is not configured",
        "issues": [],
    }


def test_ai_status_and_activity_use_the_canonical_runtime_bundle(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)

    with patch.object(ai_service.ai_queries, "insert_activity") as insert_activity:
        ai_service.log_activity("parsing", "Parsed issue", "test-model", 5, 2, 10, True)

    insert_activity.assert_called_once()
    ctx.event_bus.publish_sync.assert_called_once_with(
        "ai_activity",
        {
            "feature_type": "parsing",
            "action": "Parsed issue",
            "success": True,
            "latency_ms": 10,
        },
    )
    with patch.object(ai_service.ai_queries, "get_active_series_count", return_value=7):
        assert ai_service.get_ai_status() == {
            "configured": True,
            "circuit_state": "closed",
            "model": "test-model",
            "library_series": 7,
            "today_tokens": 24,
            "today_requests": 3,
            "daily_limit": 1000,
            "rpm_limit": 12,
        }


def test_activity_remains_durable_when_the_runtime_is_unavailable():
    with patch.object(ai_service.ai_queries, "insert_activity") as insert_activity:
        ai_service.log_activity("parsing", "Parsed issue", "test-model", 5, 2, 10, True)

    insert_activity.assert_called_once()


def test_activity_remains_durable_when_event_bus_publish_fails(monkeypatch):
    ctx = _make_context()
    ctx.event_bus.publish_sync.side_effect = RuntimeError("event bus unavailable")
    monkeypatch.setattr(core_runtime, "_runtime", ctx)

    with patch.object(ai_service.ai_queries, "insert_activity") as insert_activity:
        assert ai_service.log_activity("parsing", "Parsed issue", "test-model", 5, 2, 10, True) is None

    insert_activity.assert_called_once()
    ctx.event_bus.publish_sync.assert_called_once()


def test_ai_parse_uses_context_client_and_records_context_breaker_failure(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)

    with (
        patch("comicarr.app.ai.parsing.request_structured", side_effect=TimeoutError("upstream timeout")) as request,
        patch("comicarr.app.ai.parsing.ai_service.log_activity") as log_activity,
    ):
        assert ai_parse_filename("Batman 001.cbz") is None

    assert request.call_args.kwargs["client"] is ctx.ai_client
    assert request.call_args.kwargs["model"] == "test-model"
    ctx.ai_circuit_breaker.record_failure.assert_called_once()
    log_activity.assert_called_once()


def test_pull_list_uses_the_context_owned_client_and_limits(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)
    result = PullSuggestions(
        suggestions=[
            {
                "comic_name": "Detective Comics",
                "publisher": "DC",
                "reason": "Matches your Batman collection",
                "resolved_comic_id": "123",
            }
        ]
    )

    with (
        patch("comicarr.app.ai.pull_list._get_cached_suggestions", return_value=None),
        patch("comicarr.app.ai.pull_list._cache_suggestions") as cache_suggestions,
        patch("comicarr.app.ai.pull_list.request_structured", return_value=result) as request,
        patch("comicarr.app.ai.pull_list.ai_service.log_activity") as log_activity,
    ):
        suggestions = generate_suggestions(
            weekly_data=[{"COMIC": "Detective Comics", "ISSUE": "1090", "PUBLISHER": "DC"}],
            collection_patterns={"series_count": 1},
        )

    assert suggestions == [
        {
            "comic_name": "Detective Comics",
            "publisher": "DC",
            "reason": "Matches your Batman collection",
            "resolved_comic_id": "123",
        }
    ]
    assert request.call_args.kwargs["client"] is ctx.ai_client
    assert request.call_args.kwargs["model"] == "test-model"
    ctx.ai_circuit_breaker.record_success.assert_called_once()
    cache_suggestions.assert_called_once_with(suggestions)
    log_activity.assert_called_once()


def test_story_arc_uses_the_context_owned_client_and_records_failures(monkeypatch):
    ctx = _make_context()
    monkeypatch.setattr(core_runtime, "_runtime", ctx)
    result = ReadingOrder(
        issues=[
            {
                "series_name": "Batman",
                "issue_number": "497",
                "title": "The Broken Bat",
                "reading_order_position": 1,
            }
        ]
    )

    with (
        patch("comicarr.app.ai.story_arcs.request_structured", return_value=result) as request,
        patch("comicarr.app.ai.story_arcs.ai_service.log_activity") as log_activity,
    ):
        response = generate_reading_order("Knightfall")

    assert response == {
        "success": True,
        "issues": [
            {
                "series_name": "Batman",
                "issue_number": "497",
                "title": "The Broken Bat",
                "reading_order": 1,
                "comic_id": None,
                "issue_id": None,
                "verified": False,
                "library_status": "not_tracked",
            }
        ],
    }
    assert request.call_args.kwargs["client"] is ctx.ai_client
    assert request.call_args.kwargs["model"] == "test-model"
    ctx.ai_circuit_breaker.record_success.assert_called_once()
    log_activity.assert_called_once()

    with (
        patch("comicarr.app.ai.story_arcs.request_structured", side_effect=TimeoutError("upstream timeout")),
        patch("comicarr.app.ai.story_arcs.ai_service.log_activity") as failed_log_activity,
    ):
        assert generate_reading_order("Knightfall") == {
            "success": False,
            "error": "upstream timeout",
            "issues": [],
        }

    ctx.ai_circuit_breaker.record_failure.assert_called_once()
    failed_log_activity.assert_called_once()
