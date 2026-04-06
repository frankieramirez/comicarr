#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for comicarr.app.ai.parsing — AI filename parsing fallback."""

from unittest.mock import MagicMock, patch

from comicarr.app.ai.parsing import _build_parse_dict, _validate_against_library, ai_parse_filename
from comicarr.app.ai.schemas import FilenameParse

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_mock_config():
    cfg = MagicMock()
    cfg.AI_MODEL = "gpt-4o-mini"
    cfg.AI_TIMEOUT = 30
    return cfg


def _make_mock_circuit_breaker(allow=True):
    cb = MagicMock()
    cb.allow_request.return_value = allow
    return cb


def _make_mock_rate_limiter(can=True):
    rl = MagicMock()
    rl.can_request.return_value = can
    return rl


def _make_ai_result(series="Batman", issue="42", year="2024", volume=None):
    return FilenameParse(
        series_name=series,
        issue_number=issue,
        year=year,
        volume=volume,
    )


# ---------------------------------------------------------------------------
# _build_parse_dict
# ---------------------------------------------------------------------------

class TestBuildParseDict:
    def test_correct_keys_and_status(self):
        result = _make_ai_result()
        parsed = _build_parse_dict(result, "Batman 042 (2024).cbz")

        assert parsed["parse_status"] == "success"
        assert parsed["ai_parsed"] is True
        assert parsed["series_name"] == "Batman"
        assert parsed["series_name_decoded"] == "Batman"
        assert parsed["issue_number"] == "42"
        assert parsed["justthedigits"] == "42"
        assert parsed["issue_year"] == "2024"
        assert parsed["comicfilename"] == "Batman 042 (2024).cbz"
        assert parsed["dynamic_name"] == "batman"
        assert parsed["series_volume"] is None
        assert parsed["annual_comicid"] is None
        assert parsed["scangroup"] is None
        assert parsed["booktype"] is None
        assert parsed["reading_order"] is None
        assert parsed["issueid"] is None
        assert parsed["alt_series"] is None
        assert parsed["alt_issue"] is None
        assert parsed["sub"] is None
        assert parsed["comiclocation"] is None

    def test_empty_issue_number(self):
        result = FilenameParse(series_name="Saga", issue_number="", year=None, volume="v2")
        parsed = _build_parse_dict(result, "Saga v2.cbr")

        assert parsed["issue_number"] == ""
        assert parsed["justthedigits"] == ""
        assert parsed["series_volume"] == "v2"

    def test_volume_passthrough(self):
        result = _make_ai_result(volume="v3")
        parsed = _build_parse_dict(result, "test.cbz")
        assert parsed["series_volume"] == "v3"


# ---------------------------------------------------------------------------
# _validate_against_library
# ---------------------------------------------------------------------------

class TestValidateAgainstLibrary:
    @patch("comicarr.app.ai.parsing.db")
    def test_exact_match(self, mock_db):
        conn = MagicMock()
        mock_db.DBConnection.return_value = conn
        conn.select.return_value = [{"ComicID": "123"}]

        assert _validate_against_library("Batman") is True
        conn.select.assert_called_once()

    @patch("comicarr.app.ai.parsing.db")
    def test_case_insensitive_match(self, mock_db):
        conn = MagicMock()
        mock_db.DBConnection.return_value = conn
        # First call (exact) returns nothing, second (case insensitive) returns match
        conn.select.side_effect = [[], [{"ComicID": "456"}]]

        assert _validate_against_library("batman") is True
        assert conn.select.call_count == 2

    @patch("comicarr.app.ai.parsing.db")
    def test_alternate_search_match(self, mock_db):
        conn = MagicMock()
        mock_db.DBConnection.return_value = conn
        # Exact: no match, case-insensitive: no match, alternate search: has data
        conn.select.side_effect = [
            [],
            [],
            [{"AlternateSearch": "Dark Knight##The Batman##TDK"}],
        ]

        assert _validate_against_library("The Batman") is True

    @patch("comicarr.app.ai.parsing.db")
    def test_no_match(self, mock_db):
        conn = MagicMock()
        mock_db.DBConnection.return_value = conn
        conn.select.side_effect = [[], [], []]

        assert _validate_against_library("NonexistentComic") is False

    def test_empty_series_name(self):
        assert _validate_against_library("") is False
        assert _validate_against_library(None) is False


# ---------------------------------------------------------------------------
# ai_parse_filename
# ---------------------------------------------------------------------------

