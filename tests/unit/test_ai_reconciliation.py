#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for comicarr.app.ai.reconciliation — metadata conflict reconciliation."""

import os
import zipfile

import pytest
from unittest.mock import MagicMock, patch, call

from comicarr.app.ai.enrichment import _read_comicinfo
from comicarr.app.ai.reconciliation import (
    RECONCILABLE_FIELDS,
    _store_reconciliation_history,
    reconcile_metadata,
)
from comicarr.app.ai.schemas import ReconciliationChoice

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COMICINFO_TEMPLATE = """\
<?xml version="1.0" encoding="utf-8"?>
<ComicInfo>
  <Title>{title}</Title>
  <Series>{series}</Series>
  <Number>{number}</Number>
  <Publisher>{publisher}</Publisher>
  <Year>{year}</Year>
  <Writer>{writer}</Writer>
  <Penciller>{penciller}</Penciller>
  <Genre>{genre}</Genre>
  <AgeRating>{age_rating}</AgeRating>
  <Summary>{summary}</Summary>
</ComicInfo>
"""


def _make_cbz(tmp_path, title="Batman #1", series="Batman", number="1",
              publisher="DC Comics", year="2020", writer="Tom King",
              penciller="David Finch", genre="Superhero", age_rating="T+",
              summary="The Dark Knight.", filename="test.cbz"):
    """Create a minimal CBZ with a ComicInfo.xml for testing."""
    cbz_path = os.path.join(str(tmp_path), filename)
    xml = _COMICINFO_TEMPLATE.format(
        title=title, series=series, number=number, publisher=publisher,
        year=year, writer=writer, penciller=penciller,
        genre=genre, age_rating=age_rating, summary=summary,
    )
    with zipfile.ZipFile(cbz_path, "w") as zf:
        zf.writestr("ComicInfo.xml", xml.encode("utf-8"))
        zf.writestr("page_001.png", b"\x89PNG\r\n\x1a\n")
    return cbz_path


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


# ---------------------------------------------------------------------------
# No conflicts
# ---------------------------------------------------------------------------

class TestNoConflicts:
    def test_returns_zero_when_no_conflicts(self, tmp_path):
        """Identical values across sources means nothing to reconcile."""
        pre = {"Title": "Batman #1", "Publisher": "DC Comics", "Writer": "Tom King"}
        post = {"Title": "Batman #1", "Publisher": "DC Comics", "Writer": "Tom King"}
        cbz_path = _make_cbz(tmp_path)
        assert reconcile_metadata(cbz_path, "12345", pre, post) == 0

    def test_returns_zero_when_pre_is_none(self, tmp_path):
        """No pre-cmtag info means no comparison possible."""
        post = {"Title": "Batman #1", "Publisher": "DC Comics"}
        cbz_path = _make_cbz(tmp_path)
        assert reconcile_metadata(cbz_path, "12345", None, post) == 0

    def test_returns_zero_when_post_is_none(self, tmp_path):
        """No post-cmtag info means no comparison possible."""
        pre = {"Title": "Batman #1", "Publisher": "DC Comics"}
        cbz_path = _make_cbz(tmp_path)
        assert reconcile_metadata(cbz_path, "12345", pre, None) == 0

    def test_returns_zero_when_pre_field_blank(self, tmp_path):
        """Blank pre-cmtag value is not a conflict."""
        pre = {"Title": "", "Publisher": ""}
        post = {"Title": "Batman #1", "Publisher": "DC Comics"}
        cbz_path = _make_cbz(tmp_path)
        assert reconcile_metadata(cbz_path, "12345", pre, post) == 0

    def test_returns_zero_when_post_field_blank(self, tmp_path):
        """Blank post-cmtag value is not a conflict."""
        pre = {"Title": "Batman #1", "Publisher": "DC Comics"}
        post = {"Title": "", "Publisher": ""}
        cbz_path = _make_cbz(tmp_path)
        assert reconcile_metadata(cbz_path, "12345", pre, post) == 0


