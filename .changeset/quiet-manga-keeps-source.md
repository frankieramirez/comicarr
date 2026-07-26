---
"comicarr": patch
---

Fix manga post-processing deleting the downloaded file when the file operation
is set to hardlink or softlink. Both modes are meant to leave the download in
place; the manga path moved it regardless, so the original was destroyed. It now
uses the same mode-aware file placement as the rest of post-processing.

Manga chapters that are already in the library also import correctly again. A
repack, a manual re-run, or a post-crash retry now replaces the existing file
under every file operation mode, instead of failing on the hardlink and softlink
modes and leaving the chapter unimported.
