---
"comicarr": patch
---

Comicarr can send torrents to qBittorrent 5.2 again. Grabs had been failing with "Torrent was not added! Please check logs" even though qBittorrent logged a successful login. A wrong qBittorrent username or password now shows as a login failure in the connection test and in the grab error, instead of "Connected to qBittorrent!" followed by a failed add.
