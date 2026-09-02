---
"comicarr": patch
---

Manga volume files now count towards Have instead of reporting "0 files matched". A volume file was placed into the series folder correctly and was perfectly readable, but nothing recorded it: the filename did not parse once release tags followed the volume number, and the scan then looked the file up by issue number, which a volume file does not have. Volumes are now matched on their volume number — so on MangaDex and MyAnimeList a v20 file no longer attaches itself to chapter 20 — and a chapter-numbered file is no longer filed as issue 1 on the strength of a volume it never stated. A year disagreement between the provider and the release, which is routine for licensed manga, no longer rejects a file whose volume already matched.
