#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""SABnzbd handoff delivers content, never a callback (#552 / #564).

ADR-0002: no handoff route may require the download client to reach back into
Comicarr, and a handoff must be verifiable from the client's own response
alone. The SAB sender used to hand SAB a URL pointing at a Comicarr endpoint
that did not exist; it now multipart-POSTs the .nzb already cached at nzbpath.
"""

import types
from unittest.mock import MagicMock, patch

import pytest

import comicarr
from comicarr import sabnzbd


@pytest.fixture
def sab_config(monkeypatch):
    config = types.SimpleNamespace(
        SAB_HOST="http://sab.local:8080",
        SAB_APIKEY="sab-key",
        SAB_VERIFY=False,
        SAB_CATEGORY="comics",
    )
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)
    return config


@pytest.fixture
def cached_nzb(tmp_path):
    path = tmp_path / "Saga.001.nzb"
    path.write_bytes(b"<?xml version='1.0'?><nzb>payload</nzb>")
    return path


def _params():
    return {
        "apikey": "sab-key",
        "mode": "addfile",
        "nzbname": "Saga.001.nzb",
        "output": "json",
        "priority": "0",
        "cat": "comics",
    }


def _accepted_response():
    response = MagicMock()
    response.json.return_value = {"status": True, "nzo_ids": ["SABnzbd_nzo_abc123"]}
    return response


def test_sender_posts_the_cached_nzb_as_content(sab_config, cached_nzb):
    with patch.object(sabnzbd.requests, "post", return_value=_accepted_response()) as post:
        result = sabnzbd.SABnzbd(_params()).sender(str(cached_nzb))

    assert post.call_count == 1
    _args, kwargs = post.call_args
    data = kwargs["data"]
    files = kwargs["files"]

    assert data["mode"] == "addfile"
    assert data["apikey"] == "sab-key"
    assert data["nzbname"] == "Saga.001.nzb"
    assert data["output"] == "json"
    # SAB_PRIORITY / SAB_CATEGORY carry over unchanged.
    assert data["priority"] == "0"
    assert data["cat"] == "comics"

    filename, content, content_type = files["name"]
    assert filename == "Saga.001.nzb"
    assert content == cached_nzb.read_bytes()
    assert content_type == "application/x-nzb"

    # nzo_id stays the acceptance identity consumed by _acceptance_identity.
    assert result == {
        "status": True,
        "nzo_id": "SABnzbd_nzo_abc123",
        "queue": {
            "mode": "queue",
            "search": "SABnzbd_nzo_abc123",
            "output": "json",
            "apikey": "sab-key",
        },
    }


def test_sender_hands_sab_no_comicarr_address(sab_config, cached_nzb):
    """ADR-0002's invariant, pinned: nothing in the request points back here."""
    with patch.object(sabnzbd.requests, "post", return_value=_accepted_response()) as post:
        sabnzbd.SABnzbd(_params()).sender(str(cached_nzb))

    _args, kwargs = post.call_args
    sent = "%s %s" % (kwargs["data"], _args)
    assert "addurl" not in sent
    assert "downloadNZB" not in sent
    assert "cmd" not in kwargs["data"]
    assert "name" not in kwargs["data"]  # the callback URL's old home


def test_missing_nzb_path_is_a_clean_rejection(sab_config):
    with patch.object(sabnzbd.requests, "post") as post:
        assert sabnzbd.SABnzbd(_params()).sender(None) == {"status": False}
    assert post.call_count == 0


def test_unreadable_nzb_is_a_clean_rejection(sab_config, tmp_path):
    with patch.object(sabnzbd.requests, "post") as post:
        result = sabnzbd.SABnzbd(_params()).sender(str(tmp_path / "does-not-exist.nzb"))
    assert result == {"status": False}
    assert post.call_count == 0


def test_rejected_submission_returns_status_false(sab_config, cached_nzb):
    response = MagicMock()
    response.json.return_value = {"status": False, "error": "nope"}
    with patch.object(sabnzbd.requests, "post", return_value=response):
        assert sabnzbd.SABnzbd(_params()).sender(str(cached_nzb)) == {"status": False}


def test_chkstatus_path_still_gets_and_sends_no_file(sab_config):
    response = MagicMock()
    response.json.return_value = {"queue": {"status": "Paused"}}
    params = {"apikey": "sab-key", "mode": "queue", "output": "json"}

    with patch.object(sabnzbd.requests, "get", return_value=response) as get:
        assert sabnzbd.SABnzbd(params).sender(chkstatus=True) == {"status": True}

    _args, kwargs = get.call_args
    assert "files" not in kwargs
    assert kwargs["params"] is params
