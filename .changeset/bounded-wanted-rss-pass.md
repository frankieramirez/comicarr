---
"comicarr": patch
---

Scheduled manga RSS searches no longer pin a CPU core on large libraries. A manga series with no matching RSS entries is now skipped outright, and repeated RSS lookups for the same series run once per pass instead of once per chapter. The scheduled RSS watchlist scan now checks the Wanted list in bounded passes that resume where they left off, re-checks recent releases on every pass, and no longer blocks a manual search while it runs. Optional INI knobs `wanted_search_pass_items` (default 250) and `wanted_search_pass_seconds` (default 120) cap each watchlist pass; `0` disables that cap.
