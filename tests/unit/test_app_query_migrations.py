#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Seeded-database contracts for FastAPI domain Core query helpers."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import OperationalError

import comicarr
from comicarr import db
from comicarr.app.ai import pull_list
from comicarr.app.ai import queries as ai_queries
from comicarr.app.ai import story_arcs as ai_story_arcs
from comicarr.app.dashboard import queries as dashboard_queries
from comicarr.app.weekly import queries as weekly_queries
from comicarr.tables import (
    ai_cache,
    ai_metadata_history,
    comics,
    issues,
    metadata,
    snatched,
    storyarcs,
    weekly,
)


@pytest.fixture
def query_db(tmp_path, monkeypatch):
    """Use a file-backed SQLite engine so domain helpers exercise the real chain."""
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _seed_library(engine):
    with engine.begin() as conn:
        conn.execute(
            insert(comics),
            [
                {
                    "ComicID": "comic-alpha",
                    "ComicName": "Alpha",
                    "ComicSortName": "Alpha",
                    "ComicPublisher": "Marvel",
                    "DynamicComicName": "alpha",
                    "AlternateSearch": "The Alpha##A-Force",
                    "ComicImage": "alpha.jpg",
                    "Status": "Active",
                    "Have": 5,
                    "Total": 10,
                    "ContentType": "comic",
                },
                {
                    "ComicID": "comic-beta",
                    "ComicName": "Beta",
                    "ComicSortName": "Beta",
                    "ComicPublisher": "Marvel",
                    "DynamicComicName": None,
                    "AlternateSearch": None,
                    "ComicImage": None,
                    "Status": "Active",
                    "Have": 2,
                    "Total": 4,
                    "ContentType": "manga",
                },
                {
                    "ComicID": "comic-gamma",
                    "ComicName": "Gamma",
                    "ComicSortName": "Gamma",
                    "ComicPublisher": "DC",
                    "DynamicComicName": None,
                    "AlternateSearch": None,
                    "ComicImage": None,
                    "Status": "Active",
                    "Have": 0,
                    "Total": 0,
                    "ContentType": "comic",
                },
                {
                    "ComicID": "comic-paused",
                    "ComicName": "Paused",
                    "ComicSortName": "Paused",
                    "ComicPublisher": "DC",
                    "DynamicComicName": None,
                    "AlternateSearch": None,
                    "ComicImage": None,
                    "Status": "Paused",
                    "Have": 99,
                    "Total": 99,
                    "ContentType": "comic",
                },
            ],
        )
        conn.execute(
            insert(issues),
            [
                {
                    "IssueID": "issue-alpha-1",
                    "ComicID": "comic-alpha",
                    "Issue_Number": "1",
                    "Status": "Downloaded",
                },
            ],
        )


def test_ai_cache_helpers_preserve_json_expiry_upsert_and_no_row_semantics(query_db):
    assert ai_queries.get_cache_entry("missing", "suggestions") is None

    ai_queries.upsert_cache_entry(
        "suggestions",
        "suggestions",
        '["first"]',
        "2026-06-10 12:00:00",
        "2026-06-10 18:00:00",
    )
    ai_queries.upsert_cache_entry(
        "suggestions",
        "suggestions",
        '["updated", "value"]',
        "2026-06-10 13:00:00",
        "2026-06-11 13:00:00",
    )

    cached = ai_queries.get_cache_entry("suggestions", "suggestions")
    assert cached == {
        "data": '["updated", "value"]',
        "expires_at": "2026-06-11 13:00:00",
    }
    with query_db.connect() as conn:
        rows = conn.execute(select(ai_cache).where(ai_cache.c.cache_key == "suggestions")).all()
    assert len(rows) == 1


