---
"comicarr": patch
---

Fix the Library list showing 0% for manga you hold as volumes. A series where every volume is in the library could read 0 / 120, because a refresh reset the count and a rescan only brought it back when it found a new file. A chapter now counts when you have its file or when it sits inside a volume you have, the same as the series page, and Comicarr corrects the stored counts the first time it starts after the upgrade. The list column is now headed Have instead of Issues, since it counts chapters for manga.
