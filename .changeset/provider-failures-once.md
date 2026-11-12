---
"comicarr": patch
---

Review releases now reports each search provider failure once, in plain words, instead of repeating a raw connection error for every search variant. When a provider's host can't be reached (for example, a stopped Prowlarr), Comicarr stops trying that provider's other variants and skips other providers on the same host for two minutes, so a search with Prowlarr down finishes in seconds. Providers that fail the same way share one card.
