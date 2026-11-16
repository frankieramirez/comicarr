---
"comicarr": patch
---

qBittorrent now connects through the maintained `qbittorrent-api` library instead of an old bundled copy. Nothing changes in your settings. If qBittorrent refuses the login because of too many failed attempts, Comicarr now reports a login failure instead of a generic connection error.
