---
"comicarr": patch
---

Metatagging a manga `.cbr` now updates the issue's stored file path to the new `.cbz`. ComicTagger cannot write into a RAR archive, so tagging converts the file and deletes the original; the library row used to keep pointing at the deleted `.cbr` even though Have and Status still looked correct. Re-tagging and anything else that opens the file through that path now finds the archive that is actually on disk.
