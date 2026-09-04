# Performance verification — 2026-09-04

Baseline: commit `0c78a354`. Measurements used the same locked dependencies,
Python 3.12.9, Node 22.23.2, and local macOS hardware.

| Measurement | Before | After | Change |
| --- | ---: | ---: | ---: |
| Import queue, median warm SQLite read | 347.92 ms | 70.58 ms | 79.7% less time |
| SQL statements for 50 import groups | 53 | 4 | 92.5% fewer |
| Initial JavaScript, raw | 678,018 bytes | 622,306 bytes | 8.2% smaller |
| Initial JavaScript, gzip | 218,681 bytes | 200,922 bytes | 8.1% smaller |

The import benchmark seeds an isolated SQLite database with 20,000 files in
1,000 groups, requests 50 groups, warms each implementation, and takes the median
of seven reads. It asserts complete response equality with the baseline.
These are local service timings; production network latency and storage can differ.

The import query now fetches file details in batches of at most 100 groups,
selecting only returned fields. Filtering, ordering, pagination, confidence
averages, fallback identities, and legacy NULL/`"None"` volume behavior remain
covered by tests. MySQL retains independent group reads because its collations
can make legacy volume predicates overlap; the measured speedup is for SQLite.

Initial JavaScript counts include the entry and every recursively imported
static JS chunk, with each file compressed separately using Node's default gzip
settings. Route chunks are excluded. Removing the forced table/nuqs/zod bundle
lets the bundler keep table code behind the routes that use it.

The sidebar's “chats today” count was removed, eliminating its 30-thread request.
The AI activity drawer and upgrade modal load on demand. Production-browser tests
verify that Dashboard, Library, and Settings make no hidden chat-thread or AI
activity requests and fetch neither optional modal chunk. The drawer loads on
open and reopens successfully; a pending upgrade still displays and dismisses
the upgrade modal.

Reproduce the measurements from the repository root:

```sh
uv run python scripts/benchmark_import_queue.py --baseline-ref 0c78a354
npm --prefix frontend run build -- --manifest
node scripts/measure_initial_js.mjs frontend/dist /path/to/baseline/dist
```

Build the baseline with the same lockfiles and `--manifest`, preserving its
output in a separate directory before comparison. The benchmark's baseline ref
must be trusted because its query module is executed locally.

Validation completed:

- Backend unit suite: 2,932 passed, including the final import edge cases.
- Frontend unit suite: 480 passed.
- Chromium smoke suite: 17 passed, including two new shell-loading tests.
- Production build, TypeScript check, and required `npm run lint` passed.

The dashboard aggregate rewrite was discarded: its single grouped query took
5.56 ms versus 4.55 ms for the original three queries on 10,000 SQLite rows.
Chrome DevTools MCP was unavailable, so Core Web Vitals were not measured.
