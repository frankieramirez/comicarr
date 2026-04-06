#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for comicarr.app.ai.enrichment — ComicInfo.xml metadata enrichment."""

import os
import zipfile

import pytest
from unittest.mock import MagicMock, patch

from comicarr.app.ai.enrichment import (
    ENRICHABLE_FIELDS,
    _read_comicinfo,
    _store_history,
    _write_comicinfo,
    enrich_metadata,
    revert_field,
)
from comicarr.app.ai.schemas import MetadataEnrichment

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
</ComicInfo>
"""


def _make_cbz(tmp_path, title="Batman #1", series="Batman", number="1",
              publisher="DC Comics", year="2020", writer="Tom King",
              penciller="David Finch", genre="", age_rating="",
              filename="test.cbz", include_comicinfo=True):
    """Create a minimal CBZ with a ComicInfo.xml for testing."""
    cbz_path = os.path.join(str(tmp_path), filename)
    xml = _COMICINFO_TEMPLATE.format(
        title=title, series=series, number=number, publisher=publisher,
        year=year, writer=writer, penciller=penciller,
        genre=genre, age_rating=age_rating,
    )
    with zipfile.ZipFile(cbz_path, "w") as zf:
        if include_comicinfo:
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
# _read_comicinfo
# ---------------------------------------------------------------------------

class TestReadComicinfo:
    def test_reads_fields_from_cbz(self, tmp_path):
        cbz_path = _make_cbz(tmp_path, series="Spider-Man", number="300",
                             publisher="Marvel", genre="Superhero", age_rating="T+")
        result = _read_comicinfo(cbz_path)
        assert result is not None
        assert result["Series"] == "Spider-Man"
        assert result["Number"] == "300"
        assert result["Publisher"] == "Marvel"
        assert result["Genre"] == "Superhero"
        assert result["AgeRating"] == "T+"

    def test_returns_none_when_no_comicinfo(self, tmp_path):
        cbz_path = _make_cbz(tmp_path, include_comicinfo=False)
        result = _read_comicinfo(cbz_path)
        assert result is None

    def test_returns_none_for_nonexistent_file(self):
        result = _read_comicinfo("/nonexistent/path/comic.cbz")
        assert result is None

    def test_blank_fields_returned_as_empty_string(self, tmp_path):
        cbz_path = _make_cbz(tmp_path, genre="", age_rating="")
        result = _read_comicinfo(cbz_path)
        assert result is not None
        assert result["Genre"] == ""
        assert result["AgeRating"] == ""


# ---------------------------------------------------------------------------
# _write_comicinfo
# ---------------------------------------------------------------------------

class TestWriteComicinfo:
    def test_writes_enriched_values(self, tmp_path):
        cbz_path = _make_cbz(tmp_path, genre="", age_rating="")
        _write_comicinfo(cbz_path, {"Genre": "Superhero", "AgeRating": "T+"})

        # Verify by reading back
        result = _read_comicinfo(cbz_path)
        assert result["Genre"] == "Superhero"
        assert result["AgeRating"] == "T+"

    def test_preserves_other_files(self, tmp_path):
        cbz_path = _make_cbz(tmp_path)
        _write_comicinfo(cbz_path, {"Genre": "Horror"})

        with zipfile.ZipFile(cbz_path, "r") as zf:
            assert "page_001.png" in zf.namelist()
            assert "ComicInfo.xml" in zf.namelist()


# ---------------------------------------------------------------------------
# _store_history
# ---------------------------------------------------------------------------

class TestStoreHistory:
    @patch("comicarr.app.ai.enrichment.db")
    def test_writes_to_ai_metadata_history(self, mock_db):
        conn = MagicMock()
        mock_db.DBConnection.return_value = conn

        _store_history("12345", {"Genre": "Superhero", "AgeRating": "T+"})
        assert conn.action.call_count == 2

        # Check first call
        call_args = conn.action.call_args_list[0]
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "INSERT INTO ai_metadata_history" in sql
        assert params[0] == "issue"
        assert params[1] == "12345"
        assert params[2] == "Genre"
        assert params[3] is None  # original_value
        assert params[4] == "Superhero"
        assert params[5] == "enrichment"


# ---------------------------------------------------------------------------
# enrich_metadata
# ---------------------------------------------------------------------------

class TestEnrichMetadata:
    @patch("comicarr.app.ai.enrichment.comicarr")
    def test_skips_when_ai_not_configured(self, mock_cm, tmp_path):
        mock_cm.AI_CLIENT = None
        cbz_path = _make_cbz(tmp_path)
        assert enrich_metadata(cbz_path, "12345") == 0

    @patch("comicarr.app.ai.enrichment.comicarr")
    def test_skips_when_circuit_breaker_open(self, mock_cm, tmp_path):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=False)
        cbz_path = _make_cbz(tmp_path)
        assert enrich_metadata(cbz_path, "12345") == 0

    @patch("comicarr.app.ai.enrichment.comicarr")
    def test_skips_when_rate_limiter_at_cap(self, mock_cm, tmp_path):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=False)
        cbz_path = _make_cbz(tmp_path)
        assert enrich_metadata(cbz_path, "12345") == 0

    @patch("comicarr.app.ai.enrichment.comicarr")
    def test_skips_when_all_fields_populated(self, mock_cm, tmp_path):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        cbz_path = _make_cbz(tmp_path, genre="Superhero", age_rating="T+")
        assert enrich_metadata(cbz_path, "12345") == 0

    @patch("comicarr.app.ai.enrichment.comicarr")
    def test_skips_when_no_context_fields(self, mock_cm, tmp_path):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        # Create CBZ with all context fields blank
        cbz_path = _make_cbz(
            tmp_path, title="", series="", number="", publisher="",
            year="", writer="", penciller="", genre="", age_rating="",
        )
        assert enrich_metadata(cbz_path, "12345") == 0

    @patch("comicarr.app.ai.enrichment._store_history")
    @patch("comicarr.app.ai.enrichment.ai_service")
    @patch("comicarr.app.ai.enrichment.request_structured")
    @patch("comicarr.app.ai.enrichment.comicarr")
    def test_filters_out_fields_not_in_blank_list(self, mock_cm, mock_req, mock_svc, mock_store, tmp_path):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        # Genre is already populated, AgeRating is blank
        cbz_path = _make_cbz(tmp_path, genre="Superhero", age_rating="")

        # AI returns both Genre and AgeRating — only AgeRating should be accepted
        mock_req.return_value = MetadataEnrichment(
            fields={"Genre": "Action", "AgeRating": "T+"}
        )

        result = enrich_metadata(cbz_path, "12345")
        assert result == 1

        # Verify only AgeRating was stored
        store_call = mock_store.call_args
        assert store_call[0][1] == {"AgeRating": "T+"}

    @patch("comicarr.app.ai.enrichment._store_history")
    @patch("comicarr.app.ai.enrichment.ai_service")
    @patch("comicarr.app.ai.enrichment.request_structured")
    @patch("comicarr.app.ai.enrichment.comicarr")
    def test_only_enriches_genre_and_age_rating(self, mock_cm, mock_req, mock_svc, mock_store, tmp_path):
        """AI returns Summary and Characters — they must NOT be written."""
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        cbz_path = _make_cbz(tmp_path, genre="", age_rating="")

        # AI returns fields outside the ENRICHABLE_FIELDS set
        mock_req.return_value = MetadataEnrichment(
            fields={
                "Genre": "Superhero",
                "AgeRating": "T+",
                "Summary": "Batman fights crime.",
                "Characters": "Batman, Robin",
                "Teams": "Justice League",
                "Locations": "Gotham City",
            }
        )

        result = enrich_metadata(cbz_path, "12345")
        assert result == 2

        # Verify only Genre and AgeRating stored
        store_call = mock_store.call_args
        enriched = store_call[0][1]
        assert set(enriched.keys()) == {"Genre", "AgeRating"}
        assert "Summary" not in enriched
        assert "Characters" not in enriched

    @patch("comicarr.app.ai.enrichment._store_history")
    @patch("comicarr.app.ai.enrichment.ai_service")
    @patch("comicarr.app.ai.enrichment.request_structured")
    @patch("comicarr.app.ai.enrichment.comicarr")
    def test_happy_path_blank_genre_filled(self, mock_cm, mock_req, mock_svc, mock_store, tmp_path):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        cbz_path = _make_cbz(tmp_path, genre="", age_rating="")

        mock_req.return_value = MetadataEnrichment(
            fields={"Genre": "Superhero", "AgeRating": "T+"}
        )

        result = enrich_metadata(cbz_path, "12345")
        assert result == 2

        # Verify CBZ was updated
        updated = _read_comicinfo(cbz_path)
        assert updated["Genre"] == "Superhero"
        assert updated["AgeRating"] == "T+"

        # Verify history stored
        mock_store.assert_called_once_with("12345", {"Genre": "Superhero", "AgeRating": "T+"})

        # Verify circuit breaker success recorded
        mock_cm.AI_CIRCUIT_BREAKER.record_success.assert_called_once()

        # Verify activity logged
        mock_svc.log_activity.assert_called_once()
        assert mock_svc.log_activity.call_args[1]["success"] is True
        assert mock_svc.log_activity.call_args[1]["feature_type"] == "enrichment"

    @patch("comicarr.app.ai.enrichment.ai_service")
    @patch("comicarr.app.ai.enrichment.request_structured")
    @patch("comicarr.app.ai.enrichment.comicarr")
    def test_ai_error_records_failure(self, mock_cm, mock_req, mock_svc, tmp_path):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        cbz_path = _make_cbz(tmp_path, genre="", age_rating="")

        mock_req.side_effect = TimeoutError("Request timed out")

        result = enrich_metadata(cbz_path, "12345")
        assert result == 0

        mock_cm.AI_CIRCUIT_BREAKER.record_failure.assert_called_once()
        mock_svc.log_activity.assert_called_once()
        assert mock_svc.log_activity.call_args[1]["success"] is False

    @patch("comicarr.app.ai.enrichment._store_history")
    @patch("comicarr.app.ai.enrichment.ai_service")
    @patch("comicarr.app.ai.enrichment.request_structured")
    @patch("comicarr.app.ai.enrichment.comicarr")
    def test_skips_when_ai_returns_empty_values(self, mock_cm, mock_req, mock_svc, mock_store, tmp_path):
        mock_cm.AI_CLIENT = MagicMock()
        mock_cm.AI_CIRCUIT_BREAKER = _make_mock_circuit_breaker(allow=True)
        mock_cm.AI_RATE_LIMITER = _make_mock_rate_limiter(can=True)
        mock_cm.CONFIG = _make_mock_config()

        cbz_path = _make_cbz(tmp_path, genre="", age_rating="")

        # AI returns empty/whitespace values
        mock_req.return_value = MetadataEnrichment(
            fields={"Genre": "", "AgeRating": "   "}
        )

        result = enrich_metadata(cbz_path, "12345")
        assert result == 0
        mock_store.assert_not_called()


# ---------------------------------------------------------------------------
# revert_field
# ---------------------------------------------------------------------------

class TestRevertField:
    @patch("comicarr.app.ai.enrichment.db")
    def test_validates_issue_exists(self, mock_db):
        conn = MagicMock()
        mock_db.DBConnection.return_value = conn
        conn.select.return_value = []

        with pytest.raises(ValueError, match="Issue .* not found"):
            revert_field("99999", "Genre", "/path/to/comic.cbz")

    @patch("comicarr.app.ai.enrichment._write_comicinfo")
    @patch("comicarr.app.ai.enrichment.db")
    def test_reverts_field_to_empty(self, mock_db, mock_write):
        conn = MagicMock()
        mock_db.DBConnection.return_value = conn
        conn.select.return_value = [{"IssueID": "12345"}]

        revert_field("12345", "Genre", "/path/to/comic.cbz")

        mock_write.assert_called_once_with("/path/to/comic.cbz", {"Genre": ""})

    @patch("comicarr.app.ai.enrichment._write_comicinfo")
    @patch("comicarr.app.ai.enrichment.db")
    def test_deletes_history_entry(self, mock_db, mock_write):
        conn = MagicMock()
        mock_db.DBConnection.return_value = conn
        conn.select.return_value = [{"IssueID": "12345"}]

        revert_field("12345", "Genre", "/path/to/comic.cbz")

        # Second call should be the DELETE
        delete_call = conn.action.call_args
        sql = delete_call[0][0]
        params = delete_call[0][1]
        assert "DELETE FROM ai_metadata_history" in sql
        assert params == ["issue", "12345", "Genre", "enrichment"]


# ---------------------------------------------------------------------------
# ENRICHABLE_FIELDS constant
# ---------------------------------------------------------------------------

class TestEnrichableFields:
    def test_only_genre_and_age_rating(self):
        assert set(ENRICHABLE_FIELDS) == {"Genre", "AgeRating"}

    def test_does_not_include_dangerous_fields(self):
        dangerous = {"Summary", "Characters", "Teams", "Locations", "Notes", "Web"}
        assert not set(ENRICHABLE_FIELDS).intersection(dangerous)
