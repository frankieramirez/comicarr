---
"comicarr": patch
---

Retrying a download your torrent or usenet client rejected now actually tries that release again. When the client refused a submission, Comicarr also marked the release itself as a bad download, so every retry found the same release, skipped it as "known bad", and reported no match. Retry from Needs you now clears that mark for the issue and indexer first. Downloads that failed for other reasons keep their mark.
