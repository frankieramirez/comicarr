---
"comicarr": patch
---

Honour the file operation setting when finalizing a manual import. Confirming an import always moved files into the series folder regardless of whether File Operations was set to copy, hardlink, or softlink — so operators using a link mode to keep their download folder intact lost the source file on every manual import. Finalization now copies, hardlinks, or symlinks to match the setting, and only consumes the source under `move`.
