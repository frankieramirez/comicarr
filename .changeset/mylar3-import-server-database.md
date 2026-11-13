---
"comicarr": patch
---

Importing a Mylar3 library now works when Comicarr runs on PostgreSQL or MySQL. Before, the import wrote to a SQLite file beside the install instead of your configured database, so it reported success and your library stayed empty. The automatic pre-import backup still runs only on SQLite; back up a PostgreSQL or MySQL database with `pg_dump` or `mysqldump` before importing.
