#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""One normalised torrent snapshot for all five clients.

The distinction under test is unreachable (the client did not answer) versus
absent (it answered and does not hold this hash). Collapsing them makes recovery
abandon a live download, and every adapter reports a connection failure as a
*truthy* {"status": False} mapping, so the obvious `if not connect(...)` check
does not catch it.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import comicarr
from comicarr.torrent import monitor

ROUTE_FLAGS = ("USE_RTORRENT", "USE_DELUGE", "USE_QBITTORRENT", "USE_TRANSMISSION", "USE_UTORRENT")


@pytest.fixture(autouse=True)
def _clients_off(monkeypatch):
    for flag in ROUTE_FLAGS:
        monkeypatch.setattr(comicarr, flag, False, raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            DELUGE_HOST="d",
            DELUGE_USERNAME="u",
            DELUGE_PASSWORD="p",
            QBITTORRENT_HOST="q",
            QBITTORRENT_USERNAME="u",
            QBITTORRENT_PASSWORD="p",
            TRANSMISSION_HOST="t",
            TRANSMISSION_USERNAME="u",
            TRANSMISSION_PASSWORD="p",
            UTORRENT_HOST="ut",
            UTORRENT_USERNAME="u",
            UTORRENT_PASSWORD="p",
        ),
        raising=False,
    )


def _use(monkeypatch, flag):
    monkeypatch.setattr(comicarr, flag, True, raising=False)


class TestConfiguredRoute:
    @pytest.mark.parametrize(
        ("flag", "route"),
        [
            ("USE_RTORRENT", "rtorrent"),
            ("USE_DELUGE", "deluge"),
            ("USE_QBITTORRENT", "qbittorrent"),
            ("USE_TRANSMISSION", "transmission"),
            ("USE_UTORRENT", "utorrent"),
        ],
    )
    def test_each_client_is_recognised(self, monkeypatch, flag, route):
        _use(monkeypatch, flag)

        assert monitor.configured_route() == route

    def test_a_watch_folder_has_nothing_to_poll(self):
        assert monitor.configured_route() is None

    def test_probe_without_a_client_is_unreachable_not_absent(self):
        result = monitor.probe("abc")

        assert result["reachable"] is False
        assert result["found"] is False


class TestConnectionFailuresAreUnreachable:
    """Every adapter returns a truthy {"status": False} on failure."""

    @pytest.mark.parametrize(
        ("flag", "module_path"),
        [
            ("USE_DELUGE", "comicarr.torrent.clients.deluge"),
            ("USE_QBITTORRENT", "comicarr.torrent.clients.qbittorrent"),
            ("USE_TRANSMISSION", "comicarr.torrent.clients.transmission"),
            ("USE_UTORRENT", "comicarr.torrent.clients.utorrent"),
        ],
    )
    def test_a_dead_client_is_never_reported_absent(self, monkeypatch, flag, module_path):
        _use(monkeypatch, flag)
        client = MagicMock()
        client.connect.return_value = {"status": False, "error": "connection refused"}

        with patch("%s.TorrentClient" % module_path, return_value=client):
            result = monitor.probe("abc123")

        assert result["reachable"] is False, "a client outage must not read as 'torrent gone'"
        assert result["found"] is False

    def test_an_adapter_that_raises_is_unreachable(self, monkeypatch):
        _use(monkeypatch, "USE_DELUGE")
        client = MagicMock()
        client.connect.side_effect = RuntimeError("boom")

        with patch("comicarr.torrent.clients.deluge.TorrentClient", return_value=client):
            result = monitor.probe("abc123")

        assert result["reachable"] is False


class TestAbsence:
    def test_a_reachable_client_without_the_hash_is_absent(self, monkeypatch):
        _use(monkeypatch, "USE_DELUGE")
        client = MagicMock()
        client.connect.return_value = object()
        client.get_torrent.return_value = False

        with patch("comicarr.torrent.clients.deluge.TorrentClient", return_value=client):
            result = monitor.probe("abc123")

        assert result["reachable"] is True
        assert result["found"] is False


