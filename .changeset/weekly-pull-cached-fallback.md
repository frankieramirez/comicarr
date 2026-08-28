---
"comicarr": patch
---

Keep showing your pull list when the upstream release site is down. Comicarr now falls back to the pull-list data it already has stored for that week and polls your watchlist against it, instead of failing the whole update and leaving the week blank. A failed check for the previous week no longer aborts the current week's update either. When upstream says how soon to retry, the next pull-list check is moved up to match (never sooner than a minute, never honored beyond an hour) so fresh data arrives as soon as the site is back. If there is no stored data for the week at all, the update still reports a failure as before.
