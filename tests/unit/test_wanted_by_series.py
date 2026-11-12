#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Wanted folded by series (v2 Wanted page).

One row per series: how many issues are missing, which ones, and why. The
tabs' counts describe the whole filtered set, and pagination counts series.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.app.series import wanted_groups
from comicarr.tables import acquisition_run_items, comics, issues, metadata


def test_which_label_collapses_runs_and_folds_the_tail():
    assert wanted_groups.which_label(["23", "24"]) == "#23-24"
    assert wanted_groups.which_label([str(n) for n in range(1, 250)]) == "#1-249"
    assert wanted_groups.which_label(["5"]) == "#5"
    assert wanted_groups.which_label(["1", "2", "12.1", "AU"]) == "#1-2, #12.1, #AU"
    numbers = [str(n) for n in range(201, 263)] + [str(n) for n in range(321, 366)] + ["400", "402"] + ["500", "501"]
    # Three segments shown, the remaining four issues folded.
    assert wanted_groups.which_label(numbers) == "#201-262, #321-365, #400, +3"


def test_bucket_of_reads_the_latest_search_state():
    assert wanted_groups.bucket_of(None) == "queued"
    assert wanted_groups.bucket_of({"state": "running"}) == "searching"
    assert wanted_groups.bucket_of({"state": "no_match"}) == "not_found"
    assert wanted_groups.bucket_of({"state": "succeeded"}) == "queued"


def _row(comic, number, state=None, attempts=1, updated="2026-11-12T06:00:00+00:00", **extra):
    row = {
        "ComicID": comic,
        "ComicName": comic.title(),
        "Issue_Number": number,
        "ContentType": "comic",
        "acquisition": None if state is None else {"state": state, "attempt_count": attempts, "updated_at": updated},
    }
    row.update(extra)
    return row


def test_group_wanted_counts_every_bucket_and_filters_series_by_state():
    rows = [
        _row("superman", "23", "no_match", attempts=3),
        _row("superman", "24", "no_match", attempts=1),
        _row("akira", "1"),
        _row("akira", "2"),
        _row("akira", "3", "running"),
        _row("md-blame", "1", ContentType="manga"),
    ]

    grouped = wanted_groups.group_wanted(rows)
    assert grouped["counts"] == {"all": 6, "not_found": 2, "searching": 1, "queued": 3}
    superman, akira, blame = grouped["series"]
    assert (superman["comicid"], superman["why"], superman["which"]) == ("superman", "not_found", "#23-24")
    assert superman["max_attempts"] == 3
    assert (akira["missing"], akira["why"], akira["which"]) == (3, "searching", "#1-3")
    assert blame["kind"] == "manga"

    only_not_found = wanted_groups.group_wanted(rows, state="not_found")
    assert [g["comicid"] for g in only_not_found["series"]] == ["superman"]
    # Tab counts never change with the selected tab.
    assert only_not_found["counts"] == grouped["counts"]

    manga = wanted_groups.group_wanted(rows, kind="manga")
    assert [g["comicid"] for g in manga["series"]] == ["md-blame"]
    assert manga["counts"]["all"] == 1

    by_name = wanted_groups.group_wanted(rows, sort="name")
    assert [g["comicid"] for g in by_name["series"]] == ["akira", "md-blame", "superman"]


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


def test_wanted_series_endpoint_paginates_series_and_expands_one(wanted_db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from comicarr.app.core.context import AppContext, get_context
    from comicarr.app.core.security import require_session
    from comicarr.app.series.router import router

    with wanted_db.begin() as conn:
        conn.execute(
            insert(comics),
            [
                {"ComicID": cid, "ComicName": name, "ComicSortName": name, "Status": "Active", "ContentType": "comic"}
                for cid, name in [("c1", "Saga"), ("c2", "Monstress"), ("c3", "Paper Girls")]
            ],
        )
        conn.execute(
            insert(issues),
            [
                {"IssueID": "c1-%d" % n, "ComicID": "c1", "Issue_Number": str(n), "Status": "Wanted"}
                for n in range(1, 4)
            ]
            + [{"IssueID": "c2-1", "ComicID": "c2", "Issue_Number": "1", "Status": "Wanted"}]
            + [{"IssueID": "c3-1", "ComicID": "c3", "Issue_Number": "1", "Status": "Wanted"}]
            + [{"IssueID": "c3-2", "ComicID": "c3", "Issue_Number": "2", "Status": "Downloaded"}],
        )
        conn.execute(
            insert(acquisition_run_items),
            [
                {
                    "run_id": "run-1",
                    "command_kind": "search",
                    "entity_type": "issue",
                    "entity_id": "c2-1",
                    "state": "no_match",
                    "attempt_count": 2,
                    "created_at": "2026-11-12T05:00:00+00:00",
                    "updated_at": "2026-11-12T06:00:00+00:00",
                }
            ],
        )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "operator"
    app.dependency_overrides[get_context] = lambda: AppContext(config=SimpleNamespace())

    with TestClient(app) as client:
        body = client.get("/api/wanted/series", params={"limit": 2}).json()
        assert body["counts"] == {"all": 5, "not_found": 1, "searching": 0, "queued": 4}
        assert body["pagination"] == {"total": 3, "limit": 2, "offset": 0, "has_more": True}
        # Problems first: Monstress has the not-found issue.
        assert [s["comic_name"] for s in body["series"]] == ["Monstress", "Saga"]
        assert body["series"][0]["max_attempts"] == 2
        assert body["series"][1]["which"] == "#1-3"

        expanded = client.get("/api/wanted", params={"comic_id": "c1", "limit": 50}).json()
        assert sorted(i["IssueID"] for i in expanded["issues"]) == ["c1-1", "c1-2", "c1-3"]

        assert client.get("/api/wanted/series", params={"state": "bogus"}).status_code == 422
