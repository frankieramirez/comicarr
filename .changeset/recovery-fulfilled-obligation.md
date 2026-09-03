---
"comicarr": patch
---

Post-processing no longer stalls on downloads that were already filed. A journal row left at `post_processing` after its file had actually moved was re-driven at every startup and could never finish, because the folder it wanted to import from was already empty. Those stuck obligations held post-processing state, so Folder Monitor lost its lock on every sweep and stopped importing anything at all. Recovery now checks the library for the file before re-driving: when the issue reads Downloaded and its location resolves to a real file under the series folder, the move demonstrably happened, so the row is closed instead of retried. Anything it cannot verify is re-driven exactly as before.
