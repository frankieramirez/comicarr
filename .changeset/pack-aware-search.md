---
"comicarr": minor
---

Searches can now match pack releases from any indexer, not just DDL. When a series has *Allow packs* enabled (which still requires torrent search to be on), a result like `Solo Leveling v01-14` or `Invincible #001-144` is recognized as a multi-volume or multi-issue pack instead of being thrown away for having no single issue number. Comicarr checks the pack against what the series is missing, and one grab marks every issue it covers as Snatched — so during "Search all missing", the queued searches for the rest of those issues stop instead of hunting for each one individually. A volume pack covers every chapter belonging to its volumes, and only ever matches volume-tracked series, so a `v01-14` release can never claim issues 1–14 of an issue-tracked comic.
