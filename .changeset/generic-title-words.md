---
"comicarr": patch
---

Import no longer matches two series just because they share a generic word. Words like "Magazine", "Comics" and "The" now count only when nothing else tells the names apart, so `Wizard Magazine 090.cbz` is no longer suggested or auto-imported as MAD Magazine. These words never raise a match score, so series that matched before still match, at the same or a lower confidence.
