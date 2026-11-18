#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Series API surfaces LastUpdated/Description so the sync badge can be truthful."""

from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr.app.core import db, runtime
from comicarr.app.core.tables import comics, issues, metadata
from comicarr.app.series import queries as series_queries
from comicarr.app.series import service as series_service


@pytest.fixture
def query_db(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "data_dir", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _seed(engine):
    with engine.begin() as conn:
        conn.execute(
            insert(comics),
            [
                {
                    "ComicID": "md-synced",
                    "ComicName": "One Piece",
                    "ComicSortName": "One Piece",
                    "Status": "Active",
                    "ContentType": "manga",
                    "LatestDate": "Unknown",
                    "LastUpdated": "2026-08-16 12:00:00",
                    "Description": "Pirates hunt the One Piece.",
                },
                {
                    "ComicID": "mal-unsynced",
                    "ComicName": "Akira",
                    "ComicSortName": "Akira",
                    "Status": "Active",
                    "ContentType": "manga",
                    "LatestDate": None,
                    "LastUpdated": None,
                    "Description": None,
                },
            ],
        )


def test_series_detail_returns_refresh_timestamp_and_description(query_db):
    _seed(query_db)
    ctx = SimpleNamespace(config=SimpleNamespace(ANNUALS_ON=False))

    synced = series_service.get_comic_detail(ctx, "md-synced")["comic"][0]
    assert synced["LastUpdated"] == "2026-08-16 12:00:00"
    assert synced["LatestDate"] == "Unknown"
    assert synced["Description"] == "Pirates hunt the One Piece."

    unsynced = series_service.get_comic_detail(ctx, "mal-unsynced")["comic"][0]
    assert unsynced["LastUpdated"] is None
    assert unsynced["Description"] is None


def test_series_list_includes_the_same_sync_fields(query_db):
    _seed(query_db)
    ctx = SimpleNamespace(config=SimpleNamespace())

    by_id = {row["ComicID"]: row for row in series_service.list_comics(ctx)}
    assert by_id["md-synced"]["LastUpdated"] == "2026-08-16 12:00:00"
    assert by_id["md-synced"]["Description"] == "Pirates hunt the One Piece."
    assert by_id["mal-unsynced"]["LastUpdated"] is None
    # The dashboard's "Recently added" sorts on this; without it the panel
    # always said "No series yet".
    assert all("DateAdded" in row for row in by_id.values())


def test_query_projection_does_not_confuse_latest_release_with_last_refresh(query_db):
    _seed(query_db)
    row = series_queries.get_comic("md-synced")[0]
    assert row["LatestDate"] == "Unknown"
    assert row["LastUpdated"] == "2026-08-16 12:00:00"
    assert row["LatestDate"] != row["LastUpdated"]


def test_series_list_counts_wanted_the_way_the_wanted_page_does(query_db):
    _seed(query_db)
    with query_db.begin() as conn:
        conn.execute(
            insert(issues),
            [
                {"IssueID": "w1", "ComicID": "md-synced", "Issue_Number": "1", "Status": "Wanted"},
                {"IssueID": "w2", "ComicID": "md-synced", "Issue_Number": "2", "Status": "Wanted"},
                {"IssueID": "s1", "ComicID": "md-synced", "Issue_Number": "3", "Status": "Skipped"},
                {"IssueID": "d1", "ComicID": "md-synced", "Issue_Number": "4", "Status": "Downloaded"},
            ],
        )
    ctx = SimpleNamespace(config=SimpleNamespace())

    by_id = {row["ComicID"]: row for row in series_service.list_comics(ctx)}
    # Most wanted reads this, so a Skipped issue never counts.
    assert by_id["md-synced"]["Wanted"] == 2
    assert by_id["mal-unsynced"]["Wanted"] == 0
    paged = {row["ComicID"]: row for row in series_queries.list_comics_paginated(10)["results"]}
    assert paged["md-synced"]["Wanted"] == 2
