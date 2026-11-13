#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""comicarr/sabnzbd.py against responses recorded from a real SABnzbd.

Older SABnzbd tests mock the JSON they expect. These run the same calls
against ``FakeSabnzbd``, whose bodies come from ``tests/fixtures/sabnzbd/``,
so a field SABnzbd renamed or a status it reports differently shows up here.
"""

import pytest
import requests

import comicarr
from comicarr import sabnzbd
from comicarr.app.downloads import recovery_classify
from comicarr.app.system import connections
from tests.fakes import pipeline
from tests.fakes import sabnzbd as sab_fake
from tests.fakes.sabnzbd import FakeSabnzbd


@pytest.fixture
def sab(monkeypatch, tmp_path):
    fake = FakeSabnzbd().install(monkeypatch)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        pipeline.default_config(
            SAB_HOST=fake.host,
            SAB_APIKEY=fake.apikey,
            SAB_CATEGORY=fake.category,
            SAB_VERSION=sab_fake.VERSION,
            SAB_MOVING_DELAY=0,
            FAILED_DOWNLOAD_HANDLING=True,
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "USE_SABNZBD", True, raising=False)
    monkeypatch.setattr("comicarr.sabnzbd.time.sleep", lambda _seconds: None)
    fake.nzb = pipeline.cached_nzb(tmp_path)
    return fake


def _send(sab, path=None):
    params = {"apikey": comicarr.CONFIG.SAB_APIKEY, "mode": "addfile", "nzbname": pipeline.RELEASE, "output": "json"}
    params["cat"] = sab.category
    return sabnzbd.SABnzbd(params).sender(str(path or sab.nzb))


def _monitor_item(nzo_id):
    return {"nzo_id": nzo_id, "issueid": pipeline.ISSUE_ID, "comicid": pipeline.COMIC_ID, "download_info": {}}


def test_accepted_upload_returns_the_nzo_id_sab_assigned(sab):
    response = _send(sab)

    [nzo_id] = sab.jobs
    assert response["status"] is True
    assert response["nzo_id"] == nzo_id


def test_rejected_upload_is_not_an_acceptance(sab, tmp_path):
    broken = tmp_path / "broken.nzb"
    broken.write_bytes(b"not an nzb")

    assert _send(sab, broken) == {"status": False}
    assert sab.jobs == {}


def test_completed_history_slot_gives_the_download_folder(sab, tmp_path):
    _send(sab)
    [nzo_id] = sab.jobs
    archive = pipeline.write_download(tmp_path / "complete" / pipeline.RELEASE / pipeline.FILENAME)
    sab.complete(nzo_id, str(archive))

    found = sabnzbd.SABnzbd({}).historycheck(_monitor_item(nzo_id))

    assert found["status"] is True and found["failed"] is False
    assert found["location"] == str(archive.parent)
    assert found["name"] == pipeline.FILENAME


def test_failed_history_slot_is_a_failed_job_to_retry(sab):
    _send(sab)
    [nzo_id] = sab.jobs
    sab.fail(nzo_id)

    found = sabnzbd.SABnzbd({}).historycheck(_monitor_item(nzo_id))

    assert found["status"] is True
    assert found["failed"] is True
    assert found["name"] == pipeline.RELEASE


def test_job_missing_from_history_is_reported_removed(sab):
    _send(sab)
    [nzo_id] = sab.jobs
    sab.forget(nzo_id)

    found = sabnzbd.SABnzbd({}).historycheck(_monitor_item(nzo_id), ignore_category=True)

    assert found == {"status": "nzb removed", "failed": False}


def test_unreachable_sab_raises_instead_of_reporting_the_job_gone(sab):
    _send(sab)
    [nzo_id] = sab.jobs
    sab.reachable = False

    with pytest.raises(requests.ConnectionError):
        sabnzbd.SABnzbd({}).historycheck(_monitor_item(nzo_id))
    assert (
        recovery_classify._probe_nzb({"payload_json": '{"nzo_id": "%s"}' % nzo_id, "release_key": "k"}) == "unreachable"
    )


def test_queue_reports_a_downloading_job(sab):
    _send(sab)
    [nzo_id] = sab.jobs
    sab.start(nzo_id)

    assert sabnzbd.SABnzbd({}).queuecheck(nzo_id) is True
    sab.forget(nzo_id)
    assert sabnzbd.SABnzbd({}).queuecheck(nzo_id) is False


def test_wrong_api_key_is_reported_as_rejected(sab, monkeypatch):
    monkeypatch.setattr(comicarr.CONFIG, "SAB_APIKEY", "a-stale-key")

    probe = connections._probe_sabnzbd(comicarr.CONFIG)

    assert probe.ok is False
    assert probe.result == "SABnzbd rejected the API key"


def test_wrong_api_key_upload_is_not_an_acceptance(sab, monkeypatch):
    monkeypatch.setattr(comicarr.CONFIG, "SAB_APIKEY", "a-stale-key")

    assert _send(sab) == {"status": False}
    assert sab.jobs == {}
