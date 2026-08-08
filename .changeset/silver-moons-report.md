---
"comicarr": patch
---

The dashboard no longer goes blank when one thing behind it breaks. Every panel — the library figures, the queue, recent activity, this week's releases, recent chats — now loads on its own. If one of them cannot be answered, that panel alone says "unavailable" and offers a retry next to it, and everything else on the page still works. Previously the whole page was built from a single request, so one failure took the page down entirely, and a failure that was quietly swallowed showed up as an empty panel — indistinguishable from a genuinely quiet week.

That distinction is the point: an empty panel now means the answer really was nothing, and a broken one says so out loud. The panels also reserve their space while loading, so a slow one no longer shifts the page around as it arrives.

The dashboard reads the same information in the same order as before.
