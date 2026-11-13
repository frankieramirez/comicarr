# Benchmark

The benchmark times nine operations on a 20,000-issue library and compares
each one with the ceiling in section 7 of the
[Foundations plan](../architecture/foundations-plan.md#7-benchmark-and-budget).
It runs on your machine and in the nightly `Benchmark` workflow. Pull
requests are gated by the query-count budgets in `tests/query_budgets.py`
instead, because wall-clock time on shared CI runners is too noisy to gate
on.

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
| `schema_upgrade` | Schema upgrade | `upgrade_database` from the 0.2x row (`0003_library_chat`) to head, with the library's rows in it | 60 s |

The API reads go through the real routers in-process with a test client and
a signed-in session, so they include FastAPI and JSON encoding but not the
network. Startup launches a real process on a copy of the data folder and
stops it as soon as it answers. It includes any network calls that startup
makes, such as the publisher-imprint download, so a slow connection shows up
there.

The schema upgrade starts from the 0.2x upgrade-matrix fixture
(`tests/fixtures/upgrade_matrix/0.2x.sql`), which v0.20.0's own code built.
The run removes the fixture's small library, inserts the benchmark library's
comics, issues, story arcs, history and pull list with only the columns that
schema had, and upgrades a fresh copy of that database for each sample.
Seeding and copying are not timed.

## The nightly workflow

`.github/workflows/benchmark.yml` runs the benchmark on a GitHub runner:

- every night,
- when you start it from the Actions tab (**Benchmark**, then **Run workflow**),
- on the Changesets release PR. `release.yml` dispatches it on
  `changeset-release/main` whenever it updates that PR, because a push made
  with `GITHUB_TOKEN` starts no `pull_request` workflow.

It never runs on an ordinary pull request.

The job generates a library, runs every operation with
`--baseline tests/benchmark/baseline.json`, and uploads `benchmark-results.json`
as the `benchmark-results` artifact.

### Reading a run

The job summary has one table: each operation's median, the baseline's
median, the ceiling, and whether it was met. Under it:

- **Failures** fail the job. An operation missed its ceiling and has no
  entry in `known_misses.json`, or it has an entry and now meets its
  ceiling.
- **Warnings** do not fail the job. An operation's median is more than 25%
  above the baseline's. Runners vary, so look at a warning that repeats on
  several nights, not at one.
- **Known misses** do not fail the job. They list each listed miss with its
  issue.

Warnings and failures also show as annotations on the run. To compare a
local run the same way:

```bash
npm run benchmark -- run /tmp/comicarr-bench --baseline tests/benchmark/baseline.json
```

### Known misses

`tests/benchmark/known_misses.json` lists the operations that miss their
ceiling today, so the nightly run stays green while each one is worked on:

```json
[{"key": "rescan", "issue": "https://github.com/frankieramirez/comicarr/issues/NNNN"}]
```

Every entry names an operation key and links an open issue. The list only
shrinks: add an entry only in the change that first reports the miss, with
its issue. When the operation meets its ceiling again, the run fails until
the entry is removed and its issue is closed. Nobody raises a ceiling to
make the run pass.

### Updating the baseline

The baseline is a reference for warnings, not a gate. Update it when a change
makes an operation faster or slower on purpose, or when an operation is added:

1. Start **Benchmark** from the Actions tab on `main`, or on your branch.
2. Download the `benchmark-results` artifact.
3. Copy `benchmark-results.json` over `tests/benchmark/baseline.json`, and
   set `machine.note` and `machine.measured` to say where and when it ran.
4. Commit it in its own pull request that says why the numbers moved.

The committed baseline was measured in a Claude Code cloud container, not on
a GitHub runner, so the first nightly runs may warn until it is replaced with
a runner's numbers.

## When a ceiling is missed: the Rust clause

The roadmap reconsiders Rust only if the benchmark misses its budget. That
means a ceiling still missed after one focused optimization pass in Python
(section 7 of the Foundations plan). A miss on its own is not that signal:
it gets an issue and a known-misses entry, then the optimization pass. Only
if the same operation still misses after that pass does the issue go to the
roadmap as a Rust question.
