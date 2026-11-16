---
"comicarr": patch
---

Sending a torrent to a seedbox over SFTP now gives up after three failed uploads instead of retrying forever, and logs an error when the `paramiko` package it needs is missing. A torrent that had not finished writing no longer crashes the upload.
