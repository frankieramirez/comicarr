---
"comicarr": patch
---

rTorrent now connects through a small client built into Comicarr instead of an old bundled library. Your settings stay the same: HTTP, HTTPS, SCGI and ruTorrent's HTTPRPC URLs all still work, with basic or digest login.

Two fixes come with it:
- If rTorrent can't be reached, the download monitor now reports it as unreachable instead of stopping.
- A magnet whose details are still loading is no longer reported as a failed send.
