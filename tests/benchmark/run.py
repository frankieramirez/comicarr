#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Time each benchmark operation against its ceiling.

Every operation runs once as a warm-up and then five times; the median is
compared with the ceiling from section 7 of
``docs/architecture/foundations-plan.md``. The run works on a copy of the
library's ``data`` folder, so the generated library stays as generated.

``compare`` checks results against the committed baseline and the
known-misses list: a missed ceiling fails unless an open issue covers it, and
a slowdown of more than 25% is a warning only.
"""

import json
import os
import platform
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNS = 5
STARTUP_TIMEOUT = 120
BASELINE = HERE / "baseline.json"
KNOWN_MISSES = HERE / "known_misses.json"
SLOWDOWN = 1.25
UPGRADE_ROW = ROOT / "tests" / "fixtures" / "upgrade_matrix" / "0.2x.sql"


@dataclass(frozen=True)
class Operation:
    key: str
    label: str
    ceiling: float  # seconds


OPERATIONS = (
    Operation("library_list", "Library list API", 0.5),
    Operation("series_detail", "Series detail API, 500-issue series", 0.5),
    Operation("wanted", "Wanted API", 0.5),
    Operation("dashboard", "Dashboard API", 0.5),
    Operation("startup", "Startup to ready", 15),
    Operation("rescan", "Full library rescan", 300),
    Operation("weekly_pull_match", "Weekly pull match", 60),
    Operation("release_evaluation", "Release evaluation, 200 candidates for one issue", 2),
    Operation("schema_upgrade", "Schema upgrade of the 0.2x row at benchmark size", 60),
)


def time_it(action, runs=RUNS, setup=None):
    """Warm up once, then return ``runs`` wall-clock samples in seconds.

    ``setup``, when given, runs untimed before each call and its result is
    passed to ``action``.
    """
    samples = []
    for attempt in range(runs + 1):
        args = (setup(),) if setup else ()
        start = time.perf_counter()
        action(*args)
        if attempt:
            samples.append(time.perf_counter() - start)
    return samples


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_once(data_dir):
    """Start Comicarr on a fresh copy of ``data_dir``; return seconds until it answers.

    Ready means the HTTP server answers ``/api/auth/check-setup``, which the
    sign-in page calls first. The process is stopped as soon as it answers.
    """
    with tempfile.TemporaryDirectory(prefix="comicarr-bench-start-") as scratch:
        copy = Path(scratch) / "data"
        shutil.copytree(data_dir, copy)
        port = _free_port()
        url = "http://127.0.0.1:%d/api/auth/check-setup" % port
        command = [sys.executable, str(ROOT / "Comicarr.py"), "--nolaunch", "--datadir", str(copy), "--port", str(port)]
        start = time.perf_counter()
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            while time.perf_counter() - start < STARTUP_TIMEOUT:
                if process.poll() is not None:
                    raise RuntimeError("Comicarr exited with %s before it was ready" % process.returncode)
                try:
                    with urllib.request.urlopen(url, timeout=1) as response:
                        if response.status == 200:
                            return time.perf_counter() - start
                except (urllib.error.URLError, ConnectionError, TimeoutError):
                    pass
                time.sleep(0.02)
            raise RuntimeError("Comicarr was not ready within %d s" % STARTUP_TIMEOUT)
        finally:
            # Shutdown is not measured, and the copy is thrown away.
            process.kill()
            process.wait()


def measure_startup(data_dir, runs=RUNS):
    start_once(data_dir)
    return [start_once(data_dir) for _ in range(runs)]


def initialize(data_dir):
    """Initialize Comicarr in this process against ``data_dir``, without the scheduler."""
    import comicarr

    comicarr.DATA_DIR = str(data_dir)
    comicarr.CONFIG_FILE = str(Path(data_dir) / "config.ini")
    comicarr.DB_FILE = str(Path(data_dir) / "comicarr.db")
    comicarr.initialize(comicarr.CONFIG_FILE)


def api_client():
    """A test client over the series and dashboard routers, signed in."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import comicarr
    from comicarr.app.core.context import AppContext, get_context
    from comicarr.app.core.security import require_session
    from comicarr.app.dashboard.router import router as dashboard_router
    from comicarr.app.series.router import router as series_router

    app = FastAPI()
    app.include_router(series_router)
    app.include_router(dashboard_router)
    app.dependency_overrides[require_session] = lambda: "benchmark"
    app.dependency_overrides[get_context] = lambda: AppContext(config=comicarr.CONFIG)
    return TestClient(app)


