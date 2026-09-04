---
"comicarr": patch
---

A manga download that cannot be placed no longer stops every other import. Manga post-processing holds the global post-processing lock, and each of its six early exits — series not in the database, missing folder, no files found, no manga destination configured, a series folder outside that destination, and a failed directory create — returned without giving it back. Nothing downstream could recover: the post-processing worker skips any item while the lock is held, and the Folder Monitor that exists to rescue stalled imports bails on the same lock. One misplaced series froze the pipeline for 85 minutes. The lock is now released from a single place that covers every exit, including one taken by an exception, and it is held until the pipeline journal has been written rather than being given up part-way through.
