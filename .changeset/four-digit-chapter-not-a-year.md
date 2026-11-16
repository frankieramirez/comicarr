---
"comicarr": patch
---

Files with a four-digit chapter or issue number below 1900, such as "One Piece 1195.cbz", import as that number again. The filename reader took the number for a year, fell back to issue 1, and could import the file over the first chapter of the series. Numbers from 1900 on are still read as years when they look like one, so "Action Comics 1050 (2023)" is unchanged.
