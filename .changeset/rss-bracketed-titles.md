---
"comicarr": patch
---

An RSS feed entry whose title is wrapped in square brackets, such as `[Series, Tome 1 - Title.cbz]`, no longer stops the RSS check. Before, one such entry ended every run with "list index out of range", so RSS grabbed nothing while it stayed in the feed. Comicarr now reads the title inside the brackets, skips any title it still can't read, and logs the cause when a scheduled job fails.
