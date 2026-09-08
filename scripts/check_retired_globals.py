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

"""Fail the lint chain when a retired global reappears in source.

``GLOBAL_MESSAGES`` was the pre-EventBus message bus. Deleting its declaration
does not make its return an error: Python creates a module attribute on first
assignment, so ``comicarr.GLOBAL_MESSAGES = ...`` in a new producer would work
silently and rebuild the very coupling the Activity Center removed. A source
scan is the only gate that can fail at author time.

Contributor-facing only — no changeset (Activity Center ADR §7, #488).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Names that must not reappear in source, and why.
RETIRED_GLOBALS = {
    "GLOBAL_MESSAGES": (
        "retired by the Activity Center (#430/#484/#488). Narrate through "
        "comicarr.app.activity.events.record_activity, and publish through "
        "the EventBus 'activity' event."
    ),
    "QUIET": (
        "retired by the single log-level dial (#611/#612). It was a second "
        "verbosity control that only --quiet ever set and nothing ever "
        "cleared. Gate on logger.current_log_level(), or pass an explicit "
        "console= flag to logger.initLogger()."
    ),
    "LOG_LANG": (
        "retired with the RotatingLogger branch (#611/#619). Branching the "
        "logger on locale gave non-English installs — which is every Docker "
        "install, since python:3.12-slim sets LANG=C.UTF-8 — a second "
        "implementation that dropped logger.warning and logger.exception "
        "entirely. There is one logger for every locale now."
    ),
    "COMICINFO": (
        "retired by release candidate evaluation (#875). It was the shared "
        "match list every provider search wrote into and read back for "
        "duplicate checks. Candidate and duplicate history now live on "
        "comicarr.app.search.evaluation.EvaluationSession, which is passed "
        "through searchforissue, search_init, NZB_SEARCH, and GC.search."
    ),
    "LOG_CHARSET": (
        "retired with the RotatingLogger branch (#611/#619). It was assigned "
        "at import and never read by anything, which is the clearest evidence "
        "the locale branch never did the encoding job it claimed to."
    ),
}

# Trees that hold source. Prose keeps the history — the ADR names the retired
# global on purpose, so docs/ is deliberately not scanned.
SCAN_ROOTS = ("comicarr", "frontend/src", "frontend/tests", "tests", "scripts")

SCAN_FILES = ("Comicarr.py",)

SCAN_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs")

SKIP_DIRS = {"node_modules", "__pycache__", ".venv", "dist", "build"}

# A guard that bans a *word* would tax prose forever: an explanatory comment
# about why the global is gone is exactly what a future reader needs. Only code
# can rebuild the coupling, so comment-only lines are skipped.
COMMENT_PREFIXES = ("#", "//", "/*", "*", '"""', "'''")

# Match a whole identifier, never a fragment of a longer one. ``COMICINFO`` the
# retired global and ``_COMICINFO_TEMPLATE`` the ComicInfo.xml test fixture are
# different names, and ComicInfo.xml is a permanent part of this domain (cmtag,
# postprocessor, app/ai) — a substring ban would tax legitimate code forever. A
# real reintroduction is always an exact reference (``comicarr.COMICINFO = ...``),
# so the boundary costs the guard nothing.
RETIRED_PATTERNS = {
    name: re.compile(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(name)) for name in RETIRED_GLOBALS
}

SELF = Path(__file__).resolve()


def _iter_source_files():
    for name in SCAN_FILES:
        path = ROOT / name
        if path.is_file():
            yield path
    for root in SCAN_ROOTS:
        base = ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix not in SCAN_SUFFIXES:
                continue
            if SKIP_DIRS.intersection(path.parts):
                continue
            if path.resolve() == SELF:
                continue
            yield path


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith(COMMENT_PREFIXES)


def main() -> int:
    violations: list[str] = []

    for path in sorted(_iter_source_files()):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(lines, start=1):
            if _is_comment(line):
                continue
            for pattern in RETIRED_PATTERNS.values():
                if pattern.search(line):
                    rel = path.relative_to(ROOT).as_posix()
                    violations.append("%s:%d: %s" % (rel, lineno, line.strip()))

    if not violations:
        return 0

    print("Retired global reintroduced:", file=sys.stderr)
    for violation in violations:
        print("  %s" % violation, file=sys.stderr)
    print("", file=sys.stderr)
    for name, reason in RETIRED_GLOBALS.items():
        print("  %s: %s" % (name, reason), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
