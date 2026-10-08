#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Upcoming projection follows issues.Status after queue/unqueue."""

from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.app.series import queries as series_queries
from comicarr.app.storyarcs import queries as arc_queries
from comicarr.tables import annuals, comics, issues, metadata, weekly


@pytest.fixture
def upcoming_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _seed_week(engine):
    with engine.begin() as conn:
        conn.execute(
            insert(comics),
            [
                {
                    "ComicID": "c-wanted",
                    "ComicName": "Wanted Book",
                    "ComicSortName": "Wanted Book",
                },
                {
                    "ComicID": "c-pull",
                    "ComicName": "Pull List Only",
                    "ComicSortName": "Pull List Only",
                },
            ],
        )
        conn.execute(
            insert(issues),
            [
                {
                    "IssueID": "iss-wanted",
                    "ComicID": "c-wanted",
                    "Status": "Wanted",
                }
            ],
        )
        conn.execute(
            insert(weekly),
            [
                {
                    "COMIC": "Wanted Book",
                    "ISSUE": "1",
                    "ComicID": "c-wanted",
                    "IssueID": "iss-wanted",
                    "STATUS": "Wanted",
                    "weeknumber": "27",
                    "year": "2026",
                    "SHIPDATE": "2026-07-08",
                },
                {
                    "COMIC": "Pull List Only",
                    "ISSUE": "2",
                    "ComicID": "c-pull",
                    "IssueID": "iss-missing",
                    "STATUS": "Wanted",
                    "weeknumber": "27",
                    "year": "2026",
                    "SHIPDATE": "2026-07-08",
                },
            ],
        )


def test_unqueue_drops_issue_from_wanted_upcoming(upcoming_db):
    _seed_week(upcoming_db)

    rows = arc_queries.get_upcoming("27", "2026")
    assert {row["IssueID"] for row in rows} == {"iss-wanted", "iss-missing"}
    assert {row["Status"] for row in rows} == {"Wanted"}

    series_queries.unqueue_issue("iss-wanted", "frankie")

    rows = arc_queries.get_upcoming("27", "2026")
    assert [row["IssueID"] for row in rows] == ["iss-missing"]
    assert rows[0]["Status"] == "Wanted"


def test_upcoming_keeps_skipped_issue_out_of_include_downloaded(upcoming_db):
    _seed_week(upcoming_db)
    series_queries.unqueue_issue("iss-wanted", "frankie")

    rows = arc_queries.get_upcoming("27", "2026", include_downloaded=True)
    assert "iss-wanted" not in {row["IssueID"] for row in rows}


def _seed_annual_week(engine):
    with engine.begin() as conn:
        conn.execute(
            insert(comics).values(
                ComicID="c-annual",
                ComicName="Wanted Annual",
                ComicSortName="Wanted Annual",
            )
        )
        conn.execute(
            insert(annuals).values(
                IssueID="ann-wanted",
                ComicID="c-annual",
                Status="Wanted",
                Deleted=0,
            )
        )
        conn.execute(
            insert(weekly).values(
                COMIC="Wanted Annual",
                ISSUE="1",
                ComicID="c-annual",
                IssueID="ann-wanted",
                STATUS="Wanted",
                weeknumber="27",
                year="2026",
                SHIPDATE="2026-07-08",
            )
        )


def test_unqueue_annual_writes_annuals_and_drops_from_wanted_upcoming(upcoming_db):
    _seed_annual_week(upcoming_db)

    rows = arc_queries.get_upcoming("27", "2026")
    assert {row["IssueID"] for row in rows} == {"ann-wanted"}

    series_queries.unqueue_issue("ann-wanted", "frankie")

    rows = arc_queries.get_upcoming("27", "2026")
    assert [row["IssueID"] for row in rows] == []
    with upcoming_db.connect() as conn:
        annual = conn.execute(annuals.select().where(annuals.c.IssueID == "ann-wanted")).one()._mapping
        stray = conn.execute(issues.select().where(issues.c.IssueID == "ann-wanted")).first()
    assert annual["Status"] == "Skipped"
    assert stray is None


def test_upcoming_does_not_treat_stray_issues_skip_as_annual_skip(upcoming_db):
    """A leftover issues.Skipped row must not hide an annual that is still Wanted."""
    _seed_annual_week(upcoming_db)
    with upcoming_db.begin() as conn:
        conn.execute(
            insert(issues).values(
                IssueID="ann-wanted",
                ComicID="c-annual",
                Status="Skipped",
            )
        )

    rows = arc_queries.get_upcoming("27", "2026")
    assert {row["IssueID"] for row in rows} == {"ann-wanted"}
    assert rows[0]["Status"] == "Wanted"
