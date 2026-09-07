---
"comicarr": patch
---

Interactive search no longer crashes when DDL(External) is enabled. That provider was still called as if a MegaNZ search client existed on the external-server module; the shipped placeholder did not, so the search raised AttributeError and the whole interactive run failed. The missing client is now present and returns no results instead of crashing, so other providers can finish the search.
