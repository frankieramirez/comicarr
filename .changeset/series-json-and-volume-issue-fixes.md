---
"comicarr": patch
---

Two crashes in ComicVine refreshes are fixed:
- With the ComicVine-only setting (`cv_only`) switched off, refreshing a series' issue list no longer fails.
- Writing `series.json` for a series with no known start year no longer stops the refresh. If you have set a corrected year for that series, it is used. Otherwise Comicarr skips the file for that series and logs a warning.
