---
"comicarr": patch
---

A refresh that cannot reach the metadata provider no longer renames a series that has no folder set to "Comic ID: <id>" (and then "Fetch failed…" with a failed-add entry in Activity), and no longer un-pauses it. The series keeps its name and status, and the next refresh tries again.
