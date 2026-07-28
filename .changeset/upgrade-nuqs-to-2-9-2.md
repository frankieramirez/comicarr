---
"comicarr": patch
---

Upgrade `nuqs` to 2.9.2, which fixes an upstream bug where URL-backed state could permanently desync from the URL after React discarded a render (nuqs#1501). The library's React Router adapter on React 19 was affected, and the Library page's sorting, filtering and pagination are the state this repo keeps in the URL.
