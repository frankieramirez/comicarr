---
"comicarr": patch
---

Transmission now connects through the maintained `transmission-rpc` package instead of an old bundled copy. A Transmission host entered as `http://host:9091` with no path now reaches the standard `/transmission/rpc` endpoint. Torrent files are sent to Transmission directly, so Transmission no longer has to see Comicarr's folders to add them.
