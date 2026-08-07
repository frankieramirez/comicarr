---
"comicarr": patch
---

Stopped abandoned searches and refreshes being restored forever and counted as active work. When Comicarr restarted, it restored every unfinished search and refresh — correct for something a restart interrupted, but it also restored obligations that could never make progress, over and over, with nothing ever giving up on them. On a long-running install those accumulated into hundreds of entries. Comicarr now gives up on one that has come back from three restarts without ever finishing, records it as quarantined, and stops counting it. The bound is restarts rather than elapsed time, so an item simply queued behind a long backlog is never abandoned. Entries stranded before this shipped are cleared once on the first start after upgrading; nothing is lost, because whether an issue is wanted lives on the issue itself, and anything still wanted is picked up by the next search.

Note that this covers searches and refreshes only. A separate source of stale entries — downloads that were handed to a client and never reported back — is not addressed here, so the "in flight" number may still read higher than the work actually moving.

The status endpoint also reports `recovery_pending` alongside `in_flight`, so a surface can say "N in flight (K recovered from a restart)" instead of one number that hides the difference.
