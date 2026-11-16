#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""First-party rTorrent client against fake daemons over HTTP and SCGI (#1413)."""

import base64
import socket
import threading
import xmlrpc.client
from types import SimpleNamespace
from xmlrpc.server import SimpleXMLRPCDispatcher, SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

import pytest

from comicarr.app.downloads import rtorrent_rpc
from comicarr.torrent.clients import rtorrent

HASH = "C" * 40


class FakeDaemon:
    """In-memory rTorrent: modern (0.9.8) or legacy (0.9.6) command names."""

    def __init__(self, version="0.9.8"):
        self.version = version
        self.downloads = {}
        self.loaded = []
        self.started = []

    def _download(self, data_name):
        return {
            "name": data_name,
            "directory": "/downloads",
            "custom1": "",
            "complete": 1,
            "up": 10,
            "down": 20,
            "ratio": 1500,
            "size": 20,
            "started": 1_700_000_000,
            "multi": 0,
            "files": ["Saga 001.cbz"],
        }

    def functions(self):
        modern = self.version >= "0.9.7"
        get = (lambda new, old: new) if modern else (lambda new, old: old)

        def field(key):
            return lambda info_hash: self.downloads[info_hash][key]

        def load_raw(*args):
            data = args[-1].data if isinstance(args[-1], xmlrpc.client.Binary) else args[-1]
            self.loaded.append(("raw", data))
            self.downloads[HASH] = self._download("Saga 001")
            return 0

        def load_url(*args):
            self.loaded.append(("url", args[-1]))
            self.downloads[HASH] = self._download(HASH)
            return 0

        def try_start(info_hash):
            self.started.append(info_hash)
            self.downloads[info_hash]["name"] = "Saga 001"
            return 0

        def set_field(key):
            def setter(info_hash, value):
                self.downloads[info_hash][key] = value
                return 0

            return setter

        def multicall(*args):
            return [[h] for h in self.downloads]

        def files(info_hash, _empty, _cmd):
            return [[path] for path in self.downloads[info_hash]["files"]]

        return {
            "system.client_version": lambda: self.version,
            get("d.multicall2", "d.multicall"): multicall,
            get("d.name", "d.get_name"): field("name"),
            get("d.directory", "d.get_directory"): field("directory"),
            get("d.custom1", "d.get_custom1"): field("custom1"),
            get("d.complete", "d.get_complete"): field("complete"),
            get("d.up.total", "d.get_up_total"): field("up"),
            get("d.down.total", "d.get_down_total"): field("down"),
            get("d.ratio", "d.get_ratio"): field("ratio"),
            get("d.size_bytes", "d.get_size_bytes"): field("size"),
            "d.timestamp.started": field("started"),
            "d.is_multi_file": field("multi"),
            get("d.custom1.set", "d.set_custom1"): set_field("custom1"),
            get("d.directory.set", "d.set_directory"): set_field("directory"),
            "d.try_start": try_start,
            "d.try_stop": lambda info_hash: 0,
            "f.multicall": files,
            get("load.raw", "load_raw"): load_raw,
            get("load.raw_start", "load_raw_start"): load_raw,
            get("load.normal", "load"): load_url,
        }


def _register(dispatcher, daemon):
    for name, function in daemon.functions().items():
        dispatcher.register_function(function, name)
    dispatcher.register_multicall_functions()


@pytest.fixture
def http_daemon():
    servers = []

    def start(version="0.9.8", credentials=None):
        daemon = FakeDaemon(version)

        class Handler(SimpleXMLRPCRequestHandler):
            rpc_paths = ("/RPC2",)

            def log_message(self, *args):
                pass

            def parse_request(self):
                if not super().parse_request():
                    return False
                if credentials:
                    expected = "Basic " + base64.b64encode(credentials.encode()).decode()
                    if self.headers.get("Authorization") != expected:
                        self.send_error(401)
                        return False
                return True

        server = SimpleXMLRPCServer(("127.0.0.1", 0), requestHandler=Handler, logRequests=False, allow_none=True)
        _register(server, daemon)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return daemon, "http://127.0.0.1:%d/RPC2" % server.server_address[1]

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def scgi_daemon():
    listeners = []

    def start():
        daemon = FakeDaemon()
        dispatcher = SimpleXMLRPCDispatcher(allow_none=True)
        _register(dispatcher, daemon)
        listener = socket.create_server(("127.0.0.1", 0))
        listeners.append(listener)

        def serve():
            while True:
                try:
                    conn, _ = listener.accept()
                except OSError:
                    return
                with conn:
                    raw = b""
                    while b"," not in raw:
                        raw += conn.recv(4096)
                    size, _, rest = raw.partition(b":")
                    header_len = int(size)
                    while len(rest) < header_len + 1:
                        rest += conn.recv(4096)
                    headers = rest[:header_len].split(b"\x00")
                    length = int(headers[headers.index(b"CONTENT_LENGTH") + 1])
                    body = rest[header_len + 1 :]
                    while len(body) < length:
                        body += conn.recv(4096)
                    reply = dispatcher._marshaled_dispatch(body)
                    conn.sendall(b"Status: 200 OK\r\nContent-Type: text/xml\r\n\r\n" + reply)

        threading.Thread(target=serve, daemon=True).start()
        return daemon, "scgi://127.0.0.1:%d" % listener.getsockname()[1]

    yield start
    for listener in listeners:
        listener.close()


