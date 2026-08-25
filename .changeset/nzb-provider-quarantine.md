---
"comicarr": patch
---

Usenet downloads are no longer quarantined at completion with "immutable_payload_conflict:provider". The download pipeline recorded the provider two different ways for the same download — as "DrunkenSlug (newznab)" when the release was grabbed and as plain "DrunkenSlug" when the download finished — so the safety check that guards against a download changing identity mid-flight fired on every completed NZBGet download, sending it to Needs attention instead of importing it. Both spellings now resolve to the same provider, and existing pipeline records written under the old spelling are reconciled automatically on the next startup.
