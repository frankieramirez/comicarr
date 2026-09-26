---
"comicarr": patch
---

Metatagging no longer fails with "Can't mix strings and bytes in path components" when ComicTagger prints a warning (common on fresh Docker installs), so tagged issues land in the library instead of the untagged original.
