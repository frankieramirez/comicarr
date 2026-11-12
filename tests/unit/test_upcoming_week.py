#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Releases > Mine: publisher, kind, attention, and week selection."""

from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db
from comicarr.app.storyarcs import router as arc_router
from comicarr.app.storyarcs import service as arc_service
from comicarr.tables import comics, issues, metadata, weekly


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


def _seed(engine):
    with engine.begin() as conn:
        conn.execute(
            insert(comics),
            [
                {
                    "ComicID": "c-dc",
                    "ComicName": "Absolute Batman",
                    "ComicSortName": "Absolute Batman",
                    "ComicPublisher": "DC Comics",
                    "ContentType": "comic",
                },
                {
                    "ComicID": "c-manga",
                    "ComicName": "Dandadan",
                    "ComicSortName": "Dandadan",
                    "ComicPublisher": "Shueisha",
                    "ContentType": "manga",
                },
            ],
        )
        conn.execute(
            insert(issues),
            [
                {"IssueID": "i-dc", "ComicID": "c-dc", "Status": "Wanted"},
                {"IssueID": "i-manga", "ComicID": "c-manga", "Status": "Wanted"},
            ],
        )
        conn.execute(
            insert(weekly),
            [
                {
                    "COMIC": "Absolute Batman",
                    "ISSUE": "23",
                    "ComicID": "c-dc",
                    "IssueID": "i-dc",
                    "STATUS": "Wanted",
                    "PUBLISHER": "DC Comics",
                    "weeknumber": "5",
                    "year": "2026",
                    "SHIPDATE": "2026-02-04",
                },
                {
                    "COMIC": "Dandadan",
                    "ISSUE": "213",
                    "ComicID": "c-manga",
                    "IssueID": "i-manga",
                    "STATUS": "Wanted",
                    "PUBLISHER": None,
                    "weeknumber": "5",
                    "year": "2026",
                    "SHIPDATE": "2026-02-05",
                },
            ],
        )


def _view(*members):
    groups = tuple(
        SimpleNamespace(reason_phrase=phrase, base_reason="postprocess_failed", members=(SimpleNamespace(issue_id=issue_id),))
        for issue_id, phrase in members
    )
    return SimpleNamespace(groups=groups)


def test_rows_carry_publisher_kind_and_attention(upcoming_db, monkeypatch):
    _seed(upcoming_db)
    from comicarr.app import attention

    monkeypatch.setattr(attention, "read", lambda: _view(("i-dc", "Import failed")))

    rows = {row["IssueID"]: row for row in arc_service.get_upcoming(week="05", year="2026")}

    assert rows["i-dc"]["Publisher"] == "DC Comics"
    assert rows["i-dc"]["ContentType"] == "comic"
    assert rows["i-dc"]["attention"] == "Import failed"
    assert rows["i-dc"]["attention_reason"] == "postprocess_failed"
    # No pull-list publisher falls back to the series' own publisher.
    assert rows["i-manga"]["Publisher"] == "Shueisha"
    assert rows["i-manga"]["ContentType"] == "manga"
    assert rows["i-manga"]["attention"] is None


def test_attention_failure_leaves_rows_unannotated(upcoming_db, monkeypatch):
    _seed(upcoming_db)
    from comicarr.app import attention

    def boom():
        raise RuntimeError("journal locked")

    monkeypatch.setattr(attention, "read", boom)

    rows = arc_service.get_upcoming(week="05", year="2026")
    assert len(rows) == 2
    assert all(row["attention"] is None for row in rows)


def test_router_pads_the_week_it_asks_for(monkeypatch):
    from comicarr.app.weekly import service as weekly_service

    seen = {}
    monkeypatch.setattr(weekly_service, "week_window", lambda week, year: {"week": "5", "year": "2026"})
    monkeypatch.setattr(arc_service, "get_upcoming", lambda **kwargs: seen.update(kwargs) or [])

    assert arc_router.get_upcoming(include_downloaded=True, week=5, year=2026) == []
    assert seen == {"include_downloaded": True, "week": "05", "year": "2026"}


def test_router_needs_both_week_and_year():
    response = arc_router.get_upcoming(include_downloaded=False, week=5, year=None)
    assert response.status_code == 400


def test_router_rejects_weeks_outside_the_window(monkeypatch):
    from comicarr.app.weekly import service as weekly_service

    def out_of_range(week, year):
        raise weekly_service.WeekError("nope")

    monkeypatch.setattr(weekly_service, "week_window", out_of_range)
    response = arc_router.get_upcoming(include_downloaded=False, week=40, year=2030)
    assert response.status_code == 400
