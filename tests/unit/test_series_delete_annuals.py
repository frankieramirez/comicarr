#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Deleting a series must remove its annuals; leftover orphans are countable."""

import pytest
from sqlalchemy import func, select

from comicarr import db
from comicarr.app.series import queries as series_queries
from comicarr.search import searchforissue_checker
from comicarr.tables import annuals, comics, issues, metadata, storyarcs, upcoming


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    import comicarr as comicarr_mod

    monkeypatch.setattr(comicarr_mod, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr_mod, "CONFIG", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    metadata.create_all(db.get_engine())
    yield
    db.shutdown_engine()


def _seed_series_with_annual(comic_id="C", annual_id="A"):
    with db.get_engine().begin() as conn:
        conn.execute(
            comics.insert().values(
                ComicID=comic_id,
                ComicName="Test Series",
                ComicYear="2024",
                Status="Active",
            )
        )
        conn.execute(
            issues.insert().values(
                IssueID="I1",
                ComicID=comic_id,
                ComicName="Test Series",
                Issue_Number="1",
                Status="Downloaded",
            )
        )
        conn.execute(
            annuals.insert().values(
                IssueID=annual_id,
                ComicID=comic_id,
                ReleaseComicName="Test Series",
                Issue_Number="Annual 1",
                Status="Wanted",
                ReleaseDate="2020-01-01",
                Deleted=None,
            )
        )
        conn.execute(
            upcoming.insert().values(
                ComicID=comic_id,
                IssueID="U1",
                IssueNumber="2",
            )
        )


def test_delete_comic_removes_annuals_for_that_series():
    _seed_series_with_annual()

    series_queries.delete_comic("C")

    engine = db.get_engine()
    with engine.connect() as conn:
        annual_count = conn.execute(select(func.count()).select_from(annuals).where(annuals.c.ComicID == "C")).scalar()
        issue_count = conn.execute(select(func.count()).select_from(issues).where(issues.c.ComicID == "C")).scalar()
        upcoming_count = conn.execute(
            select(func.count()).select_from(upcoming).where(upcoming.c.ComicID == "C")
        ).scalar()
        comic_count = conn.execute(select(func.count()).select_from(comics).where(comics.c.ComicID == "C")).scalar()

    assert annual_count == 0
    assert issue_count == 0
    assert upcoming_count == 0
    assert comic_count == 0


def test_count_orphan_annuals_reports_rows_without_a_series():
    with db.get_engine().begin() as conn:
        conn.execute(
            annuals.insert().values(
                IssueID="orphan-1",
                ComicID="missing-series",
                ReleaseComicName="Gone",
                Issue_Number="Annual 1",
                Status="Wanted",
                ReleaseDate="2020-01-01",
                Deleted=None,
            )
        )

    assert series_queries.count_orphan_annuals() == 1


def test_arc_issue_without_library_series_stays_searchable():
    with db.get_engine().begin() as conn:
        conn.execute(
            storyarcs.insert().values(
                IssueArcID="ARC-1",
                StoryArcID="S1",
                ComicID="NOTINLIB",
                ComicName="Unwatched",
                IssueNumber="1",
                Status="Wanted",
                IssueDate="2020-01-01",
                ReleaseDate="2020-01-01",
                DigitalDate="0000-00-00",
            )
        )

    state = series_queries.get_search_candidate_state("ARC-1")
    assert state["SeriesComicID"] is None
    assert state["SeriesOptional"] in (True, 1)

    result = searchforissue_checker(
        "ARC-1",
        "2020-01-01",
        "2020-01-01",
        "0000-00-00",
        {},
    )
    assert result == {"status": True, "reason": None}