# ---------------------------------------------------------------------------
# AI not configured
# ---------------------------------------------------------------------------

class TestAINotConfigured:
    @patch("comicarr.app.ai.reconciliation.comicarr")
    def test_returns_zero_when_ai_client_none(self, mock_cm, tmp_path):
        """CV wins by default when AI is not configured."""
        mock_cm.AI_CLIENT = None
        pre = {"Title": "Dark Knight", "Publisher": "DC"}
        post = {"Title": "Batman #1", "Publisher": "DC Comics"}
        cbz_path = _make_cbz(tmp_path)
        assert reconcile_metadata(cbz_path, "12345", pre, post) == 0

    @patch("comicarr.app.ai.reconciliation.comicarr")
    def test_returns_zero_when_circuit_breaker_open(self, mock_cm, tmp_path):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=False)
        pre = {"Title": "Dark Knight", "Publisher": "DC"}
        post = {"Title": "Batman #1", "Publisher": "DC Comics"}
        cbz_path = _make_cbz(tmp_path)
        assert reconcile_metadata(cbz_path, "12345", pre, post) == 0

    @patch("comicarr.app.ai.reconciliation.comicarr")
    def test_returns_zero_when_rate_limiter_at_cap(self, mock_cm, tmp_path):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=False)
        pre = {"Title": "Dark Knight", "Publisher": "DC"}
        post = {"Title": "Batman #1", "Publisher": "DC Comics"}
        cbz_path = _make_cbz(tmp_path)
        assert reconcile_metadata(cbz_path, "12345", pre, post) == 0


# ---------------------------------------------------------------------------
# Conflicts detected and resolved
# ---------------------------------------------------------------------------

class TestConflictsResolved:
    @patch("comicarr.app.ai.reconciliation._store_reconciliation_history")
    @patch("comicarr.app.ai.reconciliation.ai_service")
    @patch("comicarr.app.ai.reconciliation.request_structured")
    @patch("comicarr.app.ai.reconciliation.comicarr")
    def test_happy_path_single_conflict(self, mock_cm, mock_req, mock_svc, mock_store, tmp_path):
        """One conflicting field is resolved and written back."""
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        cbz_path = _make_cbz(tmp_path, publisher="DC Comics")
        pre = {"Publisher": "DC"}
        post = {"Publisher": "DC Comics"}

        # AI picks the CV value
        mock_req.return_value = ReconciliationChoice(choices={"Publisher": "DC Comics"})

        result = reconcile_metadata(cbz_path, "12345", pre, post)
        assert result == 1

        # Verify CBZ was updated
        updated = _read_comicinfo(cbz_path)
        assert updated["Publisher"] == "DC Comics"

        # Verify history stored
        mock_store.assert_called_once()

        # Verify circuit breaker success recorded
        mock_cm.AI_CIRCUIT_BREAKER.record_success.assert_called_once()

        # Verify activity logged
        mock_svc.log_activity.assert_called_once()
        assert mock_svc.log_activity.call_args[1]["success"] is True
        assert mock_svc.log_activity.call_args[1]["feature_type"] == "reconciliation"

    @patch("comicarr.app.ai.reconciliation._store_reconciliation_history")
    @patch("comicarr.app.ai.reconciliation.ai_service")
    @patch("comicarr.app.ai.reconciliation.request_structured")
    @patch("comicarr.app.ai.reconciliation.comicarr")
    def test_happy_path_multiple_conflicts(self, mock_cm, mock_req, mock_svc, mock_store, tmp_path):
        """Multiple conflicting fields are resolved."""
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        cbz_path = _make_cbz(tmp_path, publisher="DC Comics", writer="Tom King")
        pre = {"Publisher": "DC", "Writer": "Tom King", "Genre": "Action"}
        post = {"Publisher": "DC Comics", "Writer": "Scott Snyder", "Genre": "Superhero"}

        # AI picks: CV publisher, pre writer, CV genre
        mock_req.return_value = ReconciliationChoice(choices={
            "Publisher": "DC Comics",
            "Writer": "Tom King",
            "Genre": "Superhero",
        })

        result = reconcile_metadata(cbz_path, "12345", pre, post)
        assert result == 3

        # Verify values written to CBZ
        updated = _read_comicinfo(cbz_path)
        assert updated["Publisher"] == "DC Comics"
        assert updated["Writer"] == "Tom King"
        assert updated["Genre"] == "Superhero"

    @patch("comicarr.app.ai.reconciliation._store_reconciliation_history")
    @patch("comicarr.app.ai.reconciliation.ai_service")
    @patch("comicarr.app.ai.reconciliation.request_structured")
    @patch("comicarr.app.ai.reconciliation.comicarr")
    def test_ai_picks_comicinfo_value(self, mock_cm, mock_req, mock_svc, mock_store, tmp_path):
        """AI selects the ComicInfo.xml value over CV."""
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        cbz_path = _make_cbz(tmp_path, writer="Scott Snyder")
        pre = {"Writer": "Scott Snyder"}
        post = {"Writer": "Scott A. Snyder"}

        mock_req.return_value = ReconciliationChoice(choices={"Writer": "Scott Snyder"})

        result = reconcile_metadata(cbz_path, "12345", pre, post)
        assert result == 1

        updated = _read_comicinfo(cbz_path)
        assert updated["Writer"] == "Scott Snyder"


