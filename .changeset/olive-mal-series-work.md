---
"comicarr": patch
---

Fix MyAnimeList manga series being treated as comics in two places: downloads
were post-processed down the ComicVine path instead of the manga path, and the
scheduled chapter check skipped them entirely, so they never picked up new
chapters. MangaDex-added series now also record their MangaDex id, which the
"already in library" check on search results depends on.
