#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Operator writes must UPDATE existing rows, not upsert missing IDs."""

import json
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select

from comicarr.app.series import queries as series_queries
from comicarr.app.series import router as series_router
from comicarr.app.storyarcs import queries as arc_queries
from comicarr.app.storyarcs import router as storyarcs_router
from comicarr.tables import comics, issues, storyarcs


def _engine(monkeypatch, *tables):
    engine = create_engine("sqlite://")
    for table in tables:
        table.create(engine)
    monkeypatch.setattr(series_queries.db, "get_engine", lambda: engine)
    monkeypatch.setattr(arc_queries.db, "get_engine", lambda: engine)
    return engine


def _count(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar()


def _body(response):
    if hasattr(response, "body"):
        return json.loads(response.body)
    return response


def test_pause_and_resume_missing_id_do_not_insert(monkeypatch):
    engine = _engine(monkeypatch, comics)
    assert series_queries.pause_comic("missing") is False
    assert series_queries.resume_comic("missing") is False
    assert _count(engine, comics) == 0


def test_pause_existing_series(monkeypatch):
    engine = _engine(monkeypatch, comics)
    with engine.begin() as conn:
        conn.execute(comics.insert().values(ComicID="160294", Status="Active"))
    assert series_queries.pause_comic("160294") is True
    with engine.connect() as conn:
        assert conn.execute(select(comics.c.Status)).scalar() == "Paused"
    assert series_queries.resume_comic("160294") is True
    with engine.connect() as conn:
        assert conn.execute(select(comics.c.Status)).scalar() == "Active"
    assert _count(engine, comics) == 1


def test_queue_unqueue_ignore_missing_id_do_not_insert(monkeypatch):
    engine = _engine(monkeypatch, issues)
    assert series_queries.queue_issue("missing", "frankie") is False
    assert series_queries.unqueue_issue("missing", "frankie") is False
    assert series_queries.ignore_issue("missing", "frankie") is False
    assert _count(engine, issues) == 0


def test_mark_issue_wanted_missing_id_does_not_insert(monkeypatch):
    engine = _engine(monkeypatch, issues)
    assert arc_queries.mark_issue_wanted("missing") is False
    assert _count(engine, issues) == 0


def test_mark_issue_wanted_updates_existing_row(monkeypatch):
    engine = _engine(monkeypatch, issues)
    with engine.begin() as conn:
        conn.execute(issues.insert().values(IssueID="issue-1", Status="Skipped"))
    assert arc_queries.mark_issue_wanted("issue-1") is True
    with engine.connect() as conn:
        assert conn.execute(select(issues.c.Status)).scalar() == "Wanted"
    assert _count(engine, issues) == 1


def test_pause_route_returns_404_for_unknown_series(monkeypatch):
    engine = _engine(monkeypatch, comics)
    response = series_router.pause_series("missing", SimpleNamespace())
    assert response.status_code == 404
    assert _body(response) == {"detail": "Series not found: missing"}
    assert _count(engine, comics) == 0


def test_queue_route_returns_404_for_unknown_issue(monkeypatch):
    engine = _engine(monkeypatch, issues)
    response = series_router.queue_issue("missing", "frankie", SimpleNamespace())
    assert response.status_code == 404
    assert _body(response) == {"detail": "Issue not found: missing"}
    assert _count(engine, issues) == 0


def test_unqueue_route_returns_404_for_unknown_issue(monkeypatch):
    engine = _engine(monkeypatch, issues)
    response = series_router.unqueue_issue("missing", "frankie", SimpleNamespace())
    assert response.status_code == 404
    assert _body(response) == {"detail": "Issue not found: missing"}
    assert _count(engine, issues) == 0


def test_bulk_pause_counts_only_existing_series(monkeypatch):
    engine = _engine(monkeypatch, comics)
    with engine.begin() as conn:
        conn.execute(comics.insert().values(ComicID="1", Status="Active"))
    response = series_router.bulk_pause_series({"ids": ["1", "missing"]}, SimpleNamespace())
    assert response == {"success": True, "count": 1}
    with engine.connect() as conn:
        assert conn.execute(select(comics.c.Status)).scalar() == "Paused"
    assert _count(engine, comics) == 1


def test_arc_issue_status_missing_id_does_not_insert(monkeypatch):
    engine = _engine(monkeypatch, storyarcs)
    assert arc_queries.set_issue_status("missing", "Wanted") is False
    assert _count(engine, storyarcs) == 0


def test_arc_issue_soft_delete_missing_id_does_not_insert(monkeypatch):
    engine = _engine(monkeypatch, storyarcs)
    assert arc_queries.soft_delete_arc_issue("missing") is False
    assert _count(engine, storyarcs) == 0


def test_arc_issue_status_route_returns_404_for_unknown_id(monkeypatch):
    engine = _engine(monkeypatch, storyarcs)
    response = storyarcs_router.set_arc_issue_status("ARC1", "missing", {"status": "Wanted"})
    assert response.status_code == 404
    assert _body(response) == {"detail": "Arc issue not found: missing"}
    assert _count(engine, storyarcs) == 0


def test_arc_issue_delete_route_returns_404_for_unknown_id(monkeypatch):
    engine = _engine(monkeypatch, storyarcs)
    response = storyarcs_router.delete_arc_issue("ARC1", "missing")
    assert response.status_code == 404
    assert _body(response) == {"detail": "Arc issue not found: missing"}
    assert _count(engine, storyarcs) == 0
