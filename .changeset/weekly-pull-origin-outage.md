---
"comicarr": patch
---

When the weekly pull-list source is down (Cloudflare 520-524), Releases says Walksoftly is unreachable upstream. The Weekly Pullist job honors a short Retry-After once, then waits for the normal interval until the source comes back.
