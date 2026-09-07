---
"comicarr": patch
---

Interactive search no longer crashes when DDL(External) is enabled. That provider was still called as if a MegaNZ search client existed on the external-server module; the shipped placeholder did not, so the search raised AttributeError and the whole interactive run failed. The missing client is now present and returns no results instead of crashing, so other providers can finish the search. The Release Review sheet lists DDL(External) under provider failures with the reason, and the log says once per start that the client is not installed instead of on every search.
