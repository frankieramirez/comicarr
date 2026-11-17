---
"comicarr": patch
---

Settings no longer changes a value behind your back. A search interval, RSS check interval, database update interval, search delay or AI requests-per-minute below its minimum is now refused with a message under the field, instead of being saved as the minimum while the page said "Saved". Each of those fields shows its minimum. Settings also refuses unknown MangaDex language codes or content ratings, and turning on Discord without a webhook URL.