def test_suggestion_cache_decodes_fresh_json_and_rejects_expired_entries(query_db):
    ai_queries.upsert_cache_entry(
        pull_list.CACHE_KEY,
        pull_list.CACHE_TYPE,
        '[{"title": "Fresh"}]',
        "2026-06-10 12:00:00",
        "9999-12-31 23:59:59",
    )
    assert pull_list._get_cached_suggestions() == [{"title": "Fresh"}]

    ai_queries.upsert_cache_entry(
        pull_list.CACHE_KEY,
        pull_list.CACHE_TYPE,
        '[{"title": "Expired"}]',
        "2026-06-10 12:00:00",
        "2000-01-01 00:00:00",
    )
    assert pull_list._get_cached_suggestions() is None


def test_ai_activity_and_history_helpers_mutate_seeded_database(query_db):
    ai_queries.insert_activity(
        {
            "timestamp": "2026-06-10T12:00:00",
            "feature_type": "older",
            "action_description": "older activity",
            "model": "test",
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "latency_ms": 3,
            "success": "true",
            "error_message": None,
            "entity_type": "issue",
            "entity_id": "issue-1",
        }
    )
    ai_queries.insert_activity(
        {
            "timestamp": "2026-06-10T12:00:01",
            "feature_type": "newer",
            "action_description": "newer activity",
            "model": "test",
            "prompt_tokens": 4,
            "completion_tokens": 5,
            "latency_ms": 6,
            "success": "false",
            "error_message": "failed",
            "entity_type": "issue",
            "entity_id": "issue-2",
        }
    )
    assert [row["feature_type"] for row in ai_queries.get_activity(limit=1)] == ["newer"]
    assert [row["feature_type"] for row in ai_queries.get_activity(limit=1, offset=1)] == ["older"]

    ai_queries.insert_metadata_history(
        {
            "entity_type": "issue",
            "entity_id": "issue-1",
            "field_name": "Genre",
            "original_value": "Old",
            "ai_value": "New",
            "source": "enrichment",
            "created_at": "2026-06-10 12:00:00",
        }
    )
    ai_queries.insert_metadata_history(
        {
            "entity_type": "issue",
            "entity_id": "issue-1",
            "field_name": "Genre",
            "original_value": "Old",
            "ai_value": "New",
            "source": "reconciliation",
            "provider": "comicinfo",
            "created_at": "2026-06-10 12:00:01",
        }
    )
    ai_queries.delete_metadata_history("issue", "issue-1", "Genre", "enrichment")
    with query_db.connect() as conn:
        rows = conn.execute(select(ai_metadata_history.c.source, ai_metadata_history.c.provider)).mappings().all()
    assert [dict(row) for row in rows] == [{"source": "reconciliation", "provider": "comicinfo"}]


def test_ai_lookup_and_untracked_weekly_helpers_use_seeded_rows(query_db):
    _seed_library(query_db)

    assert ai_queries.issue_exists("issue-alpha-1") is True
    assert ai_queries.issue_exists("missing") is False
    assert ai_queries.get_alternate_search("comic-alpha") == {"AlternateSearch": "The Alpha##A-Force"}
    assert ai_queries.get_alternate_search("missing") is None
    ai_queries.update_alternate_search("comic-alpha", "Updated")
    assert ai_queries.get_alternate_search("comic-alpha") == {"AlternateSearch": "Updated"}
    assert ai_queries.find_series_candidates("lph") == [{"ComicID": "comic-alpha", "ComicName": "Alpha"}]
    assert ai_queries.find_issue_by_comic_and_number("comic-alpha", "1") == {"IssueID": "issue-alpha-1"}
    assert ai_queries.find_issue_by_comic_and_number("comic-alpha", "2") is None
    assert ai_queries.get_issue_status_by_comic_and_number("comic-alpha", "1") == {"Status": "Downloaded"}
    assert ai_queries.get_issue_status_by_comic_and_number("comic-alpha", "2") is None

    with query_db.begin() as conn:
        conn.execute(
            insert(weekly),
            [
                {
                    "COMIC": "Zulu",
                    "PUBLISHER": "Marvel",
                    "ISSUE": "1",
                    "STATUS": "",
                    "ComicID": "zulu",
                    "IssueID": "zulu-1",
                },
                {
                    "COMIC": "Alpha",
                    "PUBLISHER": "Marvel",
                    "ISSUE": "1",
                    "STATUS": None,
                    "ComicID": "weekly-alpha",
                    "IssueID": "weekly-alpha-1",
                },
                {
                    "COMIC": "Tracked",
                    "PUBLISHER": "Marvel",
                    "ISSUE": "1",
                    "STATUS": "Wanted",
                    "ComicID": "tracked",
                    "IssueID": "tracked-1",
                },
            ],
        )
    assert [row["COMIC"] for row in ai_queries.get_untracked_weekly_releases()] == ["Alpha", "Zulu"]


