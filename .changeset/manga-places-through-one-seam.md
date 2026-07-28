---
"comicarr": patch
---

Route manga post-processing through the shared file placement stage. Sixty-five lines of replace-what-is-there policy — recognising a chapter an earlier pass already placed, moving an existing chapter aside rather than deleting it, putting it back when placement fails — move out of the post-processor and into the one module that owns placement.
