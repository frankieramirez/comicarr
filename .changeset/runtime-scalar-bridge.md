---
"comicarr": patch
---

Failed post-migration gate refreshes now block automatic search and downloads in both the scheduler and the operator-facing status. Previously only one copy of that flag updated, so acquisition could keep running after a migration error.
