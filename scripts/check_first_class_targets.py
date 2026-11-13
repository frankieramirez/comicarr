#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""CI gate: every first-class target scenario names a real test, or is a known gap.

Section 5 of ``docs/architecture/foundations-plan.md`` makes manga, SABnzbd and
NZBGet first-class test targets. ``docs/testing/first-class-targets.md`` holds one
row per scenario, each naming a unit test and a test in
``tests/integration/test_acquisition_pipeline.py``.

Without a check, a row can name a test that was renamed or deleted and the table
keeps claiming coverage that no longer exists. This gate reads the tables and
fails when:

- a row names a test id whose file, class or function does not exist;
- a pipeline cell names a test outside ``tests/integration/test_acquisition_pipeline.py``;
- a cell says ``pending`` and is not in ``PENDING`` below;
- a ``PENDING`` entry no longer matches a ``pending`` cell (the list only shrinks);
- the Status column disagrees with the cells;
- the coverage floors in the doc differ from ``COVERAGE_FLOORS``.

With ``--coverage <coverage.xml>`` it instead checks measured line coverage of
each target group against ``COVERAGE_FLOORS``. The backend test workflow runs
that after the unit and integration suites.

Contributor-facing only — no changeset (CLAUDE.md).

Wire-in: ``npm run lint:guards`` and ``.github/workflows/test.yml``.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = Path("docs/testing/first-class-targets.md")
PIPELINE_FILE = "tests/integration/test_acquisition_pipeline.py"
TABLES = ("Manga", "SABnzbd", "NZBGet")
COVERAGE_SECTION = "Coverage baseline"
COVERAGE_TARGET = 80.0

# (table, scenario, column) -> the build ticket that will fill the cell.
# Shrink-only: a filled cell must leave this list in the same change.
PENDING = {
}

# Group -> (module paths relative to the repo root, line-coverage floor in percent).
# A path ending in "/" covers every .py file below it. Floors only rise: when a
# change raises a figure, record the new one here and in the doc.
COVERAGE_FLOORS = {
    "SABnzbd": (("comicarr/sabnzbd.py",), 82.3),
    "NZBGet": (("comicarr/nzbget.py",), 56.4),
    "Manga": (("comicarr/app/manga/",), 91.3),
    "Downloads": (
        (
            "comicarr/app/downloads/handoff.py",
            "comicarr/app/downloads/completed_path.py",
            "comicarr/app/downloads/sab_reconcile.py",
        ),
        84.3,
    ),
}

TEST_ID = re.compile(r"`(tests/[^`]+?\.py(?:::[A-Za-z_][A-Za-z0-9_]*)+)(?:\[[^`]*\])?`")
PENDING_CELL = "pending"
COLUMNS = ("unit", "pipeline")


def _sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def _table_rows(lines: list[str]) -> list[list[str]]:
    rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= set("-: ") for cell in cells):
            continue  # the separator row
        rows.append(cells)
    return rows[1:]  # drop the header


def _defined(root: Path, test_id: str) -> bool:
    path, *names = test_id.split("::")
    source = root / path
    if not source.is_file():
        return False
    body = ast.parse(source.read_text(encoding="utf-8")).body
    for name in names:
        match = next(
            (
                node
                for node in body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name
            ),
            None,
        )
        if match is None:
            return False
        body = match.body if isinstance(match, ast.ClassDef) else []
    return True


