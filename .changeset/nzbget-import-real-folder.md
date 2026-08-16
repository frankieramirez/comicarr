---
"comicarr": patch
---

Completed NZBGet downloads are imported from the files actually sitting in the job folder. Comicarr used to look for a file with the same name as the release inside that folder, miss the real `.cbr`/`.cbz`, and mark a successful download as failed.
