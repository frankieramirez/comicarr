---
"comicarr": patch
---

Fix manga post-processing deleting the downloaded file when the file operation
is set to hardlink or softlink. Both modes are meant to leave the download in
place; the manga path moved it regardless, so the original was destroyed. It now
uses the same mode-aware file placement as the rest of post-processing.
