---
"comicarr": patch
---

Correct manga volume releases are no longer thrown away by the store-date check or by a misread title. Digital manga is routinely posted before its street date and ComicVine store dates for volumes run weeks late, so a correct release was rejected for a date that says nothing about a volume — street dates disambiguate periodical issue numbers, which recycle across runs, and volume numbers do not. The date check is now skipped on a volume pass only; chapter passes and comics keep it. Separately, a trailing volume label is no longer read as part of the series title, so a release like "<series> v20" stops looking like a different series — this only applies when the label names the volume that was actually detected, so a series genuinely titled with a trailing number is left alone.
