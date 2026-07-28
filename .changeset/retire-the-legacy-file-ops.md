---
"comicarr": patch
---

Route story-arc directory placement through the shared placement stage and remove the two legacy file-operation helpers it was the last caller of. Every file Comicarr places now goes through one module that reads the file operation setting at the moment it runs, and an architecture test keeps it that way.
