---
"comicarr": patch
---

Apply the main database's SQLite settings (WAL journaling, busy timeout, cache sizing) to the ComicVine metadata cache to reduce lock contention during concurrent lookups.
