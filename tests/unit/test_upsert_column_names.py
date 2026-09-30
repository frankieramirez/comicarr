#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Writes that used keys which are not columns of their table.

SQLite's raw SQL ignored column-name case, but since the SQLAlchemy Core
upsert (#45) any unknown key raises ``CompileError: Unconsumed column names``.
"""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr import db, updater
from comicarr.tables import comics, issues, metadata, snatched, weekly


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _seed_pull_issue(engine, pull_status):
    with engine.begin() as conn:
        conn.execute(insert(comics).values(ComicID="160294", ComicName="Absolute Batman", ComicYear="2024"))
        conn.execute(
            insert(issues).values(
                IssueID="1194150", ComicID="160294", Issue_Number="24", IssueDate="2026-11-01", Status="Wanted"
            )
        )
        conn.execute(
            insert(weekly).values(
                COMIC="Absolute Batman",
                ISSUE="24",
                STATUS=pull_status,
                ComicID="160294",
                IssueID="1194150",
                weeknumber="38",
                year="2026",
            )
        )


def _pull_row():
    return db.select_one(select(weekly).where(weekly.c.IssueID == "1194150"))


def test_snatching_an_issue_on_the_pull_list_marks_the_pull_row(fresh_db, monkeypatch):
    _seed_pull_issue(fresh_db, "Wanted")
    record_transition = MagicMock()
    monkeypatch.setattr("comicarr.app.downloads.journal.record_transition", record_transition)

    updater.foundsearch("160294", "1194150", provider="nzbgeek", nzbname="Absolute.Batman.024")

    assert _pull_row()["STATUS"] == "Snatched"
    assert record_transition.called
    assert db.select_one(select(snatched).where(snatched.c.IssueID == "1194150"))["Status"] == "Snatched"


def test_downloading_a_snatched_pull_issue_marks_the_pull_row(fresh_db):
    _seed_pull_issue(fresh_db, "Snatched")

    updater.foundsearch("160294", "1194150", down="PP", provider="nzbgeek")

    assert _pull_row()["STATUS"] == "Downloaded"


def test_post_processing_a_one_off_marks_its_pull_row(fresh_db):
    from comicarr import postprocessor

    _seed_pull_issue(fresh_db, "Snatched")

    postprocessor.mark_pull_row_downloaded("1194150")

    assert _pull_row()["STATUS"] == "Downloaded"
    assert len(db.select_all(select(weekly))) == 1
