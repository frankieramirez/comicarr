#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Completed SABnzbd downloads that stayed Snatched get post-processed once (#1129)."""

import json
import logging
import queue as queue_module
import types

import pytest
import requests
from sqlalchemy import select

import comicarr
from comicarr.app.downloads import journal, recovery_classify, sab_reconcile
from comicarr.app.downloads.sab_reconcile import RetryPostProcessError
from comicarr.db import get_engine, shutdown_engine
from comicarr.sabnzbd import match_completed_slot, normalize_release_name
from comicarr.tables import issues, metadata, nzblog, pipeline_journal


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if not hasattr(comicarr, "LOG_LEVEL") or comicarr.LOG_LEVEL is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(
            HIGHCOUNT=0,
            SAB_APIKEY="k",
            SAB_HOST="http://sab.local",
            SAB_CATEGORY="comics",
            POST_PROCESSING=True,
            NZB_DOWNLOADER=0,
            SAB_CLIENT_POST_PROCESSING=True,
            SAB_DIRECTORY=str(tmp_path),
            MANUAL_PP_FOLDER=str(tmp_path),
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "USE_SABNZBD", True, raising=False)
    monkeypatch.setattr(comicarr, "USE_NZBGET", False, raising=False)
    monkeypatch.setattr(
        "comicarr.sabnzbd.SABnzbd.queuecheck",
        lambda self, nzo_id, ignore_category=False: False,
    )
    engine = get_engine()
    metadata.create_all(engine)
    yield
    shutdown_engine()


@pytest.fixture
def pp_queue(monkeypatch):
    queue = queue_module.Queue()
    monkeypatch.setattr(comicarr, "PP_QUEUE", queue, raising=False)
    return queue


def _drain(queue):
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def _insert_journal(release_key, stage, payload=None, **fields):
    with get_engine().begin() as conn:
        conn.execute(
            pipeline_journal.insert().values(
                release_key=release_key,
                stage=stage,
                stage_rank=journal.stage_rank(stage),
                updated_date="2026-05-17 00:00:00",
                payload_json=json.dumps(payload) if payload is not None else None,
                **fields,
            )
        )
    return journal.read_one(release_key)


def _snatched_sab(release_key, payload, issueid="13"):
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID=issueid, Status="Snatched"))
        conn.execute(nzblog.insert().values(IssueID=issueid, PROVIDER=payload.get("provider") or "sab"))
    return _insert_journal(
        release_key,
        journal.SNATCHED,
        payload=payload,
        issueid=issueid,
        provider=payload.get("provider") or "sab",
        downloader_type="sabnzbd",
        nzbname=payload.get("nzbname"),
    )


def test_release_names_match_one_completed_slot():
    assert normalize_release_name("Absolute.Superman.013.nzb") == "absolute superman 013"
    slots = [
        {"nzo_id": "other", "status": "Completed", "nzb_name": "Batman.001.nzb"},
        {
            "nzo_id": "SABnzbd_nzo_real",
            "status": "Completed",
            "storage": "/data/sabnzbd/completed/comics/Absolute Superman 013.cbr",
        },
        {"nzo_id": "SABnzbd_nzo_real", "status": "Completed", "filename": "Absolute.Superman.013.nzb"},
        {"nzo_id": "queued", "status": "Downloading", "nzb_name": "Absolute.Superman.013.nzb"},
    ]
    match = match_completed_slot(slots, ["Absolute.Superman.013.nzb"])
    assert match["nzo_id"] == "SABnzbd_nzo_real"


def test_ambiguous_completed_names_are_not_chosen():
    slots = [
        {"nzo_id": "one", "status": "Completed", "nzb_name": "Absolute.Superman.013.nzb"},
        {"nzo_id": "two", "status": "Completed", "name": "Absolute Superman 013.cbr"},
    ]
    assert match_completed_slot(slots, ["Absolute Superman 013"]) is None


