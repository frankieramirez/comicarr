---
"comicarr": minor
---

The old Needs attention API routes are gone. If a script or integration still calls `GET /api/activity/band`, `POST /api/downloads/needs-attention/batch`, or `POST /api/downloads/needs-attention/{release_key}/retry`, `/search-again`, `/stop-wanting` or `/import`, switch it to `GET /api/attention` to read the queue and `POST /api/attention/resolve` to act on it. The resolve route takes an `action` (`retry`, `search_again`, `stop_wanting` or `import`) and a list of `release_keys`, so one call handles one item or many. The Comicarr web UI already uses these routes, so nothing changes in the app itself. An unknown path under `/api` now returns a 404 error instead of the web UI's HTML page, so a call to a removed or mistyped route fails clearly.
