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

"""CI gate: the ``comicarr/`` package root only shrinks (ADR-0007).

ADR-0007 sets the end state: ``comicarr/`` holds ``__init__.py`` and ``app/``
and nothing else, and ``comicarr/_vendor/`` is gone. Everything else at the
package root is listed here with the ticket that retires it.

Three lists, all **shrink-only**:

- ``ROOT_MODULES``: every ``comicarr/*.py`` file except ``__init__.py``.
- ``ROOT_PACKAGES``: every directory under ``comicarr/`` except ``app/``.
- ``VENDOR_ROOTS``: every top-level entry under ``comicarr/_vendor/`` except
  ``__init__.py`` and ``provenance.py``.

A file or directory that is on disk but not listed fails: new code goes under
``comicarr/app/``. A listed name that is no longer on disk also fails, so the
change that deletes a module deletes its entry too.

Contributor-facing only — no changeset (CLAUDE.md).

Wire-in: ``npm run lint:guards``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = "comicarr"
VENDOR_DIR = "comicarr/_vendor"

SKIP_DIR_NAMES = {"__pycache__"}

# Root module -> the GitHub issue that retires it (all children of #1402).
ROOT_MODULES: dict[str, int] = {
    "cdh_mapping": 1422,
    "cfscrape_compat": 1421,
    "comicsync": 1420,
    "config": 1423,
    "db": 1423,
    "encrypted": 1423,
    "failed": 1422,
    "filechecker": 1422,
    "getcomics": 1422,
    "helpers": 1423,
    "importer": 1420,
    "logger": 1423,
    "nzbget": 1422,
    "postprocessor": 1422,
    "rsscheck": 1421,
    "rsscheckit": 1421,
    "sabnzbd": 1422,
    "search": 1422,
    "tables": 1423,
    "updater": 1420,
    "utorrent": 1421,
    "weeklypull": 1421,
    "weeklypullit": 1421,
}

# Directory under comicarr/ other than app/ -> retiring issue.
ROOT_PACKAGES: dict[str, int] = {
    "downloaders": 1422,
    "torrent": 1422,
}

# Top-level entry under comicarr/_vendor/ -> retiring issue.
VENDOR_ROOTS: dict[str, int] = {}

ALLOWED_MODULES = frozenset({"__init__"})
ALLOWED_PACKAGES = frozenset({"app"})
ALLOWED_VENDOR = frozenset({"__init__.py", "provenance.py"})


def _on_disk() -> tuple[set[str], set[str], set[str]]:
    package = ROOT / PACKAGE_DIR
    modules = {p.stem for p in package.glob("*.py") if p.is_file()} - ALLOWED_MODULES
    packages = {p.name for p in package.iterdir() if p.is_dir() and p.name not in SKIP_DIR_NAMES} - ALLOWED_PACKAGES
    vendor_dir = ROOT / VENDOR_DIR
    vendor: set[str] = set()
    if vendor_dir.is_dir():
        vendor = {
            p.name for p in vendor_dir.iterdir() if p.name not in SKIP_DIR_NAMES and (p.is_dir() or p.suffix == ".py")
        } - ALLOWED_VENDOR
    return modules, packages, vendor


def check() -> list[str]:
    """Return one human-readable problem per line; empty when the root is clean."""
    modules, packages, vendor = _on_disk()
    problems: list[str] = []
    for label, found, listed, where in (
        ("ROOT_MODULES", modules, ROOT_MODULES, "comicarr/%s.py"),
        ("ROOT_PACKAGES", packages, ROOT_PACKAGES, "comicarr/%s/"),
        ("VENDOR_ROOTS", vendor, VENDOR_ROOTS, "comicarr/_vendor/%s"),
    ):
        for name in sorted(found - set(listed)):
            problems.append("new: %s is not in %s; put new code under comicarr/app/" % (where % name, label))
        for name in sorted(set(listed) - found):
            problems.append(
                "stale: %s is gone; delete it from %s (retired by #%d)" % (where % name, label, listed[name])
            )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("The comicarr/ package root only shrinks (ADR-0007):", file=sys.stderr)
        for line in problems:
            print("  " + line, file=sys.stderr)
        print("", file=sys.stderr)
        print("Lists live in scripts/check_root_modules.py. Never add an entry.", file=sys.stderr)
        return 1
    print(
        "Root modules OK: %d module(s), %d package(s), %d vendor root(s) left to retire"
        % (len(ROOT_MODULES), len(ROOT_PACKAGES), len(VENDOR_ROOTS))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