def test_missing_nzo_id_matches_completed_history_by_release_name(monkeypatch):
    payload = {
        "issueid": "13",
        "provider": "nzbgeek",
        "route": "sabnzbd",
        "nzbname": "Absolute.Superman.013.nzb",
        "download_info": {"provider": "nzbgeek", "id": "indexer-99"},
    }
    row = _snatched_sab("13|nzbgeek", payload)
    seen = {}

    def match(self, nzbinfo):
        seen["searched"] = nzbinfo.get("nzbname")
        return {"nzo_id": "SABnzbd_nzo_real", "status": "Completed", "nzb_name": "Absolute.Superman.013.nzb"}

    def historycheck(self, nzbinfo, **kwargs):
        seen["probed"] = nzbinfo.get("nzo_id")
        return {
            "status": True,
            "location": "/data/sabnzbd/completed/comics/Absolute Superman 013",
            "name": "Absolute Superman 013.cbr",
            "failed": False,
        }

    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.match_completed_history", match)
    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.historycheck", historycheck)

    details = recovery_classify.classify_details(row)

    assert seen["searched"] == "Absolute.Superman.013.nzb"
    assert seen["probed"] == "SABnzbd_nzo_real"
    assert details["verdict"] == recovery_classify.COMPLETE
    assert details["nzo_id"] == "SABnzbd_nzo_real"
    assert details["location"].endswith("Absolute Superman 013")
    assert journal.read_one("13|nzbgeek")["stage"] == journal.SNATCHED


def test_missing_nzo_id_without_a_history_match_is_unprobeable(monkeypatch, caplog):
    payload = {
        "issueid": "14",
        "provider": "nzbgeek",
        "route": "sabnzbd",
        "nzbname": "Absolute.Superman.014.nzb",
        "download_info": {"id": "indexer-14"},
    }
    row = _snatched_sab("14|nzbgeek", payload, issueid="14")
    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.match_completed_history", lambda self, nzbinfo: None)

    with caplog.at_level(logging.WARNING, logger="comicarr"):
        details = recovery_classify.classify_details(row)

    assert details["raw_state"] == "unprobeable"
    assert details["verdict"] == recovery_classify.UNKNOWN
    assert "downloader API unreachable" not in caplog.text
    assert "no completed history match" in caplog.text


def test_sab_outage_during_name_match_stays_unreachable(monkeypatch):
    payload = {
        "issueid": "15",
        "provider": "nzbgeek",
        "route": "sabnzbd",
        "nzbname": "Absolute.Superman.015.nzb",
        "download_info": {},
    }
    row = _snatched_sab("15|nzbgeek", payload, issueid="15")

    def match(self, nzbinfo):
        raise requests.ConnectionError("sab down")

    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.match_completed_history", match)

    details = recovery_classify.classify_details(row)

    assert details["raw_state"] == "unreachable"
    assert details["verdict"] == recovery_classify.UNKNOWN


def test_reconcile_enqueues_a_completed_snatched_row_once(pp_queue, tmp_path, monkeypatch):
    completed = tmp_path / "Absolute Superman 013"
    completed.mkdir()
    (completed / "Absolute Superman 013.cbr").write_bytes(b"comic")
    payload = {
        "issueid": "13",
        "comicid": "C13",
        "provider": "nzbgeek",
        "route": "sabnzbd",
        "nzbname": "Absolute.Superman.013.nzb",
        "download_info": {"provider": "nzbgeek", "id": "indexer-13"},
    }
    row = _snatched_sab("13|nzbgeek", payload)
    history = {
        "status": True,
        "location": str(completed),
        "name": "Absolute Superman 013.cbr",
        "failed": False,
    }
    monkeypatch.setattr(
        "comicarr.sabnzbd.SABnzbd.match_completed_history",
        lambda self, nzbinfo: {"nzo_id": "SABnzbd_nzo_real", "status": "Completed"},
    )
    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.historycheck", lambda self, nzbinfo, **kwargs: history)
    _insert_journal(
        "ddl-row",
        journal.SNATCHED,
        payload={"route": "ddl", "nzbname": "skip.nzb"},
        issueid="99",
        provider="DDL",
        downloader_type="ddl",
    )

    first = sab_reconcile.reconcile_completed_sab_downloads()
    second = sab_reconcile.reconcile_completed_sab_downloads()

    assert first == {"checked": 1, "enqueued": 1, "skipped": 0}
    assert second == {"checked": 0, "enqueued": 0, "skipped": 0}
    items = _drain(pp_queue)
    assert len(items) == 1
    assert items[0]["journal_release_key"] == row["release_key"]
    assert items[0]["nzb_folder"] == str(completed)
    assert items[0]["nzb_name"] == "Absolute.Superman.013.nzb"
    stored = journal.read_one(row["release_key"])
    assert stored["stage"] == journal.DOWNLOADED
    persisted = journal.load_payload(stored["payload_json"])
    assert persisted["nzo_id"] == "SABnzbd_nzo_real"
    assert persisted["download_info"]["nzo_id"] == "SABnzbd_nzo_real"
    assert journal.read_one("ddl-row")["stage"] == journal.SNATCHED


