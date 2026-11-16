#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Transmission adapter against a fake RPC daemon over real HTTP (#1412)."""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from comicarr.torrent.clients import transmission

HASH = "b" * 40
SESSION_ID = "fake-session"


class FakeDaemon:
    def __init__(self, require_auth=None):
        self.require_auth = require_auth
        self.calls = []
        self.paths = []
        self.added = None
        self.started = []
        self.torrents = {}


def _torrent(download_dir):
    return {
        "id": 1,
        "hashString": HASH,
        "name": "Saga 001",
        "downloadDir": download_dir,
        "percentDone": 1.0,
        "uploadedEver": 10,
        "downloadedEver": 20,
        "uploadRatio": 0.5,
        "sizeWhenDone": 20,
        "startDate": 1_700_000_000,
        "files": [{"name": "Saga 001/Saga 001.cbz", "length": 20, "bytesCompleted": 20}],
        "fileStats": [{"bytesCompleted": 20, "wanted": True, "priority": 0}],
        "priorities": [0],
        "wanted": [1],
    }


def _handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, status, payload=None):
            data = json.dumps(payload or {}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Transmission-Session-Id", SESSION_ID)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            state.paths.append(self.path)
            if state.require_auth:
                expected = "Basic " + base64.b64encode(state.require_auth.encode()).decode()
                if self.headers.get("Authorization") != expected:
                    return self._reply(401)
            if self.headers.get("X-Transmission-Session-Id") != SESSION_ID:
                return self._reply(409)
            method, args = body.get("method"), body.get("arguments") or {}
            state.calls.append(method)
            result = {"result": "success", "tag": body.get("tag"), "arguments": {}}
            if method == "session-get":
                result["arguments"] = {"version": "4.0.6", "rpc-version": 17, "rpc-version-minimum": 14}
            elif method == "torrent-add":
                state.added = args
                state.torrents[HASH] = _torrent(args.get("download-dir"))
                result["arguments"] = {"torrent-added": {"id": 1, "hashString": HASH, "name": "Saga 001"}}
            elif method == "torrent-get":
                result["arguments"] = {"torrents": [t for h, t in state.torrents.items() if h in args.get("ids", [])]}
            elif method == "torrent-start":
                state.started.append(args.get("ids"))
            return self._reply(200, result)

    return Handler


@pytest.fixture
def daemon():
    servers = []

    def start(require_auth=None):
        state = FakeDaemon(require_auth)
        server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return state, server.server_address[1]

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("http://localhost:9091", ("http", "localhost", 9091, "/transmission/rpc")),
        ("https://nas.example:443/custom/rpc", ("https", "nas.example", 443, "/custom/rpc")),
        ("localhost:9092", ("http", "localhost", 9092, "/transmission/rpc")),
        ("localhost", ("http", "localhost", 9091, "/transmission/rpc")),
    ],
)
def test_rpc_target_reads_documented_and_legacy_host_forms(address, expected):
    target = transmission.rpc_target(address)

    assert (target["protocol"], target["host"], target["port"], target["path"]) == expected


def test_connect_reaches_the_rpc_path_with_credentials(daemon):
    state, port = daemon(require_auth="user:secret")

    conn = transmission.TorrentClient().connect("http://127.0.0.1:%d" % port, "user", "secret")

    assert not isinstance(conn, dict)
    assert conn.get_session().version == "4.0.6"
    assert set(state.paths) == {"/transmission/rpc"}


def test_credentials_in_the_url_are_used_when_settings_have_none(daemon):
    state, port = daemon(require_auth="user:secret")

    conn = transmission.TorrentClient().connect("http://user:secret@127.0.0.1:%d" % port, "", "")

    assert not isinstance(conn, dict)
    assert "session-get" in state.calls


def test_wrong_credentials_are_a_connection_failure(daemon):
    _, port = daemon(require_auth="user:secret")

    result = transmission.TorrentClient().connect("http://127.0.0.1:%d" % port, "user", "wrong")

    assert result["status"] is False


def test_load_torrent_sends_the_file_and_reports_its_files(daemon, monkeypatch, tmp_path):
    state, port = daemon()
    monkeypatch.setattr(
        transmission.comicarr,
        "CONFIG",
        SimpleNamespace(TRANSMISSION_DIRECTORY="/downloads/comics", CHECK_FOLDER="/unused"),
    )
    torrent_file = tmp_path / "saga.torrent"
    torrent_file.write_bytes(b"d4:infod4:name4:sagaee")
    adapter = transmission.TorrentClient()
    adapter.connect("http://127.0.0.1:%d" % port, None, None)

    info = adapter.load_torrent(str(torrent_file))

    assert base64.b64decode(state.added["metainfo"]) == b"d4:infod4:name4:sagaee"
    assert state.added["download-dir"] == "/downloads/comics"
    assert state.started == [[HASH]]
    assert info["hash"] == HASH
    assert info["completed"] is True
    assert info["folder"] == "/downloads/comics"
    assert info["files"] == ["/downloads/comics/Saga 001/Saga 001.cbz"]
    assert info["total_filesize"] == 20


def test_missing_torrent_is_not_found(daemon):
    _, port = daemon()
    adapter = transmission.TorrentClient()
    adapter.connect("http://127.0.0.1:%d" % port, None, None)

    assert adapter.find_torrent(HASH) is False
