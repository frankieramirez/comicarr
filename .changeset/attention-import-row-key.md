---
"comicarr": patch
---

Import on Needs attention queues post-processing against that row's own journal key, then marks the band row imported when the worker finishes. A previous import of the same issue no longer silently drops the new one, and a failed or retried import no longer stacks duplicate band rows.
