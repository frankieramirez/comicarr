#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Budget, resume, and RSS-lookup skip tests for scheduled Wanted/RSS passes."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import comicarr
from comicarr.app.search.backlog import (
    PASS_MANGA_RSS,
    PASS_RSS_WANTED,
    PassBudget,
    clear_lookup_cache,
    get_rss_provider_lookup,
    mark_rssdb_refreshed,
    put_rss_provider_lookup,
    release_pass,
    rss_provider_lookup_key,
    try_acquire_pass,
)
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import metadata


@pytest.fixture
def backlog_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(WANTED_SEARCH_PASS_ITEMS=250, WANTED_SEARCH_PASS_SECONDS=120),
        raising=False,
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    metadata.create_all(get_engine())
    clear_lookup_cache()
    release_pass()
    yield
    release_pass()
    clear_lookup_cache()
    shutdown_engine()


def _issues(*ids):
    return [{"IssueID": issue_id} for issue_id in ids]


def test_item_budget_returns_only_the_next_slice(backlog_db):
    budget = PassBudget(PASS_RSS_WANTED, item_budget=2, seconds_budget=0)
    selected = budget.select_candidates(_issues("a", "b", "c", "d"), lambda row: row["IssueID"])

    assert [row["IssueID"] for row in selected] == ["a", "b"]
    for row in selected:
        budget.consume(row["IssueID"])

    resumed = PassBudget(PASS_RSS_WANTED, item_budget=2, seconds_budget=0)
    selected = resumed.select_candidates(_issues("a", "b", "c", "d"), lambda row: row["IssueID"])
    assert [row["IssueID"] for row in selected] == ["c", "d"]
    assert resumed.skipped == 2


def test_completed_cycle_idles_until_rssdb_refresh(backlog_db):
    budget = PassBudget(PASS_RSS_WANTED, item_budget=0, seconds_budget=0)
    selected = budget.select_candidates(_issues("a", "b"), lambda row: row["IssueID"])
    for row in selected:
        budget.consume(row["IssueID"])

    idle = PassBudget(PASS_RSS_WANTED, item_budget=0, seconds_budget=0)
    assert idle.select_candidates(_issues("a", "b"), lambda row: row["IssueID"]) == []
    assert idle.stop_reason == "waiting_for_rssdb"

    mark_rssdb_refreshed("gen-2")
    restarted = PassBudget(PASS_RSS_WANTED, item_budget=0, seconds_budget=0)
    selected = restarted.select_candidates(_issues("a", "b"), lambda row: row["IssueID"])
    assert [row["IssueID"] for row in selected] == ["a", "b"]


def test_new_issue_is_picked_before_unseen_older_rows(backlog_db):
    budget = PassBudget(PASS_RSS_WANTED, item_budget=1, seconds_budget=0)
    first = budget.select_candidates(_issues("old", "older"), lambda row: row["IssueID"])
    budget.consume(first[0]["IssueID"])
    assert first[0]["IssueID"] == "old"

    resumed = PassBudget(PASS_RSS_WANTED, item_budget=1, seconds_budget=0)
    selected = resumed.select_candidates(_issues("new", "old", "older"), lambda row: row["IssueID"])
    assert [row["IssueID"] for row in selected] == ["new"]


def test_time_budget_stops_remaining(backlog_db):
    clock = {"now": 0.0}

    def monotonic():
        return clock["now"]

    budget = PassBudget(PASS_RSS_WANTED, item_budget=0, seconds_budget=5, monotonic=monotonic)
    assert budget.remaining() is True
    clock["now"] = 5
    assert budget.remaining() is False
    assert budget.stop_reason == "time_budget"


def test_rss_lookup_cache_hits_within_generation(backlog_db):
    mark_rssdb_refreshed("gen-1")
    key = rss_provider_lookup_key("One Piece", "comic-1", "nzb.example")
    put_rss_provider_lookup(key, {"entries": [{"title": "hit"}]})

    cached = get_rss_provider_lookup(key)
    assert cached == {"entries": [{"title": "hit"}]}
    cached["entries"].append({"title": "mutated"})
    assert get_rss_provider_lookup(key) == {"entries": [{"title": "hit"}]}

    mark_rssdb_refreshed("gen-2")
    assert get_rss_provider_lookup(key) is None


def test_backlog_lock_does_not_use_searchlock(backlog_db, monkeypatch):
    search_lock = MagicMock()
    monkeypatch.setattr(comicarr, "SEARCHLOCK", search_lock)

    assert try_acquire_pass() is True
    assert try_acquire_pass() is False
    release_pass()
    assert try_acquire_pass() is True
    release_pass()
    search_lock.acquire.assert_not_called()
    search_lock.locked.assert_not_called()


def test_manga_pass_kind_does_not_share_rss_wanted_seen(backlog_db):
    wanted = PassBudget(PASS_RSS_WANTED, item_budget=0, seconds_budget=0)
    for row in wanted.select_candidates(_issues("shared"), lambda row: row["IssueID"]):
        wanted.consume(row["IssueID"])

    manga = PassBudget(PASS_MANGA_RSS, item_budget=0, seconds_budget=0)
    selected = manga.select_candidates(_issues("shared"), lambda row: row["IssueID"])
    assert [row["IssueID"] for row in selected] == ["shared"]
