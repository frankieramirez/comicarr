#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Read a torrent's state from whichever client is configured.

One normalised shape for all five clients, so callers stop reading
client-specific keys. Every client's own ``get_torrent`` returns something
different -- Deluge speaks libtorrent field names, qBittorrent returns raw Web
API payloads, uTorrent returns a subset -- and only rTorrent and Deluge were
ever wired into the monitor path. A torrent snatched through any of the other
three could not be monitored or recovered at all.

The distinction this module exists to preserve is **unreachable** (the client
did not answer) versus **absent** (the client answered and does not have this
hash). Collapsing them makes recovery abandon live downloads, so every failure
path here is explicit about which one it is.

Note that all five adapters report a connection failure as a *truthy*
``{"status": False, ...}`` mapping, so the common ``if not client.connect(...)``
idiom silently treats a dead client as connected. Everything here routes through
``normalize_connection_result``.
"""

import comicarr
from comicarr import logger
from comicarr.torrent.contracts import normalize_connection_result

# Normalised keys every probe result carries when `found` is True. Clients that
# cannot supply a field leave it None rather than omitting it, so callers can
# read it unconditionally.
_TORRENT_FIELDS = (
    "hash",
    "name",
    "folder",
    "completed",
    "files",
    "label",
    "total_filesize",
    "upload_total",
    "download_total",
    "ratio",
    "time_started",
)


def unreachable(reason):
    """The configured client could not be queried. Never means 'not present'."""
    return {"reachable": False, "found": False, "reason": str(reason)}


def absent(torrent_hash):
    """The client answered and does not hold this hash."""
    return {"reachable": True, "found": False, "hash": torrent_hash}


def _found(torrent_hash, **fields):
    result = {"reachable": True, "found": True, "hash": torrent_hash}
    for key in _TORRENT_FIELDS:
        result.setdefault(key, fields.get(key))
    result.update({k: v for k, v in fields.items() if k in _TORRENT_FIELDS})
    result["hash"] = torrent_hash
    return result


def configured_route():
    """Return the torrent client route in use, or None when none is monitorable."""
    if comicarr.USE_RTORRENT:
        return "rtorrent"
    if comicarr.USE_DELUGE:
        return "deluge"
    if comicarr.USE_QBITTORRENT:
        return "qbittorrent"
    if comicarr.USE_TRANSMISSION:
        return "transmission"
    if comicarr.USE_UTORRENT:
        return "utorrent"
    # Watch-folder handoff produces no client-side identity to poll.
    return None


def _probe_rtorrent(torrent_hash):
    from comicarr import rtorrent_test_client

    client = rtorrent_test_client.RTorrent()
    info = client.main(torrent_hash, check=True)
    if not info:
        return absent(torrent_hash)
    return _found(
        torrent_hash,
        name=info.get("name"),
        folder=info.get("folder"),
        completed=bool(info.get("completed")),
        files=info.get("files") or [],
        label=info.get("label"),
        total_filesize=info.get("total_filesize"),
        upload_total=info.get("upload_total"),
        download_total=info.get("download_total"),
        ratio=info.get("ratio"),
        time_started=info.get("time_started"),
    )


def _probe_deluge(torrent_hash):
    from comicarr.torrent.clients import deluge

    client = deluge.TorrentClient()
    conn = normalize_connection_result(
        client.connect(
            comicarr.CONFIG.DELUGE_HOST,
            comicarr.CONFIG.DELUGE_USERNAME,
            comicarr.CONFIG.DELUGE_PASSWORD,
        )
    )
    if isinstance(conn, dict) and conn.get("status") is False:
        return unreachable(conn.get("error", "deluge did not connect"))

    info = client.get_torrent(torrent_hash)
    if not info:
        return absent(torrent_hash)

    folder = info.get("save_path")
    files = [f.get("path") for f in (info.get("files") or []) if isinstance(f, dict)]
    return _found(
        torrent_hash,
        name=info.get("name"),
        folder=folder,
        completed=bool(info.get("is_finished")),
        # Deluge reports paths relative to save_path; callers want absolute.
        files=[_join(folder, path) for path in files],
        label=info.get("label"),
        total_filesize=info.get("total_size"),
        upload_total=info.get("total_uploaded"),
        download_total=info.get("total_payload_download"),
        ratio=info.get("ratio"),
        time_started=info.get("time_added"),
    )


def _probe_qbittorrent(torrent_hash):
    from comicarr.torrent.clients import qbittorrent

    client = qbittorrent.TorrentClient()
    conn = normalize_connection_result(
        client.connect(
            comicarr.CONFIG.QBITTORRENT_HOST,
            comicarr.CONFIG.QBITTORRENT_USERNAME,
            comicarr.CONFIG.QBITTORRENT_PASSWORD,
        )
    )
    if isinstance(conn, dict) and conn.get("status") is False:
        return unreachable(conn.get("error", "qbittorrent did not connect"))

    # get_torrent() hits /torrents/properties, which carries neither the name
    # nor the progress. /torrents/info filtered by hash carries both.
    try:
        listing = client.conn.torrents(hashes=torrent_hash.lower())
    except Exception as e:
        return unreachable(e)

    entry = next((t for t in listing or [] if str(t.get("hash", "")).lower() == torrent_hash.lower()), None)
    if entry is None:
        return absent(torrent_hash)

    folder = entry.get("save_path") or entry.get("content_path")
    try:
        files = [
            _join(folder, f.get("name"))
            for f in client.conn.get_torrent_files(torrent_hash.lower()) or []
            if f.get("name")
        ]
    except Exception:
        # The torrent is present; only the file list is unavailable.
        files = []

    return _found(
        torrent_hash,
        name=entry.get("name"),
        folder=folder,
        completed=float(entry.get("progress") or 0) >= 1,
        files=files,
        label=entry.get("category"),
        total_filesize=entry.get("size"),
        upload_total=entry.get("uploaded"),
        download_total=entry.get("downloaded"),
        ratio=entry.get("ratio"),
        time_started=entry.get("added_on"),
    )


def _probe_transmission(torrent_hash):
    from comicarr.torrent.clients import transmission

    client = transmission.TorrentClient()
    conn = normalize_connection_result(
        client.connect(
            comicarr.CONFIG.TRANSMISSION_HOST,
            comicarr.CONFIG.TRANSMISSION_USERNAME,
            comicarr.CONFIG.TRANSMISSION_PASSWORD,
        )
    )
    if isinstance(conn, dict) and conn.get("status") is False:
        return unreachable(conn.get("error", "transmission did not connect"))

    # Two calls: find_torrent returns the vendor object, get_torrent maps it.
    torrent = client.find_torrent(torrent_hash)
    if not torrent:
        return absent(torrent_hash)
    info = client.get_torrent(torrent)
    if not info:
        return absent(torrent_hash)
    return _found(torrent_hash, **{k: info.get(k) for k in _TORRENT_FIELDS if k in info})


def _probe_utorrent(torrent_hash):
    from comicarr.torrent.clients import utorrent

    client = utorrent.TorrentClient()
    conn = normalize_connection_result(
        client.connect(
            comicarr.CONFIG.UTORRENT_HOST,
            comicarr.CONFIG.UTORRENT_USERNAME,
            comicarr.CONFIG.UTORRENT_PASSWORD,
        )
    )
    if isinstance(conn, dict) and conn.get("status") is False:
        return unreachable(conn.get("error", "utorrent did not connect"))

    torrent = client.find_torrent(torrent_hash)
    if not torrent:
        return absent(torrent_hash)
    info = client.get_torrent(torrent)
    if not info:
        return absent(torrent_hash)
    # uTorrent reports no size, ratio or timing fields; they stay None.
    return _found(torrent_hash, **{k: info.get(k) for k in _TORRENT_FIELDS if k in info})


_PROBES = {
    "rtorrent": _probe_rtorrent,
    "deluge": _probe_deluge,
    "qbittorrent": _probe_qbittorrent,
    "transmission": _probe_transmission,
    "utorrent": _probe_utorrent,
}

# Clients exposing start/stop, used by the local post-processing copy path.
PAUSABLE_ROUTES = frozenset({"deluge", "transmission", "utorrent"})


def _join(folder, path):
    import os

    if not path:
        return path
    if not folder or os.path.isabs(path):
        return path
    return os.path.join(folder, path)


def _pausable_client():
    """Return a connected client exposing start/stop, or None."""
    route = configured_route()
    if route not in PAUSABLE_ROUTES:
        return None

    if route == "deluge":
        from comicarr.torrent.clients import deluge as module

        host, user, password = (
            comicarr.CONFIG.DELUGE_HOST,
            comicarr.CONFIG.DELUGE_USERNAME,
            comicarr.CONFIG.DELUGE_PASSWORD,
        )
    elif route == "transmission":
        from comicarr.torrent.clients import transmission as module

        host, user, password = (
            comicarr.CONFIG.TRANSMISSION_HOST,
            comicarr.CONFIG.TRANSMISSION_USERNAME,
            comicarr.CONFIG.TRANSMISSION_PASSWORD,
        )
    else:
        from comicarr.torrent.clients import utorrent as module

        host, user, password = (
            comicarr.CONFIG.UTORRENT_HOST,
            comicarr.CONFIG.UTORRENT_USERNAME,
            comicarr.CONFIG.UTORRENT_PASSWORD,
        )

    client = module.TorrentClient()
    conn = normalize_connection_result(client.connect(host, user, password))
    if isinstance(conn, dict) and conn.get("status") is False:
        return None
    return client


def pause(torrent_hash):
    """Pause a torrent so its files can be copied. False when unsupported."""
    client = _pausable_client()
    if client is None:
        return False
    try:
        return client.stop_torrent(torrent_hash) is not False
    except Exception as e:
        logger.warn("[TORRENT-MONITOR] could not pause %s: %s" % (torrent_hash, e))
        return False


def resume(torrent_hash):
    """Resume a torrent paused by :func:`pause`."""
    client = _pausable_client()
    if client is None:
        return False
    try:
        return client.start_torrent(torrent_hash) is not False
    except Exception as e:
        logger.warn("[TORRENT-MONITOR] could not resume %s: %s" % (torrent_hash, e))
        return False


def probe(torrent_hash):
    """Return a normalised view of ``torrent_hash`` from the configured client.

    Always returns a mapping carrying ``reachable`` and ``found``. Raises
    nothing: an adapter that throws is reported as unreachable, because a
    thrown exception cannot distinguish a dead client from a missing torrent.
    """
    route = configured_route()
    if route is None:
        return unreachable("no monitorable torrent client is configured")

    try:
        result = _PROBES[route](torrent_hash)
    except Exception as e:
        logger.warn("[TORRENT-MONITOR] %s probe failed for %s: %s" % (route, torrent_hash, e))
        return unreachable(e)

    result["client"] = route
    return result
