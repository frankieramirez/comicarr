---
"comicarr": patch
---

Startup recovery no longer reports *import / succeeded* for downloads that were never actually moved into the library. Previously, recovery could trust old download-history state as proof of completion and mark an item post-processed without running file placement, leaving the files stranded in the download directory while activity claimed a successful import. Recovery now also checks the library itself (the issue's stored location or Downloaded status) before closing an item out. When the download really did finish but was never imported, recovery re-runs the import if it can resolve the completed folder; otherwise the item lands in Needs attention as "download finished but was never imported into the library", with the files still in the download directory ready for a manual import.
