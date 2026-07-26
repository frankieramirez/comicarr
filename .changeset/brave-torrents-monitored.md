---
"comicarr": patch
---

Fix torrents snatched through qBittorrent, Transmission or uTorrent never being
monitored. They were sent to the client successfully and then left in Snatched
forever: nothing polled them, post-processing never ran, and a restart could not
pick them back up. All five torrent clients are now polled through one code
path, and a client being unreachable is kept distinct from a torrent genuinely
being gone, so an outage no longer looks like a lost download.

The auto-snatch worker now also starts for uTorrent, Transmission and
qBittorrent — and for a local-post-processing-only setup — so the releases those
clients queue are actually consumed instead of piling up unread. Torrents paused
for the local post-processing copy are resumed even when the copy fails, the
on-snatch script keeps firing for the three newly monitored clients, and every
qBittorrent and uTorrent WebUI call now has a timeout so one hung client can no
longer stall monitoring for every download.
