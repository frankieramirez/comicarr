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

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, create_autospec, patch

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


def _spec_client(module_path):
    """A fake adapter that enforces the real TorrentClient's signatures.

    A bare MagicMock accepts any call, so it cannot catch a wrong argument type
    or a method the real adapter does not have. Autospec can.
    """
    real = importlib.import_module(module_path).TorrentClient
    return create_autospec(real, instance=True)


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

    def test_a_deluge_rpc_failure_after_connect_is_unreachable_not_absent(self, monkeypatch):
        """deluge.get_torrent() swallows every RPC exception and returns False.

        Taking that as proof of absence lets recovery mark a live download
        failed on nothing worse than a daemon hiccup, so the probe re-checks
        that the daemon is still answering before calling the torrent gone.
        """
        _use(monkeypatch, "USE_DELUGE")
        client = MagicMock()
        client.connect.return_value = object()
        client.get_torrent.return_value = False
        client.conn.call.side_effect = ConnectionResetError("daemon went away")

        with patch("comicarr.torrent.clients.deluge.TorrentClient", return_value=client):
            result = monitor.probe("abc123")

        assert result["reachable"] is False, "a mid-RPC outage must not read as 'torrent gone'"
        assert result["found"] is False

    def test_a_deluge_daemon_that_still_answers_confirms_absence(self, monkeypatch):
        _use(monkeypatch, "USE_DELUGE")
        client = MagicMock()
        client.connect.return_value = object()
        client.get_torrent.return_value = False
        client.conn.call.return_value = "2.1.1"

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
    """Pause/resume against *spec'd* adapters.

    A bare MagicMock accepts any argument, so it agrees with the code even when
    the real adapter would not -- which is exactly how the Transmission
    signature mismatch below stayed green. create_autospec pins each adapter's
    real signature, so what these tests assert is what the client receives.
    """

    def test_clients_without_a_pause_api_report_it(self):
        assert "qbittorrent" not in monitor.PAUSABLE_ROUTES
        assert "rtorrent" not in monitor.PAUSABLE_ROUTES

    def test_pause_is_false_when_unsupported(self, monkeypatch):
        _use(monkeypatch, "USE_QBITTORRENT")

        assert monitor.pause("abc123") is False

    @pytest.mark.parametrize(
        ("flag", "module_path"),
        [
            ("USE_DELUGE", "comicarr.torrent.clients.deluge"),
            ("USE_UTORRENT", "comicarr.torrent.clients.utorrent"),
        ],
    )
    def test_hash_taking_clients_are_paused_and_resumed_by_hash(self, monkeypatch, flag, module_path):
        _use(monkeypatch, flag)
        client = _spec_client(module_path)
        client.stop_torrent.return_value = True
        client.start_torrent.return_value = True

        with patch("%s.TorrentClient" % module_path, return_value=client):
            assert monitor.pause("abc123") is True
            assert monitor.resume("abc123") is True

        client.stop_torrent.assert_called_once_with("abc123")
        client.start_torrent.assert_called_once_with("abc123")

    def test_transmission_is_paused_with_the_handle_not_the_hash(self, monkeypatch):
        """transmission's stop_torrent does `torrent.stop()`; a str has no .stop()."""
        _use(monkeypatch, "USE_TRANSMISSION")
        handle = object()
        client = _spec_client("comicarr.torrent.clients.transmission")
        client.find_torrent.return_value = handle
        client.stop_torrent.return_value = True
        client.start_torrent.return_value = True

        with patch("comicarr.torrent.clients.transmission.TorrentClient", return_value=client):
            assert monitor.pause("abc123") is True
            assert monitor.resume("abc123") is True

        client.stop_torrent.assert_called_once_with(handle)
        client.start_torrent.assert_called_once_with(handle)

    def test_transmission_without_the_torrent_does_not_pause(self, monkeypatch):
        _use(monkeypatch, "USE_TRANSMISSION")
        client = _spec_client("comicarr.torrent.clients.transmission")
        client.find_torrent.return_value = False

        with patch("comicarr.torrent.clients.transmission.TorrentClient", return_value=client):
            assert monitor.pause("abc123") is False

        client.stop_torrent.assert_not_called()

    def test_a_client_that_will_not_connect_cannot_pause(self, monkeypatch):
        _use(monkeypatch, "USE_DELUGE")
        client = _spec_client("comicarr.torrent.clients.deluge")
        client.connect.return_value = {"status": False, "error": "connection refused"}

        with patch("comicarr.torrent.clients.deluge.TorrentClient", return_value=client):
            assert monitor.pause("abc123") is False
            assert monitor.resume("abc123") is False

        client.stop_torrent.assert_not_called()

    def test_every_pausable_route_has_client_wiring(self):
        """PAUSABLE_ROUTES and _pause_credentials must not drift apart."""
        for route in monitor.PAUSABLE_ROUTES:
            assert monitor._pause_credentials(route) is not None, route


