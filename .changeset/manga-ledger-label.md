---
"comicarr": patch
---

A manga series tracked by volume now reads "Volumes" in the series table instead of "Chapters", with the volume shown on each row. The heading was taken from the content kind rather than from the rows themselves, so a volume ledger was labelled chapters and the type column on every row was blank — reporting the wrong one of the two things blended monitoring searches. A ledger holding both now reads "Volumes & chapters" and counts each. This covers a ComicVine manga such as One-Punch Man, which models its English volumes as the series' issues and so carries the volume as the issue number rather than as a volume number. Comic series are unchanged: a bare issue number on a comic is still an issue, and the table reads "Issues". The table also stops claiming rows are grouped by arc when every arc cell is empty.
