---
"comicarr": patch
---

Keep showing your pull list when the upstream release site is down. Comicarr now falls back to the pull-list data it already has stored for that week and polls your watchlist against it, instead of failing the whole update and leaving the week blank. A failed check for the previous week no longer aborts the current week's update either. If there is no stored data for the week, the update still reports a failure as before.
