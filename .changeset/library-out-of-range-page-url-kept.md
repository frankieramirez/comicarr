---
"comicarr": patch
---

Opening the Library with an out-of-range page in the URL (e.g. `?page=99`) still shows the last real page, but the URL is no longer rewritten to that page — it stays exactly as entered. The rewrite could not tell "rows have not loaded yet" from "genuinely past the end", which is what used to strip the page from cold deep links.
