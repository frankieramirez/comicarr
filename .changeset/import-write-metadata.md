---
"comicarr": patch
---

Imported files are tagged when Settings → Media Management → Write metadata on import is on. Inbox auto-import and manual import match now write ComicInfo.xml (and convert CBR to CBZ) the same way post-processed downloads do. A tagging failure leaves the imported file in place. With `cbr2cbz_only` set in config.ini, downloads and imports are now converted to CBZ; before, that setting left the CBR unchanged.
