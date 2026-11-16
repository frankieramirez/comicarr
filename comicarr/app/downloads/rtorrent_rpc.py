#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""A small first-party rTorrent XML-RPC client.

It covers only what Comicarr does with rTorrent: read the version, find a
download by info hash, add a .torrent or magnet, label it, move it, start and
stop it, and read its files. Three transports are supported:

* ``http://`` and ``https://``, with optional basic or digest auth and TLS
  verification against the system store or a CA bundle;
* ``scgi://host:port`` and ``scgi:///path/to/socket``;
* ``httprpc://`` and ``httprpc+https://``, ruTorrent's HTTPRPC plugin.

rTorrent 0.9.7 renamed most commands. Older daemons get the old names from
``_LEGACY_NAMES`` so both keep working.
"""

import socket
import time
import xmlrpc.client
from urllib.parse import urlparse, urlunparse

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

DEFAULT_TIMEOUT = 30
VERIFY_RETRIES = 3

_LEGACY_NAMES = {
    "d.name": "d.get_name",
    "d.directory": "d.get_directory",
    "d.custom1": "d.get_custom1",
    "d.complete": "d.get_complete",
    "d.up.total": "d.get_up_total",
    "d.down.total": "d.get_down_total",
    "d.ratio": "d.get_ratio",
    "d.size_bytes": "d.get_size_bytes",
    "d.custom1.set": "d.set_custom1",
    "d.directory.set": "d.set_directory",
    "d.hash": "d.get_hash",
    "f.path": "f.get_path",
    "load.raw": "load_raw",
    "load.raw_start": "load_raw_start",
    "load.normal": "load",
    "load.start": "load_start",
}

_FIELDS = (
    ("name", "d.name"),
    ("directory", "d.directory"),
    ("label", "d.custom1"),
    ("complete", "d.complete"),
    ("up_total", "d.up.total"),
    ("down_total", "d.down.total"),
    ("ratio", "d.ratio"),
    ("size_bytes", "d.size_bytes"),
    ("time_started", "d.timestamp.started"),
    ("multi_file", "d.is_multi_file"),
)


class RTorrentError(Exception):
    """rTorrent could not be reached or refused a command."""


def endpoint(uri):
    """Resolve ``httprpc`` schemes to the ruTorrent plugin URL; others pass through."""
    url = urlparse(uri)
    if url.scheme == "httprpc" or url.scheme.startswith("httprpc+"):
        scheme = url.scheme.split("+", 1)[1] if "+" in url.scheme else "http"
        path = url.path.rstrip("/") + "/plugins/httprpc/action.php"
        return urlunparse(url._replace(scheme=scheme, path=path))
    return uri


class _HTTPTransport:
    def __init__(self, uri, auth, verify):
        self.uri = uri
        self.session = requests.Session()
        self.session.verify = verify
        method, username, password = auth or (None, None, None)
        if username and password:
            if method == "digest":
                self.session.auth = HTTPDigestAuth(username, password)
            else:
                self.session.auth = HTTPBasicAuth(username, password)

    def request(self, body):
        try:
            response = self.session.post(
                self.uri, data=body, headers={"Content-Type": "text/xml"}, timeout=DEFAULT_TIMEOUT
            )
        except requests.RequestException as e:
            raise RTorrentError(str(e)) from e
        if response.status_code != 200:
            raise RTorrentError("rTorrent answered HTTP %s" % response.status_code)
        return response.content


class _SCGITransport:
    def __init__(self, uri):
        url = urlparse(uri)
        if url.hostname:
            self.address = (socket.AF_INET, (url.hostname, url.port or 5000))
        else:
            self.address = (socket.AF_UNIX, url.path)

    def request(self, body):
        headers = b"CONTENT_LENGTH\x00%d\x00SCGI\x001\x00REQUEST_METHOD\x00POST\x00" % len(body)
        payload = b"%d:%s," % (len(headers), headers) + body
        family, address = self.address
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(DEFAULT_TIMEOUT)
                sock.connect(address)
                sock.sendall(payload)
                chunks = []
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
        except OSError as e:
            raise RTorrentError(str(e)) from e
        response = b"".join(chunks)
        _, _, content = response.partition(b"\r\n\r\n")
        return content or response


class Download:
    """One rTorrent download, read when created and refreshed on demand."""

    def __init__(self, session, info_hash):
        self.session = session
        self.info_hash = info_hash.upper()
        self.refresh()

    def refresh(self):
        values = self.session.multicall([(rpc, self.info_hash) for _, rpc in _FIELDS])
        for (attr, _), value in zip(_FIELDS, values, strict=True):
            setattr(self, attr, value)
        self.complete = bool(self.complete)
        self.multi_file = bool(self.multi_file)
        self.ratio = (self.ratio or 0) / 1000.0
        return self

    def files(self):
        rows = self.session.call("f.multicall", self.info_hash, "", self.session.name("f.path") + "=")
        return [row[0] for row in rows]

    def start(self):
        self.session.call("d.try_start", self.info_hash)
        return True

    def stop(self):
        self.session.call("d.try_stop", self.info_hash)
        return True

    def set_label(self, label):
        self.session.call("d.custom1.set", self.info_hash, label)
        self.label = label

    def set_directory(self, directory):
        self.session.call("d.try_stop", self.info_hash)
        self.session.call("d.directory.set", self.info_hash, directory)
        self.directory = directory

    def erase(self):
        self.session.call("d.erase", self.info_hash)


class Session:
    """A connection to one rTorrent daemon."""

    def __init__(self, uri, auth=None, verify=True, sleep=time.sleep):
        uri = endpoint(uri)
        scheme = urlparse(uri).scheme
        if scheme in ("http", "https"):
            self.transport = _HTTPTransport(uri, auth, verify)
        elif scheme == "scgi":
            self.transport = _SCGITransport(uri)
        else:
            raise RTorrentError("unsupported rTorrent URL scheme %r" % scheme)
        self.sleep = sleep
        self.modern = True
        self.version_text = self.call("system.client_version")
        self.version = tuple(int(part) for part in str(self.version_text).split(".") if part.isdigit())
        self.modern = self.version >= (0, 9, 7)

    def name(self, command):
        return command if self.modern else _LEGACY_NAMES.get(command, command)

    def call(self, method, *params):
        body = xmlrpc.client.dumps(params, methodname=self.name(method)).encode("utf-8")
        try:
            (result,), _ = xmlrpc.client.loads(self.transport.request(body))
        except xmlrpc.client.Fault as e:
            raise RTorrentError(e.faultString) from e
        except RTorrentError:
            raise
        except Exception as e:
            raise RTorrentError("unreadable reply from rTorrent: %s" % e) from e
        return result

    def multicall(self, calls):
        batch = [{"methodName": self.name(method), "params": list(params)} for method, *params in calls]
        results = self.call("system.multicall", batch)
        values = []
        for result in results:
            if isinstance(result, dict):
                raise RTorrentError(result.get("faultString", "rTorrent refused a command"))
            values.append(result[0])
        return values

    def hashes(self):
        if self.modern:
            rows = self.call("d.multicall2", "", "main", "d.hash=")
        else:
            rows = self.call("d.multicall", "main", "d.get_hash=")
        return [row[0].upper() for row in rows]

    def find(self, info_hash):
        info_hash = info_hash.upper()
        if info_hash not in self.hashes():
            return None
        return Download(self, info_hash)

    def _load(self, command, payload):
        args = ("", payload) if self.modern else (payload,)
        self.call(command, *args)

    def _wait_for(self, info_hash):
        for attempt in range(VERIFY_RETRIES):
            found = self.find(info_hash)
            if found is not None:
                return found
            if attempt < VERIFY_RETRIES - 1:
                self.sleep(1)
        return None

    def load_raw(self, data, info_hash, start=False):
        """Add a .torrent from its bytes; the Download once rTorrent lists it, else None."""
        self._load("load.raw_start" if start else "load.raw", xmlrpc.client.Binary(data))
        return self._wait_for(info_hash)

    def load_magnet(self, magnet, info_hash):
        """Add and start a magnet; wait briefly for its metadata to replace the hash name."""
        self._load("load.normal", magnet)
        download = self._wait_for(info_hash)
        if download is None:
            return None
        download.start()
        for _ in range(VERIFY_RETRIES):
            if download.info_hash not in str(download.name).upper():
                break
            self.sleep(1)
            download.refresh()
        return download
