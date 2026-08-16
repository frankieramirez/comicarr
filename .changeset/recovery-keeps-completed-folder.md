---
"comicarr": patch
---

Restart recovery of a finished SABnzbd or NZBGet download now keeps the completed folder the downloader already reported. Comicarr used to throw away that path and then fail post-processing with "nzb_folder is required", leaving a successful download stuck after a restart.
