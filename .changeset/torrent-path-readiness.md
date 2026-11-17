---
"comicarr": patch
---

Torrent searches are no longer blocked with "the download directory is not reachable" when your torrent client's save folder only exists on the client's side, as it often does in Docker. Comicarr now checks the folder it actually reads, the Folder Monitor folder when that is on. When it can't tell, Settings shows the path as unknown instead of not ready.