# ---------------------------------------------------------------------------
# AI selects value not matching input — falls back to CV
# ---------------------------------------------------------------------------

class TestSynthesisRejection:
    @patch("comicarr.app.ai.reconciliation._store_reconciliation_history")
    @patch("comicarr.app.ai.reconciliation.ai_service")
    @patch("comicarr.app.ai.reconciliation.request_structured")
    @patch("comicarr.app.ai.reconciliation.comicarr")
    def test_synthesised_value_falls_back_to_cv(self, mock_cm, mock_req, mock_svc, mock_store, tmp_path):
        """When AI returns a value not matching either source, CV wins."""
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        cbz_path = _make_cbz(tmp_path, publisher="DC Comics")
        pre = {"Publisher": "DC"}
        post = {"Publisher": "DC Comics"}

        # AI synthesises a new value
        mock_req.return_value = ReconciliationChoice(
            choices={"Publisher": "DC Comics Inc."}
        )

        result = reconcile_metadata(cbz_path, "12345", pre, post)
        assert result == 1

        # CV value should be used as fallback
        updated = _read_comicinfo(cbz_path)
        assert updated["Publisher"] == "DC Comics"


# ---------------------------------------------------------------------------
# LLM timeout
# ---------------------------------------------------------------------------

class TestLLMTimeout:
    @patch("comicarr.app.ai.reconciliation.ai_service")
    @patch("comicarr.app.ai.reconciliation.request_structured")
    @patch("comicarr.app.ai.reconciliation.comicarr")
    def test_timeout_returns_zero(self, mock_cm, mock_req, mock_svc, tmp_path):
        """LLM timeout means CV wins — returns 0."""
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        cbz_path = _make_cbz(tmp_path)
        pre = {"Publisher": "DC"}
        post = {"Publisher": "DC Comics"}

        mock_req.side_effect = TimeoutError("Request timed out")

        result = reconcile_metadata(cbz_path, "12345", pre, post)
        assert result == 0

        # Circuit breaker failure recorded
        mock_cm.AI_CIRCUIT_BREAKER.record_failure.assert_called_once()

        # Activity logged as failure
        mock_svc.log_activity.assert_called_once()
        assert mock_svc.log_activity.call_args[1]["success"] is False


# ---------------------------------------------------------------------------
# Single-field conflict still triggers reconciliation
# ---------------------------------------------------------------------------

