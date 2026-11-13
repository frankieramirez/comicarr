# Benchmark

The benchmark times eight operations on a 20,000-issue library and compares
each one with the ceiling in section 7 of the
[Foundations plan](../architecture/foundations-plan.md#7-benchmark-and-budget).
It runs on your machine. Pull requests are gated by the query-count budgets
in `tests/query_budgets.py` instead, because wall-clock time on shared CI
runners is too noisy to gate on.

## Run it

```bash
npm run benchmark -- generate /tmp/comicarr-bench
npm run benchmark -- run /tmp/comicarr-bench --output results.json
```

`generate` needs an empty or missing folder and takes a few seconds. `run`
takes about a minute and exits non-zero when an operation misses its
ceiling. Pass `--only <key>` (repeatable) to time a single operation, for
example `--only rescan`.

`run` works on a copy of the library's `data` folder, so you can run it
again on the same library. Generate a new library in each week you run it: the
pull list is stamped with the week it was generated in, and the dashboard and
the weekly pull match read the current week.

## The library

`tests/benchmark/library.py` builds it from a fixed seed (`--seed`, default
20261113). The same seed gives the same rows and the same files.

| What | Count |
|---|---|
| Series | 400: 350 comic, 50 manga |
| Issues | 20,000. One series has 500; the rest follow a long tail, a fifth of them five issues or fewer |
| Files | 15,000 one-byte files with realistic names, one per downloaded issue |
| Wanted issues | 2,000 |
| Story arcs | 50, of 6 to 24 issues each |
| History | 5,000 `snatched` rows, each with a matching activity event |
| This week's pull | 500 rows, 120 of them for followed series |

The files hold one byte rather than none because FileChecker skips empty
files, and a rescan that skips every file never parses a name.

`folder/data` holds `comicarr.db` (SQLite, at the current schema head) and a
`config.ini` pointing the comic and manga folders at `folder/library`.
`folder/summary.json` records the seed and the row counts.

## The operations

Each operation runs once as a warm-up, then five times. The table reports
the median.

| Key | Operation | What it times | Ceiling |
|---|---|---|---|
| `library_list` | Library list API | `GET /api/series` | 500 ms |
| `series_detail` | Series detail API | `GET /api/series/{id}` for the 500-issue series | 500 ms |
| `wanted` | Wanted API | `GET /api/wanted/series`, the Wanted page's first read | 500 ms |
| `dashboard` | Dashboard API | The library, activity and upcoming panel reads, one after another | 500 ms |
| `startup` | Startup to ready | From launching `Comicarr.py` until `/api/auth/check-setup` answers | 15 s |
| `rescan` | Full library rescan | `forceRescan` for every series | 5 min |
| `weekly_pull_match` | Weekly pull match | `new_pullcheck` for this week's 500 pull rows | 60 s |
| `release_evaluation` | Release evaluation | One `EvaluationSession` over 200 candidates for one issue | 2 s |

The API reads go through the real routers in-process with a test client and
a signed-in session, so they include FastAPI and JSON encoding but not the
network. Startup launches a real process on a copy of the data folder and
stops it as soon as it answers. It includes any network calls that startup
makes, such as the publisher-imprint download, so a slow connection shows up
there.

The schema upgrade ceiling is not measured yet. It arrives with the nightly
workflow.

## The baseline

`tests/benchmark/baseline.json` holds the first measurement, with the
machine it ran on. It is a reference point, not a gate: compare your
`results.json` with it to see whether a change moved an operation.

A ceiling that the code misses is reported and gets its own issue. Nobody
raises the ceiling to make the run pass.
