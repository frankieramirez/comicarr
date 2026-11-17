#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""MCP library reads: get_series, list_issues, list_wanted, get_issue_story (#1304)."""

import pytest

from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.core.db import get_engine
from comicarr.app.core.tables import activity_events, annuals, issues
from comicarr.app.search import search_history
from tests.mcp_harness import KEY, make_app, mcp_client, seed_library, teardown_library

AUTH = {"Authorization": "Bearer " + KEY}

EXTRA_ISSUES = [
    {
        "IssueID": "5003",
        "ComicID": "1001",
        "ComicName": "Saga",
        "Issue_Number": "64",
        "Int_IssueNumber": 64000,
        "Status": "Wanted",
        "AcquisitionIntent": "wanted",
        "ReleaseDate": "2023-01-11",
    },
    {
        "IssueID": "5004",
        "ComicID": "1001",
        "ComicName": "Saga",
        "Issue_Number": "67",
        "Int_IssueNumber": 67000,
        "Status": "Skipped",
        "AcquisitionIntent": "skipped",
        "ReleaseDate": "2999-06-01",
    },
    {
        "IssueID": "7001",
        "ComicID": "md-abc",
        "ComicName": "Dandadan",
        "Issue_Number": "1",
        "Int_IssueNumber": 1000,
        "Status": "Wanted",
        "AcquisitionIntent": "wanted",
        "ReleaseDate": "2021-04-05",
    },
]


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
    engine = get_engine()
    assert ensure_acquisition_schema(engine).ready
    with engine.begin() as conn:
        for row in EXTRA_ISSUES:
            conn.execute(issues.insert().values(**row))
        conn.execute(
            issues.update().where(issues.c.IssueID == "5002").values(ReleaseDate="2023-02-08", Int_IssueNumber=65000)
        )
        conn.execute(issues.update().where(issues.c.IssueID == "5001").values(Int_IssueNumber=66000))
    yield
    teardown_library()


async def _call(name, arguments):
    async with mcp_client(make_app(), Authorization=AUTH["Authorization"]) as mcp:
        return await mcp.call_tool(name, arguments)


@pytest.mark.asyncio
async def test_get_series_reports_counts_providers_and_the_last_and_next_issue():
    result = await _call("get_series", {"series_id": "1001"})
    assert not result.is_error, result.content
    out = result.structured_content
    assert (out["name"], out["kind"], out["status"], out["have"], out["total"]) == ("Saga", "comic", "Active", 60, 66)
    assert out["counts"]["issues"] == 4
    assert out["counts"]["wanted"] == 1, out["counts"]
    assert out["counts"]["skipped"] == 1
    assert out["last_issue"] == {"issue_id": "5002", "number": "65", "release_date": "2023-02-08"}
    assert out["next_issue"] == {"issue_id": "5004", "number": "67", "release_date": "2999-06-01"}
    assert [link["provider"] for link in out["providers"]] == ["comicvine"]


@pytest.mark.asyncio
async def test_list_issues_pages_and_filters_by_state():
    first = (await _call("list_issues", {"series_id": "1001", "limit": 2})).structured_content
    assert [i["issue_id"] for i in first["issues"]] == ["5004", "5002"]  # newest first
    assert (first["total"], first["next_offset"]) == (4, 2)
    last = (await _call("list_issues", {"series_id": "1001", "limit": 2, "offset": 2})).structured_content
    assert [i["issue_id"] for i in last["issues"]] == ["5003", "5001"]
    assert last["next_offset"] is None

    wanted = (await _call("list_issues", {"series_id": "1001", "state": "Wanted"})).structured_content
    assert [(i["issue_id"], i["state"], i["eligible"]) for i in wanted["issues"]] == [("5003", "Wanted", True)]
    assert wanted["total"] == 1


