---
"comicarr": patch
---

NZBGet downloads that land under a configured category subdirectory are now found and post-processed. NZBGet files a completed download under `<DestDir>/<category>/`, but Comicarr only looked in `<DestDir>/`, so the folder it resolved did not exist. Post-processing aborted before reaching a terminal stage and the stranded obligation held the post-processing lock, which stopped Folder Monitor from sweeping anything else.
