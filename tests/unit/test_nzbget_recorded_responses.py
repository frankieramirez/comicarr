#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""comicarr/nzbget.py against responses recorded from a real NZBGet.

These run Comicarr's NZBGet calls against ``FakeNzbget``, whose answers come
from ``tests/fixtures/nzbget/``, so a field NZBGet renamed or a status it
reports differently shows up here.
"""

import xmlrpc.client

import pytest

import comicarr
from comicarr import nzbget
from comicarr.app.downloads import recovery_classify
from comicarr.app.system import connections
from tests.fakes import pipeline
from tests.fakes.nzbget import FakeNzbget


@pytest.fixture
def nzb(monkeypatch, tmp_path):
    fake = FakeNzbget().install(monkeypatch)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        pipeline.default_config(
            NZBGET_HOST=fake.host,
            NZBGET_PORT=fake.port,
            NZBGET_USERNAME=fake.username,
            NZBGET_PASSWORD=fake.password,
            NZBGET_CATEGORY=fake.category,
            NZBGET_CLIENT_POST_PROCESSING=True,
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "USE_NZBGET", True, raising=False)
    monkeypatch.setattr(comicarr, "USE_SABNZBD", False, raising=False)
    monkeypatch.setattr("comicarr.nzbget.time.sleep", lambda _seconds: None)
    fake.nzb = pipeline.cached_nzb(tmp_path)
    return fake


def _send(nzb, path=None):
    return nzbget.NZBGet().sender(str(path or nzb.nzb))


def _monitor_item(nzbid):
    return {"NZBID": nzbid, "issueid": pipeline.ISSUE_ID, "comicid": pipeline.COMIC_ID, "download_info": {}}


def test_append_returns_the_nzbid_nzbget_assigned(nzb):
    response = _send(nzb)

    [nzbid] = nzb.jobs
    assert response == {"status": True, "NZBID": nzbid}
    [append] = [call for call in nzb.calls if call["method"] == "append"]
    assert append["params"][2] == "comics"
    assert nzb.jobs[nzbid]["name"] == pipeline.RELEASE


def test_processor_polls_the_queue_until_the_job_reaches_history(nzb):
    _send(nzb)
    [nzbid] = nzb.jobs
    nzb.start(nzbid, polls=3)

    found = nzbget.NZBGet().processor(_monitor_item(nzbid))

    assert len([call for call in nzb.calls if call["method"] == "listgroups"]) == 4
    assert found["status"] == "file not found"
    nzb.forget(nzbid)
    assert nzbget.NZBGet().historycheck(_monitor_item(nzbid)) == {"status": False}


def test_history_dest_dir_is_mapped_into_nzbget_directory(nzb, monkeypatch, tmp_path):
    local = tmp_path / "nzbget" / "completed"
    monkeypatch.setattr(comicarr.CONFIG, "NZBGET_DIRECTORY", str(local))
    _send(nzb)
    [nzbid] = nzb.jobs
    nzb.complete(nzbid)

    found = nzbget.NZBGet().historycheck(_monitor_item(nzbid))

    assert nzb.remote_dest(nzbid) == "/config/completed/comics/%s" % pipeline.RELEASE
    assert found["status"] is True and found["failed"] is False
    assert str(found["location"]) == str(local / "comics" / pipeline.RELEASE)


def test_history_dest_dir_is_used_as_is_when_comicarr_can_see_it(nzb, tmp_path):
    shared = tmp_path / "shared"
    nzb.main_dir = str(shared)
    _send(nzb)
    [nzbid] = nzb.jobs
    nzb.complete(nzbid)
    folder = shared / "completed" / "comics" / pipeline.RELEASE
    folder.mkdir(parents=True)

    found = nzbget.NZBGet().historycheck(_monitor_item(nzbid))

    assert found["location"] == str(folder)
    assert found["name"] == pipeline.RELEASE


def _failed(nzb, how):
    _send(nzb)
    [nzbid] = nzb.jobs
    nzb.fail(nzbid, how)
    return nzbget.NZBGet().historycheck(_monitor_item(nzbid))


def test_par_failure_is_a_failed_download(nzb):
    found = _failed(nzb, "par")

    assert found["status"] is True and found["failed"] is True
    assert found["name"] == pipeline.RELEASE


def test_unpack_failure_is_a_failed_download(nzb):
    found = _failed(nzb, "unpack")

    assert found["status"] is True and found["failed"] is True
    assert found["name"] == pipeline.RELEASE


def test_health_failure_is_a_failed_download(nzb):
    found = _failed(nzb, "health")

    assert found["status"] is True and found["failed"] is True
    assert found["name"] == pipeline.RELEASE


def test_restart_probe_finds_a_finished_job_in_history(nzb, monkeypatch, tmp_path):
    monkeypatch.setattr(comicarr.CONFIG, "NZBGET_DIRECTORY", str(tmp_path))
    _send(nzb)
    [nzbid] = nzb.jobs
    nzb.complete(nzbid)

    probed = recovery_classify._nzbget_history({"release_key": "k"}, payload={"NZBID": nzbid})

    assert probed["status"] is True and probed["failed"] is False
    assert probed["name"] == pipeline.RELEASE


def test_restart_probe_finds_the_job_from_the_saved_handoff(nzb, monkeypatch, tmp_path):
    monkeypatch.setattr(comicarr.CONFIG, "NZBGET_DIRECTORY", str(tmp_path))
    _send(nzb)
    [nzbid] = nzb.jobs
    nzb.complete(nzbid)
    # handoff.record_acceptance saves the identity the client returned with str().
    saved = {"route": "nzbget", "client": "nzbget", "NZBID": str(nzbid)}

    probed = recovery_classify._nzbget_history({"release_key": "k"}, payload=saved)

    assert probed["status"] is True


def test_wrong_password_upload_is_not_an_acceptance(nzb, monkeypatch):
    monkeypatch.setattr(comicarr.CONFIG, "NZBGET_PASSWORD", "a-stale-password")

    assert _send(nzb) == {"status": False}
    assert nzb.jobs == {}


def test_wrong_password_probe_is_reported_as_rejected(nzb, monkeypatch):
    monkeypatch.setattr(comicarr.CONFIG, "NZBGET_PASSWORD", "a-stale-password")

    probe = connections._probe_nzbget(comicarr.CONFIG)

    assert probe.ok is False
    assert probe.result == "NZBGet rejected the username or password"
    with pytest.raises(xmlrpc.client.ProtocolError) as raised:
        nzbget.NZBGet().historycheck(_monitor_item(1))
    assert raised.value.errcode == 401


def test_right_password_probe_reports_the_version(nzb):
    probe = connections._probe_nzbget(comicarr.CONFIG)

    assert probe.ok is True
    assert probe.version == "26.3"
