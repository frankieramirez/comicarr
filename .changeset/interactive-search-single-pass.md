---
"comicarr": patch
---

Interactive release search ("Review missing" and the per-issue search icon) now answers in a fraction of the time. It used to run through the same retry machinery as the automatic search — an RSS cache pass, up to three zero-padded issue-number query variants per provider, and a 30-second courtesy wait between provider queries — which multiplied across a series review into minutes of dead time and was the main reason review sessions hit the 10-minute timeout. The interactive flow now fires one live query per provider (plus the bare-title pass that pack discovery needs) with no waits in between; a provider that objects to the pace shows up as a provider failure on the sheet instead of stalling the whole session. The automatic "Search all missing" flow keeps its retries and rate-limit backoff unchanged.
