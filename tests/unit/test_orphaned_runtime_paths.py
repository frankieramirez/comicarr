#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

import comicarr
from comicarr import logger, maintenance, sabnzbd
from comicarr.app.downloads import postprocessing
from comicarr.app.search import commands


@pytest.mark.parametrize(
    ("annchk", "entity_type"),
    (("no", "issue"), ("yes", "annual")),
)
def test_failed_download_retry_uses_durable_search_command(monkeypatch, annchk, entity_type):
    failure = {
        "mode": "retry",
        "annchk": annchk,
        "issueid": "issue-1",
        "comicid": "comic-1",
        "comicname": "Saga",
        "issuenumber": "1",
    }
    observed = []
    legacy_queueit = MagicMock()

    class FakeFailedProcessor:
        def __init__(self, *, queue, **_kwargs):
            self.queue = queue

        def Process(self):
            self.queue.put([failure])

    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(FAILED_DOWNLOAD_HANDLING=True), raising=False)
    monkeypatch.setattr(comicarr, "failed", SimpleNamespace(FailedProcessor=FakeFailedProcessor), raising=False)
    monkeypatch.setattr(
        comicarr,
        "webserve",
        SimpleNamespace(WebInterface=lambda: SimpleNamespace(queueit=legacy_queueit)),
        raising=False,
    )
    monkeypatch.setattr(
        commands,
        "enqueue_search_command",
        lambda payload, **kwargs: observed.append((payload, kwargs)),
        raising=False,
    )

    postprocessing._post_process(
        {
            "nzb_name": "Saga 001.cbz",
            "nzb_folder": "/downloads/Saga",
            "failed": True,
            "download_info": {"id": "nzo-1", "provider": "sabnzbd"},
        }
    )

    assert observed == [
        (
            {
                "issueid": "issue-1",
                "comicid": "comic-1",
                "comicname": "Saga",
                "issuenumber": "1",
                "manual": True,
                "entity_type": entity_type,
            },
            {
                "trigger": "failed_download_retry",
                "work_queue": None,
                "ledger": None,
                "run_id": None,
                "maintenance": None,
                "scope_type": entity_type,
                "scope_id": "issue-1",
            },
        )
    ]
    legacy_queueit.assert_not_called()


def test_sab_version_probe_sets_runtime_version_without_web_interface(monkeypatch):
    config = SimpleNamespace(
        SAB_HOST="https://sab.invalid",
        SAB_APIKEY="secret",
        SAB_VERIFY=True,
        SAB_VERSION=None,
        writeconfig=MagicMock(),
    )
    response = MagicMock(status_code=200)
    response.json.return_value = {"version": "4.4.1"}
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)
    monkeypatch.setattr(sabnzbd.requests, "get", MagicMock(return_value=response))

    result = sabnzbd.SABnzbd(params=None).sab_versioncheck()

    assert result is None
    assert config.SAB_VERSION == "4.4.1"
    config.writeconfig.assert_not_called()
    sabnzbd.requests.get.assert_called_once_with(
        "https://sab.invalid/api",
        params={"mode": "version", "output": "json", "apikey": "secret"},
        verify=True,
        timeout=30,
    )


def test_sab_version_probe_uses_plain_text_and_conservative_fallback(monkeypatch):
    config = SimpleNamespace(
        SAB_HOST="http://sab.invalid",
        SAB_APIKEY="secret",
        SAB_VERIFY=False,
        SAB_VERSION=None,
    )
    text_response = MagicMock(status_code=200, text="4.3.0\n")
    text_response.json.side_effect = ValueError("not json")
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)
    monkeypatch.setattr(sabnzbd.requests, "get", MagicMock(return_value=text_response))

    assert sabnzbd.SABnzbd(params=None).sab_versioncheck() is None
    assert config.SAB_VERSION == "4.3.0"

    config.SAB_VERSION = None
    monkeypatch.setattr(sabnzbd.requests, "get", MagicMock(side_effect=requests.RequestException("offline")))

    assert sabnzbd.SABnzbd(params=None).sab_versioncheck() == "some value"
    assert config.SAB_VERSION is None

    monkeypatch.setattr(sabnzbd.requests, "get", MagicMock(return_value=MagicMock(status_code=503)))

    assert sabnzbd.SABnzbd(params=None).sab_versioncheck() == "some value"
    assert config.SAB_VERSION is None

    malformed_response = MagicMock(status_code=200, text="")
    malformed_response.json.return_value = []
    monkeypatch.setattr(sabnzbd.requests, "get", MagicMock(return_value=malformed_response))

    assert sabnzbd.SABnzbd(params=None).sab_versioncheck() == "some value"
    assert config.SAB_VERSION is None


def test_maintenance_logging_uses_logger_boundary(monkeypatch):
    calls = []
    legacy_toggle = MagicMock()
    monkeypatch.setattr(
        comicarr,
        "webserve",
        SimpleNamespace(WebInterface=lambda: SimpleNamespace(toggleVerbose=legacy_toggle)),
        raising=False,
    )
    monkeypatch.setattr(logger, "configure_log_level", lambda level: calls.append(level), raising=False)

    instance = object.__new__(maintenance.Maintenance)
    instance.toggle_logging(0)
    instance.toggle_logging(2)

    assert calls == [0, 2]
    legacy_toggle.assert_not_called()


def test_configure_log_level_keeps_the_console_attached_at_every_level(monkeypatch):
    """The dial sets severity; it never detaches the console.

    Replaces test_configure_log_level_preserves_quiet_console_behavior, which
    pinned an inverted console expression: under Docker it silenced stdout the
    moment an operator raised verbosity, the exact defect #610 reported. See
    docs/architecture/logging-levels.md.
    """
    calls = []
    config = SimpleNamespace(LOG_DIR="/tmp/logs", MAX_LOGSIZE=1024, MAX_LOGFILES=3)
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)
    monkeypatch.setattr(comicarr, "LOG_LEVEL", 1, raising=False)
    monkeypatch.setattr(logger, "initLogger", lambda **kwargs: calls.append(kwargs), raising=False)

    logger.configure_log_level(0)
    logger.configure_log_level(2)
    logger.configure_log_level(None)

    assert comicarr.LOG_LEVEL == 1
    assert calls == [
        {"console": True, "log_dir": "/tmp/logs", "max_logsize": 1024, "max_logfiles": 3, "loglevel": 0},
        {"console": True, "log_dir": "/tmp/logs", "max_logsize": 1024, "max_logfiles": 3, "loglevel": 2},
        {"console": True, "log_dir": "/tmp/logs", "max_logsize": 1024, "max_logfiles": 3, "loglevel": 1},
    ]
