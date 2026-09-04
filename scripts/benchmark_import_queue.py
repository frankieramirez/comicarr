#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Benchmark the import queue on isolated SQLite data; never opens the app DB.

Run: uv run python scripts/benchmark_import_queue.py --baseline-ref HEAD
The optional ref must be trusted: its query module is executed for comparison.
"""

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from comicarr import db  # noqa: E402
from comicarr.app.series import queries  # noqa: E402
from comicarr.tables import importresults  # noqa: E402


def warm_caches(read):
    read()


def measure(engine, read, repeats):
    statements = []

    def record(*args):
        statements.append(args[2])

    warm_caches(read)
    event.listen(engine, "before_cursor_execute", record)
    samples = []
    try:
        for _ in range(repeats):
            start = time.perf_counter()
            result = read()
            samples.append((time.perf_counter() - start) * 1000)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return result, {"median_ms": round(statistics.median(samples), 2), "queries": len(statements) // repeats}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref")
    parser.add_argument("--groups", type=int, default=1000)
    parser.add_argument("--files-per-group", type=int, default=20)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    baseline = None
    if args.baseline_ref:
        source = subprocess.check_output(
            ["git", "show", f"{args.baseline_ref}:comicarr/app/series/queries.py"], cwd=ROOT, text=True
        )
        namespace = {"__name__": "benchmark_baseline"}
        exec(compile(source, "baseline_queries.py", "exec"), namespace)
        baseline = namespace["get_import_pending"]

    with tempfile.TemporaryDirectory(prefix="comicarr-perf-") as directory:
        engine = create_engine(f"sqlite:///{directory}/benchmark.db")
        importresults.create(engine)
        rows = [
            {
                "impID": f"{group}-{issue}",
                "DynamicName": f"series-{group:06d}",
                "ComicName": f"Series {group:06d}",
                "Volume": None if group % 2 else "1",
                "ComicFilename": f"issue-{issue:04d}.cbz",
                "Status": "Not Imported",
                "MatchConfidence": 80,
            }
            for group in range(args.groups)
            for issue in range(args.files_per_group)
        ]
        with engine.begin() as conn:
            conn.execute(importresults.insert(), rows)
        report = {"rows": len(rows), "page_groups": args.limit, "repeats": args.repeats}
        try:
            with patch.object(db, "get_engine", return_value=engine):
                if baseline:
                    before, report["before"] = measure(engine, lambda: baseline(limit=args.limit), args.repeats)
                after, report["after"] = measure(
                    engine, lambda: queries.get_import_pending(limit=args.limit), args.repeats
                )
                if baseline:
                    assert before == after, "The optimized response differs from the baseline"
                    report["responses_equal"] = True
        finally:
            engine.dispose()
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
