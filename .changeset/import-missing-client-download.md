---
"comicarr": patch
---

"Import" on "A finished download was not found on disk" works now. These rows never saved where your usenet client put the download, so Import, and Import all, always failed with "No rows could be resolved". Comicarr now records the folder it expected. For rows already waiting, Import looks for the job by name in your SABnzbd or NZBGet folder and check folder. Fix the folder mapping between Comicarr and your client first, then Import picks them up.
