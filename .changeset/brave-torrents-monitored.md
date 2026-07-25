---
"comicarr": patch
---

Fix torrents snatched through qBittorrent, Transmission or uTorrent never being
monitored. They were sent to the client successfully and then left in Snatched
forever: nothing polled them, post-processing never ran, and a restart could not
pick them back up. All five torrent clients are now polled through one code
path, and a client being unreachable is kept distinct from a torrent genuinely
being gone, so an outage no longer looks like a lost download.
