---
"comicarr": patch
---

When post-processing, a file move, a DDL download, or a hand-off to your download client fails, the log now says which step failed, names the release, provider or client, and the source and destination paths, and includes the full traceback. Passwords, API keys, and credentials in URLs are redacted from these lines.
