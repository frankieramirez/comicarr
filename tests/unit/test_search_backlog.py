#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Budget, resume, and pass-scoped RSS lookup memo tests for scheduled RSS passes."""

import threading
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

import comicarr
from comicarr.app.search.backlog import (
    PASS_RSS_WANTED,
    PassBudget,
    get_rss_provider_lookup,
    is_recent_release,
    mark_rssdb_refreshed,
    put_rss_provider_lookup,
    release_pass,
    rss_lookup_memo,
    rss_provider_lookup_key,
    try_acquire_pass,
)
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, issues, metadata, rss_search_seen


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
    release_pass()
    yield
    release_pass()
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


def test_rss_lookup_memo_hits_only_inside_the_pass():
    key = rss_provider_lookup_key("One Piece", "comic-1", "nzb.example", "1997", None, False)

    put_rss_provider_lookup(key, {"entries": [{"title": "outside"}]})
    assert get_rss_provider_lookup(key) is None

    with rss_lookup_memo():
        put_rss_provider_lookup(key, {"entries": [{"title": "hit"}]})
        cached = get_rss_provider_lookup(key)
        assert cached == {"entries": [{"title": "hit"}]}
        cached["entries"].append({"title": "mutated"})
        assert get_rss_provider_lookup(key) == {"entries": [{"title": "hit"}]}

    assert get_rss_provider_lookup(key) is None
    with rss_lookup_memo():
        assert get_rss_provider_lookup(key) is None


def test_rss_lookup_memo_does_not_cross_threads():
    key = rss_provider_lookup_key("One Piece", "comic-1", "nzb.example")
    seen_in_thread = []

    with rss_lookup_memo():
        put_rss_provider_lookup(key, "no results")
        assert get_rss_provider_lookup(key) == "no results"
        worker = threading.Thread(target=lambda: seen_in_thread.append(get_rss_provider_lookup(key)))
        worker.start()
        worker.join()

    assert seen_in_thread == [None]


def test_rss_lookup_key_separates_year_version_and_oneoff():
    base = rss_provider_lookup_key("One Piece", "comic-1", "nzb.example", "1997", "v1", False)

    assert base != rss_provider_lookup_key("One Piece", "comic-1", "nzb.example", "1998", "v1", False)
    assert base != rss_provider_lookup_key("One Piece", "comic-1", "nzb.example", "1997", "v2", False)
    assert base != rss_provider_lookup_key("One Piece", "comic-1", "other.example", "1997", "v1", False)
    assert rss_provider_lookup_key("One Piece", "comic-1", "p", oneoff=True) == rss_provider_lookup_key(
        "one piece", None, "p", oneoff=True
    )


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


def test_recent_releases_are_rechecked_on_top_of_the_budget(backlog_db):
    mark_rssdb_refreshed("gen-1")
    rows = [
        {"IssueID": "fresh", "StoreDate": "2026-10-01"},
        {"IssueID": "a", "StoreDate": "2020-01-01"},
        {"IssueID": "b", "StoreDate": "2019-01-01"},
    ]

    def recent(row):
        return is_recent_release(row, today=date(2026, 10, 6))

    first = PassBudget(PASS_RSS_WANTED, item_budget=2, seconds_budget=0)
    selected = first.select_candidates(rows, lambda row: row["IssueID"], recent=recent)
    assert [row["IssueID"] for row in selected] == ["fresh", "a"]
    for row in selected:
        first.consume(row["IssueID"])

    mark_rssdb_refreshed("gen-2")
    second = PassBudget(PASS_RSS_WANTED, item_budget=2, seconds_budget=0)
    selected = second.select_candidates(rows, lambda row: row["IssueID"], recent=recent)
    assert [row["IssueID"] for row in selected] == ["fresh", "b"]


def test_is_recent_release_ignores_placeholder_and_bad_dates():
    today = date(2026, 10, 6)

    assert is_recent_release({"StoreDate": "2026-09-30"}, today=today) is True
    assert is_recent_release({"StoreDate": "0000-00-00", "DigitalDate": "2026-10-05"}, today=today) is True
    assert is_recent_release({"StoreDate": "2026-09-01"}, today=today) is False
    assert (
        is_recent_release({"StoreDate": "0000-00-00", "IssueDate": None, "DigitalDate": "junk"}, today=today) is False
    )


def test_negative_budget_disables_the_cap_instead_of_slicing_from_the_end(backlog_db):
    budget = PassBudget(PASS_RSS_WANTED, item_budget=-5, seconds_budget=-1)
    selected = budget.select_candidates(_issues("a", "b", "c"), lambda row: row["IssueID"])

    assert [row["IssueID"] for row in selected] == ["a", "b", "c"]
    assert budget.remaining() is True


