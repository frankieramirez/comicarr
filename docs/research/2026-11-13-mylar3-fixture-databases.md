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

**Fixture recipe, as run (2026-11-13, #1227).** `tests/fixtures/upgrade_matrix/build.py` builds the three Mylar3 fixtures from Mylar3's own schema code rather than from anyone's library. Mylar3 code is fetched at build time and never committed:

1. Fetch the pinned tag from `https://github.com/mylar3/mylar3` into a throwaway bare repository and `git archive` it.
2. Use a Python 3.11 environment with enough of Mylar3's dependencies to import it (`MYLAR_REQUIREMENTS` in the script; set `MYLAR_PYTHON` to reuse one). The tags' own `requirements.txt` cannot be installed as written: v0.4.0 pins `Pillow~=6.2.2`, which no longer builds, and feedparser 5 does not build on 3.11 either. Neither package touches the schema.
3. Write a seed `config.ini` into an empty data directory, then do what `Mylar.py` does at startup, without the web server: set `PROG_DIR`, `DATA_DIR`, `CONFIG_FILE` and `DB_FILE`, call `mylar.config.Config(...).read(startup=True)`, then `mylar.dbcheck()`. Starting `Mylar.py` and killing it is not needed. Calling `dbcheck()` without first reading the config still fails as predicted, because `CONFIG` is `None`. `read(startup=False)` fails too, on v0.6.9 and v0.8.3, because it calls `provider_sequence()`, which queries `provider_searches` before `dbcheck()` has created it.
4. Three tag-specific fixes, all outside the schema: put each tag's bundled `lib/` after the standard library on `sys.path` (v0.4.0 ships a `pathlib` that imports `collections.Sequence`); give feedparser 6 an empty `_FeedParserMixin` (v0.4.0 patches feedparser 5's parser class at import, for RSS only); and install `setuptools<81` (v0.6.9 imports `pkg_resources`).
5. Insert the standard synthetic library with plain SQL, skipping columns the tag lacks, then dump to SQL text with the script's version-stable dumper. `mylar_info` is the only table `dbcheck()` fills (one row, `DatabaseVersion = 0`, from v0.6.4 on). No other generated rows or timestamps needed pinning, and rebuilds reproduce the committed files byte for byte.

What it produced: v0.4.0 creates 19 tables and has no `mylar_info`. v0.6.9 and v0.8.3 create 24 tables each. The matrix imports each through `Mylar3Migration.execute()` into a fresh install. Row counts, statuses and file locations survive, the app boots after the operator releases the reconciliation gate, and a second import adds no rows. The config import has two bugs, filed as #1254 (Mylar's `config_version` is copied, so Comicarr's config migrations run again) and #1255 (unset credentials become the literal `"None"`).

## Sources

- `comicarr/migration.py`: `MIGRATABLE_TABLES`, column-intersection copy via `PRAGMA table_info`, version read from `mylar_info.DatabaseVersion` with `unknown` fallback.
- https://github.com/mylar3/mylar3 tags v0.1.0 to v0.8.3 (clone of the upstream repository): release dates and `mylar/__init__.py` at each tag.
- `mylar/__init__.py` at v0.8.3, `dbcheck()` (line 791 onward): `CREATE TABLE IF NOT EXISTS` plus `ALTER TABLE ... ADD COLUMN` probing; table list; `mylar_info` creation at line 828.
- `git diff v0.6.0 v0.8.3 -- mylar/__init__.py` in mylar3: the added columns listed above.
- `mylar/maintenance.py` at v0.8.3, lines 70, 147 and 345: where `DatabaseVersion` is read and updated.
- `requirements.txt` at v0.8.3: dependencies needed to run the generator.
