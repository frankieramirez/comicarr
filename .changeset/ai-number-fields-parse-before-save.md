---
"comicarr": patch
---

Clearing an AI number field (timeout, requests per minute, daily token limit) no longer fails the whole settings save with "Failed to save configuration" — the field now falls back to its default (30 / 20 / 100000) like the other numeric settings.