@pytest.mark.asyncio
async def test_list_issues_orders_annuals_among_issues_by_release_date():
    with get_engine().begin() as conn:
        conn.execute(annuals.update().where(annuals.c.IssueID == "6001").values(ReleaseDate="2023-02-01"))
    app = make_app()
    app.state.ctx.config.ANNUALS_ON = True
    async with mcp_client(app, Authorization=AUTH["Authorization"]) as mcp:
        page = (await mcp.call_tool("list_issues", {"series_id": "1001"})).structured_content
    assert [(i["issue_id"], i["entity_type"]) for i in page["issues"]] == [
        ("5004", "issue"),
        ("5002", "issue"),
        ("6001", "annual"),
        ("5003", "issue"),
        ("5001", "issue"),
    ]


@pytest.mark.asyncio
async def test_list_wanted_by_issue_and_by_series():
    every = (await _call("list_wanted", {})).structured_content
    assert sorted(i["issue_id"] for i in every["issues"]) == ["5003", "7001"]
    assert every["series"] == [] and every["total"] == 2
    assert all(i["last_search"] is None for i in every["issues"])

    one = (await _call("list_wanted", {"series_id": "md-abc"})).structured_content
    assert [(i["issue_id"], i["series_name"]) for i in one["issues"]] == [("7001", "Dandadan")]

    grouped = (await _call("list_wanted", {"group_by": "series", "limit": 1})).structured_content
    assert grouped["issues"] == [] and grouped["total"] == 2 and grouped["next_offset"] == 1
    assert grouped["series"][0]["missing"] == 1 and grouped["series"][0]["queued"] == 1


@pytest.mark.asyncio
async def test_list_wanted_rejects_a_series_filter_on_grouped_results():
    result = await _call("list_wanted", {"group_by": "series", "series_id": "1001"})
    assert result.is_error and result.structured_content["code"] == "invalid_argument"


@pytest.mark.asyncio
async def test_get_issue_story_explains_the_last_search_without_log_lines():
    search_history.record(
        "5003",
        [
            {
                "candidate": {"title": "Saga 064 (2023)", "provider": "indexer-a", "size_bytes": 40_000_000},
                "verdict": {"status": "accepted"},
            },
            {
                "candidate": {"title": "Saga 063 (2023)", "provider": "indexer-a"},
                "verdict": {"status": "rejected", "reason_code": "rejected.issue_mismatch"},
            },
        ],
        searched_at="2026-11-14T10:00:00+00:00",
    )
    with get_engine().begin() as conn:
        conn.execute(
            activity_events.insert().values(
                created_at="2026-11-14T10:00:00+00:00",
                activity="search",
                status="no_match",
                subject_type="issue",
                subject_id="5003",
                subject_label="Saga #64",
            )
        )
    result = await _call("get_issue_story", {"issue_id": "5003"})
    assert not result.is_error, result.content
    story = result.structured_content
    assert (story["series_id"], story["series_name"], story["number"], story["state"]) == (
        "1001",
        "Saga",
        "64",
        "Wanted",
    )
    assert story["attempts"] == {"search": 1, "grab": 0, "download": 0, "imported": 0}
    last = story["last_search"]
    assert (last["results"], last["accepted"], last["rejected"]) == (2, 1, 1)
    assert last["reasons"] == [{"code": "rejected.issue_mismatch", "label": "wrong issue", "count": 1}]
    assert [c["title"] for c in last["candidates"]] == ["Saga 064 (2023)"]
    assert "log" not in story


@pytest.mark.asyncio
async def test_get_issue_story_reads_an_annual():
    story = (await _call("get_issue_story", {"issue_id": "6001"})).structured_content
    assert (story["entity_type"], story["series_name"], story["last_search"]) == ("annual", "Saga", None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name, arguments",
    [
        ("get_series", {"series_id": "nope"}),
        ("list_issues", {"series_id": "nope"}),
        ("get_issue_story", {"issue_id": "nope"}),
    ],
)
async def test_an_unknown_id_is_not_found(name, arguments):
    result = await _call(name, arguments)
    assert result.is_error and result.structured_content["code"] == "not_found"
