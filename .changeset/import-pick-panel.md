---
"comicarr": minor
---

Import now splits the review queue into **Needs a pick**, **Confident** and **Ignored** tabs, each with its count, and has a filter box. Clicking a group opens a pick panel beside the table. It lists the series the files could be, each scored the same way the inbox scan scores it and marked as in your library or not. When your library has no close match, it also searches ComicVine or MangaDex. The panel says why the group stopped for you: two series share the title, the best guess fell under your auto-import bar, or the files name more than one year. It also shows each file's size and when the files were found, and lets you edit issue numbers in place. **Import as …** settles the group; for a series that isn't in your library yet, it adds the series first.

When you match an inbox folder, Comicarr remembers the series you picked, and new files that later land in that same folder import as that series. Groups that clear your auto-import bar but didn't import on their own wait under Confident, and **Import N confident matches** in the header imports all of them at once. This release adds a database migration for the remembered folder picks.
