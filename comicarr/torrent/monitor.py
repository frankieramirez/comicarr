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

import os

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
    # `hash` is itself a _TORRENT_FIELDS key and several adapters return their
    # own copy of it, so the caller-supplied hash stays authoritative.
    result["hash"] = torrent_hash
    return result


# TORRENT_DOWNLOADER value -> route. Mirrors the client map in
# comicarr/app/search/health.py; 0 (watch folder) yields no identity to poll.
_DOWNLOADER_ROUTES = {
    1: "utorrent",
    2: "rtorrent",
    3: "transmission",
    4: "deluge",
    5: "qbittorrent",
}


def route_for_downloader(downloader):
    """Route for a TORRENT_DOWNLOADER value, or None when nothing can be polled."""
    try:
        return _DOWNLOADER_ROUTES.get(int(downloader or 0))
    except (TypeError, ValueError):
        return None


def is_monitorable_downloader(downloader):
    """Whether a TORRENT_DOWNLOADER value yields an identity ``probe()`` can poll.

    The snatched-queue producer (``comicarr/search.py``) and the consumer that
    drains it (``SNPOOL`` in ``comicarr/__init__.py``) must agree on this, or
    releases pile up on a queue nothing reads.
    """
    return route_for_downloader(downloader) is not None


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

    # deluge.get_torrent() catches every exception from core.get_torrent_status
    # and returns False, so a daemon that dies after connect() succeeded is
    # indistinguishable from a genuine miss. Ask the daemon whether it is still
    # there before calling the torrent absent -- recovery treats absent as proof
    # the download is gone and would mark a live torrent failed.
    info = client.get_torrent(torrent_hash)
    if not info:
        try:
            client.conn.call("daemon.info")
        except Exception as e:
            return unreachable(e)
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


def utorrent_base_url(host):
    """Normalise UTORRENT_HOST the way the uTorrent sender does.

    ``UTORRENT_HOST`` is documented as ``URL:PORT`` and may or may not carry a
    scheme or a trailing ``/gui``. The vendored client does
    ``urljoin(base_url, "token.html")`` and ``base_url + "?token="`` with no
    fix-up of its own, so an unnormalised host builds a URL that always fails.
    This mirrors comicarr/utorrent.py, which is the form known to work.
    """
    if not host:
        return host
    if not host.startswith("http"):
        host = "http://" + host
    if host.endswith("/"):
        host = host[:-1]
    if host.endswith("/gui"):
        host = host[:-4]
    return "%s/gui/" % host


def _probe_utorrent(torrent_hash):
    from comicarr.torrent.clients import utorrent

    client = utorrent.TorrentClient()
    conn = normalize_connection_result(
        client.connect(
            utorrent_base_url(comicarr.CONFIG.UTORRENT_HOST),
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
    if not path:
        return path
    if not folder or os.path.isabs(path):
        return path
    return os.path.join(folder, path)


def _pause_credentials(route):
    """Return (client module, host, user, password) for a pausable route."""
    if route == "deluge":
        from comicarr.torrent.clients import deluge as module

        return (
            module,
            comicarr.CONFIG.DELUGE_HOST,
            comicarr.CONFIG.DELUGE_USERNAME,
            comicarr.CONFIG.DELUGE_PASSWORD,
        )
    if route == "transmission":
        from comicarr.torrent.clients import transmission as module

        return (
            module,
            comicarr.CONFIG.TRANSMISSION_HOST,
            comicarr.CONFIG.TRANSMISSION_USERNAME,
            comicarr.CONFIG.TRANSMISSION_PASSWORD,
        )
    if route == "utorrent":
        from comicarr.torrent.clients import utorrent as module

        return (
            module,
            utorrent_base_url(comicarr.CONFIG.UTORRENT_HOST),
            comicarr.CONFIG.UTORRENT_USERNAME,
            comicarr.CONFIG.UTORRENT_PASSWORD,
        )
    # A route added to PAUSABLE_ROUTES without wiring it here must fail loudly
    # rather than quietly borrowing another client's credentials.
    return None


def _pausable_client():
    """Return ``(route, connected client)`` exposing start/stop, or ``(None, None)``."""
    route = configured_route()
    if route not in PAUSABLE_ROUTES:
        return None, None

    credentials = _pause_credentials(route)
    if credentials is None:
        logger.warn("[TORRENT-MONITOR] %s is pausable but has no client wiring" % route)
        return None, None

    module, host, user, password = credentials
    client = module.TorrentClient()
    conn = normalize_connection_result(client.connect(host, user, password))
    if isinstance(conn, dict) and conn.get("status") is False:
        logger.warn("[TORRENT-MONITOR] could not connect to %s to pause/resume" % route)
        return None, None
    return route, client


def _pause_target(route, client, torrent_hash):
    """Resolve what this client's start/stop expects for ``torrent_hash``.

    Deluge and uTorrent take the hash. Transmission's ``stop_torrent``/
    ``start_torrent`` call ``.stop()``/``.start()`` on a vendor torrent object,
    so the hash has to be resolved to a handle first.
    """
    if route != "transmission":
        return torrent_hash
    return client.find_torrent(torrent_hash)


def pause(torrent_hash):
    """Pause a torrent so its files can be copied. False when unsupported."""
    route, client = _pausable_client()
    if client is None:
        return False
    try:
        target = _pause_target(route, client, torrent_hash)
        if not target:
            logger.warn("[TORRENT-MONITOR] %s has no torrent %s to pause" % (route, torrent_hash))
            return False
        return client.stop_torrent(target) is not False
    except Exception as e:
        logger.warn("[TORRENT-MONITOR] could not pause %s: %s" % (torrent_hash, e))
        return False


def resume(torrent_hash):
    """Resume a torrent paused by :func:`pause`."""
    route, client = _pausable_client()
    if client is None:
        return False
    try:
        target = _pause_target(route, client, torrent_hash)
        if not target:
            logger.warn("[TORRENT-MONITOR] %s has no torrent %s to resume" % (route, torrent_hash))
            return False
        return client.start_torrent(target) is not False
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