def test_retry_refuses_a_download_sab_has_not_finished(monkeypatch):
    payload = {
        "issueid": "13",
        "provider": "nzbgeek",
        "route": "sabnzbd",
        "nzo_id": "SABnzbd_nzo_live",
        "nzbname": "Absolute.Superman.013.nzb",
        "download_info": {"nzo_id": "SABnzbd_nzo_live"},
    }
    row = _snatched_sab("13|nzbgeek", payload)
    monkeypatch.setattr(
        "comicarr.sabnzbd.SABnzbd.queuecheck",
        lambda self, nzo_id, ignore_category=False: True,
    )

    with pytest.raises(RetryPostProcessError) as raised:
        sab_reconcile.retry_postprocess(row["release_key"])

    assert raised.value.status_code == 409
    assert "not finished" in str(raised.value)
    assert journal.read_one(row["release_key"])["stage"] == journal.SNATCHED


def test_retry_endpoint_queues_post_processing(pp_queue, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from comicarr.app.core.security import require_session
    from comicarr.app.downloads.router import router

    completed = tmp_path / "Absolute Superman 015"
    completed.mkdir()
    payload = {
        "issueid": "15",
        "comicid": "C15",
        "provider": "nzbgeek",
        "route": "sabnzbd",
        "nzbname": "Absolute.Superman.015.nzb",
        "download_info": {"id": "indexer-15"},
    }
    row = _snatched_sab("15|nzbgeek", payload, issueid="15")
    monkeypatch.setattr(
        "comicarr.sabnzbd.SABnzbd.match_completed_history",
        lambda self, nzbinfo: {"nzo_id": "SABnzbd_nzo_015", "status": "Completed"},
    )
    monkeypatch.setattr(
        "comicarr.sabnzbd.SABnzbd.historycheck",
        lambda self, nzbinfo, **kwargs: {
            "status": True,
            "location": str(completed),
            "name": "Absolute Superman 015.cbr",
            "failed": False,
        },
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "operator"

    with TestClient(app) as client:
        missing = client.post("/api/downloads/retry-postprocess", json={})
        assert missing.status_code == 400
        queued = client.post("/api/downloads/retry-postprocess", json={"release_key": row["release_key"]})

    assert queued.status_code == 200
    assert queued.json()["action"] == "enqueued"
    assert len(_drain(pp_queue)) == 1
    assert journal.read_one(row["release_key"])["stage"] == journal.DOWNLOADED
    with get_engine().connect() as conn:
        stored = conn.execute(select(pipeline_journal).where(pipeline_journal.c.release_key == "15|nzbgeek")).fetchone()
    assert stored is not None


def _completed_job(tmp_path, name="Absolute Superman 014"):
    completed = tmp_path / name
    completed.mkdir()
    (completed / ("%s.cbr" % name)).write_bytes(b"comic")
    return completed


def _sab_payload(issueid="14", nzo_id="SABnzbd_nzo_014"):
    return {
        "issueid": issueid,
        "comicid": "C" + issueid,
        "provider": "nzbgeek",
        "route": "sabnzbd",
        "nzo_id": nzo_id,
        "nzbname": "Absolute.Superman.0%s.nzb" % issueid,
        "download_info": {"nzo_id": nzo_id},
    }


def test_retry_is_refused_and_hidden_when_post_processing_is_off(pp_queue, monkeypatch):
    row = _snatched_sab("14|nzbgeek", _sab_payload(), issueid="14")
    monkeypatch.setattr(comicarr.CONFIG, "POST_PROCESSING", False)

    with pytest.raises(RetryPostProcessError) as raised:
        sab_reconcile.retry_postprocess(row["release_key"])

    assert raised.value.status_code == 409
    assert "turned off" in str(raised.value)
    assert _drain(pp_queue) == []
    assert journal.read_one(row["release_key"])["stage"] == journal.SNATCHED
    assert sab_reconcile.retry_postprocess_eligible(row, _sab_payload()) is False


def test_sweep_probe_keeps_sab_history_until_the_row_is_downloaded(pp_queue, tmp_path, monkeypatch):
    completed = _completed_job(tmp_path)
    row = _snatched_sab("14|nzbgeek", _sab_payload(), issueid="14")
    calls = []

    def historycheck(self, nzbinfo, **kwargs):
        calls.append(("historycheck", kwargs.get("keep_history")))
        return {"status": True, "location": str(completed), "name": "x.cbr", "failed": False}

    def remove_history(self, nzo_id, status):
        calls.append(("remove", nzo_id, status, journal.read_one(row["release_key"])["stage"]))

    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.historycheck", historycheck)
    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.remove_history", remove_history)

    result = sab_reconcile.queue_completed_postprocess(row)

    assert result["action"] == "enqueued"
    assert calls == [
        ("historycheck", True),
        ("remove", "SABnzbd_nzo_014", "Completed", journal.DOWNLOADED),
    ]


def test_rejected_folder_keeps_history_and_goes_to_manual_review(pp_queue, monkeypatch):
    row = _snatched_sab("14|nzbgeek", _sab_payload(), issueid="14")
    removed = []
    monkeypatch.setattr(
        "comicarr.sabnzbd.SABnzbd.historycheck",
        lambda self, nzbinfo, **kwargs: {
            "status": True,
            "location": "/not/under/any/configured/root",
            "name": "x.cbr",
            "failed": False,
        },
    )
    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.remove_history", lambda self, *a: removed.append(a))

    result = sab_reconcile.queue_completed_postprocess(row)

    assert result["action"] == "unplaced"
    assert removed == []
    assert _drain(pp_queue) == []
    assert journal.read_one(row["release_key"])["stage"] == journal.MANUAL_REVIEW


def test_failed_sab_job_without_failed_handling_is_terminalized(pp_queue, monkeypatch):
    row = _snatched_sab("14|nzbgeek", _sab_payload(), issueid="14")
    monkeypatch.setattr(
        "comicarr.sabnzbd.SABnzbd.historycheck",
        lambda self, nzbinfo, **kwargs: {"status": "failed_no_auto_handling", "failed": True, "name": "x"},
    )

    removed = []
    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.remove_history", lambda self, *a: removed.append(a))

    result = sab_reconcile.queue_completed_postprocess(row)

    assert result["action"] == "failed"
    assert _drain(pp_queue) == []
    assert journal.read_one(row["release_key"])["stage"] == journal.FAILED
    assert removed == [("SABnzbd_nzo_014", "Failed")]


def test_losing_the_transition_does_not_queue_a_second_item(pp_queue, tmp_path, monkeypatch):
    completed = _completed_job(tmp_path)
    row = _snatched_sab("14|nzbgeek", _sab_payload(), issueid="14")
    monkeypatch.setattr(
        "comicarr.sabnzbd.SABnzbd.historycheck",
        lambda self, nzbinfo, **kwargs: {"status": True, "location": str(completed), "name": "x", "failed": False},
    )
    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.remove_history", lambda self, *a: None)

    def lost_race(rkey, stage, **kwargs):
        with get_engine().begin() as conn:
            conn.execute(
                pipeline_journal.update()
                .where(pipeline_journal.c.release_key == rkey)
                .values(stage=journal.DOWNLOADED, stage_rank=journal.stage_rank(journal.DOWNLOADED))
            )
        return False

    monkeypatch.setattr(journal, "record_transition", lost_race)

    result = sab_reconcile.queue_completed_postprocess(row)

    assert result == {"action": "not-won", "release_key": row["release_key"], "stage": journal.DOWNLOADED}
    assert _drain(pp_queue) == []


@pytest.mark.parametrize("status", ["nzb removed", "file not found"])
def test_monitor_does_not_review_a_row_another_path_already_claimed(status, monkeypatch):
    from comicarr.app.downloads import service

    _insert_journal("14|nzbgeek", journal.DOWNLOADED, payload=_sab_payload(), issueid="14", provider="nzbgeek")
    recorded = []
    monkeypatch.setattr(service, "_cdh_record_entry", recorded.append)
    item = {"nzo_id": "SABnzbd_nzo_014", "journal_release_key": "14|nzbgeek", "issueid": "14"}

    assert service._cdh_record_terminal_outcome(item, {"status": status, "failed": False}) is True
    assert recorded == []
    assert journal.read_one("14|nzbgeek")["stage"] == journal.DOWNLOADED


def test_monitor_still_reviews_a_snatched_row_whose_job_vanished(monkeypatch):
    from comicarr.app.downloads import service

    _insert_journal("14|nzbgeek", journal.SNATCHED, payload=_sab_payload(), issueid="14", provider="nzbgeek")
    recorded = []
    monkeypatch.setattr(service, "_cdh_record_entry", recorded.append)
    item = {"nzo_id": "SABnzbd_nzo_014", "journal_release_key": "14|nzbgeek", "issueid": "14"}

    assert service._cdh_record_terminal_outcome(item, {"status": "nzb removed", "failed": False}) is True
    assert [entry.reason for entry in recorded] == ["sab_job_missing_from_client"]


def test_full_search_page_is_not_trusted_for_a_single_match(monkeypatch):
    from comicarr import sabnzbd

    one = {"status": "Completed", "nzo_id": "SABnzbd_nzo_a", "nzb_name": "Absolute.Superman.013.nzb"}
    other = {"status": "Completed", "nzo_id": "SABnzbd_nzo_b", "nzb_name": "Absolute Superman 013.nzb"}
    filler = [{"status": "Completed", "nzo_id": "f%d" % n, "nzb_name": "Other %d" % n} for n in range(49)]
    pages = {50: [one] + filler, 200: [other]}
    monkeypatch.setattr(sabnzbd.SABnzbd, "list_history_slots", lambda self, search=None, limit=200: list(pages[limit]))

    client = sabnzbd.SABnzbd({})
    assert client.match_completed_history({"nzbname": "Absolute.Superman.013.nzb"}) is None


def test_short_search_page_still_checks_recent_history_for_a_twin(monkeypatch):
    from comicarr import sabnzbd

    one = {"status": "Completed", "nzo_id": "SABnzbd_nzo_a", "nzb_name": "Absolute.Superman.013.nzb"}
    twin = {"status": "Completed", "nzo_id": "SABnzbd_nzo_b", "nzb_name": "Absolute Superman 013.nzb"}
    pages = {50: [one], 200: [one, twin]}
    monkeypatch.setattr(sabnzbd.SABnzbd, "list_history_slots", lambda self, search=None, limit=200: list(pages[limit]))

    client = sabnzbd.SABnzbd({})
    assert client.match_completed_history({"nzbname": "Absolute.Superman.013.nzb"}) is None

    pages[200] = [one]
    assert client.match_completed_history({"nzbname": "Absolute.Superman.013.nzb"}) == one


def test_downloaded_retry_is_limited_to_sab_rows(pp_queue, tmp_path):
    completed = _completed_job(tmp_path)
    payload = {**_sab_payload(), "route": "nzbget", "nzb_folder": str(completed)}
    row = _insert_journal("14|nzbgeek", journal.DOWNLOADED, payload=payload, issueid="14", downloader_type="nzbget")

    assert sab_reconcile.retry_postprocess_eligible(row, payload) is False
    assert sab_reconcile.queue_completed_postprocess(row)["action"] == "not-sab"
    assert _drain(pp_queue) == []


def test_history_release_targets_the_job_matched_by_name(pp_queue, tmp_path, monkeypatch):
    completed = _completed_job(tmp_path)
    payload = {k: v for k, v in _sab_payload().items() if k != "nzo_id"}
    payload["download_info"] = {"provider": "nzbgeek"}
    row = _snatched_sab("14|nzbgeek", payload, issueid="14")
    removed = []
    monkeypatch.setattr(
        "comicarr.sabnzbd.SABnzbd.match_completed_history",
        lambda self, nzbinfo: {"nzo_id": "SABnzbd_nzo_matched", "status": "Completed"},
    )
    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.queuecheck", lambda self, *a, **k: False)
    monkeypatch.setattr(
        "comicarr.sabnzbd.SABnzbd.historycheck",
        lambda self, nzbinfo, **kwargs: {
            "status": True,
            "location": str(completed),
            "name": "x.cbr",
            "failed": False,
            "nzo_id": nzbinfo["nzo_id"],
        },
    )
    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.remove_history", lambda self, *a: removed.append(a))

    assert sab_reconcile.queue_completed_postprocess(row)["action"] == "enqueued"
    assert removed == [("SABnzbd_nzo_matched", "Completed")]
    saved = journal.load_payload(journal.read_one(row["release_key"])["payload_json"])
    assert saved["nzo_id"] == "SABnzbd_nzo_matched"


def test_startup_recovery_keeps_history_until_the_row_is_downloaded(pp_queue, tmp_path, monkeypatch):
    from comicarr.app.downloads import recovery

    completed = _completed_job(tmp_path)
    row = _snatched_sab("14|nzbgeek", _sab_payload(), issueid="14")
    calls = []

    def historycheck(self, nzbinfo, **kwargs):
        calls.append(("historycheck", kwargs.get("keep_history")))
        return {"status": True, "location": str(completed), "name": "x.cbr", "failed": False}

    def remove_history(self, nzo_id, status):
        calls.append(("remove", nzo_id, status, journal.read_one(row["release_key"])["stage"]))

    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.queuecheck", lambda self, *a, **k: False)
    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.historycheck", historycheck)
    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.remove_history", remove_history)

    assert recovery._resolve_row(row) == "complete-pp-enqueued"
    assert calls == [
        ("historycheck", True),
        ("remove", "SABnzbd_nzo_014", "Completed", journal.DOWNLOADED),
    ]
    assert len(_drain(pp_queue)) == 1


def test_startup_recovery_keeps_history_for_a_rejected_folder(pp_queue, monkeypatch):
    from comicarr.app.downloads import recovery

    row = _snatched_sab("14|nzbgeek", _sab_payload(), issueid="14")
    removed = []
    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.queuecheck", lambda self, *a, **k: False)
    monkeypatch.setattr(
        "comicarr.sabnzbd.SABnzbd.historycheck",
        lambda self, nzbinfo, **kwargs: {
            "status": True,
            "location": "/not/under/any/configured/root",
            "name": "x.cbr",
            "failed": False,
        },
    )
    monkeypatch.setattr("comicarr.sabnzbd.SABnzbd.remove_history", lambda self, *a: removed.append(a))

    assert recovery._resolve_row(row) == "complete-manual-review"
    assert removed == []
    assert _drain(pp_queue) == []


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_processor_stops_watching_once_its_job_leaves_the_queue(monkeypatch):
    from comicarr import sabnzbd

    responses = [
        {"noofslots": 1, "queue": {"slots": [{"filename": "x", "status": "Downloading", "mbleft": "5"}]}},
        {"noofslots": 0, "queue": {"slots": [], "status": "Downloading", "mbleft": "900"}},
    ]
    sent = []

    def get(url, params=None, **kwargs):
        sent.append(dict(params))
        return _FakeResponse(responses.pop(0))

    seen = {}

    def historycheck(self, nzbinfo, **kwargs):
        seen.update(kwargs)
        return {"status": True}

    monkeypatch.setattr(sabnzbd.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(sabnzbd.requests, "get", get)
    monkeypatch.setattr(sabnzbd.SABnzbd, "historycheck", historycheck)
    monkeypatch.setattr(comicarr.CONFIG, "SAB_VERIFY", False, raising=False)

    client = sabnzbd.SABnzbd(
        {
            "nzo_id": "SABnzbd_nzo_013",
            "queue": {"mode": "queue", "search": "x", "output": "json", "apikey": "k", "category": "comics"},
        }
    )

    assert client.processor() == {"status": True}
    assert len(sent) == 2
    assert all("category" not in params for params in sent)
    assert all(params.get("nzo_ids") == "SABnzbd_nzo_013" for params in sent)
    assert seen.get("ignore_category") is True


def test_historycheck_probe_leaves_completed_history_in_sab(tmp_path, monkeypatch):
    from comicarr import sabnzbd

    archive = tmp_path / "Absolute Superman 013.cbr"
    archive.write_bytes(b"comic")
    slot = {"nzo_id": "SABnzbd_nzo_013", "status": "Completed", "script": "", "storage": str(archive)}
    monkeypatch.setattr(
        sabnzbd.requests, "get", lambda url, params=None, **kw: _FakeResponse({"history": {"slots": [slot]}})
    )
    removed = []
    monkeypatch.setattr(sabnzbd.SABnzbd, "remove_history", lambda self, nzo_id, status: removed.append(nzo_id))
    for key, value in {"SAB_VERSION": "4.0.0", "SAB_VERIFY": False, "SAB_DIRECT_UNPACK": False}.items():
        monkeypatch.setattr(comicarr.CONFIG, key, value, raising=False)
    nzbinfo = {"nzo_id": "SABnzbd_nzo_013", "issueid": "13", "comicid": "C13", "download_info": {}}
    client = sabnzbd.SABnzbd({})

    probed = client.historycheck(nzbinfo, ignore_category=True, keep_history=True)
    consumed = client.historycheck(nzbinfo, ignore_category=True)

    assert probed["status"] is True and consumed["status"] is True
    assert removed == ["SABnzbd_nzo_013"]
