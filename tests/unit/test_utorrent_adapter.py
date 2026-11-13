#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""uTorrent adapter behavior against recorded WebUI responses (#1229).

These fixtures were recorded against the adapter before its WebUI client was
replaced, and they must pass unchanged after the swap. A local HTTP server
plays the WebUI so the real request and response path runs.
"""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qsl, urlsplit

import pytest

from comicarr.torrent.clients import utorrent

USERNAME = "admin"
PASSWORD = "secret"
TOKEN = "TOKEN-XYZ"
HASH = "ABC123"

TORRENT = [HASH, 201, "My Comic", 1000, 1000] + [0] * 6 + ["comics"] + [0] * 14 + ["/downloads/My Comic"]
TOKEN_PAGE = "<html><div id='token' style='display:none;'>%s</div></html>" % TOKEN
LIST_RESPONSE = {"build": 1, "label": [], "torrents": [TORRENT], "torrentc": "1"}
FILES_RESPONSE = {
    "build": 1,
    "files": [HASH, [["My Comic 001.cbz", 100, 100, 2], ["sub/My Comic 002.cbz", 100, 100, 2]]],
}
ACTION_RESPONSE = {"build": 1}


class _WebUI(BaseHTTPRequestHandler):
    requests = None

    def log_message(self, *args):
        pass

    def do_GET(self):
        expected = "Basic " + base64.b64encode(("%s:%s" % (USERNAME, PASSWORD)).encode()).decode()
        if self.headers.get("Authorization") != expected:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="uTorrent"')
            self.end_headers()
            return

        parts = urlsplit(self.path)
        query = dict(parse_qsl(parts.query))
        self.requests.append((parts.path, query, self.headers.get("Cookie")))

        if parts.path == "/gui/token.html":
            self._send(TOKEN_PAGE.encode(), cookie="GUID=guid123")
            return
        if query.get("token") != TOKEN:
            self.send_response(400)
            self.end_headers()
            return
        if query.get("list") == "1":
            payload = LIST_RESPONSE
        elif query.get("action") == "getfiles":
            payload = FILES_RESPONSE
        else:
            payload = ACTION_RESPONSE
        self._send(json.dumps(payload).encode())

    def _send(self, body, cookie=None):
        self.send_response(200)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def webui():
    handler = type("Handler", (_WebUI,), {"requests": []})
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d/gui/" % server.server_address[1], handler.requests
    finally:
        server.shutdown()
        server.server_close()


def _connected(url):
    adapter = utorrent.TorrentClient()
    adapter.connect(url, USERNAME, PASSWORD)
    return adapter


def _calls(requests):
    """The authenticated requests after the token fetch, as (action, hash)."""
    calls = []
    for path, query, cookie in requests:
        if path == "/gui/token.html":
            continue
        assert path == "/gui/"
        assert query.pop("token") == TOKEN
        assert cookie == "GUID=guid123"
        calls.append(query)
    return calls


def test_connect_fetches_token(webui):
    url, requests = webui
    adapter = utorrent.TorrentClient()

    conn = adapter.connect(url, USERNAME, PASSWORD)

    assert conn is adapter.conn
    assert [path for path, _query, _cookie in requests] == ["/gui/token.html"]


def test_connect_returns_existing_connection(webui):
    url, requests = webui
    adapter = _connected(url)
    first = adapter.conn

    assert adapter.connect(url, USERNAME, PASSWORD) is first
    assert len(requests) == 1


def test_connect_without_host_fails():
    result = utorrent.TorrentClient().connect("", USERNAME, PASSWORD)

    assert result["status"] is False
    assert result["error"] == "No host specified"


def test_connect_with_wrong_password_fails(webui):
    url, _requests = webui

    result = utorrent.TorrentClient().connect(url, USERNAME, "wrong")

    assert result["status"] is False
    assert "401" in str(result["error"])


def test_connect_without_credentials_fails(webui):
    url, _requests = webui

    result = utorrent.TorrentClient().connect(url, None, None)

    assert result["status"] is False


def test_find_torrent_lists_and_matches_hash(webui):
    url, requests = webui
    adapter = _connected(url)

    found = adapter.find_torrent(HASH)
    missing = adapter.find_torrent("NOPE")

    assert found == TORRENT
    assert missing is False
    assert _calls(requests) == [{"list": "1"}, {"list": "1"}]


def test_get_torrent_reads_files_and_properties(webui):
    url, requests = webui
    adapter = _connected(url)

    info = adapter.get_torrent(TORRENT)

    assert info == {
        "hash": HASH,
        "name": "My Comic",
        "label": "comics",
        "folder": "/downloads/My Comic",
        "completed": True,
        "files": ["/downloads/My Comic/My Comic 001.cbz", "/downloads/My Comic/sub/My Comic 002.cbz"],
    }
    assert _calls(requests) == [{"action": "getfiles", "hash": HASH}]


def test_get_torrent_rejects_pre_3_clients(webui):
    url, _requests = webui
    adapter = _connected(url)
    old = list(TORRENT)
    old[26] = ""

    with pytest.raises(Exception, match="uTorrent 3.0"):
        adapter.get_torrent(old)


def test_start_torrent_sends_start_action(webui):
    url, requests = webui
    adapter = _connected(url)

    result = adapter.start_torrent(HASH)

    assert result == (200, ACTION_RESPONSE)
    assert _calls(requests) == [{"action": "start", "hash": HASH}]


def test_stop_torrent_sends_stop_action(webui):
    url, requests = webui
    adapter = _connected(url)

    result = adapter.stop_torrent(HASH)

    assert result == (200, ACTION_RESPONSE)
    assert _calls(requests) == [{"action": "stop", "hash": HASH}]


def test_delete_torrent_lists_files_then_removes_data(webui):
    url, requests = webui
    adapter = _connected(url)

    deleted = adapter.delete_torrent(TORRENT)

    assert deleted == ["/downloads/My Comic/My Comic 001.cbz", "/downloads/My Comic/sub/My Comic 002.cbz"]
    assert _calls(requests) == [
        {"action": "getfiles", "hash": HASH},
        {"action": "removedata", "hash": HASH},
    ]
