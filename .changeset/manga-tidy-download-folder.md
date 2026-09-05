---
"comicarr": patch
---

Manga imports no longer leave an empty folder behind in your download directory. With file handling set to move, the volume was taken into the library but its now-empty release folder stayed in the completed directory forever, and nothing ever cleared them, so they built up one per import. The folder is now removed once the import has emptied it, on the same terms as comics: only under move, never for a Manual Run, and never when a file is still sitting in it.