@pytest.fixture
def rss_watchlist(tmp_path, monkeypatch):
    from comicarr import search as legacy_search
    from comicarr.app.acquisition.maintenance import ensure_acquisition_schema

    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            EXTRA_NEWZNABS=[],
            EXTRA_TORZNABS=[],
            ENABLE_DDL=True,
            ENABLE_GETCOMICS=True,
            ENABLE_EXTERNAL_SERVER=False,
            EXPERIMENTAL=False,
            NEWZNAB=False,
            TORZNAB=False,
            ENABLE_TORRENT_SEARCH=False,
            ENABLE_TORRENTS=False,
            ENABLE_PUBLIC=False,
            ENABLE_32P=False,
            ENABLE_TORZNAB=False,
            ANNUALS_ON=False,
            FAILED_DOWNLOAD_HANDLING=False,
            FAILED_AUTO=False,
            SEARCH_STORYARCS=False,
            RSS_CHECKINTERVAL=20,
            WANTED_SEARCH_PASS_ITEMS=250,
            WANTED_SEARCH_PASS_SECONDS=0,
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "SEARCH_TIER_DATE", "2000-01-01")
    search_lock = MagicMock()
    search_lock.locked.return_value = False
    monkeypatch.setattr(comicarr, "SEARCHLOCK", search_lock)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(legacy_search, "provider_order", lambda: [])
    shutdown_engine()
    metadata.create_all(get_engine())
    assert ensure_acquisition_schema(get_engine()).ready
    release_pass()
    rss_lookups = []

    def fake_batched_lookup(*_args, rsslist=None, **_kwargs):
        rss_lookups.append([row[8] for row in rsslist])
        return {"entries": []}

    monkeypatch.setattr(comicarr.rsscheck, "nzbdbsearch", fake_batched_lookup)
    yield SimpleNamespace(search=legacy_search, search_lock=search_lock, rss_lookups=rss_lookups)
    release_pass()
    shutdown_engine()


def _wanted(issue_id, comic_id="160294", release_date="2020-01-01"):
    return issues.insert().values(
        IssueID=issue_id,
        ComicID=comic_id,
        ComicName="Absolute Batman",
        Issue_Number=issue_id,
        Status="Wanted",
        AcquisitionIntent="wanted",
        ReleaseDate=release_date,
        IssueDate=release_date,
        DigitalDate="0000-00-00",
        DateAdded="2000-01-01",
    )


def _seed_watchlist(*rows):
    with get_engine().begin() as conn:
        conn.execute(
            comics.insert().values(
                ComicID="160294",
                ComicName="Absolute Batman",
                ComicName_Filesafe="Absolute_Batman",
                ComicYear="2024",
                ComicPublisher="DC",
                Status="Active",
                Type="Comic",
            )
        )
        for row in rows:
            conn.execute(row)


def _seen_ids():
    with get_engine().connect() as conn:
        return {row.issue_id for row in conn.execute(select(rss_search_seen.c.issue_id))}


def test_rss_scan_skips_when_a_pass_is_running_without_touching_searchlock(rss_watchlist):
    _seed_watchlist(_wanted("1"))
    assert try_acquire_pass() is True

    result = rss_watchlist.search.searchforissue(rsschecker="yes")

    assert result == {"status": "IN PROGRESS"}
    assert rss_watchlist.rss_lookups == []
    rss_watchlist.search_lock.acquire.assert_not_called()


def test_rss_scan_marks_skipped_rows_seen_so_the_cycle_completes(rss_watchlist):
    _seed_watchlist(_wanted("1"), _wanted("orphan", comic_id="missing-series"))
    mark_rssdb_refreshed("gen-1")

    rss_watchlist.search.searchforissue(rsschecker="yes")

    assert rss_watchlist.rss_lookups == [["1"]]
    assert _seen_ids() == {"1", "orphan"}

    rss_watchlist.search.searchforissue(rsschecker="yes")
    assert [ids for ids in rss_watchlist.rss_lookups if ids] == [["1"]]

    mark_rssdb_refreshed("gen-2")
    rss_watchlist.search.searchforissue(rsschecker="yes")
    assert [ids for ids in rss_watchlist.rss_lookups if ids] == [["1"], ["1"]]


def test_rss_scan_resumes_after_the_item_budget(rss_watchlist):
    comicarr.CONFIG.WANTED_SEARCH_PASS_ITEMS = 1
    _seed_watchlist(_wanted("1", release_date="2020-02-01"), _wanted("2", release_date="2020-01-01"))
    mark_rssdb_refreshed("gen-1")

    rss_watchlist.search.searchforissue(rsschecker="yes")
    rss_watchlist.search.searchforissue(rsschecker="yes")

    assert rss_watchlist.rss_lookups == [["1"], ["2"]]


def test_rss_scan_stops_at_the_time_budget(rss_watchlist, monkeypatch):
    clock = {"now": 0.0}

    def ticking_clock():
        clock["now"] += 10
        return clock["now"]

    monkeypatch.setattr(
        rss_watchlist.search,
        "PassBudget",
        lambda kind: PassBudget(kind, item_budget=0, seconds_budget=15, monotonic=ticking_clock),
    )
    _seed_watchlist(_wanted("1", release_date="2020-02-01"), _wanted("2", release_date="2020-01-01"))
    mark_rssdb_refreshed("gen-1")

    rss_watchlist.search.searchforissue(rsschecker="yes")

    assert rss_watchlist.rss_lookups == [["1"]]
    assert _seen_ids() == {"1"}


def test_rss_scan_releases_the_pass_lock_after_an_error(rss_watchlist, monkeypatch):
    def broken_lookup(*_args, **_kwargs):
        raise RuntimeError("rssdb unavailable")

    monkeypatch.setattr(comicarr.rsscheck, "nzbdbsearch", broken_lookup)
    _seed_watchlist(_wanted("1"))

    with pytest.raises(RuntimeError):
        rss_watchlist.search.searchforissue(rsschecker="yes")

    assert try_acquire_pass() is True
    rss_watchlist.search_lock.acquire.assert_not_called()
