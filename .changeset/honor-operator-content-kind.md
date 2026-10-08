---
"comicarr": patch
---

Reclassifying a MangaDex or MyAnimeList series as comic now stops manga sync, RSS chapter search, and manga library stats from treating it as manga. The stored content kind wins; the id prefix is used only when content kind was never set.
