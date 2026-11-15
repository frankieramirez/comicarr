---
"comicarr": patch
---

At log level 2 (Debug), a search now says exactly what it did. Each provider request logs a `[SEARCH-QUERY]` line with the series and issue IDs, the provider name, the query text, and how many results came back. Each batch of results logs an `[EVALUATION]` summary, and each release gets a line with its verdict and reason code, such as `reason=rejected.series_mismatch`. Search the Logs page for `issue=<IssueID>` or `reason=` to see why an issue was not grabbed. These lines never include provider URLs or API keys, and searching works the same at every log level.
