---
"comicarr": patch
---

Fixed the "in flight" count reporting work that stopped happening long ago. When Comicarr restarted, it restored every unfinished search and refresh — correct for something a restart interrupted, but it also restored obligations that could never make progress, over and over, with nothing ever giving up on them. On a long-running install those accumulated into hundreds of entries the health count reported as active work, so the number told you nothing. Comicarr now gives up on an item that has come back from three restarts without ever finishing, records it as quarantined, and stops counting it. The bound is restarts rather than elapsed time, so an item that is simply queued behind a long backlog is never abandoned. Entries stranded before this shipped are cleared once on the first start after upgrading; nothing is lost, because whether an issue is wanted lives on the issue itself and anything still wanted is picked up by the next search.

The status endpoint also reports `recovery_pending` alongside `in_flight`, so a surface can say "N in flight (K recovered from a restart)" instead of one number that hides the difference.
