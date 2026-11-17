#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Story arc rows with Manual NULL stay visible, and searches stop adding empty rows (#1514).

Mylar3 imports and newly added arcs leave Manual NULL. ``Manual != 'deleted'``
is NULL for those rows in SQL, so every arc query used to drop them.
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert, select, text

import comicarr
from comicarr.app.core.db import get_engine, shutdown_engine
from comicarr.app.core.tables import metadata, storyarcs
from comicarr.app.storyarcs import queries


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    metadata.create_all(get_engine())
    yield
    shutdown_engine()


def _row(issue_arc_id, issue_id, manual=None, status="Skipped"):
    return {
        "StoryArcID": "ARC1",
        "StoryArc": "Big Event",
        "ComicName": "Hero",
        "IssueNumber": issue_arc_id[-1],
        "IssueID": issue_id,
        "IssueArcID": issue_arc_id,
        "ReadingOrder": int(issue_arc_id[-1]),
        "Status": status,
        "Manual": manual,
    }


def _seed(*rows):
    with get_engine().begin() as conn:
        conn.execute(insert(storyarcs), list(rows))


def test_arcs_with_null_manual_are_listed_opened_and_counted():
    _seed(_row("A1", "I1"), _row("A2", "I2"), _row("A3", "I3", manual="deleted"))

    assert [arc["StoryArcID"] for arc in queries.list_arcs()] == ["ARC1"]
    assert queries.get_arc_stats("ARC1") is not None
    assert {row["IssueArcID"] for row in queries.get_arc_issues("ARC1")} == {"A1", "A2"}

    queries.want_all_issues("ARC1")
    with get_engine().connect() as conn:
        wanted = conn.execute(select(storyarcs.c.IssueArcID).where(storyarcs.c.Status == "Wanted")).scalars()
        assert set(wanted) == {"A1", "A2"}


def test_search_uses_the_null_safe_update_for_story_arcs():
    source = Path(comicarr.__file__).with_name("search.py").read_text()
    assert "update(storyarcs)" in source and "storyarcs.c.DateAdded.is_(None)" in source


def test_migration_removes_only_rows_that_belong_to_no_arc(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "cleanup.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(storyarcs), [_row("A1", "I1")])
        conn.execute(insert(storyarcs), [{"IssueID": "I1", "DateAdded": "2026-11-17"}] * 3)

    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0025_storyarcs_empty_rows.py"
    spec = importlib.util.spec_from_file_location("rev0025", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as conn:
        ops = Operations(MigrationContext.configure(conn))
        module.op = ops
        module.upgrade()

    with engine.connect() as conn:
        assert conn.execute(text("SELECT IssueArcID FROM storyarcs")).scalars().all() == ["A1"]
