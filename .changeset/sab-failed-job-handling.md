---
"comicarr": patch
---

When SABnzbd reports an Unpack or Repair failure, Comicarr now honors the Failed download handling setting: retries run when it is on, and the snatched job is marked failed instead of being polled forever when it is off.
