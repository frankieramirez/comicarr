---
"comicarr": patch
---

Restarting Comicarr while SABnzbd is still downloading, repairing, or extracting a release no longer marks that download complete. Comicarr checks SAB's active queue first (including jobs moved to another SAB category), and a completed job without a usable folder is sent to Needs attention instead of a failed post-processing command.
