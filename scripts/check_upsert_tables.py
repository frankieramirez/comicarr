#  Copyright (C) 2025–2026 Comicarr contributors
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

"""CI gate: every literal ``upsert`` table name is a key of ``TABLE_MAP``.

``db.upsert()`` resolves its table by dict lookup (``comicarr/app/core/db.py``), so a
name that is merely mis-cased — ``"Issues"`` for ``"issues"`` — type-checks,
imports, and lints clean, then raises ``ValueError: Unknown table for upsert``
the first time that branch runs. Six such literals silently broke series
refresh on a live deployment (#561): the failure only surfaces on the write
path, which is exactly the path unit tests tend not to reach.

The lookup key is a plain string, so no type can carry the constraint. An AST
scan at author time is the cheapest gate that closes the class.

Table names built at runtime (``db.upsert(updatetable, ...)``) cannot be
checked statically and are skipped — the literals are where the typo lives.

Contributor-facing only — no changeset (CLAUDE.md).

Wire-in: ``npm run lint:guards``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES_PATH = ROOT / "comicarr" / "app" / "core" / "tables.py"

# Trees that can call upsert. Tests are scanned too: a mis-cased literal in a
# fixture pins the wrong contract just as convincingly as one in source.
SCAN_GLOBS = (
    "comicarr/**/*.py",
    "tests/**/*.py",
    "Comicarr.py",
)

SKIP_DIR_NAMES = {"_vendor", "__pycache__", ".venv", "node_modules"}

# upsert(table, values, controls) — table is arg 0.
# upsert_conn(conn, table, values, controls) — table is arg 1.
TABLE_ARG_INDEX = {"upsert": 0, "upsert_conn": 1}


def _table_map_keys() -> set[str]:
    """Extract the TABLE_MAP keys from tables.py without importing SQLAlchemy."""
    tree = ast.parse(TABLES_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "TABLE_MAP" not in targets or not isinstance(node.value, ast.Dict):
            continue
        return {k.value for k in node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    raise SystemExit("check_upsert_tables: TABLE_MAP literal not found in %s" % TABLES_PATH)


def _iter_source_files():
    seen = set()
    for glob in SCAN_GLOBS:
        for path in sorted(ROOT.glob(glob)):
            if not path.is_file() or path.suffix != ".py":
                continue
            if SKIP_DIR_NAMES.intersection(path.parts):
                continue
            if path in seen:
                continue
            seen.add(path)
            yield path


def _called_name(func: ast.expr) -> str | None:
    """Return the bare function name for ``upsert(...)`` and ``db.upsert(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def main() -> int:
    valid = _table_map_keys()
    violations: list[tuple[str, int, str]] = []

    for path in _iter_source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            index = TABLE_ARG_INDEX.get(_called_name(node.func) or "")
            if index is None or len(node.args) <= index:
                continue
            arg = node.args[index]
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                continue  # runtime-built name; not statically checkable
            if arg.value not in valid:
                violations.append((rel, node.lineno, arg.value))

    if not violations:
        return 0

    print("Unknown upsert table name (not a key of tables.TABLE_MAP):", file=sys.stderr)
    for rel, lineno, name in violations:
        suggestion = ""
        lowered = name.lower()
        if lowered in valid:
            suggestion = ' — did you mean "%s"?' % lowered
        print('  %s:%d: "%s"%s' % (rel, lineno, name, suggestion), file=sys.stderr)
    print("", file=sys.stderr)
    print("TABLE_MAP keys are lowercase; db.upsert() raises ValueError at runtime", file=sys.stderr)
    print("for anything else. See comicarr/app/core/tables.py and comicarr/app/core/db.py.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
