#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""How far along each in-flight download is, for Releases and the issue page.

The pipeline journal knows which client each open release went to and the
client's own id for it (SABnzbd ``nzo_id``, NZBGet ``NZBID``, a torrent
hash). This asks those clients once per call for their queues and maps the
answer back to issue ids. Clients without a cheap queue read (watch folders,
blackhole, Deluge, Transmission, rTorrent, uTorrent, DDL) report no percent
rather than a guess. A short cache keeps a busy page from hammering clients.
"""

from __future__ import annotations

import threading
import time

import requests
from sqlalchemy import select

import comicarr
from comicarr import db, logger
from comicarr.app.downloads import journal
from comicarr.tables import pipeline_journal

_TIMEOUT = 5
_CACHE_SECONDS = 15
_cache_lock = threading.Lock()
_cache: dict = {"at": 0.0, "key": None, "value": None}

# Journal stages after the client finished: Comicarr is importing the file.
_IMPORTING = (journal.DOWNLOADED, journal.POST_PROCESSING, journal.MOVED)


def _text(value) -> str:
    return "" if value in (None, "None") else str(value).strip()


def _open_rows(issue_ids):
    wanted = sorted({str(i) for i in issue_ids if i})
    if not wanted:
        return {}
    try:
        rows = db.select_all(
            select(
                pipeline_journal.c.issueid,
                pipeline_journal.c.downloader_type,
                pipeline_journal.c.hash,
                pipeline_journal.c.stage,
                pipeline_journal.c.payload_json,
                pipeline_journal.c.updated_date,
            )
            .where(pipeline_journal.c.issueid.in_(wanted))
            .where(pipeline_journal.c.stage.in_(journal.OPEN_STAGES))
            .order_by(pipeline_journal.c.updated_date.desc())
        )
    except Exception as e:
        logger.fdebug("[DOWNLOAD-PROGRESS] Unable to read the journal: %s" % e)
        return {}
    latest = {}
    for row in rows or []:
        latest.setdefault(str(row["issueid"]), row)
    return latest


def _sab_queue(config):
    host = _text(getattr(config, "SAB_HOST", None)).rstrip("/")
    apikey = _text(getattr(config, "SAB_APIKEY", None))
    if not host or not apikey:
        return {}
    response = requests.get(
        host + "/api",
        params={"mode": "queue", "output": "json", "limit": 500, "apikey": apikey},
        timeout=_TIMEOUT,
        verify=bool(getattr(config, "SAB_VERIFY", False)),
        allow_redirects=False,
    )
    slots = ((response.json() or {}).get("queue") or {}).get("slots") or []
    found = {}
    for slot in slots:
        try:
            percent = float(slot.get("percentage"))
        except (TypeError, ValueError):
            continue
        found[str(slot.get("nzo_id"))] = {"percent": percent, "time_left": slot.get("timeleft") or None}
    return found


def _nzbget_queue(config):
    host = _text(getattr(config, "NZBGET_HOST", None)).rstrip("/")
    if not host.startswith(("http://", "https://")):
        return {}
    port = _text(getattr(config, "NZBGET_PORT", None))
    sub = _text(getattr(config, "NZBGET_SUB", None)).strip("/")
    base = "%s:%s" % (host, port) if port else host
    if sub:
        base = "%s/%s" % (base, sub)
    username = _text(getattr(config, "NZBGET_USERNAME", None))
    password = _text(getattr(config, "NZBGET_PASSWORD", None))
    response = requests.get(
        base + "/jsonrpc/listgroups",
        auth=(username, password) if username or password else None,
        timeout=_TIMEOUT,
        allow_redirects=False,
    )
    found = {}
    for group in (response.json() or {}).get("result") or []:
        try:
            total = float(group.get("FileSizeMB") or 0)
            left = float(group.get("RemainingSizeMB") or 0)
        except (TypeError, ValueError):
            continue
        if total > 0:
            found[str(group.get("NZBID"))] = {"percent": max(0.0, min(100.0, (total - left) * 100 / total))}
    return found


def _qbittorrent(config, hashes):
    if not hashes:
        return {}
    from comicarr.torrent.clients.qbittorrent import TorrentClient

    client = TorrentClient().connect(
        _text(getattr(config, "QBITTORRENT_HOST", None)),
        _text(getattr(config, "QBITTORRENT_USERNAME", None)),
        _text(getattr(config, "QBITTORRENT_PASSWORD", None)),
    )
    if isinstance(client, dict):
        return {}
    found = {}
    for torrent in client.torrents(hashes="|".join(sorted(hashes))) or []:
        try:
            progress = float(torrent.get("progress"))
        except (TypeError, ValueError):
            continue
        eta = torrent.get("eta")
        found[str(torrent.get("hash") or "").lower()] = {
            "percent": max(0.0, min(100.0, progress * 100)),
            "time_left": "%ds" % eta if isinstance(eta, int) and 0 < eta < 8640000 else None,
        }
    return found


def _safely(label, read, *args):
    try:
        return read(*args)
    except Exception as e:
        logger.fdebug("[DOWNLOAD-PROGRESS] %s queue unavailable: %s" % (label, e))
        return {}


def _client_id(row, payload, *keys):
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
        info = payload.get("download_info")
        if isinstance(info, dict) and info.get(key) not in (None, ""):
            return str(info[key])
    return None


def _compute(issue_ids, config):
    rows = _open_rows(issue_ids)
    if not rows:
        return {}
    plans = {}
    for issue_id, row in rows.items():
        payload = journal.load_payload(row.get("payload_json")) or {}
        kind = _text(row.get("downloader_type")).lower()
        if row.get("stage") in _IMPORTING:
            plans[issue_id] = ("importing", None)
        elif kind == "nzb" and getattr(comicarr, "USE_SABNZBD", False):
            plans[issue_id] = ("sab", _client_id(row, payload, "nzo_id"))
        elif kind == "nzb" and getattr(comicarr, "USE_NZBGET", False):
            plans[issue_id] = ("nzbget", _client_id(row, payload, "NZBID"))
        elif kind == "torrent" and getattr(comicarr, "USE_QBITTORRENT", False):
            torrent_hash = _text(row.get("hash")) or _client_id(row, payload, "hash")
            plans[issue_id] = ("qbittorrent", torrent_hash.lower() if torrent_hash else None)
        else:
            plans[issue_id] = ("unknown", None)

    needs = {kind for kind, ref in plans.values() if ref}
    sab = _safely("SABnzbd", _sab_queue, config) if "sab" in needs else {}
    nzbget = _safely("NZBGet", _nzbget_queue, config) if "nzbget" in needs else {}
    hashes = {ref for kind, ref in plans.values() if kind == "qbittorrent" and ref}
    qbit = _safely("qBittorrent", _qbittorrent, config, hashes) if hashes else {}
    queues = {"sab": sab, "nzbget": nzbget, "qbittorrent": qbit}

    out = {}
    for issue_id, (kind, ref) in plans.items():
        if kind == "importing":
            out[issue_id] = {"phase": "importing", "percent": None, "time_left": None}
            continue
        hit = queues.get(kind, {}).get(ref) if ref else None
        out[issue_id] = {
            "phase": "downloading",
            "percent": round(hit["percent"]) if hit else None,
            "time_left": (hit or {}).get("time_left"),
        }
    return out


def progress_by_issue(issue_ids, *, config=None):
    """``{issue_id: {phase, percent, time_left}}`` for issues with an open download."""
    config = config if config is not None else getattr(comicarr, "CONFIG", None)
    key = tuple(sorted({str(i) for i in issue_ids or [] if i}))
    if not key or config is None:
        return {}
    now = time.monotonic()
    with _cache_lock:
        if _cache["key"] == key and now - _cache["at"] < _CACHE_SECONDS:
            return dict(_cache["value"])
    value = _compute(key, config)
    with _cache_lock:
        _cache.update(at=now, key=key, value=value)
    return dict(value)


def reset_cache():
    with _cache_lock:
        _cache.update(at=0.0, key=None, value=None)
