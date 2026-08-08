---
"comicarr": patch
---

The dashboard now opens with a health band that answers the only question worth opening it for: is anything broken right now? It reports whether a download route is usable, how many indexers are responding, and whether the workers are running — one quiet line when everything is fine, amber naming the specific component when it is not, and red with a link straight to the settings page that fixes it when nothing can get through.

Alongside those it carries a **last successful search** line, which is the one that matters most. Every other signal reports the state of a component; this one reports whether searching has actually produced anything lately, and it goes amber once nothing has run for twice your search interval. That is the reading that catches the failure the rest of the page cannot: for weeks, downloads could be completely broken while every component reported itself fine and the dashboard looked like a quiet week. This line would have read "11 days ago".

The band never guesses in your favour. If the health check itself cannot be reached, it says "Cannot determine health" rather than going quiet — an unanswered question is not good news. And the last-successful-search line is never hidden, at any age, including when nothing has ever run.
