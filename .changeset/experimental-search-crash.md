---
"comicarr": patch
---

Fix searches stopping early when the old Experimental search setting is still on. Comicarr removed Experimental (NZBIndex) search in an earlier release, but a saved setting still put it in the search order, and reaching it ended the whole search for that issue before any provider after it ran. Comicarr now ignores the setting, so every other provider is searched again. Activity > Health still shows the notice that Experimental search is gone; add a Usenet indexer through Prowlarr or as a Newznab provider instead.
