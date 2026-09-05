---
"comicarr": patch
---

Manual post-processing now reports when another import is busy, while queued downloads retry and folder monitoring waits. Imports and restart recovery share execution ownership so overlapping requests cannot release each other's processing lock. Completion preserves download records belonging to other story arcs.
