---
"comicarr": patch
---

Fix bulk actions on the Wanted and Upcoming lists doing nothing. Selecting rows
never registered, so the action bar reported no selection and Search or Skip ran
against an empty set.
