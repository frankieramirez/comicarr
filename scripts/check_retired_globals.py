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
# Package globals retired into AppContext fields (#1478, #1402). Each group
# moved every reader and writer to ``runtime.current().<field>`` in one change.
_RUNTIME_FIELD_GROUPS = {
    "scheduler status and schedule stamps (#1539)": (
        "MONITOR_STATUS",
        "IMPORTINBOX_STATUS",
        "SEARCH_STATUS",
        "RSS_STATUS",
        "WEEKLY_STATUS",
        "VERSION_STATUS",
        "UPDATER_STATUS",
        "MANGA_SYNC_STATUS",
        "FORCE_STATUS",
        "WEEKLY_MANUAL_NEXT_RUN",
        "SCHED_RSS_LAST",
        "SCHED_WEEKLY_LAST",
        "SCHED_MONITOR_LAST",
        "SCHED_SEARCH_LAST",
        "SCHED_VERSION_LAST",
        "SCHED_DBUPDATE_LAST",
        "SCHED_MANGA_SYNC_LAST",
        "SCHED_UPDATER_LAST",
    ),
    "work queues (#1540)": (
        "SNATCHED_QUEUE",
        "NZB_QUEUE",
        "PP_QUEUE",
        "SEARCH_QUEUE",
        "DDL_QUEUE",
        "RETURN_THE_NZBQUEUE",
        "ADD_LIST",
        "ISSUE_WATCH_LIST",
        "REFRESH_QUEUE",
    ),
    "process locks (#1540)": (
        "INIT_LOCK",
        "ACQUISITION_RESUME_LOCK",
        "APILOCK",
        "SEARCHLOCK",
        "DDL_LOCK",
    ),
    "worker-pool references (#1540)": (
        "SNPOOL",
        "NZBPOOL",
        "SEARCHPOOL",
        "PPPOOL",
        "DDLPOOL",
        "MASS_ADD",
        "MASS_REFRESH",
    ),
    "install paths (#1541)": (
        "PROG_DIR",
        "DATA_DIR",
        "DB_FILE",
    ),
    "version and install state (#1541)": (
        "INSTALL_TYPE",
        "CURRENT_BRANCH",
        "CURRENT_VERSION",
        "CURRENT_VERSION_NAME",
        "CURRENT_RELEASE_NAME",
        "LATEST_VERSION",
        "UPDATE_STATE",
        "UPDATE_REASON",
        "UPDATE_VALUE",
    ),
    # CV_TIMEOUT is also an INI key and CV_CACHE a log prefix, so neither can
    # be a banned word; the general comicarr.<UPPER> gate (#1543) covers them.
    "metadata and provider sessions (#1541)": (
        "CV_SESSION",
        "CV_RATE_LIMITER",
        "CV_HEADERS",
        "CVURL",
        "METRON_API",
        "PROVIDER_STATUS",
        "PROVIDER_BLOCKLIST",
        "PROVIDER_START_ID",
        "BACKENDSTATUS_CV",
        "BACKENDSTATUS_WS",
    ),
    "scheduler, AI clients, DDL and cache state and import progress (#1543)": (
        "SCHED",
        "AI_CLIENT",
        "AI_ASYNC_CLIENT",
        "AI_CIRCUIT_BREAKER",
        "AI_RATE_LIMITER",
        "COMICSORT",
        "PUBLISHER_IMPRINTS",
        "DDL_QUEUED",
        "DDL_STUCK_NOTIFIED",
        "PACK_ISSUEIDS_DONT_QUEUE",
        "FOLDER_CACHE",
        "CHECK_FOLDER_CACHE",
        "IMPORT_STATUS",
        "IMPORT_FILES",
        "IMPORT_TOTALFILES",
        "IMPORT_CID_COUNT",
        "IMPORT_PARSED_COUNT",
        "IMPORT_FAILURE_COUNT",
        "IMPORTLOCK",
        "IMPORTBUTTON",
        "SSE_KEY",
        "SETUP_TOKEN",
    ),
    # ``started`` is retired too, but as a lowercase English word it cannot be
    # banned; the general comicarr.<UPPER> gate does not cover it either.
    "lifecycle and acquisition gate state (#1543)": (
        "SIGNAL",
        "START_UP",
        "DB_EMPTY",
        "ACQUISITION_SCHEMA_READY",
        "ACQUISITION_SCHEMA_VERSION",
        "ACQUISITION_SCHEMA_ERROR",
        "ACQUISITION_WORKERS_BLOCKED",
        "ACQUISITION_BLOCK_REASON",
        "MIGRATION_IN_PROGRESS",
        "MIGRATION_STATUS",
        "MIGRATION_CURRENT_TABLE",
        "MIGRATION_TABLES_COMPLETE",
        "MIGRATION_TABLES_TOTAL",
        "MIGRATION_ERROR",
        "MIGRATION_RECONCILIATION",
    ),
    "download-client route flags (#1543)": (
        "USE_SABNZBD",
        "USE_NZBGET",
        "USE_BLACKHOLE",
        "USE_RTORRENT",
        "USE_DELUGE",
        "USE_TRANSMISSION",
        "USE_QBITTORRENT",
        "USE_UTORRENT",
        "USE_WATCHDIR",
    ),
    "search, pull-list and provider state (#1543)": (
        "WWT_CF_COOKIEVALUE",
        "KEYS_32P",
        "PULLNEW",
        "PULLBYFILE",
        "CURRENT_WEEKNUMBER",
        "CURRENT_YEAR",
        "SEARCH_TIER_DATE",
        "REQS",
        "DB_BACKFILL",
    ),
    # MAINTENANCE itself is retired too, but it is also the [MAINTENANCE-MODE]
    # log prefix; the general comicarr.<UPPER> gate covers it.
    "maintenance-mode progress (#1543)": (
        "MAINTENANCE_UPDATE",
        "MAINTENANCE_DB_TOTAL",
        "MAINTENANCE_DB_COUNT",
    ),
}

