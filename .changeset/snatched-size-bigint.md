---
"comicarr": patch
---

On PostgreSQL and MySQL, grabbing a release larger than 2 GiB (common for packs) no longer fails when its size is recorded. The upgrade widens the stored size column; SQLite installs are unaffected.
