---
"comicarr": patch
---

Fix hardlink and softlink operations on Windows. The Windows-specific branch never ran its link logic and its fallback code raised a `TypeError` instead of dropping down to copy mode; all platforms now use `os.link`/`os.symlink` with the existing copy fallback.
