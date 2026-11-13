#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for scripts/check_first_class_targets.py — the first-class targets table gate."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_first_class_targets.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("check_first_class_targets", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture
def tree(tmp_path):
    unit = tmp_path / "tests" / "unit" / "test_fake.py"
    unit.parent.mkdir(parents=True)
    unit.write_text("def test_one():\n    pass\n\nclass TestGroup:\n    def test_two(self):\n        pass\n")
    pipeline = tmp_path / "tests" / "integration" / "test_acquisition_pipeline.py"
    pipeline.parent.mkdir(parents=True)
    pipeline.write_text("def test_end_to_end():\n    pass\n")
    return tmp_path


FLOORS = {"SABnzbd": (("comicarr/sabnzbd.py",), 50.0)}
COVERAGE = "## Coverage baseline\n\n| Group | Modules | Lines | Floor | Gap |\n|---|---|---|---|---|\n| SABnzbd | x | 50.0% | 50.0% | 30.0 |\n"


def _doc(
    manga_rows,
    other_row="| A | `tests/unit/test_fake.py::test_one` | `tests/integration/test_acquisition_pipeline.py::test_end_to_end` | covered |",
):
    header = "| Scenario | Unit test | Pipeline test | Status |\n|---|---|---|---|\n"
    parts = ["## Manga\n\n" + header + "\n".join(manga_rows) + "\n"]
    for table in ("SABnzbd", "NZBGet"):
        parts.append("## %s\n\n%s%s\n" % (table, header, other_row))
    return "\n".join(parts) + "\n" + COVERAGE


def test_real_doc_passes(guard):
    assert guard.main([]) == 0


def test_covered_and_pending_rows_pass(guard, tree):
    doc = _doc(
        [
            "| Covered | `tests/unit/test_fake.py::TestGroup::test_two` | `tests/integration/test_acquisition_pipeline.py::test_end_to_end` | covered |",
            "| Gap | `tests/unit/test_fake.py::test_one` | pending | pending #9 |",
        ]
    )
    assert guard.check_doc(doc, tree, {("Manga", "Gap", "pipeline"): 9}, FLOORS) == []


def test_missing_test_id_fails(guard, tree):
    doc = _doc(
        [
            "| Gone | `tests/unit/test_fake.py::test_renamed` | `tests/integration/test_acquisition_pipeline.py::test_end_to_end` | covered |"
        ]
    )
    errors = guard.check_doc(doc, tree, {}, FLOORS)
    assert errors == ["Manga / Gone: test does not exist: tests/unit/test_fake.py::test_renamed"]


def test_missing_method_on_a_real_class_fails(guard, tree):
    doc = _doc(
        [
            "| Gone | `tests/unit/test_fake.py::TestGroup::test_one` | `tests/integration/test_acquisition_pipeline.py::test_end_to_end` | covered |"
        ]
    )
    assert any("does not exist" in e for e in guard.check_doc(doc, tree, {}, FLOORS))


def test_untested_row_not_on_the_pending_list_fails(guard, tree):
    doc = _doc(["| Gap | `tests/unit/test_fake.py::test_one` | pending | pending #9 |"])
    errors = guard.check_doc(doc, tree, {}, FLOORS)
    assert "Manga / Gap: pipeline test is pending but not in PENDING" in errors


def test_stale_pending_entry_fails(guard, tree):
    doc = _doc(
        [
            "| Filled | `tests/unit/test_fake.py::test_one` | `tests/integration/test_acquisition_pipeline.py::test_end_to_end` | covered |"
        ]
    )
    errors = guard.check_doc(doc, tree, {("Manga", "Filled", "pipeline"): 9}, FLOORS)
    assert errors == ["stale PENDING entry (cell is no longer pending, or the row is gone): Manga / Filled / pipeline"]


def test_pipeline_cell_must_name_the_pipeline_module(guard, tree):
    doc = _doc(["| Wrong | `tests/unit/test_fake.py::test_one` | `tests/unit/test_fake.py::test_one` | covered |"])
    assert any("pipeline test must live in" in e for e in guard.check_doc(doc, tree, {}, FLOORS))


def test_status_must_name_the_owning_ticket(guard, tree):
    doc = _doc(["| Gap | `tests/unit/test_fake.py::test_one` | pending | pending |"])
    errors = guard.check_doc(doc, tree, {("Manga", "Gap", "pipeline"): 9}, FLOORS)
    assert errors == ["Manga / Gap: status must read 'pending' and name #9"]


def test_doc_floor_must_match_the_script(guard, tree):
    doc = _doc(
        [
            "| A | `tests/unit/test_fake.py::test_one` | `tests/integration/test_acquisition_pipeline.py::test_end_to_end` | covered |"
        ]
    )
    errors = guard.check_doc(doc, tree, {}, {"SABnzbd": (("comicarr/sabnzbd.py",), 61.0)})
    assert errors == ["coverage baseline for SABnzbd reads 50.0% in the doc but COVERAGE_FLOORS says 61.0%"]


def _coverage_xml(path, hits):
    lines = "".join('<line number="%d" hits="%d"/>' % (n, h) for n, h in enumerate(hits, 1))
    path.write_text(
        '<?xml version="1.0" ?><coverage><sources><source>/repo/comicarr</source></sources><packages><package><classes>'
        '<class filename="sabnzbd.py"><lines>%s</lines></class>'
        '<class filename="other.py"><lines><line number="1" hits="0"/></lines></class>'
        "</classes></package></packages></coverage>" % lines
    )
    return path


def test_coverage_at_or_above_the_floor_passes(guard, tmp_path):
    report = _coverage_xml(tmp_path / "coverage.xml", [1, 1, 0, 0])
    assert guard.check_coverage(report, FLOORS) == []


def test_coverage_below_the_floor_fails(guard, tmp_path):
    report = _coverage_xml(tmp_path / "coverage.xml", [1, 0, 0, 0])
    assert guard.check_coverage(report, FLOORS) == ["SABnzbd line coverage fell to 25.0%, below its recorded 50.0%"]


def test_coverage_with_no_measured_lines_fails(guard, tmp_path):
    report = _coverage_xml(tmp_path / "coverage.xml", [])
    assert guard.check_coverage(report, FLOORS) == ["SABnzbd: no measured lines in %s" % report]