def _get(client, *paths):
    def action():
        for path in paths:
            response = client.get(path)
            if response.status_code != 200:
                raise RuntimeError("GET %s returned %s" % (path, response.status_code))

    return action


def rescan_all():
    """forceRescan every series, as a full library rescan does."""
    from comicarr import db, updater

    for row in db.raw_select_all("SELECT ComicID FROM comics ORDER BY ComicID"):
        updater.forceRescan(row["ComicID"])


def weekly_pull_match():
    from comicarr import weeklypull
    from comicarr.app.storyarcs.service import get_current_week

    week, year = get_current_week()
    return lambda: weeklypull.new_pullcheck(int(week), year)


def release_candidates(series, others, count=200):
    """Search results for one issue: mostly the series itself, as a name search returns."""
    name, year = series["ComicName"], series["ComicYear"]
    wanted = int(series["Total"]) // 2
    titles = ["%s %03d (2018) (Digital) (Zone-Empire)" % (name, wanted)]
    for n in range(1, 81):
        titles.append("%s %03d (%s) (Digital) (Group)" % (name, n + wanted // 2, year))
    for n in range(1, 31):
        titles.append("%s #%d (%s) (webrip)" % (name, n, year))
    for n in range(1, 21):
        titles.append("%s v2 %03d (2021) (Digital)" % (name, n))
    for k in range(20):
        titles.append("%s #%d-%d (%s) (Pack)" % (name, k * 25 + 1, k * 25 + 25, year))
    for other in others:
        titles.append("%s %03d (2018) (Digital)" % (other, wanted))
    titles = titles[:count]
    return [
        {
            "title": title,
            "link": "https://indexer.invalid/get/%d" % index,
            "pubdate": "Wed, 10 Jan 2018 12:00:00 +0000",
            "length": str(40 * 1024 * 1024),
            "site": "experimental",
            "id": "candidate-%d" % index,
            "pack": "(Pack)" in title,
            "seeders": "5",
            "peers": "1",
        }
        for index, title in enumerate(titles)
    ], wanted


def release_evaluation(comic_id):
    from comicarr import db
    from comicarr.app.search.evaluation import EvaluationSession

    series = db.raw_select_one("SELECT * FROM comics WHERE ComicID = ?", [comic_id])
    others = [
        row["ComicName"]
        for row in db.raw_select_all(
            "SELECT ComicName FROM comics WHERE ComicID != ? ORDER BY ComicID LIMIT 50", [comic_id]
        )
    ]
    entries, number = release_candidates(series, others)
    if len(entries) != 200:
        raise RuntimeError("expected 200 candidates, built %d" % len(entries))
    info = {
        "ComicName": series["ComicName"],
        "nzbprov": "experimental",
        "RSS": "no",
        "UseFuzzy": "1",
        "StoreDate": "2018-01-01",
        "IssueDate": "2018-01-01",
        "digitaldate": "0000-00-00",
        "booktype": "Print",
        "ignore_booktype": False,
        "SeriesYear": series["ComicYear"],
        "ComicVersion": None,
        "IssDateFix": "no",
        "ComicYear": "2018",
        "IssueID": "%s-%04d" % (comic_id, number),
        "ComicID": comic_id,
        "IssueNumber": str(number),
        "manual": True,
        "newznab_host": None,
        "torznab_host": None,
        "oneoff": False,
        "tmpprov": "experimental",
        "SARC": None,
        "IssueArcID": None,
        "cmloopit": 3,
        "findcomiciss": str(number),
        "intIss": number * 1000,
        "chktpb": 0,
        "provider_stat": {"type": "experimental", "id": 1, "active": True, "hits": 0},
    }
    return lambda: EvaluationSession().evaluate(entries, info)


# Tables seeded at benchmark size in the 0.2x row; the fixture's own small
# library is removed first.
UPGRADE_TABLES = ("comics", "issues", "storyarcs", "snatched", "weekly")


def seed_upgrade_row(library, database):
    """Write the 0.2x upgrade-matrix row to ``database``, seeded with the benchmark library.

    The row is that release's schema at ``0003_library_chat``, built from its
    git tag (see ``tests/fixtures/upgrade_matrix/build.py``). The library's rows
    are rebuilt from its seed and inserted with only the columns the old
    schema had, as an install that ran 0.2x for a while would hold them.
    """
    import sqlite3

    from tests.benchmark.library import Spec, build_rows, pull_rows

    library = Path(library)
    summary = json.loads((library / "summary.json").read_text())
    rows = build_rows(Spec(**summary["spec"]), summary["seed"], library)
    rows["weekly"] = pull_rows(Spec(**summary["spec"]), rows, rows["rng"])
    connection = sqlite3.connect(database)
    try:
        connection.executescript(UPGRADE_ROW.read_text(encoding="utf-8"))
        for table in UPGRADE_TABLES:
            present = {row[1] for row in connection.execute('PRAGMA table_info("%s")' % table)}
            connection.execute('DELETE FROM "%s"' % table)
            columns = [column for column in rows[table][0] if column in present]
            connection.executemany(
                'INSERT INTO "%s" (%s) VALUES (%s)'
                % (table, ", ".join('"%s"' % c for c in columns), ", ".join("?" for _ in columns)),
                [tuple(row.get(c) for c in columns) for row in rows[table]],
            )
        connection.commit()
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        connection.close()
    if revision != "0003_library_chat":
        raise RuntimeError("the 0.2x row is at %s, expected 0003_library_chat" % revision)
    return database


def schema_upgrade(library, scratch):
    """Time ``upgrade_database`` from the seeded 0.2x row, on a fresh copy each run."""
    from sqlalchemy import create_engine

    from comicarr.app.core.schema import upgrade_database

    template = seed_upgrade_row(library, Path(scratch) / "upgrade-0.2x.db")
    copies = iter(range(RUNS + 1))

    def setup():
        copy = Path(scratch) / ("upgrade-%d.db" % next(copies))
        shutil.copyfile(template, copy)
        return copy

    def action(copy):
        engine = create_engine("sqlite:///%s" % copy)
        try:
            upgrade_database(engine)
        finally:
            engine.dispose()

    return action, setup


def machine():
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor() or platform.machine(),
        "cpus": os.cpu_count(),
    }


def run(library, only=None):
    """Measure every operation against ``library`` and return the results."""
    library = Path(library).resolve()
    summary = json.loads((library / "summary.json").read_text())
    wanted = set(only or [op.key for op in OPERATIONS])
    samples = {}
    with tempfile.TemporaryDirectory(prefix="comicarr-bench-run-") as scratch:
        data = Path(scratch) / "data"
        shutil.copytree(library / "data", data)
        if "startup" in wanted:
            samples["startup"] = measure_startup(library / "data")
        initialize(data)
        largest = summary["largest_series"]
        with api_client() as client:
            reads = {
                "library_list": _get(client, "/api/series"),
                "series_detail": _get(client, "/api/series/%s" % largest),
                "wanted": _get(client, "/api/wanted/series"),
                "dashboard": _get(
                    client, "/api/dashboard/library", "/api/dashboard/activity", "/api/dashboard/upcoming"
                ),
            }
            for key, action in reads.items():
                if key in wanted:
                    samples[key] = time_it(action)
        if "rescan" in wanted:
            samples["rescan"] = time_it(rescan_all)
        if "weekly_pull_match" in wanted:
            samples["weekly_pull_match"] = time_it(weekly_pull_match())
        if "release_evaluation" in wanted:
            samples["release_evaluation"] = time_it(release_evaluation(largest))
        if "schema_upgrade" in wanted:
            action, setup = schema_upgrade(library, scratch)
            samples["schema_upgrade"] = time_it(action, setup=setup)
        from comicarr import db

        db.shutdown_engine()

    operations = []
    for op in OPERATIONS:
        if op.key not in samples:
            continue
        median = statistics.median(samples[op.key])
        operations.append(
            {
                "key": op.key,
                "label": op.label,
                "median_s": round(median, 4),
                "samples_s": [round(s, 4) for s in samples[op.key]],
                "ceiling_s": op.ceiling,
                "met": median <= op.ceiling,
            }
        )
    return {"machine": machine(), "library": summary, "runs": RUNS, "operations": operations}


def _seconds(value):
    if value < 1:
        return "%d ms" % round(value * 1000)
    return "%.2f s" % value


def table(results):
    """The results as a plain-text table, measured against ceiling."""
    rows = [("Operation", "Median", "Ceiling", "Result")]
    for op in results["operations"]:
        rows.append(
            (op["label"], _seconds(op["median_s"]), _seconds(op["ceiling_s"]), "met" if op["met"] else "MISSED")
        )
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def load_known_misses(path=KNOWN_MISSES):
    """Operation keys whose missed ceiling has an open issue, mapped to that issue."""
    entries = json.loads(Path(path).read_text())
    known = {}
    for entry in entries:
        key, issue = entry.get("key"), entry.get("issue", "")
        if key not in {op.key for op in OPERATIONS}:
            raise ValueError("known_misses.json names an unknown operation: %r" % key)
        if not issue.startswith("https://github.com/"):
            raise ValueError("known_misses.json entry for %s must link its issue" % key)
        known[key] = issue
    return known


@dataclass
class Verdict:
    failures: list
    warnings: list
    notes: list

    @property
    def ok(self):
        return not self.failures


def compare(results, baseline=None, known_misses=None):
    """Judge ``results``: missed ceilings fail, slowdowns over 25% warn.

    A miss listed in ``known_misses`` is a note, not a failure. A listed
    operation that now meets its ceiling fails too, so the list only shrinks:
    remove the entry and close its issue.
    """
    known = known_misses or {}
    before = {op["key"]: op for op in (baseline or {}).get("operations", [])}
    verdict = Verdict([], [], [])
    for op in results["operations"]:
        key, label = op.get("key"), op["label"]
        if not op["met"]:
            if key in known:
                verdict.notes.append("%s missed its ceiling, known: %s" % (label, known[key]))
            else:
                verdict.failures.append(
                    "%s missed its ceiling: %s against %s"
                    % (label, _seconds(op["median_s"]), _seconds(op["ceiling_s"]))
                )
        elif key in known:
            verdict.failures.append(
                "%s now meets its ceiling; remove it from known_misses.json and close %s" % (label, known[key])
            )
        old = before.get(key)
        if old and op["median_s"] > old["median_s"] * SLOWDOWN:
            verdict.warnings.append(
                "%s is %d%% slower than the baseline: %s against %s"
                % (
                    label,
                    round((op["median_s"] / old["median_s"] - 1) * 100),
                    _seconds(op["median_s"]),
                    _seconds(old["median_s"]),
                )
            )
    return verdict


def markdown(results, verdict, baseline=None):
    """A job-summary report: the table, then failures, warnings and notes."""
    before = {op["key"]: op["median_s"] for op in (baseline or {}).get("operations", [])}
    lines = ["## Benchmark", "", "| Operation | Median | Baseline | Ceiling | Result |", "|---|---|---|---|---|"]
    for op in results["operations"]:
        old = before.get(op.get("key"))
        lines.append(
            "| %s | %s | %s | %s | %s |"
            % (
                op["label"],
                _seconds(op["median_s"]),
                _seconds(old) if old is not None else "none",
                _seconds(op["ceiling_s"]),
                "met" if op["met"] else "**missed**",
            )
        )
    for title, items in (
        ("Failures", verdict.failures),
        ("Warnings", verdict.warnings),
        ("Known misses", verdict.notes),
    ):
        if items:
            lines += ["", "### %s" % title, ""] + ["- %s" % item for item in items]
    return "\n".join(lines) + "\n"
