---
"comicarr": patch
---

A post-processing stop no longer stays in flight forever. Comicarr retries it a few times on restart, then moves it to Needs attention instead of blocking newer work.
