---
"comicarr": patch
---

Adding a comic found through Metron search now works. With *Use Metron for search* enabled, search results carried Metron's own series id, and adding one — from the search page or the library import scan — looked that id up on ComicVine as if it were a ComicVine volume, which failed with "list index out of range" (or silently added the wrong series). Metron results are now tagged as Metron's, and adding one resolves the series to its ComicVine volume through Metron's own record first; a series Metron can't map to ComicVine fails with a clear message instead of a crash. Separately, importing a manga whose MangaDex entry has no chapters (for example one whose chapters were removed) no longer aborts with "'list' object has no attribute 'items'" after creating the series — the import completes and falls back to MyAnimeList's chapter count as designed.
