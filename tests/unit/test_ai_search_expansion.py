#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for comicarr.app.ai.search_expansion."""

import json
from unittest.mock import MagicMock, patch

import pytest

from comicarr.app.ai.schemas import SearchExpansion


class _FakeDBConnection:
    """Minimal DB stub for search expansion tests."""

    def __init__(self, select_results=None):
        self._select_results = select_results or {}
        self._action_calls = []

    def select(self, query, args=None):
        for key, val in self._select_results.items():
            if key in query:
                return val
        return []

    def action(self, query, args=None):
        self._action_calls.append((query, args))


class TestExpandSearchQueries:
    """Test expand_search_queries function."""

    @patch("comicarr.app.ai.search_expansion.ai_service")
    @patch("comicarr.app.ai.search_expansion.db")
    @patch("comicarr.app.ai.search_expansion.request_structured")
    @patch("comicarr.app.ai.search_expansion.comicarr")
    def test_returns_alternates_on_success(self, mock_comicarr, mock_structured, mock_db, mock_ai_service):
        mock_comicarr.AI_CLIENT = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER.allow_request.return_value = True
        mock_comicarr.AI_RATE_LIMITER = MagicMock()
        mock_comicarr.AI_RATE_LIMITER.can_request.return_value = True
        mock_comicarr.CONFIG = MagicMock()
        mock_comicarr.CONFIG.AI_MODEL = "gpt-4"
        mock_comicarr.CONFIG.AI_TIMEOUT = 30

        fake_db = _FakeDBConnection(select_results={
            "AlternateSearch": [],
            "ai_cache": [],
        })
        mock_db.DBConnection.return_value = fake_db

        mock_structured.return_value = SearchExpansion(
            queries=["The Amazing Spider-Man", "ASM", "Spider-Man Marvel"]
        )

        from comicarr.app.ai.search_expansion import expand_search_queries

        result = expand_search_queries("12345", "Spider-Man", publisher="Marvel", year="2020")

        assert len(result) == 3
        assert "The Amazing Spider-Man" in result
        assert "ASM" in result
        assert "Spider-Man Marvel" in result
        mock_comicarr.AI_CIRCUIT_BREAKER.record_success.assert_called_once()
        mock_ai_service.log_activity.assert_called_once()

    @patch("comicarr.app.ai.search_expansion.comicarr")
    def test_ai_not_configured_returns_empty(self, mock_comicarr):
        mock_comicarr.AI_CLIENT = None

        from comicarr.app.ai.search_expansion import expand_search_queries

        result = expand_search_queries("12345", "Spider-Man")

        assert result == []

    @patch("comicarr.app.ai.search_expansion.comicarr")
    def test_circuit_breaker_open_returns_empty(self, mock_comicarr):
        mock_comicarr.AI_CLIENT = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER.allow_request.return_value = False

        from comicarr.app.ai.search_expansion import expand_search_queries

        result = expand_search_queries("12345", "Spider-Man")

        assert result == []

    @patch("comicarr.app.ai.search_expansion.db")
    @patch("comicarr.app.ai.search_expansion.comicarr")
    def test_already_has_5_expansions_returns_empty(self, mock_comicarr, mock_db):
        mock_comicarr.AI_CLIENT = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER.allow_request.return_value = True
        mock_comicarr.AI_RATE_LIMITER = MagicMock()
        mock_comicarr.AI_RATE_LIMITER.can_request.return_value = True

        five_expansions = json.dumps(["alt1", "alt2", "alt3", "alt4", "alt5"])
        fake_db = _FakeDBConnection(select_results={
            "ai_cache": [{"data": five_expansions}],
        })
        mock_db.DBConnection.return_value = fake_db

        from comicarr.app.ai.search_expansion import expand_search_queries

        result = expand_search_queries("12345", "Spider-Man")

        assert result == []

    @patch("comicarr.app.ai.search_expansion.ai_service")
    @patch("comicarr.app.ai.search_expansion.db")
    @patch("comicarr.app.ai.search_expansion.request_structured")
    @patch("comicarr.app.ai.search_expansion.comicarr")
    def test_deduplicates_against_existing_alternates(self, mock_comicarr, mock_structured, mock_db, mock_ai_service):
        mock_comicarr.AI_CLIENT = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER.allow_request.return_value = True
        mock_comicarr.AI_RATE_LIMITER = MagicMock()
        mock_comicarr.AI_RATE_LIMITER.can_request.return_value = True
        mock_comicarr.CONFIG = MagicMock()
        mock_comicarr.CONFIG.AI_MODEL = "gpt-4"
        mock_comicarr.CONFIG.AI_TIMEOUT = 30

        fake_db = _FakeDBConnection(select_results={
            "AlternateSearch": [{"AlternateSearch": "The Dark Knight"}],
            "ai_cache": [],
        })
        mock_db.DBConnection.return_value = fake_db

        # LLM returns one that matches existing and two new ones
        mock_structured.return_value = SearchExpansion(
            queries=["The Dark Knight", "TDK", "Batman Dark Knight"]
        )

        from comicarr.app.ai.search_expansion import expand_search_queries

        result = expand_search_queries("12345", "Batman")

        # "The Dark Knight" should be filtered out as it already exists
        assert "The Dark Knight" not in result
        assert "TDK" in result
        assert "Batman Dark Knight" in result
        assert len(result) == 2

    @patch("comicarr.app.ai.search_expansion.ai_service")
    @patch("comicarr.app.ai.search_expansion.db")
    @patch("comicarr.app.ai.search_expansion.request_structured")
    @patch("comicarr.app.ai.search_expansion.comicarr")
    def test_deduplicates_against_series_name(self, mock_comicarr, mock_structured, mock_db, mock_ai_service):
        mock_comicarr.AI_CLIENT = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER.allow_request.return_value = True
        mock_comicarr.AI_RATE_LIMITER = MagicMock()
        mock_comicarr.AI_RATE_LIMITER.can_request.return_value = True
        mock_comicarr.CONFIG = MagicMock()
        mock_comicarr.CONFIG.AI_MODEL = "gpt-4"
        mock_comicarr.CONFIG.AI_TIMEOUT = 30

        fake_db = _FakeDBConnection(select_results={
            "AlternateSearch": [],
            "ai_cache": [],
        })
        mock_db.DBConnection.return_value = fake_db

        # LLM returns the series name itself as one of the alternates
        mock_structured.return_value = SearchExpansion(
            queries=["batman", "The Dark Knight"]
        )

        from comicarr.app.ai.search_expansion import expand_search_queries

        result = expand_search_queries("12345", "Batman")

        # "batman" should be filtered out as it matches series name (case-insensitive)
        assert len(result) == 1
        assert "The Dark Knight" in result

    @patch("comicarr.app.ai.search_expansion.ai_service")
    @patch("comicarr.app.ai.search_expansion.db")
    @patch("comicarr.app.ai.search_expansion.request_structured")
    @patch("comicarr.app.ai.search_expansion.comicarr")
    def test_llm_timeout_returns_empty(self, mock_comicarr, mock_structured, mock_db, mock_ai_service):
        mock_comicarr.AI_CLIENT = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER.allow_request.return_value = True
        mock_comicarr.AI_RATE_LIMITER = MagicMock()
        mock_comicarr.AI_RATE_LIMITER.can_request.return_value = True
        mock_comicarr.CONFIG = MagicMock()
        mock_comicarr.CONFIG.AI_MODEL = "gpt-4"
        mock_comicarr.CONFIG.AI_TIMEOUT = 30

        fake_db = _FakeDBConnection(select_results={
            "AlternateSearch": [],
            "ai_cache": [],
        })
        mock_db.DBConnection.return_value = fake_db

        mock_structured.side_effect = TimeoutError("Request timed out")

        from comicarr.app.ai.search_expansion import expand_search_queries

        result = expand_search_queries("12345", "Spider-Man")

        assert result == []
        mock_comicarr.AI_CIRCUIT_BREAKER.record_failure.assert_called_once()

    @patch("comicarr.app.ai.search_expansion.ai_service")
    @patch("comicarr.app.ai.search_expansion.db")
    @patch("comicarr.app.ai.search_expansion.request_structured")
    @patch("comicarr.app.ai.search_expansion.comicarr")
    def test_llm_returns_empty_array(self, mock_comicarr, mock_structured, mock_db, mock_ai_service):
        mock_comicarr.AI_CLIENT = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER.allow_request.return_value = True
        mock_comicarr.AI_RATE_LIMITER = MagicMock()
        mock_comicarr.AI_RATE_LIMITER.can_request.return_value = True
        mock_comicarr.CONFIG = MagicMock()
        mock_comicarr.CONFIG.AI_MODEL = "gpt-4"
        mock_comicarr.CONFIG.AI_TIMEOUT = 30

        fake_db = _FakeDBConnection(select_results={
            "AlternateSearch": [],
            "ai_cache": [],
        })
        mock_db.DBConnection.return_value = fake_db

        mock_structured.return_value = SearchExpansion(queries=[])

        from comicarr.app.ai.search_expansion import expand_search_queries

        result = expand_search_queries("12345", "Spider-Man")

        assert result == []
        mock_comicarr.AI_CIRCUIT_BREAKER.record_success.assert_called_once()

    @patch("comicarr.app.ai.search_expansion.comicarr")
    def test_rate_limit_reached_returns_empty(self, mock_comicarr):
        mock_comicarr.AI_CLIENT = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER = MagicMock()
        mock_comicarr.AI_CIRCUIT_BREAKER.allow_request.return_value = True
        mock_comicarr.AI_RATE_LIMITER = MagicMock()
        mock_comicarr.AI_RATE_LIMITER.can_request.return_value = False

        from comicarr.app.ai.search_expansion import expand_search_queries

        result = expand_search_queries("12345", "Spider-Man")

        assert result == []


