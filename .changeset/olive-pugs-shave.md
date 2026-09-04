---
"comicarr": patch
---

Fixed status colours that were missing or unreadable in several places.

In **Settings → Acquisition Health**, badges and stat tiles in the "ready" and "warning" states were drawn with no colour at all — no green or amber border, tint, or text — so they were indistinguishable from a plain tile. Error-state tiles were unaffected. The confirmation banner and the "Verified build" indicator on the same tab had the same problem.

In **manual import**, the "Saved" confirmation was drawn in near-white and was effectively invisible against a light background; it is now green. The **library scan** summary banner lost its green border and tint the same way.

Light mode also renders de-emphasised text correctly again: the separators and small metadata labels on series detail, issue detail, search results, and the releases page were being drawn at full contrast instead of muted. Words that were sitting on that same low-contrast token (series-detail labels, empty-state copy, form labels) now use the readable muted colour.
