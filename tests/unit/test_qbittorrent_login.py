#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""qBittorrent login handling across Web API versions (#1159)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from comicarr._vendor.qbittorrent import client as vendor_client
from comicarr.torrent.clients import qbittorrent

HASH = "A" * 40
MAGNET = "magnet:?xt=urn:btih:" + HASH


def _response(status_code, text):
    return SimpleNamespace(status_code=status_code, text=text)


class FakeSession:
    """Stands in for requests.Session against a fake qBittorrent WebUI."""

    def __init__(self, login_response):
        self.login_response = login_response
        self.posts = []
        self.present = False

    def get(self, url, **kwargs):
        if url.endswith("api/v2/app/preferences"):
            return _response(403, "Forbidden")
        if url.endswith("api/v2/app/version"):
            return _json(200, "v5.2.4")
        if url.endswith("api/v2/torrents/properties"):
            if not self.present:
                return _json(404, "")
            return _json(200, '{"save_path": "/downloads", "total_size": 1, "addition_date": 0}')
        if url.endswith("api/v2/torrents/files"):
            return _json(200, '[{"name": "Absolute Wonder Woman 001.cbz"}]')
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, data=None, **kwargs):
        self.posts.append(url)
        if url.endswith("api/v2/auth/login"):
            return self.login_response
        if url.endswith("api/v2/torrents/add"):
            self.present = True
            return _json(200, '{"added_torrent_ids": ["a"], "failure_count": 0}')
        raise AssertionError(f"unexpected POST {url}")


def _json(status_code, text):
    response = MagicMock(status_code=status_code, text=text)
    if status_code >= 400:
        response.raise_for_status.side_effect = RuntimeError(f"HTTP {status_code}")
    return response


@pytest.fixture
def webui(monkeypatch):
    sessions = []

    def install(login_response):
        def make_session():
            session = FakeSession(login_response)
            sessions.append(session)
            return session

        monkeypatch.setattr(vendor_client.requests, "Session", make_session)
        return sessions

    return install


@pytest.fixture
def config(monkeypatch):
    import comicarr

    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(QBITTORRENT_LOADACTION="default"))
    monkeypatch.setattr(
        "comicarr.app.downloads.torrent_routing.qbittorrent_destination",
        lambda _config, _comicid: SimpleNamespace(category="comics", savepath=None),
    )


@pytest.mark.parametrize(
    "login_response",
    [_response(204, ""), _response(200, "Ok."), _response(200, "Ok.\n")],
    ids=["qbt-5.2-204-empty", "legacy-200-ok", "legacy-200-ok-newline"],
)
def test_successful_login_authenticates(webui, login_response):
    webui(login_response)
    client = vendor_client.Client("http://127.0.0.1:8082")

    assert client.login("user", "secret") is None
    assert client._is_authenticated is True


@pytest.mark.parametrize(
    "login_response",
    [_response(200, "Fails."), _response(403, "Your IP address has been banned"), _response(401, "")],
    ids=["wrong-password", "ip-banned", "unauthorized-empty"],
)
def test_failed_login_stays_unauthenticated(webui, login_response):
    webui(login_response)
    client = vendor_client.Client("http://127.0.0.1:8082")

    assert client.login("user", "wrong") == login_response.text
    assert client._is_authenticated is False


def test_204_login_lets_grab_reach_torrents_add(webui, config, monkeypatch):
    sessions = webui(_response(204, ""))
    monkeypatch.setattr(qbittorrent.time, "sleep", lambda _seconds: None)
    adapter = qbittorrent.TorrentClient()

    assert adapter.connect("http://127.0.0.1:8082", "user", "secret") is adapter.client
    info = adapter.load_torrent(MAGNET)

    assert any(url.endswith("api/v2/torrents/add") for url in sessions[-1].posts)
    assert info["status"] is True
    assert info["hash"] == HASH
    assert info["label"] == "comics"


def test_204_login_passes_connection_test(webui):
    webui(_response(204, ""))

    result = qbittorrent.TorrentClient().connect("http://127.0.0.1:8082", "user", "secret", test=True)

    assert result == {"status": True, "version": "v5.2.4"}


def test_rejected_login_fails_connection_test(webui):
    webui(_response(200, "Fails."))
    adapter = qbittorrent.TorrentClient()

    result = adapter.connect("http://127.0.0.1:8082", "user", "wrong", test=True)

    assert result["status"] is False
    assert "login failed" in result["error"]
    assert adapter.conn is None


def test_unauthenticated_load_returns_error_without_waiting(config):
    adapter = qbittorrent.TorrentClient()
    adapter.client = SimpleNamespace(_is_authenticated=False)

    with patch.object(qbittorrent.time, "sleep", side_effect=AssertionError("must not wait")):
        result = adapter.load_torrent(MAGNET)

    assert result == {"status": False, "error": "Not logged in to qBittorrent"}


def test_torrent_missing_after_add_reports_clear_error(config, monkeypatch):
    monkeypatch.setattr(qbittorrent.time, "sleep", lambda _seconds: None)
    adapter = qbittorrent.TorrentClient()
    adapter.client = SimpleNamespace(
        _is_authenticated=True,
        get_torrent=MagicMock(side_effect=RuntimeError("404")),
        download_from_link=MagicMock(),
    )

    result = adapter.load_torrent(MAGNET)

    assert result == {"status": False, "error": "Torrent not found on qBittorrent after adding it"}
