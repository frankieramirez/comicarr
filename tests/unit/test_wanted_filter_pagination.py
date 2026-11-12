#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Wanted queue search must filter before pagination (#408).

A client-side filter over the current page only reports page-local match
counts while the footer still describes the unfiltered queue. These pins
force the server query to apply ``search`` before limit/offset so totals,
has_more, and returned rows all describe the same filtered set.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.app.series import queries as series_queries
from comicarr.app.series import router as series_router
from comicarr.app.series import service as series_service
from comicarr.tables import comics, issues, metadata


@pytest.fixture
def wanted_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _seed_multi_page_wanted(engine):
    """53 Wanted rows: 12 match 'Saga' — 9 on the first page of 50, 3 beyond."""
    with engine.begin() as conn:
        conn.execute(
            insert(comics),
            [
                {
                    "ComicID": "comic-filler",
                    "ComicName": "Alpha Filler",
                    "ComicSortName": "Alpha Filler",
                    "ComicPublisher": "Image",
                    "Status": "Active",
                    "Have": 0,
                    "Total": 41,
                    "ContentType": "comic",
                },
                {
                    "ComicID": "comic-saga",
                    "ComicName": "Saga",
                    "ComicSortName": "Saga",
                    "ComicPublisher": "Image",
                    "Status": "Active",
                    "Have": 0,
                    "Total": 12,
                    "ContentType": "comic",
                },
            ],
        )
        issue_rows = []
        # First 41 of page 1 are non-matches.
        for i in range(1, 42):
            issue_rows.append(
                {
                    "IssueID": f"filler-{i}",
                    "ComicID": "comic-filler",
                    "Issue_Number": str(i),
                    "Status": "Wanted",
                    "DateAdded": f"2026-01-{i:02d}",
                }
            )
        # Next 9 of page 1 match "Saga".
        for i in range(1, 10):
            issue_rows.append(
                {
                    "IssueID": f"saga-{i}",
                    "ComicID": "comic-saga",
                    "Issue_Number": str(i),
                    "Status": "Wanted",
                    "DateAdded": f"2026-02-{i:02d}",
                }
            )
        # Page 2 has 3 more Saga matches (issues 10–12).
        for i in range(10, 13):
            issue_rows.append(
                {
                    "IssueID": f"saga-{i}",
                    "ComicID": "comic-saga",
                    "Issue_Number": str(i),
                    "Status": "Wanted",
                    "DateAdded": f"2026-03-{i:02d}",
                }
            )
        conn.execute(insert(issues), issue_rows)


def test_wanted_search_filters_before_pagination_across_pages(wanted_db):
    _seed_multi_page_wanted(wanted_db)

    unfiltered = series_queries.get_wanted_issues(limit=50, offset=0)
    assert unfiltered["total"] == 53
    assert unfiltered["has_more"] is True
    assert len(unfiltered["results"]) == 50

    # Without search the first page only has 9 Saga rows — the page-local
    # filter that caused #408 would report 9 matches and keep Next enabled
    # against an unfiltered total of 53.
    page_local_matches = [
        row
        for row in unfiltered["results"]
        if "saga" in (row.get("ComicName") or "").lower() or "saga" in (row.get("Issue_Number") or "").lower()
    ]
    assert len(page_local_matches) == 9

    page1 = series_queries.get_wanted_issues(limit=50, offset=0, search="Saga")
    assert page1["total"] == 12
    assert page1["has_more"] is False
    assert len(page1["results"]) == 12
    assert all(row["ComicName"] == "Saga" for row in page1["results"])
    assert {row["IssueID"] for row in page1["results"]} == {f"saga-{i}" for i in range(1, 13)}

    # Filtered set is smaller than one page, so a second page is empty and
    # does not invent more of the unfiltered queue.
    page2 = series_queries.get_wanted_issues(limit=50, offset=50, search="Saga")
    assert page2["total"] == 12
    assert page2["has_more"] is False
    assert page2["results"] == []

    # Clearing search restores the unfiltered multi-page queue.
    restored = series_queries.get_wanted_issues(limit=50, offset=0, search="")
    assert restored["total"] == 53
    assert restored["has_more"] is True


def test_wanted_search_matches_issue_number_and_is_case_insensitive(wanted_db):
    _seed_multi_page_wanted(wanted_db)

    by_number = series_queries.get_wanted_issues(limit=10, offset=0, search="12")
    assert by_number["total"] == 2  # filler-12 and saga-12
    assert {row["IssueID"] for row in by_number["results"]} == {
        "filler-12",
        "saga-12",
    }

    lower = series_queries.get_wanted_issues(limit=50, offset=0, search="saga")
    assert lower["total"] == 12


def test_get_wanted_service_forwards_search(monkeypatch):
    captured = {}

    def fake_get_wanted_issues(**kwargs):
        captured.update(kwargs)
        return {
            "results": [{"IssueID": "1", "ComicName": "Saga"}],
            "total": 1,
            "limit": 50,
            "offset": 0,
            "has_more": False,
        }

    monkeypatch.setattr(series_service.series_queries, "get_wanted_issues", fake_get_wanted_issues)
    monkeypatch.setattr(
        series_service.series_queries,
        "get_latest_search_items_by_entity_ids",
        lambda entity_ids: {},
    )
    result = series_service.get_wanted(SimpleNamespace(config=None), limit=50, offset=0, search="Saga")
    assert captured == {"limit": 50, "offset": 0, "search": "Saga", "comic_id": None}
    assert result["pagination"]["total"] == 1
    assert result["issues"][0]["IssueID"] == "1"
    assert result["issues"][0]["acquisition"] is None


def test_wanted_route_forwards_q_as_search(monkeypatch):
    spy = MagicMock(return_value={"issues": [], "pagination": {}})
    monkeypatch.setattr(series_router.series_service, "get_wanted", spy)
    ctx = SimpleNamespace()

    series_router.get_wanted(limit=50, offset=0, q="flash", story_arcs=False, comic_id=None, ctx=ctx)

    spy.assert_called_once_with(
        ctx,
        limit=50,
        offset=0,
        include_story_arcs=False,
        search="flash",
        comic_id=None,
    )
