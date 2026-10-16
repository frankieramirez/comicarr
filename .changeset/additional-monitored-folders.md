---
"comicarr": minor
---

The Folder Monitor can now watch more than one completed-download folder. Add extra folders, one per line, under Settings → Download Clients → Completed downloads. Each pass scans the main monitored folder first, then each extra folder, and imports with the same file operation (copy, hardlink or move), so seeding torrents keep their files. A missing or unreadable extra folder is logged and skipped without stopping the others. The extra folders only apply while the main monitored folder (`CHECK_FOLDER`) is set.