class TestPersistSuccessfulExpansion:
    """Test persist_successful_expansion function."""

    @patch("comicarr.app.ai.search_expansion.db")
    def test_updates_alternate_search_and_cache(self, mock_db):
        fake_db = _FakeDBConnection(select_results={
            "AlternateSearch": [{"AlternateSearch": "Existing Alt"}],
            "ai_cache": [],
        })
        mock_db.DBConnection.return_value = fake_db

        from comicarr.app.ai.search_expansion import persist_successful_expansion

        persist_successful_expansion("12345", "New Alt")

        # Should have 2 action calls: UPDATE comics + INSERT ai_cache
        assert len(fake_db._action_calls) == 2

        update_query, update_args = fake_db._action_calls[0]
        assert "UPDATE comics SET AlternateSearch" in update_query
        assert update_args[0] == "Existing Alt##New Alt"
        assert update_args[1] == "12345"

        cache_query, cache_args = fake_db._action_calls[1]
        assert "INSERT OR REPLACE INTO ai_cache" in cache_query
        assert cache_args[0] == "expansion_12345"
        assert cache_args[1] == "expansion"
        assert json.loads(cache_args[2]) == ["New Alt"]

    @patch("comicarr.app.ai.search_expansion.db")
    def test_does_not_duplicate_existing_alternate(self, mock_db):
        fake_db = _FakeDBConnection(select_results={
            "AlternateSearch": [{"AlternateSearch": "Existing Alt"}],
            "ai_cache": [],
        })
        mock_db.DBConnection.return_value = fake_db

        from comicarr.app.ai.search_expansion import persist_successful_expansion

        persist_successful_expansion("12345", "existing alt")

        # Should only have the ai_cache insert, no UPDATE since it already exists (case-insensitive)
        assert len(fake_db._action_calls) == 1
        cache_query, _ = fake_db._action_calls[0]
        assert "ai_cache" in cache_query

    @patch("comicarr.app.ai.search_expansion.db")
    def test_first_alternate_no_existing(self, mock_db):
        fake_db = _FakeDBConnection(select_results={
            "AlternateSearch": [],
            "ai_cache": [],
        })
        mock_db.DBConnection.return_value = fake_db

        from comicarr.app.ai.search_expansion import persist_successful_expansion

        persist_successful_expansion("12345", "New Alt")

        update_query, update_args = fake_db._action_calls[0]
        assert "UPDATE comics SET AlternateSearch" in update_query
        assert update_args[0] == "New Alt"

    @patch("comicarr.app.ai.search_expansion.db")
    def test_appends_to_ai_cache(self, mock_db):
        existing_cache = json.dumps(["prev alt 1", "prev alt 2"])
        fake_db = _FakeDBConnection(select_results={
            "AlternateSearch": [{"AlternateSearch": "prev alt 1##prev alt 2"}],
            "ai_cache": [{"data": existing_cache}],
        })
        mock_db.DBConnection.return_value = fake_db

        from comicarr.app.ai.search_expansion import persist_successful_expansion

        persist_successful_expansion("12345", "New Alt")

        cache_query, cache_args = fake_db._action_calls[1]
        cached_list = json.loads(cache_args[2])
        assert cached_list == ["prev alt 1", "prev alt 2", "New Alt"]
