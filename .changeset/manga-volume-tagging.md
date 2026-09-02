---
"comicarr": patch
---

Manga volumes are now tagged as volumes rather than as issues of a series-named volume. An imported volume either carried no metadata at all or was written as issue N of a volume named after the series, which is not what a manga volume is — the file *is* volume N and has no issue number. The volume is now read from the ledger and written as the volume, with the issue number cleared. Periodical tagging is untouched: a non-manga series, a missing ledger row, or a ledger with no volume numbers all produce the same tag as before. Tagging also no longer leaves a file less readable than it found it — the pre-tagging permissions are restored afterwards.
