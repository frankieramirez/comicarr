---
"comicarr": patch
---

Packs that list more than one range, such as `1-3,5` or `1-3 5-7`, are recognised again. Only the first range was read, so the rest of the title was parsed as a number, the pack was discarded as unreadable, and its issues stayed Wanted even though a valid pack was available.

Releases from Newznab and Torznab indexers are also identified correctly when the download link carries its id as the only query parameter. Those releases previously took their identity from the URL path, or lost the last character of the id, so genuinely different releases could look identical and be skipped as duplicates, and a snatch could be logged under an id that post-processing could not match back to the issue.
