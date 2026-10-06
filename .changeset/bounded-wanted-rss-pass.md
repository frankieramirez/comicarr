---
"comicarr": patch
---

Scheduled Wanted and RSS backlog searches now run in bounded passes and resume where they left off, so a large Wanted list can no longer pin a CPU core for days or block a manual search. RSS lookups for the same series are reused until the feed cache refreshes. Optional INI knobs `wanted_search_pass_items` (default 250) and `wanted_search_pass_seconds` (default 120) cap each pass; `0` disables that cap.