def _no_sleep(_seconds):
    pass


@pytest.mark.parametrize("version", ["0.9.8", "0.9.6"])
def test_raw_load_label_directory_and_read_back(http_daemon, version):
    daemon, url = http_daemon(version)
    session = rtorrent_rpc.Session(url, sleep=_no_sleep)

    download = session.load_raw(b"d4:infod4:name4:sagaee", HASH)
    download.set_label("comics")
    download.set_directory("/downloads/comics")
    download.refresh()

    assert daemon.loaded == [("raw", b"d4:infod4:name4:sagaee")]
    assert download.label == "comics"
    assert download.directory == "/downloads/comics"
    assert download.complete is True
    assert download.ratio == 1.5
    assert download.files() == ["Saga 001.cbz"]


def test_magnet_is_started_and_waits_for_its_name(http_daemon):
    daemon, url = http_daemon()
    session = rtorrent_rpc.Session(url, sleep=_no_sleep)

    download = session.load_magnet("magnet:?xt=urn:btih:" + HASH, HASH)

    assert daemon.loaded == [("url", "magnet:?xt=urn:btih:" + HASH)]
    assert daemon.started == [HASH]
    assert download.name == "Saga 001"


def test_missing_download_is_none(http_daemon):
    _, url = http_daemon()

    assert rtorrent_rpc.Session(url, sleep=_no_sleep).find(HASH) is None


def test_basic_auth_is_sent(http_daemon):
    _, url = http_daemon(credentials="user:secret")

    session = rtorrent_rpc.Session(url, auth=("basic", "user", "secret"))

    assert session.version_text == "0.9.8"
    with pytest.raises(rtorrent_rpc.RTorrentError):
        rtorrent_rpc.Session(url, auth=("basic", "user", "wrong"))


def test_scgi_transport(scgi_daemon):
    daemon, url = scgi_daemon()
    session = rtorrent_rpc.Session(url, sleep=_no_sleep)

    download = session.load_raw(b"raw", HASH)

    assert session.version == (0, 9, 8)
    assert download.name == "Saga 001"
    assert daemon.loaded == [("raw", b"raw")]


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("httprpc://seedbox/rutorrent/", "http://seedbox/rutorrent/plugins/httprpc/action.php"),
        ("httprpc+https://seedbox/rutorrent", "https://seedbox/rutorrent/plugins/httprpc/action.php"),
        ("https://seedbox/RPC2", "https://seedbox/RPC2"),
    ],
)
def test_httprpc_scheme_points_at_the_rutorrent_plugin(uri, expected):
    assert rtorrent_rpc.endpoint(uri) == expected


@pytest.mark.parametrize(
    ("host", "rpc_path", "expected"),
    [
        ("localhost:8080", "RPC2", "http://localhost:8080/RPC2"),
        ("https://seedbox:443", "RPC2", "https://seedbox:443/RPC2"),
        ("scgi://localhost:5000", "RPC2", "scgi://localhost:5000/"),
        ("httprpc://seedbox/rutorrent", None, "httprpc://seedbox/rutorrent/"),
    ],
)
def test_adapter_builds_the_rpc_url(host, rpc_path, expected):
    assert rtorrent.rpc_url(host, rpc_path) == expected


def test_adapter_send_and_check_round_trip(http_daemon, monkeypatch, tmp_path):
    daemon, url = http_daemon()
    monkeypatch.setattr(rtorrent_rpc.time, "sleep", _no_sleep)
    monkeypatch.setattr(
        rtorrent.comicarr,
        "CONFIG",
        SimpleNamespace(
            RTORRENT_HOST=url.rsplit("/", 1)[0],
            RTORRENT_RPC_URL="RPC2",
            RTORRENT_USERNAME=None,
            RTORRENT_PASSWORD=None,
            RTORRENT_AUTHENTICATION="basic",
            RTORRENT_VERIFY=False,
            RTORRENT_CA_BUNDLE=None,
            RTORRENT_STARTONLOAD=True,
            RTORRENT_LABEL="comics",
            RTORRENT_DIRECTORY=None,
        ),
    )
    monkeypatch.setattr(rtorrent, "info_hash_of_file", lambda _path: HASH)
    torrent_file = tmp_path / "saga.torrent"
    torrent_file.write_bytes(b"d4:infod4:name4:sagaee")

    sent = rtorrent.send_or_check(filepath=str(torrent_file))
    checked = rtorrent.send_or_check(HASH, check=True)

    assert daemon.started == [HASH]
    assert sent["label"] == "comics"
    assert sent["files"] == ["/downloads/Saga 001.cbz"]
    assert checked["hash"] == HASH
    assert checked["completed"] is True


def test_adapter_unreachable_daemon_raises(monkeypatch):
    monkeypatch.setattr(
        rtorrent.comicarr,
        "CONFIG",
        SimpleNamespace(
            RTORRENT_HOST="http://127.0.0.1:9",
            RTORRENT_RPC_URL="RPC2",
            RTORRENT_USERNAME=None,
            RTORRENT_PASSWORD=None,
            RTORRENT_AUTHENTICATION="basic",
            RTORRENT_VERIFY=False,
            RTORRENT_CA_BUNDLE=None,
        ),
    )

    with pytest.raises(rtorrent_rpc.RTorrentError):
        rtorrent.send_or_check(HASH, check=True)
