---
"comicarr": patch
---

The Import Inbox no longer auto-imports a file into a series that doesn't have that issue number. A file like `Wizard Magazine 090.cbz` that fuzzy-matches MAD Magazine now goes to review with MAD as the suggestion, instead of landing untagged in the MAD folder. Files without an issue number still auto-import on confidence alone.

The auto-import confidence threshold is now a setting: Settings → Media Management → Import Behavior → Auto-import confidence. It defaults to 80. Set it above 100 to send everything to review.