class TestNormalisation:
    def test_deluge_fields_are_mapped_and_paths_absolute(self, monkeypatch):
        _use(monkeypatch, "USE_DELUGE")
        client = MagicMock()
        client.connect.return_value = object()
        client.get_torrent.return_value = {
            "name": "Chainsaw Man 165",
            "save_path": "/downloads",
            "is_finished": True,
            "files": [{"path": "Chainsaw Man 165.cbz"}],
            "total_size": 1234,
            "total_uploaded": 10,
            "total_payload_download": 1234,
            "ratio": 0.5,
            "time_added": 111,
        }

        with patch("comicarr.torrent.clients.deluge.TorrentClient", return_value=client):
            result = monitor.probe("abc123")

        assert result["found"] is True
        assert result["completed"] is True
        assert result["folder"] == "/downloads"
        assert result["files"] == ["/downloads/Chainsaw Man 165.cbz"]
        assert result["total_filesize"] == 1234
        assert result["time_started"] == 111

    def test_qbittorrent_progress_becomes_completed(self, monkeypatch):
        _use(monkeypatch, "USE_QBITTORRENT")
        client = MagicMock()
        client.connect.return_value = object()
        client.conn.torrents.return_value = [
            {
                "hash": "abc123",
                "name": "Chainsaw Man 165",
                "save_path": "/downloads",
                "progress": 1,
                "size": 99,
                "uploaded": 1,
                "downloaded": 99,
                "ratio": 0.1,
                "added_on": 222,
                "category": "comics",
            }
        ]
        client.conn.get_torrent_files.return_value = [{"name": "Chainsaw Man 165.cbz"}]

        with patch("comicarr.torrent.clients.qbittorrent.TorrentClient", return_value=client):
            result = monitor.probe("ABC123")

        assert result["found"] is True
        assert result["completed"] is True
        assert result["files"] == ["/downloads/Chainsaw Man 165.cbz"]
        assert result["label"] == "comics"

    def test_qbittorrent_incomplete_is_not_completed(self, monkeypatch):
        _use(monkeypatch, "USE_QBITTORRENT")
        client = MagicMock()
        client.connect.return_value = object()
        client.conn.torrents.return_value = [{"hash": "abc123", "progress": 0.42, "save_path": "/downloads"}]
        client.conn.get_torrent_files.return_value = []

        with patch("comicarr.torrent.clients.qbittorrent.TorrentClient", return_value=client):
            result = monitor.probe("abc123")

        assert result["found"] is True
        assert result["completed"] is False

    @pytest.mark.parametrize(
        ("flag", "module_path"),
        [
            ("USE_TRANSMISSION", "comicarr.torrent.clients.transmission"),
            ("USE_UTORRENT", "comicarr.torrent.clients.utorrent"),
        ],
    )
    def test_two_call_clients_are_resolved_via_find_then_get(self, monkeypatch, flag, module_path):
        """find_torrent returns a vendor handle, not a record; a one-call shim fails."""
        _use(monkeypatch, flag)
        handle = object()
        client = MagicMock()
        client.connect.return_value = object()
        client.find_torrent.return_value = handle
        client.get_torrent.return_value = {
            "name": "Chainsaw Man 165",
            "folder": "/downloads",
            "completed": True,
            "files": ["/downloads/Chainsaw Man 165.cbz"],
        }

        with patch("%s.TorrentClient" % module_path, return_value=client):
            result = monitor.probe("abc123")

        client.get_torrent.assert_called_once_with(handle)
        assert result["found"] is True
        assert result["completed"] is True

    def test_utorrent_missing_fields_are_none_not_absent_keys(self, monkeypatch):
        """uTorrent reports no size, ratio or timing; callers still read them."""
        _use(monkeypatch, "USE_UTORRENT")
        client = MagicMock()
        client.connect.return_value = object()
        client.find_torrent.return_value = object()
        client.get_torrent.return_value = {
            "hash": "abc123",
            "name": "Chainsaw Man 165",
            "folder": "/downloads",
            "completed": False,
            "files": [],
            "label": "",
        }

        with patch("comicarr.torrent.clients.utorrent.TorrentClient", return_value=client):
            result = monitor.probe("abc123")

        for field in ("total_filesize", "upload_total", "download_total", "ratio", "time_started"):
            assert field in result
            assert result[field] is None


class TestPauseCapability:
    def test_clients_without_a_pause_api_report_it(self):
        assert "qbittorrent" not in monitor.PAUSABLE_ROUTES
        assert "rtorrent" not in monitor.PAUSABLE_ROUTES

    def test_pause_is_false_when_unsupported(self, monkeypatch):
        _use(monkeypatch, "USE_QBITTORRENT")

        assert monitor.pause("abc123") is False
