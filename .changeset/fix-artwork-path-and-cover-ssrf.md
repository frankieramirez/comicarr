---
"comicarr": patch
---

Harden artwork cache paths and cover image fetches against path traversal and SSRF (allowlisted hosts, no redirects, size and content-type caps).
