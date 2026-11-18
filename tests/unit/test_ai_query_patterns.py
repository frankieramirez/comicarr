#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Database contract tests for AI query patterns."""

import pytest

import comicarr
from comicarr.app.ai.query_patterns import execute_pattern
from comicarr.app.core import db, runtime
from comicarr.app.core.tables import comics, metadata


@pytest.fixture
def completion_series(tmp_path, monkeypatch):
    """Create completion-filter fixtures in a real temporary SQLite database."""
    monkeypatch.setattr(runtime.current(), "data_dir", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()

    engine = db.get_engine()
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            comics.insert(),
            [
                {"ComicID": "zero", "ComicName": "Zero Total", "Have": 9, "Total": 0, "Status": "Active"},
                {"ComicID": "lower", "ComicName": "Lower Boundary", "Have": 1, "Total": 4, "Status": "Active"},
                {"ComicID": "middle", "ComicName": "Middle", "Have": 1, "Total": 2, "Status": "Active"},
                {"ComicID": "upper", "ComicName": "Upper Boundary", "Have": 3, "Total": 4, "Status": "Active"},
                {"ComicID": "above", "ComicName": "Above Range", "Have": 9, "Total": 10, "Status": "Active"},
                {"ComicID": "paused", "ComicName": "Paused", "Have": 7, "Total": 10, "Status": "Paused"},
                {"ComicID": "paused-zero", "ComicName": "Paused Zero", "Have": 0, "Total": 0, "Status": "Paused"},
            ],
        )

    yield
    db.shutdown_engine()


def test_completion_filter_includes_boundaries_orders_and_excludes_paused(completion_series):
    rows = execute_pattern("completion_filter", {"min_pct": 25, "max_pct": 75, "limit": 20})

    assert [(row["ComicID"], row["pct"]) for row in rows] == [
        ("upper", 75.0),
        ("middle", 50.0),
        ("lower", 25.0),
    ]


def test_completion_filter_treats_zero_total_as_zero_percent(completion_series):
    rows = execute_pattern("completion_filter", {"min_pct": 0, "max_pct": 0, "limit": 20})

    assert [(row["ComicID"], row["pct"]) for row in rows] == [("zero", 0)]


def test_completion_filter_applies_validated_limit_after_percentage_ordering(completion_series):
    rows = execute_pattern("completion_filter", {"min_pct": 0, "max_pct": 100, "limit": 2})

    assert [row["ComicID"] for row in rows] == ["above", "upper"]
