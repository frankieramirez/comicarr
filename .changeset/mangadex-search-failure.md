---
"comicarr": patch
---

When MangaDex can't be reached, manga search now says so instead of showing an empty "no results" list, both in the app and for AI agents using `find_series` (which now get a retryable "provider unavailable" answer). This also covers searches that fall back to MangaDex after MyAnimeList fails.
