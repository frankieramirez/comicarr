---
"comicarr": patch
---

Import Inbox auto-matches now actually move files into your library. High-confidence matches previously got marked Imported without the move, rename, or series rescan ever running, leaving the files behind in the import directory. Auto-matched files now go through the same finalization as manual matches, files that stay in the inbox after a successful import (archive-in-place or copy modes) are no longer re-imported on every scan, and if finalization fails the files fall back to the manual review queue instead of being falsely marked Imported. Auto-imported records also keep their real match source and confidence instead of being relabeled as 100% manual matches.
