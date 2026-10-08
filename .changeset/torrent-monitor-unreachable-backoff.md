---
"comicarr": patch
---

If the torrent client is briefly unreachable while Comicarr is watching a download, the monitor now retries with backoff instead of dropping the item. After repeated failures it appears in Needs attention as an unreachable-client review rather than sitting as Snatched until restart.
