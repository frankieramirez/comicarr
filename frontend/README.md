# Comicarr Frontend

The frontend is a React 19 + Vite application. Production builds are served by
the FastAPI application from `frontend/dist`.

## Common Commands

```bash
npm run dev
npm run lint
npm run format:check
npm run typecheck
npm run test:run
npm run build
```

## E2E Tests

The Playwright suite runs against the built React bundle served by Comicarr,
not against Vite or MSW. Build the frontend first, then run the suite from this
directory:

```bash
npm run build
npm run test:e2e:smoke
npm run test:e2e:full
```

`npm run test:e2e` is an alias for the required Chromium smoke suite. Smoke
tests start Comicarr with an isolated seeded data directory, sign in through
the real login page, and verify protected navigation plus API/auth contracts.
The full suite starts with an empty data directory and covers the first-run
setup token flow plus restart behavior.

Useful environment variables:

- `COMICARR_E2E_PORT`: port for the seeded smoke server, default `18090`.
- `COMICARR_E2E_BASE_URL`: use an already-running Comicarr instance instead
  of letting Playwright start one.
- `COMICARR_E2E_DATADIR`: data directory for the managed smoke server.
- `COMICARR_E2E_PYTHON`: Python executable used to start `Comicarr.py`.
- `COMICARR_E2E_KEEP_DATA`: set to `1` to preserve generated data for
  debugging.
- `COMICARR_E2E_FULL_PORT`: alternate port for the first-run full suite,
  default `COMICARR_E2E_PORT + 1`.
- `COMICARR_E2E_FULL_DATADIR`: data directory for the first-run full suite.

When debugging failures, inspect `playwright-report/` and `test-results/e2e/`.
Both directories are ignored locally and uploaded by CI on failure.
