---
"comicarr": patch
---

Comicarr now writes comic tags itself instead of running the bundled ComicTagger. Your tagging settings stay the same: ComicRack (`ComicInfo.xml`) and Comic Book Lover tags, CBR to CBZ conversion, the overwrite setting and the volume options all work as before, and the tags still come from ComicVine.

What changes:
- A CBZ that already has tags, with overwriting off, is now left as it is and placed normally. Before, it was reported as a tagging failure.
- When overwriting is on, fields Comicarr does not manage, such as a GTIN or a translator credit, are now kept instead of dropped.
- The Notes field now reads "Tagged by Comicarr". It still ends with `[Issue ID 12345]` (or `[CVDB12345]`), so other library tools can still find the ComicVine issue.
- Comicarr no longer creates a `.ComicTagger` folder in your home directory. The old `cmtagger_path` and `ct_settingspath` settings are ignored.