class _RetryingWriteEngine:
    def __init__(self, locked_attempts):
        self.locked_attempts = locked_attempts
        self.execute_calls = 0

    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, _statement):
        self.execute_calls += 1
        if self.execute_calls <= self.locked_attempts:
            raise OperationalError("database is locked", None, RuntimeError("database is locked"))


def test_ai_writes_keep_legacy_lock_retry_and_exhaustion_contract(monkeypatch):
    retries = []
    retrying_engine = _RetryingWriteEngine(locked_attempts=1)
    monkeypatch.setattr(ai_queries.db, "get_engine", lambda: retrying_engine)
    monkeypatch.setattr(ai_queries.time, "sleep", retries.append)

    ai_queries.insert_activity({"timestamp": "2026-06-10T12:00:00"})

    assert retrying_engine.execute_calls == 2
    assert retries == [1]

    exhausted_engine = _RetryingWriteEngine(locked_attempts=ai_queries._WRITE_ATTEMPTS)
    monkeypatch.setattr(ai_queries.db, "get_engine", lambda: exhausted_engine)
    ai_queries.insert_metadata_history({"entity_type": "issue", "entity_id": "issue-1"})

    assert exhausted_engine.execute_calls == ai_queries._WRITE_ATTEMPTS
    assert retries == [1] * (ai_queries._WRITE_ATTEMPTS + 1)


def test_ai_library_and_story_arc_helpers_preserve_order_and_safe_no_rows(query_db):
    _seed_library(query_db)

    assert [row["ComicPublisher"] for row in ai_queries.get_active_publisher_counts()] == ["Marvel", "DC"]
    assert ai_queries.get_active_series_count() == 3
    assert ai_queries.get_active_series_names() == ["Alpha", "Beta", "Gamma"]
    assert ai_queries.get_active_completion_rate() == 50.0
    assert ai_queries.find_exact_library_match("Alpha", "alpha") == {"ComicID": "comic-alpha"}
    assert ai_queries.find_case_insensitive_library_match("ALPHA") == {"ComicID": "comic-alpha"}
    assert ai_queries.get_alternate_search_values() == [{"AlternateSearch": "The Alpha##A-Force"}]
    assert ai_queries.get_issue_status_by_id("missing") is None
    assert ai_queries.get_issue_status_by_id("issue-alpha-1") == {"Status": "Downloaded"}

    values = {
        "StoryArcID": "AI_TEST",
        "StoryArc": "Test arc",
        "ComicName": "Alpha",
        "IssueNumber": "1",
        "IssueName": "First",
        "ReadingOrder": 1,
        "ComicID": "comic-alpha",
        "IssueID": "issue-alpha-1",
        "Status": "Added",
        "IssueArcID": "AI_TEST_1",
        "Manual": "ai",
        "DateAdded": "2026-06-10 12:00:00",
    }
    ai_queries.replace_storyarc(values)
    ai_queries.replace_storyarc({**values, "Status": "Wanted"})
    with query_db.connect() as conn:
        rows = conn.execute(select(storyarcs).where(storyarcs.c.IssueArcID == "AI_TEST_1")).mappings().all()
    assert len(rows) == 1
    assert {name: rows[0][name] for name in values} == {**values, "Status": "Wanted"}


