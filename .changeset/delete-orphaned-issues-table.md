---
"comicarr": patch
---

Remove the unreachable `IssuesTable` component and the code that existed only to support it. The component was dropped from the series detail page during the frontend redesign and has had no caller since, along with its bulk-metatag hook, progress-bar cell and two supporting types. No user-visible behaviour changes.
