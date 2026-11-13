#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The database reconciliation stage that follows a placed file.

These run the stage against a real schema, with the legacy updater
collaborators it calls by default, so a second run proves the writes converge
rather than that a mock was called twice.
"""

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr import db, updater
from comicarr.app.downloads.postprocess_pipeline import (
    ANNUAL,
    ISSUE,
    MANGA,
    PostProcessPlacedItem,
    PostProcessReconcileStage,
)
from comicarr.tables import annuals, comics, issues, metadata, snatched

# Rewritten on every run by design; everything else must hold still.
_CLOCK_COLUMNS = {"DateAdded", "FilesUpdated"}


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(comics).values(ComicID="C1", ComicName="Saga", Have=2, Total=10))
        conn.execute(
            insert(issues).values(
                IssueID="I7",
                ComicID="C1",
                ComicName="Saga",
                Issue_Number="7",
                IssueDate="2013-01-01",
                Status="Snatched",
            )
        )
        conn.execute(
            insert(annuals).values(
                IssueID="A1",
                ComicID="C1",
                ComicName="Saga",
                Issue_Number="1",
                IssueDate="2014-01-01",
                ReleaseComicName="Saga Annual",
                Status="Snatched",
                Deleted=0,
            )
        )
        conn.execute(insert(comics).values(ComicID="M1", ComicName="Chainsaw Man", Have=0, Total=3))
        for number, status in (("1", "Downloaded"), ("2", "Snatched")):
            conn.execute(
                insert(issues).values(
                    IssueID=f"M1-{number}", ComicID="M1", ComicName="Chainsaw Man", Issue_Number=number, Status=status
                )
            )
        conn.execute(insert(snatched).values(IssueID="M1-2", ComicID="M1", Status="Snatched", Provider="nyaa"))
    yield tmp_path
    db.shutdown_engine()


def _stage():
    return PostProcessReconcileStage(totals=updater.totals, foundsearch=updater.foundsearch)


def _placed(tmp_path, name):
    path = tmp_path / "library" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"x" * 64)
    return str(path)


def _snapshot():
    def rows(table):
        return sorted(
            (
                tuple((k, v) for k, v in sorted(row.items()) if k not in _CLOCK_COLUMNS)
                for row in db.select_all(select(table))
            ),
            key=repr,
        )

    return {
        name: rows(table)
        for name, table in (("comics", comics), ("issues", issues), ("annuals", annuals), ("snatched", snatched))
    }


def _row(table, issue_id):
    return db.select_one(select(table).where(table.c.IssueID == issue_id))


def _have(comic_id):
    return db.select_one(select(comics.c.Have).where(comics.c.ComicID == comic_id))["Have"]


def test_a_placed_comic_issue_is_marked_downloaded_and_counted(library):
    dst = _placed(library, "Saga 007 (2013).cbz")

    result = _stage().reconcile(
        PostProcessPlacedItem(comic_id="C1", issue_id="I7", kind=ISSUE, placed_path=dst, download_type="PP")
    )

    assert (result.table, result.marked_downloaded) == ("issues", True)
    row = _row(issues, "I7")
    assert (row["Status"], row["Location"], row["ComicSize"]) == ("Downloaded", "Saga 007 (2013).cbz", "64")
    assert _have("C1") == 3
    history = _row(snatched, "I7")
    assert (history["Status"], history["Issue_Number"]) == ("Post-Processed", "7")


def test_a_placed_annual_writes_the_annuals_row(library):
    dst = _placed(library, "Saga Annual 001 (2014).cbz")

    result = _stage().reconcile(
        PostProcessPlacedItem(comic_id="C1", issue_id="A1", kind=ANNUAL, placed_path=dst, download_type="PP")
    )

    assert (result.table, result.marked_downloaded) == ("annuals", True)
    row = _row(annuals, "A1")
    assert (row["Status"], row["Location"], row["ComicSize"]) == ("Downloaded", "Saga Annual 001 (2014).cbz", "64")
    assert _row(issues, "I7")["Status"] == "Snatched"
    assert _have("C1") == 3
    history = _row(snatched, "A1")
    assert (history["ComicName"], history["Status"]) == ("Saga Annual", "Post-Processed")


def test_a_placed_manga_chapter_moves_its_history_and_the_series_recount(library):
    dst = _placed(library, "Chainsaw Man 002.cbz")
    stage = _stage()

    stage.reconcile(PostProcessPlacedItem(comic_id="M1", issue_id="M1-2", kind=MANGA, placed_path=dst))
    assert stage.recount_series("M1") == 2

    row = _row(issues, "M1-2")
    assert (row["Status"], row["Location"]) == ("Downloaded", "Chainsaw Man 002.cbz")
    # Pins the inherited write: db.upsert lays the key over the values, and a
    # NULL Provider never conflicts, so the chapter gains a second Snatched row.
    history = db.select_all(select(snatched).where(snatched.c.IssueID == "M1-2"))
    assert sorted((row["Status"], row["Provider"] or "") for row in history) == [("Snatched", ""), ("Snatched", "nyaa")]
    assert _have("M1") == 2


def test_a_file_that_is_not_there_is_not_marked_downloaded(library):
    totals, foundsearch = [], []
    stage = PostProcessReconcileStage(
        totals=lambda *a, **k: totals.append((a, k)), foundsearch=lambda *a, **k: foundsearch.append((a, k))
    )

    result = stage.reconcile(
        PostProcessPlacedItem(comic_id="C1", issue_id="I7", kind=ISSUE, placed_path=str(library / "missing.cbz"))
    )

    assert result.marked_downloaded is False
    assert _row(issues, "I7")["Status"] == "Snatched"
    assert len(totals) == len(foundsearch) == 1


def test_a_second_run_after_a_restart_changes_nothing(library):
    stage = _stage()
    placed = [
        PostProcessPlacedItem(
            comic_id="C1", issue_id="I7", kind=ISSUE, placed_path=_placed(library, "Saga 007.cbz"), download_type="PP"
        ),
        PostProcessPlacedItem(
            comic_id="C1",
            issue_id="A1",
            kind=ANNUAL,
            placed_path=_placed(library, "Saga Annual 001.cbz"),
            download_type="PP",
        ),
        PostProcessPlacedItem(comic_id="M1", issue_id="M1-2", kind=MANGA, placed_path=_placed(library, "CSM 002.cbz")),
    ]

    def run():
        for item in placed:
            stage.reconcile(item)
        stage.recount_series("M1")

    run()
    first = _snapshot()
    run()

    assert _snapshot() == first
    assert _have("C1") == 4