# Retired names whose context field is not simply the lowercased name.
_FIELD_RENAMES = {
    "RETURN_THE_NZBQUEUE": "return_nzb_queue",
    "APILOCK": "api_lock",
    "SEARCHLOCK": "search_lock",
    "SNPOOL": "sn_pool",
    "NZBPOOL": "nzb_pool",
    "SEARCHPOOL": "search_pool",
    "PPPOOL": "pp_pool",
    "DDLPOOL": "ddl_pool",
    "MASS_ADD": "mass_add_pool",
    "MASS_REFRESH": "mass_refresh_pool",
    "CVURL": "cv_url",
    "BACKENDSTATUS_CV": "backend_status_cv",
    "BACKENDSTATUS_WS": "backend_status_ws",
    "SCHED": "scheduler",
    "COMICSORT": "comic_sort",
    "IMPORTLOCK": "import_lock",
    "IMPORTBUTTON": "import_button",
}

for _group, _names in _RUNTIME_FIELD_GROUPS.items():
    for _name in _names:
        RETIRED_GLOBALS[_name] = (
            "retired with the %s. Read and write runtime.current().%s "
            "(comicarr.app.core.runtime) instead of a comicarr package global."
            % (_group, _FIELD_RENAMES.get(_name, _name.lower()))
        )

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

# Files that drive historical Comicarr and Mylar3 release trees, where the
# package globals are those releases' real API. Only the runtime-field names
# are exempt there; every other retired name is still checked.
HISTORICAL_FILES = {"tests/fixtures/upgrade_matrix/build.py"}
_RUNTIME_FIELD_NAMES = {name for names in _RUNTIME_FIELD_GROUPS.values() for name in names}


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
            rel = path.relative_to(ROOT).as_posix()
            for name, pattern in RETIRED_PATTERNS.items():
                if rel in HISTORICAL_FILES and name in _RUNTIME_FIELD_NAMES:
                    continue
                if pattern.search(line):
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
