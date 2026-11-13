# Which Mylar3 databases do people migrate from, and how do we build a fixture without a real library?

## Findings

Users of upstream `mylar3/mylar3` can arrive from any tag between v0.4.0 (June 2020) and v0.8.3 (August 2025, the latest upstream tag). Forks of Mylar3 were not examined and are not covered by these fixtures. Mylar3 has no numbered schema migrations. `dbcheck()` in `mylar/__init__.py` creates every table with `CREATE TABLE IF NOT EXISTS` and then probes columns one at a time, adding any that are missing with `ALTER TABLE ... ADD COLUMN`. So an old database is upgraded in place each time a newer Mylar3 starts, and a database's shape depends on the last Mylar3 release that opened it.

The schema grew slowly. Counting statements in `dbcheck()`:

| Tag | Date | Tables created | Column additions |
|-----|------|----------------|------------------|
| v0.4.0 | 2020-06-01 | 20 | 112 |
| v0.5.0 | 2021-03-29 | 21 | 117 |
| v0.6.0 | 2021-11-02 | 21 | 122 |
| v0.7.0 | 2022-12-09 | 25 | 131 |
| v0.8.0 | 2024-03-14 | 25 | 135 |
| v0.8.3 | 2025-08-17 | 25 | 135 |

Between v0.6.0 and v0.8.3 the columns added to tables Comicarr migrates are `comics.cv_removed`, `issues.forced_file`, `rssdb.Issue_Number`, `rssdb.ComicName`, `storyarcs.ArcImage`, `jobhistory.last_date`, and five `ddl_info` columns (`site`, `submit_date`, `pack`, `link_type`, `tmp_filename`). The schema has not changed since v0.8.0.

`mylar_info.DatabaseVersion` first appears in v0.6.4 (2022-02-08). Before that the table does not exist, so Comicarr's migration preview reports the version as `unknown` for any database last opened by v0.6.3 or older. After that it is 0 until `maintenance.py` bumps it during a maintenance run.

Comicarr's reader is tolerant by design. `comicarr/migration.py` copies the 16 tables in `MIGRATABLE_TABLES`, skips any table missing on either side, and copies only the columns both sides share (via `PRAGMA table_info`). The main risks an upgrade test should catch are therefore a missing `mylar_info`, missing late columns, and data in columns Comicarr does not have.

**Recommended fixture recipe.** Build fixtures from Mylar3's own schema code rather than from anyone's library:

1. Check out a pinned tag in a throwaway Python 3 environment with that tag's `requirements.txt`.
2. Point Mylar3 at an empty data directory and let `dbcheck()` create the schema by starting `Mylar.py --nolaunch --datadir <dir>` and stopping it after startup. Calling `dbcheck()` directly after setting only `DB_FILE` does not work: `CONFIG` is `None` at import, and `dbcheck()` reads `CONFIG.DYNAMIC_UPDATE`.
3. Insert a small synthetic library with plain SQL: a few comics, their issues and annuals, a story arc, a snatched row, a failed row and a weekly row, using made-up IDs and names.
4. Export each database to SQL text (`sqlite3 <name>.db .dump > <name>.sql`) and commit the `.sql` files plus the generator script, so they can be reviewed and rebuilt.

Three fixtures cover the range: **v0.4.0** (oldest, no `mylar_info`), **v0.6.9** (mid-range, `mylar_info` present, before the 2022 additions), and **v0.8.3** (current). The generator is headless and needs no network beyond fetching the tag.

Caveat: this note did not run the recipe. Step 2 should be confirmed against v0.4.0, whose startup code is older.

## Sources

- `comicarr/migration.py`: `MIGRATABLE_TABLES`, column-intersection copy via `PRAGMA table_info`, version read from `mylar_info.DatabaseVersion` with `unknown` fallback.
- https://github.com/mylar3/mylar3 tags v0.1.0 to v0.8.3 (clone of the upstream repository): release dates and `mylar/__init__.py` at each tag.
- `mylar/__init__.py` at v0.8.3, `dbcheck()` (line 791 onward): `CREATE TABLE IF NOT EXISTS` plus `ALTER TABLE ... ADD COLUMN` probing; table list; `mylar_info` creation at line 828.
- `git diff v0.6.0 v0.8.3 -- mylar/__init__.py` in mylar3: the added columns listed above.
- `mylar/maintenance.py` at v0.8.3, lines 70, 147 and 345: where `DatabaseVersion` is read and updated.
- `requirements.txt` at v0.8.3: dependencies needed to run the generator.
