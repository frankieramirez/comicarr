#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The benchmark library is the same every time for the same seed."""

import datetime
import hashlib
import random

from sqlalchemy import create_engine, select

import comicarr
from comicarr import db
from comicarr.tables import comics, issues, snatched, storyarcs
from tests.benchmark import __main__ as cli
from tests.benchmark.library import BENCHMARK, generate, library_files, series_sizes

TODAY = datetime.date(2026, 11, 13)


def _digest(root):
    engine = create_engine("sqlite:///%s" % (root / "data" / "comicarr.db"))
    digest = hashlib.sha256()
    with engine.connect() as conn:
        for table in (comics, issues, storyarcs, snatched):
            for row in conn.execute(select(table).order_by(*table.c)).all():
                # Paths differ between the two folders; everything else must not.
                digest.update(repr(tuple(str(v).replace(str(root), "<root>") for v in row)).encode())
    engine.dispose()
    return digest.hexdigest()


def test_same_seed_gives_the_same_library(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    try:
        first = generate(tmp_path / "a", seed=7, today=TODAY)
        second = generate(tmp_path / "b", seed=7, today=TODAY)
    finally:
        db.shutdown_engine()

    assert first == second
    arc_rows = first["rows"].pop("storyarcs")
    assert 50 * 6 <= arc_rows <= 50 * 24
    assert first["rows"] == {
        "comics": 400,
        "issues": 20_000,
        "snatched": 5_000,
        "activity_events": 5_000,
        "weekly": 500,
        "wanted": 2_000,
    }
    assert first["files"] == 15_000
    assert library_files(tmp_path / "a") == library_files(tmp_path / "b")
    assert len(library_files(tmp_path / "a")) == 15_000
    assert _digest(tmp_path / "a") == _digest(tmp_path / "b")


def test_series_sizes_are_a_long_tail_that_sums_exactly():
    sizes = series_sizes(random.Random(1), BENCHMARK)
    assert len(sizes) == 400
    assert sum(sizes) == 20_000
    assert max(sizes) == sizes[0] == 500
    assert min(sizes) >= 1
    small = sum(1 for s in sizes if s <= 5)
    assert 40 <= small <= 160, small


def test_run_exits_non_zero_when_a_ceiling_is_missed(monkeypatch, capsys, tmp_path):
    def fake_run(_folder, only=None):
        return {
            "operations": [
                {"label": "Library list API", "median_s": 0.02, "ceiling_s": 0.5, "met": True},
                {"label": "Full library rescan", "median_s": 400.0, "ceiling_s": 300, "met": False},
            ]
        }

    monkeypatch.setattr(cli, "run", fake_run)
    output = tmp_path / "results.json"
    assert cli.main(["run", str(tmp_path), "--output", str(output)]) == 1
    printed = capsys.readouterr()
    assert "Full library rescan  400.00 s  300.00 s  MISSED" in printed.out
    assert "Library list API     20 ms     500 ms    met" in printed.out
    assert "Missed: Full library rescan" in printed.err
    assert output.exists()

    monkeypatch.setattr(cli, "run", lambda _folder, only=None: {"operations": fake_run(None)["operations"][:1]})
    assert cli.main(["run", str(tmp_path)]) == 0
