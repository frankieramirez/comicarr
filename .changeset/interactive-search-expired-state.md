---
"comicarr": patch
---

Review releases now says "Search timed out" when an interactive search session expires, instead of the generic "Search unavailable" panel with a raw server message (#766). The expired state explains that sessions last 10 minutes at most, offers a "Start a new search" button, and — for series-wide searches, where long runs actually hit the limit — suggests searching a single issue instead. Confirming a grab against an expired session now also gets a plain explanation rather than the raw error text. Under the hood the sheet also stops polling an expired session; previously it kept requesting the dead session every two seconds until the sheet was closed.
