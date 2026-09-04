---
"comicarr": patch
---

A download that finished and imported while Comicarr was down is no longer failed on the next start. Startup recovery cross-checks the library before deciding a release is gone, but it looked for a status the library never carries: post-processing writes 'Post-Processed' to the history table and 'Downloaded' onto the issue, so the check could not return true. It also only ever read the issues table, while an annual's completion is written to annuals and a story arc's to storyarcs. Annuals were hit hardest — their ComicVine ids sit above the range Comicarr reserves for one-off downloads, which suppresses the fallback check — so an annual that imported cleanly was re-probed and failed on every restart.
