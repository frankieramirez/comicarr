---
"comicarr": patch
---

When SABnzbd reports a failed job (Unpack, Repair, moving, or another stage), Comicarr now honors the Failed download handling setting: retries run when it is on, and the snatched job is marked failed instead of being polled forever when it is off. Restart recovery closes those rows the same way.
