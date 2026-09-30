---
"comicarr": patch
---

Comicarr no longer removes a SABnzbd download that is still unpacking or repairing when it stops waiting for it, so the job isn't cancelled and its files aren't deleted. "Remove failed" in SABnzbd settings now asks SABnzbd to delete files only for downloads that actually failed.
