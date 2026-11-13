#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Benchmark CLI: ``generate`` a library, then ``run`` the operations on it.

    uv run python -m tests.benchmark generate /tmp/bench
    uv run python -m tests.benchmark run /tmp/bench --output results.json

See docs/testing/benchmark.md.
"""

import argparse
import json
import logging
import os
import sys

from tests.benchmark.library import DEFAULT_SEED, generate
from tests.benchmark.run import KNOWN_MISSES, OPERATIONS, compare, load_known_misses, markdown, run, table


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m tests.benchmark", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    make = commands.add_parser("generate", help="build the benchmark library in a new folder")
    make.add_argument("folder")
    make.add_argument("--seed", type=int, default=DEFAULT_SEED)

    measure = commands.add_parser("run", help="time every operation against its ceiling")
    measure.add_argument("folder", help="a folder made by generate")
    measure.add_argument("--output", help="write the results as JSON to this file")
    measure.add_argument("--only", action="append", choices=[op.key for op in OPERATIONS], help="repeatable")
    measure.add_argument("--baseline", help="warn when an operation is over 25%% slower than this results file")
    measure.add_argument("--known-misses", default=str(KNOWN_MISSES), help="misses that have an open issue")
    measure.add_argument(
        "--summary",
        default=os.environ.get("GITHUB_STEP_SUMMARY"),
        help="append a Markdown report to this file (default: $GITHUB_STEP_SUMMARY)",
    )

    args = parser.parse_args(argv)
    if args.command == "generate":
        summary = generate(args.folder, seed=args.seed)
        print(json.dumps(summary, indent=2))
        return 0

    # Comicarr logs every rescanned file; keep the table readable.
    logging.disable(logging.INFO)
    results = run(args.folder, only=args.only)
    logging.disable(logging.NOTSET)
    if args.output:
        with open(args.output, "w") as handle:
            json.dump(results, handle, indent=2)
            handle.write("\n")
    print(table(results))

    baseline = None
    if args.baseline:
        with open(args.baseline) as handle:
            baseline = json.load(handle)
    verdict = compare(results, baseline, load_known_misses(args.known_misses))
    if args.summary:
        with open(args.summary, "a") as handle:
            handle.write(markdown(results, verdict, baseline))
    annotate = os.environ.get("GITHUB_ACTIONS") == "true"
    for kind, items in (("warning", verdict.warnings), ("notice", verdict.notes), ("error", verdict.failures)):
        for item in items:
            print("::%s::%s" % (kind, item) if annotate else "%s: %s" % (kind.capitalize(), item), file=sys.stderr)
    if verdict.failures:
        missed = [op["label"] for op in results["operations"] if not op["met"]]
        if missed:
            print("\nMissed: %s" % ", ".join(missed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
