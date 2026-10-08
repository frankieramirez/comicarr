#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""SAB Unpack/Repair failures must use CONFIG.FAILED_DOWNLOAD_HANDLING (#965)."""

import queue as queuelib
import types
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

import comicarr
from comicarr import failed as failed_mod
from comicarr import sabnzbd
from comicarr.app.downloads import journal
from comicarr.app.downloads.service import _cdh_monitor_owned
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import metadata, pipeline_journal

NZO_ID = "SABnzbd_nzo_x"
ISSUE_ID = "issue-x"
COMIC_ID = "comic-x"
PROVIDER = "nzb.su"


@pytest.fixture
def sab_config(monkeypatch):
    config = types.SimpleNamespace(
        SAB_HOST="http://sab.local:8080",
        SAB_APIKEY="sab-key",
        SAB_VERIFY=False,
        SAB_CATEGORY="comics",
        SAB_VERSION="4.5.0",
        SAB_MOVING_DELAY=0,
        SAB_REMOVE_COMPLETED=True,
        SAB_REMOVE_FAILED=True,
        FAILED_DOWNLOAD_HANDLING=True,
    )
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)
    monkeypatch.setattr(sabnzbd.time, "sleep", lambda _s: None)
    monkeypatch.setattr(sabnzbd.SABnzbd, "remove_history", lambda *a, **k: None)
    return config


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if not hasattr(comicarr, "LOG_LEVEL") or comicarr.LOG_LEVEL is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    engine = get_engine()
    metadata.create_all(engine)
    yield
    shutdown_engine()


def _failed_history(stage_log=None):
    response = MagicMock()
    response.json.return_value = {
        "history": {
            "slots": [
                {
                    "nzo_id": NZO_ID,
                    "status": "Failed",
                    "script": "None",
                    "storage": "/dl/x",
                    "nzb_name": "x.nzb",
                    "stage_log": stage_log
                    if stage_log is not None
                    else [{"name": "Unpack", "actions": ["Failed: CRC error"]}],
                }
            ]
        }
    }
    return response


def _failed_unpack_history():
    return _failed_history()


def _nzbinfo():
    return {
        "nzo_id": NZO_ID,
        "issueid": ISSUE_ID,
        "comicid": COMIC_ID,
        "download_info": {"provider": PROVIDER, "id": NZO_ID, "nzbname": "x"},
    }


def _row(key):
    with get_engine().connect() as conn:
        r = conn.execute(select(pipeline_journal).where(pipeline_journal.c.release_key == key)).fetchone()
        return dict(r._mapping) if r else None


def test_historycheck_unpack_failure_with_handling_on_returns_failed_true(sab_config, monkeypatch):
    monkeypatch.setattr(sabnzbd.requests, "get", MagicMock(return_value=_failed_unpack_history()))

    result = sabnzbd.SABnzbd({}).historycheck(_nzbinfo())

    assert result["status"] is True
    assert result["failed"] is True
    assert result["issueid"] == ISSUE_ID
    assert result["name"] == "x"


def test_historycheck_unpack_failure_with_handling_off_returns_distinct_status(sab_config, monkeypatch):
    sab_config.FAILED_DOWNLOAD_HANDLING = False
    monkeypatch.setattr(sabnzbd.requests, "get", MagicMock(return_value=_failed_unpack_history()))

    result = sabnzbd.SABnzbd({}).historycheck(_nzbinfo())

    assert result["status"] == "failed_no_auto_handling"
    assert result["failed"] is True
    assert result["issueid"] == ISSUE_ID


def test_historycheck_moving_unpack_failure_is_a_failed_job(sab_config, monkeypatch):
    monkeypatch.setattr(
        sabnzbd.requests,
        "get",
        MagicMock(return_value=_failed_history([{"name": "Unpack", "actions": ["Failed: error moving files"]}])),
    )

    result = sabnzbd.SABnzbd({}).historycheck(_nzbinfo())

    assert result["status"] is True
    assert result["failed"] is True


