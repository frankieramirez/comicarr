#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Removing jobs from SABnzbd history must not cancel or delete live jobs.

SABnzbd's ``mode=history&name=delete`` cancels a job that is still queued for
post-processing, and with ``del_files=1`` it also deletes that job's data.
"""

import types
from unittest.mock import MagicMock

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
        SAB_VERSION="4.5.0",
        SAB_MOVING_DELAY=0,
        SAB_REMOVE_COMPLETED=True,
        SAB_REMOVE_FAILED=True,
    )
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)
    monkeypatch.setattr(sabnzbd.time, "sleep", lambda _s: None)
    return config


def _history(status):
    response = MagicMock()
    response.json.return_value = {
        "history": {
            "slots": [
                {
                    "nzo_id": "SABnzbd_nzo_abc123",
                    "status": status,
                    "script": "None",
                    "storage": "",
                    "bytes": "1000",
                }
            ]
        }
    }
    return response


def _removal():
    response = MagicMock()
    response.json.return_value = {"status": True}
    return response


@pytest.mark.parametrize("status", ["Completed", "Queued"])
def test_removing_a_job_that_did_not_fail_keeps_its_files(sab_config, monkeypatch, status):
    get = MagicMock(return_value=_removal())
    monkeypatch.setattr(sabnzbd.requests, "get", get)

    sabnzbd.SABnzbd({}).remove_history("SABnzbd_nzo_abc123", status)

    params = get.call_args.kwargs["params"]
    assert params["name"] == "delete"
    assert "del_files" not in params


def test_removing_a_failed_job_deletes_its_files_when_configured(sab_config, monkeypatch):
    get = MagicMock(return_value=_removal())
    monkeypatch.setattr(sabnzbd.requests, "get", get)

    sabnzbd.SABnzbd({}).remove_history("SABnzbd_nzo_abc123", "Failed")

    assert get.call_args.kwargs["params"]["del_files"] == 1


@pytest.mark.parametrize("status", ["Queued", "Extracting", "Repairing", "Verifying"])
def test_a_job_still_processing_after_the_wait_is_left_in_sab(sab_config, monkeypatch, status):
    get = MagicMock(return_value=_history(status))
    monkeypatch.setattr(sabnzbd.requests, "get", get)
    nzbinfo = {"nzo_id": "SABnzbd_nzo_abc123", "issueid": "1", "comicid": "2", "download_info": {}}

    result = sabnzbd.SABnzbd({}).historycheck(nzbinfo, roundtwo=True)

    assert result == {"failed": False, "status": "unhandled status of: %s" % status}
    assert all(c.kwargs["params"].get("name") != "delete" for c in get.call_args_list)