def test_save_arc_replaces_legacy_row_and_clears_omitted_columns(query_db):
    issue_arc_id = "AI_REPLACE0_1"
    with query_db.begin() as conn:
        conn.execute(
            insert(storyarcs),
            {
                "StoryArcID": "AI_REPLACE0",
                "StoryArc": "Old arc",
                "ComicName": "Legacy title",
                "IssueNumber": "0",
                "IssueArcID": issue_arc_id,
                "Publisher": "Legacy publisher",
                "ArcImage": "legacy.jpg",
                "Manual": "legacy",
            },
        )

    with patch("comicarr.app.ai.story_arcs.uuid.uuid4", return_value=SimpleNamespace(hex="replace00rest")):
        result = ai_story_arcs.save_arc(
            "New arc",
            [
                {
                    "series_name": "Alpha",
                    "issue_number": "1",
                    "title": "First",
                    "reading_order": 1,
                    "comic_id": "comic-alpha",
                    "issue_id": "issue-alpha-1",
                    "library_status": "wanted",
                }
            ],
        )

    assert result == {"success": True, "arc_id": "AI_REPLACE0"}
    with query_db.connect() as conn:
        row = conn.execute(select(storyarcs).where(storyarcs.c.IssueArcID == issue_arc_id)).mappings().one()
    assert row["StoryArc"] == "New arc"
    assert row["Status"] == "Wanted"
    assert row["Publisher"] is None
    assert row["ArcImage"] is None


def test_dashboard_helpers_keep_inclusive_cutoff_order_and_content_type_totals(query_db):
    _seed_library(query_db)
    with query_db.begin() as conn:
        conn.execute(
            insert(snatched),
            [
                {
                    "IssueID": "boundary",
                    "ComicID": "comic-alpha",
                    "ComicName": "Alpha",
                    "Issue_Number": "1",
                    "Status": "Snatched",
                    "Provider": "one",
                    "DateAdded": "2026-06-10 12:00:00",
                },
                {
                    "IssueID": "newest",
                    "ComicID": "comic-alpha",
                    "ComicName": "Alpha",
                    "Issue_Number": "2",
                    "Status": "Snatched",
                    "Provider": "two",
                    "DateAdded": "2026-06-10 12:00:01",
                },
                {
                    "IssueID": "old",
                    "ComicID": "comic-alpha",
                    "ComicName": "Alpha",
                    "Issue_Number": "0",
                    "Status": "Snatched",
                    "Provider": "three",
                    "DateAdded": "2026-06-10 11:59:59",
                },
            ],
        )
    recent = dashboard_queries.get_recent_activity("2026-06-10 12:00:00")
    assert [row["IssueID"] for row in recent] == ["newest", "boundary"]
    assert dashboard_queries.get_library_stats() == {
        "total_series": 3,
        "total_issues": 7,
        "total_expected": 14,
    }
    assert dashboard_queries.get_library_stats("manga") == {
        "manga_series": 1,
        "manga_have": 2,
        "manga_total": 4,
    }
    assert dashboard_queries.get_library_stats("comic") == {
        "comic_series": 2,
        "comic_have": 5,
        "comic_total": 10,
    }


def test_weekly_helper_matches_unpadded_week_and_orders_by_title(query_db):
    with query_db.begin() as conn:
        conn.execute(
            insert(weekly),
            [
                {"COMIC": "Zulu", "ISSUE": "1", "ComicID": "z", "IssueID": "z-1", "weeknumber": "1", "year": "2026"},
                {"COMIC": "Alpha", "ISSUE": "1", "ComicID": "a", "IssueID": "a-1", "weeknumber": "1", "year": "2026"},
                {
                    "COMIC": "Other week",
                    "ISSUE": "1",
                    "ComicID": "other",
                    "IssueID": "other-1",
                    "weeknumber": "2",
                    "year": "2026",
                },
            ],
        )

    assert [row["COMIC"] for row in weekly_queries.get_weekly_releases("01", "2026")] == ["Alpha", "Zulu"]
    assert weekly_queries.get_weekly_releases("03", "2026") == []
