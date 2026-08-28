---
"comicarr": patch
---

Fix DDL downloads that could stall in Queued and never resume. When a GetComics download failed and Comicarr retried the remaining links, or when a download failed for the last time, the item was left marked as still in progress inside the running process. Any later attempt to queue that same download was treated as a duplicate and silently dropped, so the item sat in Queued until Comicarr was restarted. Those paths now release the item when they finish, and the retry runs as expected.

A GetComics download that ran out of links on its very first attempt also logged a misleading "DDL worker rejected item" error and skipped its own cleanup. It is now reported as an ordinary download failure.
