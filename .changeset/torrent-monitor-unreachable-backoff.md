---
"comicarr": patch
---

If the torrent client is briefly unreachable while Comicarr is watching a download, the monitor now retries with growing backoff for about 30 minutes instead of dropping the item. After that it appears in Needs attention as an unreachable-client review rather than sitting as Snatched until restart. A bad torrent hash or a broken auto-snatch script is reported as that failure, not as a client outage.