class TestAiParseFilename:
    """Tests for the main ai_parse_filename entry point."""

    @patch("comicarr.app.ai.parsing.ai_service")
    @patch("comicarr.app.ai.parsing.request_structured")
    @patch("comicarr.app.ai.parsing._validate_against_library")
    @patch("comicarr.app.ai.parsing.comicarr")
    def test_happy_path(self, mock_cm, mock_validate, mock_req, mock_svc):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        ai_result = _make_ai_result(series="Spider-Man", issue="300", year="1988")
        mock_req.return_value = ai_result
        mock_validate.return_value = True

        result = ai_parse_filename("Spider-Man.300.1988.cbz")

        assert result is not None
        assert result["parse_status"] == "success"
        assert result["series_name"] == "Spider-Man"
        assert result["issue_number"] == "300"
        assert result["issue_year"] == "1988"
        assert result["ai_parsed"] is True

        mock_cm.AI_CIRCUIT_BREAKER.record_success.assert_called_once()
        mock_svc.log_activity.assert_called_once()
        assert mock_svc.log_activity.call_args[1]["success"] is True

    @patch("comicarr.app.ai.parsing.comicarr")
    def test_ai_not_configured(self, mock_cm):
        mock_cm.AI_CLIENT = None

        result = ai_parse_filename("anything.cbz")
        assert result is None

    @patch("comicarr.app.ai.parsing.comicarr")
    def test_circuit_breaker_open(self, mock_cm):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=False)

        result = ai_parse_filename("anything.cbz")
        assert result is None

    @patch("comicarr.app.ai.parsing.comicarr")
    def test_rate_limiter_at_cap(self, mock_cm):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=False)

        result = ai_parse_filename("anything.cbz")
        assert result is None

    @patch("comicarr.app.ai.parsing.ai_service")
    @patch("comicarr.app.ai.parsing.request_structured")
    @patch("comicarr.app.ai.parsing._validate_against_library")
    @patch("comicarr.app.ai.parsing.comicarr")
    def test_no_library_match(self, mock_cm, mock_validate, mock_req, mock_svc):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        mock_req.return_value = _make_ai_result(series="UnknownComic", issue="1")
        mock_validate.return_value = False

        result = ai_parse_filename("UnknownComic 001.cbz")
        assert result is None

        mock_svc.log_activity.assert_called_once()
        assert mock_svc.log_activity.call_args[1]["success"] is False
        assert mock_svc.log_activity.call_args[1]["error_message"] == "No library match"

    @patch("comicarr.app.ai.parsing.ai_service")
    @patch("comicarr.app.ai.parsing.request_structured")
    @patch("comicarr.app.ai.parsing.comicarr")
    def test_llm_timeout(self, mock_cm, mock_req, mock_svc):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        mock_req.side_effect = TimeoutError("Request timed out")

        result = ai_parse_filename("timeout-file.cbz")
        assert result is None

        mock_cm.AI_CIRCUIT_BREAKER.record_failure.assert_called_once()
        mock_svc.log_activity.assert_called_once()
        assert mock_svc.log_activity.call_args[1]["success"] is False

    @patch("comicarr.app.ai.parsing.ai_service")
    @patch("comicarr.app.ai.parsing.request_structured")
    @patch("comicarr.app.ai.parsing.comicarr")
    def test_llm_invalid_json(self, mock_cm, mock_req, mock_svc):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        mock_req.side_effect = ValueError("Failed to parse structured response from LLM")

        result = ai_parse_filename("bad-response.cbz")
        assert result is None

        mock_cm.AI_CIRCUIT_BREAKER.record_failure.assert_called_once()
        mock_svc.log_activity.assert_called_once()
        assert mock_svc.log_activity.call_args[1]["success"] is False
        assert "Failed to parse" in (mock_svc.log_activity.call_args[1]["error_message"] or "")

    @patch("comicarr.app.ai.parsing.ai_service")
    @patch("comicarr.app.ai.parsing.request_structured")
    @patch("comicarr.app.ai.parsing._validate_against_library")
    @patch("comicarr.app.ai.parsing.comicarr")
    def test_watchcomic_and_publisher_passed(self, mock_cm, mock_validate, mock_req, mock_svc):
        """Verify that watchcomic and publisher context is forwarded to the LLM."""
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        mock_req.return_value = _make_ai_result()
        mock_validate.return_value = True

        ai_parse_filename("file.cbz", watchcomic="Batman", publisher="DC Comics")

        call_args = mock_req.call_args
        user_prompt = call_args[1]["user_prompt"]
        assert "Batman" in user_prompt
        assert "DC Comics" in user_prompt

    @patch("comicarr.app.ai.parsing.ai_service")
    @patch("comicarr.app.ai.parsing.request_structured")
    @patch("comicarr.app.ai.parsing._validate_against_library")
    @patch("comicarr.app.ai.parsing.comicarr")
    def test_result_has_all_parseit_keys(self, mock_cm, mock_validate, mock_req, mock_svc):
        """The returned dict must include every key listFiles() accesses."""
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        mock_req.return_value = _make_ai_result()
        mock_validate.return_value = True

        result = ai_parse_filename("test.cbz")
        assert result is not None

        # Keys required by listFiles() justparse path
        required_keys = [
            "parse_status", "sub", "comicfilename", "comiclocation",
            "series_name", "series_name_decoded", "issueid",
            "alt_series", "alt_issue", "dynamic_name",
            "series_volume", "issue_year", "issue_number",
            "scangroup", "reading_order", "booktype",
            "justthedigits", "annual_comicid",
        ]
        for key in required_keys:
            assert key in result, "Missing key: %s" % key