def check_doc(text: str, root: Path, pending: dict, floors: dict) -> list[str]:
    errors: list[str] = []
    sections = _sections(text)
    seen_pending: set[tuple[str, str, str]] = set()

    for table in TABLES:
        if table not in sections:
            errors.append("missing table: ## %s" % table)
            continue
        rows = _table_rows(sections[table])
        if not rows:
            errors.append("%s: table has no rows" % table)
        for cells in rows:
            if len(cells) != 4:
                errors.append("%s: row needs 4 cells, got %d: %s" % (table, len(cells), " | ".join(cells)))
                continue
            scenario, status = cells[0], cells[3]
            tickets: set[int] = set()
            for column, cell in zip(COLUMNS, cells[1:3], strict=True):
                key = (table, scenario, column)
                if cell.lower() == PENDING_CELL:
                    if key in pending:
                        seen_pending.add(key)
                        tickets.add(pending[key])
                    else:
                        errors.append("%s / %s: %s test is pending but not in PENDING" % (table, scenario, column))
                    continue
                ids = TEST_ID.findall(cell)
                if not ids:
                    errors.append("%s / %s: %s cell names no test id: %r" % (table, scenario, column, cell))
                for test_id in ids:
                    if column == "pipeline" and not test_id.startswith(PIPELINE_FILE + "::"):
                        errors.append(
                            "%s / %s: pipeline test must live in %s: %s" % (table, scenario, PIPELINE_FILE, test_id)
                        )
                    elif not _defined(root, test_id):
                        errors.append("%s / %s: test does not exist: %s" % (table, scenario, test_id))
            if tickets:
                named = {int(n) for n in re.findall(r"#(\d+)", status)}
                if not status.lower().startswith(PENDING_CELL) or not tickets <= named:
                    want = ", ".join("#%d" % t for t in sorted(tickets))
                    errors.append("%s / %s: status must read 'pending' and name %s" % (table, scenario, want))
            elif not status.lower().startswith("covered"):
                errors.append("%s / %s: both tests are named, so status must start with 'covered'" % (table, scenario))

    for key in sorted(set(pending) - seen_pending):
        errors.append("stale PENDING entry (cell is no longer pending, or the row is gone): %s / %s / %s" % key)

    recorded = {}
    for cells in _table_rows(sections.get(COVERAGE_SECTION, [])):
        floor = re.search(r"(\d+(?:\.\d+)?)%", cells[3]) if len(cells) > 3 else None
        if floor:
            recorded[cells[0]] = float(floor.group(1))
    for group, (_paths, value) in floors.items():
        if recorded.get(group) != value:
            errors.append(
                "coverage baseline for %s reads %s in the doc but COVERAGE_FLOORS says %.1f%%"
                % (group, "%.1f%%" % recorded[group] if group in recorded else "nothing", value)
            )
    return errors


def measure(coverage_xml: Path, floors: dict) -> dict[str, tuple[int, int]]:
    """Return group -> (covered lines, total lines) from coverage.py's XML report."""
    tree = ET.parse(coverage_xml)
    totals = {group: [0, 0] for group in floors}
    for cls in tree.iter("class"):
        # coverage.py writes filenames relative to its source, the comicarr package.
        filename = cls.get("filename", "")
        rel = filename if filename.startswith("comicarr/") else "comicarr/" + filename
        for group, (paths, _floor) in floors.items():
            if any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in paths):
                lines = list(cls.iter("line"))
                totals[group][0] += sum(1 for line in lines if int(line.get("hits", "0")) > 0)
                totals[group][1] += len(lines)
    return {group: (hit, total) for group, (hit, total) in totals.items()}


def check_coverage(coverage_xml: Path, floors: dict) -> list[str]:
    errors = []
    for group, (hit, total) in measure(coverage_xml, floors).items():
        floor = floors[group][1]
        if total == 0:
            errors.append("%s: no measured lines in %s" % (group, coverage_xml))
            continue
        percent = 100.0 * hit / total
        gap = max(0.0, COVERAGE_TARGET - percent)
        print(
            "%-10s %5.1f%% of %d lines (floor %.1f%%, %.1f points to %d%%)"
            % (group, percent, total, floor, gap, COVERAGE_TARGET)
        )
        if round(percent, 1) < floor:
            errors.append("%s line coverage fell to %.1f%%, below its recorded %.1f%%" % (group, percent, floor))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coverage", type=Path, help="check a coverage.xml against the recorded floors")
    args = parser.parse_args(argv)

    if args.coverage:
        errors = check_coverage(args.coverage, COVERAGE_FLOORS)
        label = "First-class target coverage fell below its recorded floor"
    else:
        errors = check_doc((ROOT / DOC).read_text(encoding="utf-8"), ROOT, PENDING, COVERAGE_FLOORS)
        label = "%s is out of step with the tests" % DOC.as_posix()

    if errors:
        print("%s:" % label, file=sys.stderr)
        for error in errors:
            print("  " + error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
