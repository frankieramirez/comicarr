---
"comicarr": patch
---

Fix bulk actions on the Wanted and Upcoming lists doing nothing. Selecting rows
never registered, so the action bar reported no selection and Search or Skip ran
against an empty set.

Clearing the selection, changing page, or a row disappearing now also unchecks
the rows, so a later bulk action cannot skip issues you already cleared or that
are no longer on screen. A bulk Skip or Mark Wanted that fails partway through
now reports how many issues were applied and keeps only the failures selected,
instead of reporting a total failure and retrying the ones that succeeded.
