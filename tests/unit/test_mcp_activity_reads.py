#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""MCP activity and download reads (#1305)."""

import datetime

import pytest
from sqlalchemy import insert

from comicarr.db import get_engine
from comicarr.tables import acquisition_run_items, activity_events, ddl_info, pipeline_journal, snatched
from tests.mcp_harness import KEY, LEGACY, MODERN, make_app, mcp_client, seed_library, teardown_library

AUTH = "Bearer " + KEY


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _event(subject_type, subject_id, label, created_at, **extra):
    return {
        "created_at": created_at,
        "activity": "search",
        "status": "no_match",
        "subject_type": subject_type,
        "subject_id": subject_id,
        "subject_label": label,
        **extra,
    }


def _insert(conn, table, rows):
    # One row at a time: the rows carry different columns.
    for row in rows:
        conn.execute(insert(table).values(**row))


def seed_activity():
    """Activity for Saga and Dandadan, a stuck run item, a moving grab, one failed
    download in Needs attention, two history rows and a direct-download queue."""
    with get_engine().begin() as conn:
        _insert(
            conn,
            activity_events,
            [
                _event("issue", "5001", "Saga #66", "2026-11-14T09:00:00+00:00", parent_series_id="1001"),
                _event("series", "1001", "Saga", "2026-11-14T10:00:00+00:00", activity="series", status="started"),
                _event("issue", "md-1", "Dandadan #1", "2026-11-14T11:00:00+00:00", parent_series_id="md-abc"),
                _event(
                    "annual",
                    "6001",
                    "Saga Annual #1",
                    "2026-11-14T12:00:00+00:00",
                    parent_series_id="1001",
                    actor="mcp",
                ),
            ],
        )
        _insert(
            conn,
            acquisition_run_items,
            [
                {
                    "run_id": "run-7",
                    "command_kind": "search_issue",
                    "entity_type": "issue",
                    "entity_id": "5001",
                    "state": "accepted",
                    "dispatch_state": "pending",
                    "queue_priority": "routine",
                    "attempt_count": 0,
                    "created_at": "2020-01-01T00:00:00+00:00",
                    "updated_at": "2020-01-01T00:00:00+00:00",
                }
            ],
        )
        _insert(
            conn,
            pipeline_journal,
            [
                {
                    "release_key": "rk-moving",
                    "issueid": "5002",
                    "provider": "SABnzbd",
                    "stage": "snatched",
                    "stage_rank": 20,
                    "updated_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
                {
                    "release_key": "rk-failed",
                    "issueid": "5001",
                    "provider": "DDL",
                    "stage": "failed",
                    "stage_rank": 60,
                    "updated_date": "2026-11-14 08:00:00",
                    "fail_reason": "download_failed",
                    "payload_json": '{"comicid": "1001", "comicname": "Saga", "issuenumber": "66"}',
                },
            ],
        )
        _insert(
            conn,
            snatched,
            [
                {
                    "IssueID": "5002",
                    "ComicID": "1001",
                    "ComicName": "Saga",
                    "Issue_Number": "65",
                    "Size": 41_000_000,
                    "DateAdded": "2026-11-13 08:00:00",
                    "Status": "Post-Processed",
                    "Provider": "SABnzbd",
                    "FolderName": "/downloads/complete/Saga.065",
                    "Hash": "deadbeef",
                },
                {
                    "IssueID": "5001",
                    "ComicID": "1001",
                    "ComicName": "Saga",
                    "Issue_Number": "66",
                    "DateAdded": "2026-11-14 08:00:00",
                    "Status": "Failed",
                    "Provider": "DDL",
                },
            ],
        )
        _insert(
            conn,
            ddl_info,
            [
                {
                    "ID": "ddl-1",
                    "series": "Saga",
                    "year": "2012",
                    "filename": "Saga 066 (2026).cbz",
                    "issueid": "5001",
                    "comicid": "1001",
                    "link": "https://files.example/secret-token",
                    "status": "Queued",
                    "site": "GetComics",
                    "submit_date": "2026-11-14 08:00:00",
                    "updated_date": "2026-11-14 08:00:00",
                },
                {
                    "ID": "ddl-2",
                    "series": "Paper Girls",
                    "filename": "Paper Girls v01.cbz",
                    "status": "Downloading",
                    "site": "GetComics",
                    "pack": 1,
                    "updated_date": "2026-11-14 09:00:00",
                },
                {"ID": "ddl-3", "series": "Wired", "status": "Completed", "updated_date": "2026-11-14 07:00:00"},
            ],
        )


@pytest.fixture(autouse=True)
def _library(tmp_path, monkeypatch):
    seed_library(tmp_path, monkeypatch)
    seed_activity()
    yield
    teardown_library()


async def _call(name, arguments):
    async with mcp_client(make_app(), Authorization=AUTH) as mcp:
        return await mcp.call_tool(name, arguments)


@pytest.mark.asyncio
async def test_list_activity_is_newest_first_and_pages():
    page = (await _call("list_activity", {"limit": 3})).structured_content
    assert [e["subject_id"] for e in page["events"]] == ["6001", "md-1", "1001"]
    assert (page["total"], page["next_offset"]) == (4, 3)
    assert page["events"][0]["actor"] == "mcp"
    assert page["events"][2]["series_id"] == "1001"


@pytest.mark.asyncio
async def test_list_activity_scoped_to_a_series_returns_only_that_series():
    page = (await _call("list_activity", {"series_id": "1001"})).structured_content
    assert sorted(e["subject_id"] for e in page["events"]) == ["1001", "5001", "6001"]
    assert {e["series_id"] for e in page["events"]} == {"1001"}


@pytest.mark.asyncio
async def test_list_activity_scoped_to_an_annual_finds_its_events():
    page = (await _call("list_activity", {"issue_id": "6001"})).structured_content
    assert [(e["subject_type"], e["subject_id"]) for e in page["events"]] == [("annual", "6001")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments, code",
    [
        ({"series_id": "nope"}, "not_found"),
        ({"issue_id": "nope"}, "not_found"),
        ({"series_id": "1001", "issue_id": "5001"}, "invalid_argument"),
    ],
)
async def test_list_activity_rejects_a_bad_scope(arguments, code):
    result = await _call("list_activity", arguments)
    assert result.is_error and result.structured_content["code"] == code


@pytest.mark.asyncio
async def test_list_in_flight_carries_the_ids_a_cancel_needs_and_flags_stuck_work():
    page = (await _call("list_in_flight", {})).structured_content
    assert (page["total"], page["stuck"]) == (2, 1)
    by_kind = {item["kind"]: item for item in page["items"]}
    run = by_kind["run"]
    assert (run["run_id"], run["issue_id"], run["state"], run["stuck"]) == ("run-7", "5001", "accepted", True)
    assert isinstance(run["item_id"], str) and run["item_id"]
    journal = by_kind["journal"]
    assert (journal["release_key"], journal["state"], journal["stuck"]) == ("rk-moving", "snatched", False)

    stuck = (await _call("list_in_flight", {"stuck_only": True})).structured_content
    assert [item["run_id"] for item in stuck["items"]] == ["run-7"]


@pytest.mark.asyncio
async def test_list_attention_groups_problems_with_their_release_keys():
    page = (await _call("list_attention", {})).structured_content
    assert (page["total"], page["items_total"]) == (1, 1)
    problem = page["problems"][0]
    assert (problem["series_id"], problem["reason_code"], problem["count"]) == ("1001", "download_failed", 1)
    assert [(i["release_key"], i["issue_id"]) for i in problem["items"]] == [("rk-failed", "5001")]
    assert problem["actions"]

    elsewhere = (await _call("list_attention", {"series_id": "md-abc"})).structured_content
    assert (elsewhere["total"], elsewhere["problems"]) == (0, [])


@pytest.mark.asyncio
async def test_list_download_history_filters_and_hides_folders_and_hashes():
    page = (await _call("list_download_history", {})).structured_content
    assert [(d["issue_number"], d["status"]) for d in page["downloads"]] == [("66", "Failed"), ("65", "Post-Processed")]
    assert page["downloads"][1]["size_bytes"] == 41_000_000
    rendered = str(page)
    assert "/downloads/complete" not in rendered and "deadbeef" not in rendered

    failed = (await _call("list_download_history", {"status": "Failed"})).structured_content
    assert [d["issue_id"] for d in failed["downloads"]] == ["5001"]


@pytest.mark.asyncio
async def test_list_download_queue_shows_active_items_without_links():
    page = (await _call("list_download_queue", {})).structured_content
    assert sorted(d["queue_id"] for d in page["downloads"]) == ["ddl-1", "ddl-2"]
    assert page["total"] == 2
    assert "secret-token" not in str(page)

    downloading = (await _call("list_download_queue", {"status": "Downloading"})).structured_content
    assert [(d["queue_id"], d["pack"]) for d in downloading["downloads"]] == [("ddl-2", True)]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, version", [("legacy", LEGACY), (MODERN, MODERN)], ids=[LEGACY, MODERN])
async def test_each_tool_reads_seeded_rows_in_each_protocol_era(mode, version):
    expected = {
        "list_activity": ("events", 4),
        "list_in_flight": ("items", 2),
        "list_attention": ("problems", 1),
        "list_download_history": ("downloads", 2),
        "list_download_queue": ("downloads", 2),
    }
    async with mcp_client(make_app(), mode=mode, Authorization=AUTH) as mcp:
        assert mcp.session.protocol_version == version
        for name, (key, count) in expected.items():
            result = await mcp.call_tool(name, {})
            assert not result.is_error, (name, result.content)
            assert len(result.structured_content[key]) == count, (name, result.structured_content)
