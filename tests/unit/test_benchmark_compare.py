#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The nightly benchmark fails only on a ceiling and warns on a slowdown."""

import datetime
import json

import pytest
from sqlalchemy import create_engine, text

import comicarr
from comicarr import db
from comicarr.app.core.schema import upgrade_database
from tests.benchmark import __main__ as cli
from tests.benchmark.library import Spec, generate
from tests.benchmark.run import (
    BASELINE,
    KNOWN_MISSES,
    OPERATIONS,
    compare,
    load_known_misses,
    markdown,
    seed_upgrade_row,
)

ISSUE = "https://github.com/frankieramirez/comicarr/issues/9999"


def _results(median, ceiling=60, key="rescan", label="Full library rescan"):
    return {
        "operations": [{"key": key, "label": label, "median_s": median, "ceiling_s": ceiling, "met": median <= ceiling}]
    }


BASELINE_RESULTS = _results(10.0)


def test_a_26_percent_slowdown_warns_without_failing():
    verdict = compare(_results(12.6), BASELINE_RESULTS)
    assert verdict.ok
    assert verdict.warnings == ["Full library rescan is 26% slower than the baseline: 12.60 s against 10.00 s"]


def test_a_24_percent_slowdown_is_quiet():
    verdict = compare(_results(12.4), BASELINE_RESULTS)
    assert verdict.ok
    assert verdict.warnings == []


def test_a_missed_ceiling_fails():
    verdict = compare(_results(61.0), BASELINE_RESULTS)
    assert not verdict.ok
    assert verdict.failures == ["Full library rescan missed its ceiling: 61.00 s against 60.00 s"]


def test_a_known_miss_does_not_fail():
    verdict = compare(_results(61.0), BASELINE_RESULTS, {"rescan": ISSUE})
    assert verdict.ok
    assert verdict.notes == ["Full library rescan missed its ceiling, known: %s" % ISSUE]


def test_a_known_miss_that_now_meets_its_ceiling_fails_so_the_list_shrinks():
    verdict = compare(_results(5.0), BASELINE_RESULTS, {"rescan": ISSUE})
    assert not verdict.ok
    assert "remove it from known_misses.json" in verdict.failures[0]


def test_a_known_miss_must_name_an_operation_and_link_its_issue(tmp_path):
    path = tmp_path / "known.json"
    path.write_text(json.dumps([{"key": "rescan", "issue": "too slow"}]))
    with pytest.raises(ValueError, match="link its issue"):
        load_known_misses(path)
    path.write_text(json.dumps([{"key": "nope", "issue": ISSUE}]))
    with pytest.raises(ValueError, match="unknown operation"):
        load_known_misses(path)
    path.write_text(json.dumps([{"key": "rescan", "issue": ISSUE}]))
    assert load_known_misses(path) == {"rescan": ISSUE}


def test_the_committed_files_cover_every_operation():
    load_known_misses(KNOWN_MISSES)
    baseline = json.loads(BASELINE.read_text())
    assert [op["key"] for op in baseline["operations"]] == [op.key for op in OPERATIONS]
    assert all(op["met"] for op in baseline["operations"])


def test_the_summary_shows_the_baseline_and_the_warning():
    results = _results(12.6)
    report = markdown(results, compare(results, BASELINE_RESULTS), BASELINE_RESULTS)
    assert "| Full library rescan | 12.60 s | 10.00 s | 60.00 s | met |" in report
    assert "### Warnings" in report


def test_the_cli_warns_on_a_slowdown_and_fails_on_a_miss(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(BASELINE_RESULTS))
    summary = tmp_path / "summary.md"

    monkeypatch.setattr(cli, "run", lambda _folder, only=None: _results(12.6))
    assert cli.main(["run", str(tmp_path), "--baseline", str(baseline), "--summary", str(summary)]) == 0
    assert "Warning: Full library rescan is 26% slower" in capsys.readouterr().err
    assert "### Warnings" in summary.read_text()

    monkeypatch.setattr(cli, "run", lambda _folder, only=None: _results(61.0))
    assert cli.main(["run", str(tmp_path), "--baseline", str(baseline)]) == 1

    known = tmp_path / "known.json"
    known.write_text(json.dumps([{"key": "rescan", "issue": ISSUE}]))
    assert cli.main(["run", str(tmp_path), "--known-misses", str(known)]) == 0


def test_the_0_2x_row_is_seeded_at_library_size_and_upgrades(tmp_path, monkeypatch):
    spec = Spec(
        comic_series=8,
        manga_series=2,
        issues=200,
        files=120,
        wanted=30,
        story_arcs=2,
        history=40,
        largest_series=50,
        pull_list=10,
        pull_followed=4,
    )
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    try:
        generate(tmp_path / "lib", seed=3, spec=spec, today=datetime.date(2026, 11, 13))
    finally:
        db.shutdown_engine()

    database = seed_upgrade_row(tmp_path / "lib", tmp_path / "row.db")
    engine = create_engine("sqlite:///%s" % database)
    try:
        upgrade_database(engine)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM issues")).scalar() == 200
            assert conn.execute(text("SELECT COUNT(*) FROM comics")).scalar() == 10
            assert conn.execute(text("SELECT COUNT(*) FROM snatched")).scalar() == 40
            # The fixture's own small library is gone.
            assert conn.execute(text("SELECT COUNT(*) FROM comics WHERE ComicID = '900001'")).scalar() == 0
    finally:
        engine.dispose()
