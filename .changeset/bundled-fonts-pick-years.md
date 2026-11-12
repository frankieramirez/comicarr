---
"comicarr": patch
---

The redesign's typefaces, Inter Tight and JetBrains Mono, now ship with Comicarr and load on every install. Before, they came from Google Fonts, which Comicarr's own security policy blocked, so most browsers fell back to system fonts. The script that sets light or dark mode before the page draws had the same problem and could flash the wrong theme; it now loads as its own file.

The Import pick panel now offers a library series even when the files name a different year than the one the series started in, since files usually carry the issue's cover year. Such a series scores lower than a full match and the panel says why, so it is never auto-imported on that guess alone.