class TestSingleFieldConflict:
    @patch("comicarr.app.ai.reconciliation._store_reconciliation_history")
    @patch("comicarr.app.ai.reconciliation.ai_service")
    @patch("comicarr.app.ai.reconciliation.request_structured")
    @patch("comicarr.app.ai.reconciliation.comicarr")
    def test_one_field_conflict_triggers_reconciliation(self, mock_cm, mock_req, mock_svc, mock_store, tmp_path):
        """Even a single conflicting field should trigger AI reconciliation."""
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        cbz_path = _make_cbz(tmp_path, genre="Superhero")
        pre = {"Genre": "Action"}
        post = {"Genre": "Superhero"}

        mock_req.return_value = ReconciliationChoice(choices={"Genre": "Superhero"})

        result = reconcile_metadata(cbz_path, "12345", pre, post)
        assert result == 1
        mock_req.assert_called_once()


# ---------------------------------------------------------------------------
# History entries
# ---------------------------------------------------------------------------

class TestHistoryEntries:
    @patch("comicarr.app.ai.reconciliation.db")
    def test_stores_both_provider_rows(self, mock_db):
        """Each conflict should produce two history rows: comicinfo and cv."""
        conn = MagicMock()
        mock_db.DBConnection.return_value = conn

        conflicts = {
            "Publisher": {"comicinfo": "DC", "cv": "DC Comics"},
        }
        resolved = {"Publisher": "DC Comics"}

        _store_reconciliation_history("12345", conflicts, resolved)

        assert conn.action.call_count == 2

        # First call: comicinfo provider
        first_call = conn.action.call_args_list[0]
        sql = first_call[0][0]
        params = first_call[0][1]
        assert "INSERT INTO ai_metadata_history" in sql
        assert params[0] == "issue"
        assert params[1] == "12345"
        assert params[2] == "Publisher"
        assert params[3] == "DC"  # original_value = comicinfo value
        assert params[4] == "DC Comics"  # ai_value = resolved value
        assert params[5] == "reconciliation"
        assert params[6] == "comicinfo"

        # Second call: cv provider
        second_call = conn.action.call_args_list[1]
        params = second_call[0][1]
        assert params[3] == "DC Comics"  # original_value = cv value
        assert params[4] == "DC Comics"  # ai_value = resolved value
        assert params[5] == "reconciliation"
        assert params[6] == "cv"

    @patch("comicarr.app.ai.reconciliation.db")
    def test_multiple_conflicts_multiple_history_rows(self, mock_db):
        """Two conflicts should produce four history rows."""
        conn = MagicMock()
        mock_db.DBConnection.return_value = conn

        conflicts = {
            "Publisher": {"comicinfo": "DC", "cv": "DC Comics"},
            "Writer": {"comicinfo": "Tom King", "cv": "Scott Snyder"},
        }
        resolved = {"Publisher": "DC Comics", "Writer": "Tom King"}

        _store_reconciliation_history("12345", conflicts, resolved)
        assert conn.action.call_count == 4

    @patch("comicarr.app.ai.reconciliation.db")
    def test_skips_unresolved_fields(self, mock_db):
        """Fields not in resolved dict should not produce history rows."""
        conn = MagicMock()
        mock_db.DBConnection.return_value = conn

        conflicts = {
            "Publisher": {"comicinfo": "DC", "cv": "DC Comics"},
            "Writer": {"comicinfo": "Tom King", "cv": "Scott Snyder"},
        }
        resolved = {"Publisher": "DC Comics"}  # Writer not resolved

        _store_reconciliation_history("12345", conflicts, resolved)
        assert conn.action.call_count == 2  # Only Publisher rows


# ---------------------------------------------------------------------------
# RECONCILABLE_FIELDS constant
# ---------------------------------------------------------------------------

class TestReconcilableFields:
    def test_expected_fields_present(self):
        expected = {
            "Title", "Summary", "Publisher", "Genre", "AgeRating",
            "Writer", "Penciller", "Inker", "Colorist", "Letterer",
        }
        assert set(RECONCILABLE_FIELDS) == expected

    def test_does_not_include_series_or_number(self):
        """Series and Number should never be reconciled — they're identity fields."""
        assert "Series" not in RECONCILABLE_FIELDS
        assert "Number" not in RECONCILABLE_FIELDS