def test_historycheck_moving_unpack_failure_with_handling_off_terminalizes(sab_config, monkeypatch):
    sab_config.FAILED_DOWNLOAD_HANDLING = False
    monkeypatch.setattr(
        sabnzbd.requests,
        "get",
        MagicMock(return_value=_failed_history([{"name": "Unpack", "actions": ["Failed: error moving files"]}])),
    )

    result = sabnzbd.SABnzbd({}).historycheck(_nzbinfo())

    assert result["status"] == "failed_no_auto_handling"
    assert result["failed"] is True


def test_historycheck_download_stage_failure_is_a_failed_job(sab_config, monkeypatch):
    monkeypatch.setattr(
        sabnzbd.requests,
        "get",
        MagicMock(return_value=_failed_history([{"name": "Download", "actions": ["Failed: Aborted"]}])),
    )

    result = sabnzbd.SABnzbd({}).historycheck(_nzbinfo())

    assert result["status"] is True
    assert result["failed"] is True


def test_historycheck_download_stage_failure_with_handling_off_terminalizes(sab_config, monkeypatch):
    sab_config.FAILED_DOWNLOAD_HANDLING = False
    monkeypatch.setattr(
        sabnzbd.requests,
        "get",
        MagicMock(return_value=_failed_history([{"name": "Download", "actions": ["Failed: Aborted"]}])),
    )

    result = sabnzbd.SABnzbd({}).historycheck(_nzbinfo())

    assert result["status"] == "failed_no_auto_handling"
    assert result["failed"] is True


def test_cdh_monitor_terminalizes_when_sab_handling_is_off(sab_config, isolated_db, monkeypatch):
    sab_config.FAILED_DOWNLOAD_HANDLING = False
    key = journal.release_key(ISSUE_ID, PROVIDER)
    journal.record_transition(
        key,
        journal.SNATCHED,
        issueid=ISSUE_ID,
        provider=PROVIDER,
        nzbname="x",
    )
    assert _row(key)["stage"] == journal.SNATCHED

    nzb_queue = MagicMock()
    monkeypatch.setattr(comicarr, "NZB_QUEUE", nzb_queue, raising=False)
    monkeypatch.setattr(comicarr, "RETURN_THE_NZBQUEUE", MagicMock(), raising=False)
    monkeypatch.setattr(comicarr, "PP_QUEUE", MagicMock(), raising=False)

    nzstat = {
        "status": "failed_no_auto_handling",
        "failed": True,
        "name": "x",
        "location": "/dl",
        "issueid": ISSUE_ID,
        "comicid": COMIC_ID,
        "apicall": True,
        "download_info": {"provider": PROVIDER, "id": NZO_ID, "nzbname": "x"},
    }
    item = {
        "nzo_id": NZO_ID,
        "issueid": ISSUE_ID,
        "comicid": COMIC_ID,
        "journal_release_key": key,
        "download_info": nzstat["download_info"],
    }

    _cdh_monitor_owned(queuelib.Queue(), item, nzstat)

    row = _row(key)
    assert row["stage"] == journal.FAILED
    assert row["fail_reason"] == failed_mod.FAIL_REASON_NO_AUTO_HANDLING
    assert key not in {r["release_key"] for r in journal.read_open()}
    nzb_queue.put.assert_not_called()


def test_historycheck_unexpected_error_is_not_swallowed_as_transient(sab_config, monkeypatch):
    response = MagicMock()
    response.json.return_value = {
        "history": {
            "slots": [
                {
                    "nzo_id": NZO_ID,
                    "status": "Failed",
                    "script": "None",
                    "storage": "/dl/x",
                    "nzb_name": "x.nzb",
                    "stage_log": [{"name": "Unpack", "actions": ["Failed: CRC error"]}],
                }
            ]
        }
    }
    monkeypatch.setattr(sabnzbd.requests, "get", MagicMock(return_value=response))

    def boom(*_a, **_k):
        raise RuntimeError("programming error")

    monkeypatch.setattr(sabnzbd, "_stage_action_text", boom)

    with pytest.raises(RuntimeError, match="programming error"):
        sabnzbd.SABnzbd({}).historycheck(_nzbinfo())
