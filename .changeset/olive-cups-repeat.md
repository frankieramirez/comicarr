---
"comicarr": patch
---

Fix Mylar3 config migration discarding every setting when the source config used NZBsu or DOGnzb

`_BAD_DEFINITIONS` carried seven remapping entries for NZBsu and DOGnzb — providers Mylar3 shipped built in and Comicarr no longer defines. `migrate_mylar3_config` reads that table independently of `_CONFIG_DEFINITIONS`, so a `config.ini` with an `[NZBsu]` or `[DOGnzb]` section produced keys nothing could define. `process_kwargs` then raised `KeyError` inside `writeconfig`, and the caller swallowed it as "config migration failed (data migration succeeded)" — so all 400+ settings were dropped and the install came up on defaults, with one log line as the only trace.

The seven entries are removed, and the migration now skips any undefined key with a warning instead of losing the whole batch to it.