class TestDownloaderRoutes:
    """The producer (search.py) and the consumer (SNPOOL) must agree on this."""

    @pytest.mark.parametrize(
        ("downloader", "route"),
        [
            (0, None),
            (1, "utorrent"),
            (2, "rtorrent"),
            (3, "transmission"),
            (4, "deluge"),
            (5, "qbittorrent"),
        ],
    )
    def test_each_downloader_value_maps_to_its_route(self, downloader, route):
        assert monitor.route_for_downloader(downloader) == route
        assert monitor.is_monitorable_downloader(downloader) is (route is not None)

    @pytest.mark.parametrize("value", (None, "", "nonsense", 99, -1))
    def test_unknown_downloader_values_are_not_monitorable(self, value):
        assert monitor.is_monitorable_downloader(value) is False

    def test_every_probe_route_is_reachable_from_a_downloader_value(self):
        """A route with a probe but no downloader mapping could never be selected."""
        mapped = {monitor.route_for_downloader(d) for d in range(1, 6)}
        assert mapped == set(monitor._PROBES)


class TestUtorrentHostNormalisation:
    @pytest.mark.parametrize(
        ("configured", "expected"),
        [
            ("utorrent.local:8080", "http://utorrent.local:8080/gui/"),
            ("http://utorrent.local:8080", "http://utorrent.local:8080/gui/"),
            ("http://utorrent.local:8080/", "http://utorrent.local:8080/gui/"),
            ("http://utorrent.local:8080/gui", "http://utorrent.local:8080/gui/"),
            ("http://utorrent.local:8080/gui/", "http://utorrent.local:8080/gui/"),
        ],
    )
    def test_every_documented_host_form_reaches_the_same_gui_url(self, configured, expected):
        assert monitor.utorrent_base_url(configured) == expected

    def test_the_probe_connects_to_the_normalised_url(self, monkeypatch):
        """The vendored client does urljoin(base_url, 'token.html') with no fix-up."""
        _use(monkeypatch, "USE_UTORRENT")
        comicarr.CONFIG.UTORRENT_HOST = "utorrent.local:8080"
        client = _spec_client("comicarr.torrent.clients.utorrent")
        client.find_torrent.return_value = False

        with patch("comicarr.torrent.clients.utorrent.TorrentClient", return_value=client):
            monitor.probe("abc123")

        assert client.connect.call_args[0][0] == "http://utorrent.local:8080/gui/"


class TestSnapshotShape:
    def test_the_caller_supplied_hash_wins_over_the_clients_own(self, monkeypatch):
        """Transmission and uTorrent return their own `hash`; the probe's is canonical."""
        _use(monkeypatch, "USE_TRANSMISSION")
        client = _spec_client("comicarr.torrent.clients.transmission")
        client.find_torrent.return_value = object()
        client.get_torrent.return_value = {"hash": "SOMETHING-ELSE", "name": "n", "completed": True}

        with patch("comicarr.torrent.clients.transmission.TorrentClient", return_value=client):
            result = monitor.probe("abc123")

        assert result["hash"] == "abc123"
