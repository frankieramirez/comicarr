#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Unit tests for torrentinfo() snatch_status contract.

torrentinfo is the probe used by the auto-snatch worker and restart recovery.
Every return path that callers index must be a dict with snatch_status set.
"""

from unittest.mock import MagicMock, patch

import pytest

import comicarr
from comicarr.app.search import service

HASH40 = "a" * 40


@pytest.fixture(autouse=True)
def _torrent_flags(monkeypatch):
    """Default to no torrent client; tests opt in to Deluge/rTorrent."""
    monkeypatch.setattr(comicarr, "USE_RTORRENT", False, raising=False)
    monkeypatch.setattr(comicarr, "USE_DELUGE", False, raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        type(
            "C",
            (),
            {
                "DELUGE_HOST": "localhost",
                "DELUGE_USERNAME": "u",
                "DELUGE_PASSWORD": "p",
                "AUTO_SNATCH_SCRIPT": "",
                "PP_SSHHOST": "",
                "PP_SSHPORT": "",
                "PP_SSHUSER": "",
                "PP_SSHLOCALCD": "/tmp",
                "PP_SSHKEYFILE": None,
                "PP_SSHPASSWD": None,
            },
        )(),
        raising=False,
    )


def _deluge_torrent(finished=False):
    return {
        "is_finished": finished,
        "num_files": 1,
        "save_path": "/downloads",
        "total_size": 1000,
        "total_uploaded": 0,
        "total_payload_download": 500,
        "time_added": 1,
        "files": [{"path": "Saga.cbz"}],
        "name": "Saga.cbz",
    }


def test_missing_issue_returns_monitor_error_dict(monkeypatch):
    """Missing issue row must return a dict, not crash indexing None."""
    monkeypatch.setattr(service.db, "select_one", lambda stmt: None)

    result = service.torrentinfo(issueid="999")

    assert isinstance(result, dict)
    assert result["snatch_status"] == "MONITOR ERROR"


def test_rtorrent_import_path_no_importerror_and_status(monkeypatch):
    """rTorrent path must import from comicarr (not relative under app.search)."""
    monkeypatch.setattr(comicarr, "USE_RTORRENT", True)
    monkeypatch.setattr(comicarr, "USE_DELUGE", False)

    class FakeRTorrent:
        def main(self, torrent_hash=None, check=False):
            return {"completed": False, "files": ["a.cbz"], "folder": "/dl"}

    with patch("comicarr.rtorrent_test_client.RTorrent", return_value=FakeRTorrent()):
        result = service.torrentinfo(torrent_hash=HASH40, download=True)

    assert isinstance(result, dict)
    assert "snatch_status" in result
    assert result["snatch_status"] == "IN PROGRESS"


def test_deluge_unfinished_download_true_is_in_progress(monkeypatch):
    monkeypatch.setattr(comicarr, "USE_DELUGE", True)
    monkeypatch.setattr(comicarr, "USE_RTORRENT", False)

    fake_client = MagicMock()
    fake_client.connect.return_value = True
    fake_client.get_torrent.return_value = _deluge_torrent(finished=False)

    with patch("comicarr.torrent.clients.deluge.TorrentClient", return_value=fake_client):
        result = service.torrentinfo(torrent_hash=HASH40, download=True)

    assert isinstance(result, dict)
    assert result["snatch_status"] == "IN PROGRESS"


def test_neither_client_returns_monitor_error_dict():
    result = service.torrentinfo(torrent_hash=HASH40, download=True)

    assert isinstance(result, dict)
    assert result is not None
    assert result["snatch_status"] == "MONITOR ERROR"


def test_not_found_path_still_works(monkeypatch):
    monkeypatch.setattr(comicarr, "USE_DELUGE", True)
    monkeypatch.setattr(comicarr, "USE_RTORRENT", False)

    fake_client = MagicMock()
    fake_client.connect.return_value = True
    fake_client.get_torrent.return_value = False

    with patch("comicarr.torrent.clients.deluge.TorrentClient", return_value=fake_client):
        result = service.torrentinfo(torrent_hash=HASH40, download=True)

    assert isinstance(result, dict)
    assert result["snatch_status"] == "NOT FOUND"
    assert result["hash"] == HASH40


def test_download_false_present_incomplete_is_in_progress(monkeypatch):
    """Recovery probes with download=False; present incomplete must not be absent."""
    monkeypatch.setattr(comicarr, "USE_DELUGE", True)
    monkeypatch.setattr(comicarr, "USE_RTORRENT", False)

    fake_client = MagicMock()
    fake_client.connect.return_value = True
    fake_client.get_torrent.return_value = _deluge_torrent(finished=False)

    with patch("comicarr.torrent.clients.deluge.TorrentClient", return_value=fake_client):
        result = service.torrentinfo(torrent_hash=HASH40, download=False, monitor=False)

    assert isinstance(result, dict)
    assert result["snatch_status"] == "IN PROGRESS"


def test_deluge_connect_failure_dict_is_monitor_error_not_not_found(monkeypatch):
    """Deluge connect returns truthy {status: False}; must not fall through to NOT FOUND."""
    monkeypatch.setattr(comicarr, "USE_DELUGE", True)
    monkeypatch.setattr(comicarr, "USE_RTORRENT", False)

    fake_client = MagicMock()
    fake_client.connect.return_value = {"status": False, "error": "connection refused"}
    fake_client.get_torrent.return_value = False

    with patch("comicarr.torrent.clients.deluge.TorrentClient", return_value=fake_client):
        result = service.torrentinfo(torrent_hash=HASH40, download=True)

    assert isinstance(result, dict)
    assert result["snatch_status"] == "MONITOR ERROR"
    fake_client.get_torrent.assert_not_called()


def test_deluge_connect_false_is_monitor_error(monkeypatch):
    monkeypatch.setattr(comicarr, "USE_DELUGE", True)
    monkeypatch.setattr(comicarr, "USE_RTORRENT", False)

    fake_client = MagicMock()
    fake_client.connect.return_value = False

    with patch("comicarr.torrent.clients.deluge.TorrentClient", return_value=fake_client):
        result = service.torrentinfo(torrent_hash=HASH40, download=True)

    assert isinstance(result, dict)
    assert result["snatch_status"] == "MONITOR ERROR"
    fake_client.get_torrent.assert_not_called()


def test_rtorrent_none_missing_hash_is_not_found_dict(monkeypatch):
    """rTorrent check-miss bare-returns None; must not TypeError on len(None)."""
    monkeypatch.setattr(comicarr, "USE_RTORRENT", True)
    monkeypatch.setattr(comicarr, "USE_DELUGE", False)

    class FakeRTorrent:
        def main(self, torrent_hash=None, check=False):
            return None

    with patch("comicarr.rtorrent_test_client.RTorrent", return_value=FakeRTorrent()):
        result = service.torrentinfo(torrent_hash=HASH40, download=True)

    assert isinstance(result, dict)
    assert result["snatch_status"] == "NOT FOUND"
    assert result["hash"] == HASH40
