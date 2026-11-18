#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""qBittorrent login and add handling across Web API versions (#1159, #1410).

The client talks to a fake qBittorrent WebUI over real HTTP, so these tests
cover what ``qbittorrent-api`` actually sends and how the adapter reads it.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from comicarr.app.downloads.torrent.clients import qbittorrent

HASH = "A" * 40
MAGNET = "magnet:?xt=urn:btih:" + HASH


class FakeWebUI:
    def __init__(self, login_status, login_body):
        self.login_status = login_status
        self.login_body = login_body
        self.posts = []
        self.added = {}
        self.present = False


def _handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status, body="", content_type="text/plain"):
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            if self.path.endswith("auth/login") and status < 300:
                self.send_header("Set-Cookie", "SID=fake; path=/")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if path.endswith("app/version"):
                return self._send(200, "v5.2.4")
            if path.endswith("app/webapiVersion"):
                return self._send(200, "2.11.4")
            if path.endswith("torrents/properties"):
                if not state.present:
                    return self._send(404, "")
                body = {"save_path": "/downloads", "total_size": 1, "addition_date": 0}
                return self._send(200, json.dumps(body), "application/json")
            if path.endswith("torrents/files"):
                return self._send(200, json.dumps([{"name": "Absolute Wonder Woman 001.cbz"}]), "application/json")
            return self._send(404, "")

        do_POST_body = None

        def do_POST(self):
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            state.posts.append(path)
            if path.endswith("auth/login"):
                return self._send(state.login_status, state.login_body)
            if path.endswith("torrents/add"):
                state.present = True
                state.added = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
                return self._send(200, "Ok.")
            if path.endswith("torrents/properties"):
                fields = parse_qs(raw.decode())
                if not state.present or not fields.get("hash"):
                    return self._send(404, "")
                body = {"save_path": "/downloads", "total_size": 1, "addition_date": 0}
                return self._send(200, json.dumps(body), "application/json")
            if path.endswith("torrents/files"):
                return self._send(200, json.dumps([{"name": "Absolute Wonder Woman 001.cbz"}]), "application/json")
            if path.endswith("app/version"):
                return self._send(200, "v5.2.4")
            return self._send(404, "")

    return Handler


@pytest.fixture
def webui():
    servers = []

    def start(login_status=204, login_body=""):
        state = FakeWebUI(login_status, login_body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return state, "http://127.0.0.1:%d" % server.server_address[1]

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def config(monkeypatch):
    import comicarr

    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(QBITTORRENT_LOADACTION="default"))
    monkeypatch.setattr(
        "comicarr.app.downloads.torrent_routing.qbittorrent_destination",
        lambda _config, _comicid: SimpleNamespace(category="comics", savepath=None),
    )


@pytest.mark.parametrize(
    ("status", "body"),
    [(204, ""), (200, "Ok.")],
    ids=["qbt-5.2-204-empty", "legacy-200-ok"],
)
def test_successful_login_connects(webui, status, body):
    _, host = webui(status, body)
    adapter = qbittorrent.TorrentClient()

    assert adapter.connect(host, "user", "secret") is adapter
    assert adapter.authenticated is True


@pytest.mark.parametrize(
    ("status", "body"),
    [(200, "Fails."), (403, "Your IP address has been banned"), (401, "")],
    ids=["wrong-password", "ip-banned", "unauthorized-empty"],
)
def test_failed_login_reports_login_failure(webui, status, body):
    _, host = webui(status, body)
    adapter = qbittorrent.TorrentClient()

    result = adapter.connect(host, "user", "wrong")

    assert result["status"] is False
    assert "login failed" in result["error"]
    assert adapter.conn is None
    assert adapter.authenticated is False


def test_204_login_lets_grab_reach_torrents_add(webui, config, monkeypatch):
    state, host = webui(204, "")
    monkeypatch.setattr(qbittorrent.time, "sleep", lambda _seconds: None)
    adapter = qbittorrent.TorrentClient()

    assert adapter.connect(host, "user", "secret") is adapter
    info = adapter.load_torrent(MAGNET)

    assert any(path.endswith("torrents/add") for path in state.posts)
    assert state.added == {"urls": MAGNET, "category": "comics"}
    assert info["status"] is True
    assert info["hash"] == HASH
    assert info["label"] == "comics"
    assert info["name"] == "Absolute Wonder Woman 001.cbz"


def test_204_login_passes_connection_test(webui):
    _, host = webui(204, "")

    result = qbittorrent.TorrentClient().connect(host, "user", "secret", test=True)

    assert result == {"status": True, "version": "v5.2.4"}


def test_rejected_login_fails_connection_test(webui):
    _, host = webui(200, "Fails.")
    adapter = qbittorrent.TorrentClient()

    result = adapter.connect(host, "user", "wrong", test=True)

    assert result["status"] is False
    assert "login failed" in result["error"]
    assert adapter.conn is None


def test_unreachable_host_is_a_connection_failure():
    adapter = qbittorrent.TorrentClient()

    result = adapter.connect("http://127.0.0.1:9", "user", "secret")

    assert result["status"] is False
    assert adapter.conn is None


def test_unauthenticated_load_returns_error_without_waiting(config):
    adapter = qbittorrent.TorrentClient()

    with patch.object(qbittorrent.time, "sleep", side_effect=AssertionError("must not wait")):
        result = adapter.load_torrent(MAGNET)

    assert result == {"status": False, "error": "Not logged in to qBittorrent"}


def test_torrent_missing_after_add_reports_clear_error(config, monkeypatch):
    monkeypatch.setattr(qbittorrent.time, "sleep", lambda _seconds: None)
    adapter = qbittorrent.TorrentClient()
    adapter.client = SimpleNamespace(
        torrents_properties=MagicMock(side_effect=RuntimeError("404")),
        torrents_add=MagicMock(),
    )
    adapter.conn = adapter

    result = adapter.load_torrent(MAGNET)

    assert result == {"status": False, "error": "Torrent not found on qBittorrent after adding it"}
