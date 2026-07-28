---
"comicarr": patch
---

Surface the actual reason a search is blocked instead of a generic placeholder.

When no acquisition route was handoff-ready, the search-missing preview and the
Wanted force-search both read a `reason` key that `get_search_health()` never
returns, so every blocked search reported `no_viable_acquisition_route` no matter
the cause. Route readiness already computes a specific blocker per route
(`path_not_ready`, `client_not_ready`, `disabled`, `providers_temporarily_blocked`,
a maintenance hold); the blocked response now reports the one closest to ready,
and the series search dialog explains it in plain language while keeping the raw
code visible for support.
