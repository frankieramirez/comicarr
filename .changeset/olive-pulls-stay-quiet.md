---
"comicarr": patch
---

Report a pull-list outage in plain language instead of dumping raw response
headers into the log. When the pull-list host is unhealthy, Cloudflare answers
on its behalf; only one of those replies was recognised, so the rest were
logged as an unreadable header dump. All of them now explain that the source is
temporarily unreachable and that the data shown may be stale, including how
long upstream asked us to wait when it says so.
