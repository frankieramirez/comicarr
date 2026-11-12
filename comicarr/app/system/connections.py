#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Connection checks for Activity > Health and Settings > Download clients.

Each configured connection (the download clients, the indexers as one group,
and the metadata sources) gets a probe that asks the far end one cheap
question and times the answer. Probes only read: a failed check never blocks
a provider or a route; the search and handoff paths keep their own failure
policy.

Results live in memory. They are a snapshot of "the last time we asked", so
a restart honestly starts with nothing checked; the hourly ``connection_check``
job fills them again.
"""

from __future__ import annotations

import statistics
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable

import requests

import comicarr
from comicarr import logger
from comicarr.app.common.redaction import redact_sensitive_text

JOB_ID = "connection_check"
JOB_NAME = "Connection Check"
CHECK_INTERVAL_MINUTES = 60
_TIMEOUT = 10

_NZB_CLIENTS = {0: "sabnzbd", 1: "nzbget", 2: "blackhole"}
_TORRENT_CLIENTS = {
    0: "watchdir",
    1: "utorrent",
    2: "rtorrent",
    3: "transmission",
    4: "deluge",
    5: "qbittorrent",
}
_TORRENT_HOST_KEYS = {
    "utorrent": "UTORRENT_HOST",
    "rtorrent": "RTORRENT_HOST",
    "transmission": "TRANSMISSION_HOST",
    "deluge": "DELUGE_HOST",
    "qbittorrent": "QBITTORRENT_HOST",
}
LABELS = {
    "sabnzbd": "SABnzbd",
    "nzbget": "NZBGet",
    "blackhole": "Blackhole folder",
    "watchdir": "Watch folder",
    "utorrent": "uTorrent",
    "rtorrent": "rTorrent",
    "transmission": "Transmission",
    "deluge": "Deluge",
    "qbittorrent": "qBittorrent",
    "ddl": "Direct download",
    "indexers": "Indexers",
    "comicvine": "ComicVine",
    "metron": "Metron",
    "mangadex": "MangaDex",
}


@dataclass
class Probe:
    """What a probe found. ``ok`` is None when nothing could be asked."""

    ok: bool | None
    result: str
    latency_ms: float | None = None
    version: str | None = None
    active: int | None = None
    latency_label: str | None = None
    responding: int | None = None


@dataclass
class Connection:
    key: str
    label: str
    kind: str  # "client", "indexers" or "metadata"
    route: str | None
    probe: Callable[[object], Probe] = field(repr=False)


_RESULTS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _config(config=None):
    return config if config is not None else comicarr.CONFIG


def _text(value) -> str:
    return "" if value in (None, "None") else str(value).strip()


def _scrub(error, *secrets) -> str:
    return redact_sensitive_text(str(error), secrets=tuple(s for s in secrets if s))[:300]


def _timed_get(url, **kwargs):
    started = time.monotonic()
    response = requests.get(url, timeout=_TIMEOUT, **kwargs)
    return response, round((time.monotonic() - started) * 1000, 1)


def _request_failure(name, error, *secrets) -> Probe:
    if isinstance(error, requests.exceptions.Timeout):
        return Probe(False, "%s didn't answer within %ss" % (name, _TIMEOUT))
    if isinstance(error, requests.exceptions.ConnectionError):
        return Probe(False, "Couldn't reach %s" % name)
    return Probe(False, _scrub(error, *secrets))


# ── download clients ────────────────────────────────────────────────────────


def _probe_sabnzbd(config) -> Probe:
    host = _text(getattr(config, "SAB_HOST", None)).rstrip("/")
    apikey = _text(getattr(config, "SAB_APIKEY", None))
    if not host:
        return Probe(None, "No host set")
    verify = bool(getattr(config, "SAB_VERIFY", False))
    url = host + "/api"
    try:
        response, latency = _timed_get(
            url, params={"mode": "version", "output": "json"}, verify=verify, allow_redirects=False
        )
    except requests.exceptions.RequestException as e:
        return _request_failure("SABnzbd", e, apikey)
    if response.status_code != 200:
        return Probe(False, "SABnzbd answered with HTTP %s" % response.status_code, latency)
    try:
        version = (response.json() or {}).get("version")
    except ValueError:
        return Probe(False, "That address didn't answer like SABnzbd", latency)
    if not apikey:
        return Probe(False, "Reachable, but no API key is set", latency, version)
    try:
        queue, _ = _timed_get(
            url,
            params={"mode": "queue", "output": "json", "limit": 0, "apikey": apikey},
            verify=verify,
            allow_redirects=False,
        )
        payload = queue.json() if queue.status_code == 200 else {}
    except (requests.exceptions.RequestException, ValueError) as e:
        return Probe(False, _scrub(e, apikey), latency, version)
    if isinstance(payload, dict) and payload.get("error"):
        return Probe(False, "SABnzbd rejected the API key", latency, version)
    slots = (payload.get("queue") or {}).get("noofslots") if isinstance(payload, dict) else None
    try:
        active = int(slots) if slots is not None else None
    except (TypeError, ValueError):
        active = None
    return Probe(True, "Reachable", latency, version, active)


def _probe_nzbget(config) -> Probe:
    host = _text(getattr(config, "NZBGET_HOST", None)).rstrip("/")
    if not host.startswith(("http://", "https://")):
        return Probe(None, "Host needs http:// or https://")
    port = _text(getattr(config, "NZBGET_PORT", None))
    sub = _text(getattr(config, "NZBGET_SUB", None)).strip("/")
    base = "%s:%s" % (host, port) if port else host
    if sub:
        base = "%s/%s" % (base, sub)
    username = _text(getattr(config, "NZBGET_USERNAME", None))
    password = _text(getattr(config, "NZBGET_PASSWORD", None))
    auth = (username, password) if username or password else None
    try:
        response, latency = _timed_get(base + "/jsonrpc/version", auth=auth, allow_redirects=False)
    except requests.exceptions.RequestException as e:
        return _request_failure("NZBGet", e, password)
    if response.status_code == 401:
        return Probe(False, "NZBGet rejected the username or password", latency)
    if response.status_code != 200:
        return Probe(False, "NZBGet answered with HTTP %s" % response.status_code, latency)
    try:
        version = (response.json() or {}).get("result")
    except ValueError:
        return Probe(False, "That address didn't answer like NZBGet", latency)
    return Probe(True, "Reachable", latency, str(version) if version else None)


def _probe_folder(path_key) -> Callable[[object], Probe]:
    def probe(config) -> Probe:
        import os

        path = _text(getattr(config, path_key, None))
        if not path:
            return Probe(False, "No folder set")
        real = os.path.realpath(os.path.expanduser(path))
        if not os.path.isdir(real):
            return Probe(False, "Folder not found: %s" % path)
        if not os.access(real, os.W_OK):
            return Probe(False, "Comicarr can't write to %s" % path)
        return Probe(True, "Ready", latency_label="local")

    return probe


def _probe_torrent(client) -> Callable[[object], Probe]:
    def probe(config) -> Probe:
        host = _text(getattr(config, _TORRENT_HOST_KEYS[client], None))
        if not host:
            return Probe(None, "No host set")
        prefix = client.upper()
        username = _text(getattr(config, prefix + "_USERNAME", None))
        password = _text(getattr(config, prefix + "_PASSWORD", None))
        started = time.monotonic()
        try:
            result = _connect_torrent(client, config, host, username, password)
        except Exception as e:
            return Probe(False, _scrub(e, password))
        latency = round((time.monotonic() - started) * 1000, 1)
        if isinstance(result, dict) and result.get("status") is False:
            return Probe(False, _scrub(result.get("error") or "Connection failed", password), latency)
        version = result.get("version") if isinstance(result, dict) else None
        return Probe(True, "Reachable", latency, str(version) if version else None)

    return probe


def _connect_torrent(client, config, host, username, password):
    if client == "qbittorrent":
        from comicarr.torrent.clients.qbittorrent import TorrentClient

        return TorrentClient().connect(host, username, password, test=True)
    if client == "deluge":
        from comicarr.torrent.clients.deluge import TorrentClient

        return TorrentClient().connect(host, username, password, test=True)
    if client == "transmission":
        from comicarr.torrent.clients.transmission import TorrentClient

        conn = TorrentClient().connect(host, username, password)
        if isinstance(conn, dict):
            return conn
        try:
            return {"status": True, "version": conn.get_session().version}
        except Exception as e:
            return {"status": False, "error": str(e)}
    if client == "rtorrent":
        from comicarr.torrent.clients.rtorrent import TorrentClient

        return TorrentClient().connect(
            host,
            username,
            password,
            getattr(config, "RTORRENT_AUTHENTICATION", "basic"),
            getattr(config, "RTORRENT_VERIFY", False),
            getattr(config, "RTORRENT_RPC_URL", None),
            getattr(config, "RTORRENT_CA_BUNDLE", None),
            test=True,
        )
    from comicarr.torrent.clients.utorrent import TorrentClient

    return TorrentClient().connect(host, username, password)


# ── indexers ────────────────────────────────────────────────────────────────


def _indexer_targets(config):
    from comicarr.app.search import prowlarr
    from comicarr.app.search.provider_config import providers_from_config

    targets = []
    if getattr(config, "NEWZNAB", False):
        for provider in providers_from_config(config, "newznab"):
            if provider.enabled and provider.host:
                url = provider.host.rstrip("/")
                if not url.endswith("api"):
                    url += "/api"
                targets.append((provider.name, url, provider.api_key, provider.verify))
    if getattr(config, "ENABLE_TORZNAB", False):
        for provider in providers_from_config(config, "torznab"):
            if provider.enabled and provider.host:
                targets.append((provider.name, provider.host.rstrip("/"), provider.api_key, provider.verify))
    if prowlarr.configured(config):
        targets.append(("Prowlarr", None, _text(getattr(config, "PROWLARR_APIKEY", None)), None))
    return targets


def _probe_one_indexer(config, name, url, api_key, verify):
    if url is None:
        from comicarr.app.search import prowlarr

        started = time.monotonic()
        result = prowlarr.check_connection(
            getattr(config, "PROWLARR_HOST", None),
            api_key,
            verify=bool(getattr(config, "PROWLARR_VERIFY", True)),
            timeout=_TIMEOUT,
        )
        latency = round((time.monotonic() - started) * 1000, 1)
        return bool(result.get("success")), latency, result.get("error")
    try:
        response, latency = _timed_get(
            url, params={"t": "caps", "apikey": api_key}, verify=bool(verify), allow_redirects=False
        )
    except requests.exceptions.RequestException as e:
        return False, None, _request_failure(name, e, api_key).result
    if response.status_code != 200:
        return False, latency, "%s answered with HTTP %s" % (name, response.status_code)
    body = response.text[:2000].lower()
    if "<error" in body:
        return False, latency, "%s returned an error" % name
    return True, latency, None


def _probe_indexers(config) -> Probe:
    targets = _indexer_targets(config)
    if not targets:
        return Probe(None, "No indexers enabled")
    latencies = []
    failures = []
    for name, url, api_key, verify in targets:
        ok, latency, error = _probe_one_indexer(config, name, url, api_key, verify)
        if ok and latency is not None:
            latencies.append(latency)
        if not ok:
            failures.append(_scrub(error or name, api_key))
    median = round(statistics.median(latencies), 1) if latencies else None
    responding = len(targets) - len(failures)
    if not failures:
        return Probe(True, "All responding", median, latency_label="median", responding=responding)
    if len(failures) == len(targets):
        result = failures[0] if len(failures) == 1 else "None responding"
        return Probe(False, result, median, latency_label="median", responding=0)
    return Probe(
        False,
        "%s of %s not responding: %s" % (len(failures), len(targets), failures[0]),
        median,
        latency_label="median",
        responding=responding,
    )


# ── metadata sources ────────────────────────────────────────────────────────


def _probe_comicvine(config) -> Probe:
    api_key = _text(getattr(config, "COMICVINE_API", None))
    if not api_key:
        return Probe(None, "No API key set")
    headers = {"User-Agent": _text(getattr(config, "CV_USER_AGENT", None)) or "Comicarr"}
    try:
        response, latency = _timed_get(
            "https://comicvine.gamespot.com/api/types/",
            params={"api_key": api_key, "format": "json"},
            headers=headers,
        )
    except requests.exceptions.RequestException as e:
        return _request_failure("ComicVine", e, api_key)
    if response.status_code in (401, 403):
        return Probe(False, "ComicVine rejected the API key", latency)
    if response.status_code == 420 or response.status_code == 429:
        return Probe(False, "Rate limited by ComicVine", latency)
    if response.status_code != 200:
        return Probe(False, "ComicVine answered with HTTP %s" % response.status_code, latency)
    try:
        status = (response.json() or {}).get("status_code")
    except ValueError:
        status = None
    if status not in (None, 1):
        return Probe(False, "ComicVine rejected the API key", latency)
    return Probe(True, "Reachable", latency)


def _probe_metron(config) -> Probe:
    username = _text(getattr(config, "METRON_USERNAME", None))
    password = _text(getattr(config, "METRON_PASSWORD", None))
    if not username or not password:
        return Probe(None, "No account set")
    try:
        response, latency = _timed_get(
            "https://metron.cloud/api/publisher/",
            params={"page_size": 1},
            auth=(username, password),
            headers={"User-Agent": "Comicarr"},
        )
    except requests.exceptions.RequestException as e:
        return _request_failure("Metron", e, password)
    if response.status_code in (401, 403):
        return Probe(False, "Metron rejected the username or password", latency)
    if response.status_code == 429:
        return Probe(False, "Rate limited by Metron", latency)
    if response.status_code != 200:
        return Probe(False, "Metron answered with HTTP %s" % response.status_code, latency)
    return Probe(True, "Reachable", latency)


def _probe_mangadex(config) -> Probe:
    try:
        response, latency = _timed_get("https://api.mangadex.org/ping", headers={"User-Agent": "Comicarr"})
    except requests.exceptions.RequestException as e:
        return _request_failure("MangaDex", e)
    if response.status_code == 429:
        return Probe(False, "Rate limited by MangaDex", latency)
    if response.status_code != 200:
        return Probe(False, "MangaDex answered with HTTP %s" % response.status_code, latency)
    return Probe(True, "Reachable", latency)


# ── registry ────────────────────────────────────────────────────────────────


def configured_connections(config=None) -> list[Connection]:
    """Every connection the current settings describe, in display order."""
    config = _config(config)
    if config is None:
        return []
    found = []
    nzb = _NZB_CLIENTS.get(int(getattr(config, "NZB_DOWNLOADER", 3) or 0))
    if nzb == "sabnzbd" and _text(getattr(config, "SAB_HOST", None)):
        found.append(Connection("sabnzbd", LABELS["sabnzbd"], "client", "nzb", _probe_sabnzbd))
    elif nzb == "nzbget" and _text(getattr(config, "NZBGET_HOST", None)):
        found.append(Connection("nzbget", LABELS["nzbget"], "client", "nzb", _probe_nzbget))
    elif nzb == "blackhole" and _text(getattr(config, "BLACKHOLE_DIR", None)):
        found.append(Connection("blackhole", LABELS["blackhole"], "client", "nzb", _probe_folder("BLACKHOLE_DIR")))

    if getattr(config, "ENABLE_TORRENTS", False):
        torrent = _TORRENT_CLIENTS.get(int(getattr(config, "TORRENT_DOWNLOADER", 0) or 0))
        if torrent == "watchdir":
            if _text(getattr(config, "LOCAL_WATCHDIR", None)):
                found.append(
                    Connection("watchdir", LABELS["watchdir"], "client", "torrent", _probe_folder("LOCAL_WATCHDIR"))
                )
        elif torrent and _text(getattr(config, _TORRENT_HOST_KEYS[torrent], None)):
            found.append(Connection(torrent, LABELS[torrent], "client", "torrent", _probe_torrent(torrent)))

    if getattr(config, "ENABLE_DDL", False):
        found.append(Connection("ddl", LABELS["ddl"], "client", "ddl", _probe_folder("DDL_LOCATION")))

    if _indexer_targets(config):
        found.append(Connection("indexers", LABELS["indexers"], "indexers", None, _probe_indexers))
    if _text(getattr(config, "COMICVINE_API", None)):
        found.append(Connection("comicvine", LABELS["comicvine"], "metadata", None, _probe_comicvine))
    if _text(getattr(config, "METRON_USERNAME", None)) and _text(getattr(config, "METRON_PASSWORD", None)):
        found.append(Connection("metron", LABELS["metron"], "metadata", None, _probe_metron))
    if getattr(config, "MANGADEX_ENABLED", False):
        found.append(Connection("mangadex", LABELS["mangadex"], "metadata", None, _probe_mangadex))
    return found


def _entry(connection: Connection, probe: Probe | None, checked_at: float | None, config) -> dict:
    entry = {
        "key": connection.key,
        "label": connection.label,
        "kind": connection.kind,
        "route": connection.route,
        "checked_at": checked_at,
        "ok": None,
        "result": None,
        "latency_ms": None,
        "latency_label": None,
        "version": None,
        "active": None,
        "responding": None,
    }
    if probe is not None:
        entry.update(asdict(probe))
    if connection.kind == "indexers":
        entry["count"] = len(_indexer_targets(config))
    return entry


def test_connection(key, config=None) -> dict | None:
    """Run one probe now and remember its answer. ``None`` for an unknown key."""
    config = _config(config)
    connection = next((c for c in configured_connections(config) if c.key == key), None)
    if connection is None:
        return None
    try:
        probe = connection.probe(config)
    except Exception as e:
        logger.warn("[CONNECTIONS] %s check failed unexpectedly: %s" % (connection.label, e))
        probe = Probe(False, _scrub(e))
    entry = _entry(connection, probe, time.time(), config)
    with _LOCK:
        _RESULTS[key] = entry
    return entry


def test_all(config=None) -> list[dict]:
    config = _config(config)
    return [test_connection(c.key, config) for c in configured_connections(config)]


def snapshot(config=None) -> list[dict]:
    """The configured connections with the last answer each one gave."""
    config = _config(config)
    with _LOCK:
        known = dict(_RESULTS)
    rows = []
    for connection in configured_connections(config):
        stored = known.get(connection.key)
        if stored is not None:
            stored = {**stored, "label": connection.label, "route": connection.route}
            if connection.kind == "indexers":
                stored["count"] = len(_indexer_targets(config))
            rows.append(stored)
        else:
            rows.append(_entry(connection, None, None, config))
    return rows


def reset():
    """Forget every stored answer (tests, and after a settings change)."""
    with _LOCK:
        _RESULTS.clear()


def summarize(rows) -> str:
    checked = [row for row in rows if row.get("ok") is not None]
    if not checked:
        return "Nothing to check"
    good = sum(1 for row in checked if row["ok"])
    if good == len(checked):
        return "%s of %s reachable" % (good, len(checked))
    return "%s of %s not responding" % (len(checked) - good, len(checked))


def run():
    """Scheduled entry point: check everything and leave a one-line summary."""
    from comicarr.app.system import job_results

    rows = test_all()
    job_results.record(JOB_ID, summarize(rows))
    return rows
