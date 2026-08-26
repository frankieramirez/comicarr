---
"comicarr": minor
---

Series with *Allow packs* enabled can now actually find pack releases on indexers like Nyaa. Searches used to send only issue-numbered queries ("Solo Leveling 001"), which never return pack-shaped titles, so the pack matcher had nothing to work with; an extra bare-title query pass now runs after the numbered ones. Pack detection also understands two more common release shapes: brace-delimited metadata ("Solo Leveling v01-14 {2021-2025} {Digital}"), and numberless complete-series packs ("Solo Leveling (2021-2026) (Digital)" or "{2021-2023}"), which are matched as covering every issue of the series that isn't already downloaded. A grabbed complete-series pack marks all of those issues as Snatched, so "Search all missing" and Review missing stop hunting for them individually.
