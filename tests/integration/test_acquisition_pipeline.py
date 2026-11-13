#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""End-to-end acquisition stage contracts with fake external boundaries."""

import os
import queue
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import comicarr
from comicarr import db, importer
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.acquisition.models import ItemOutcome
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.core.context import AppContext
from comicarr.app.downloads import handoff, journal, postprocessing, recovery
from comicarr.app.series import service as series_service
from comicarr.tables import acquisition_run_items, acquisition_runs, comics, issues, metadata, nzblog, pipeline_journal
from tests.fakes import manga as manga_fake
from tests.fakes import pipeline
from tests.fakes import sabnzbd as sab_fake
from tests.fakes.nzbget import FakeNzbget
from tests.fakes.sabnzbd import FakeSabnzbd


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(MANUAL_PP_FOLDER=str(tmp_path / "downloads")),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "SEARCH_QUEUE", queue.Queue(), raising=False)
    monkeypatch.setattr(comicarr, "PP_QUEUE", queue.Queue(), raising=False)
    monkeypatch.setattr(comicarr, "ACQUISITION_WORKERS_BLOCKED", False, raising=False)
    monkeypatch.setattr(comicarr, "ACQUISITION_BLOCK_REASON", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("COMICARR_ACQUISITION_MAINTENANCE", raising=False)
    db.shutdown_engine()
    metadata.create_all(db.get_engine())
    assert ensure_acquisition_schema(db.get_engine()).ready
    yield
    db.shutdown_engine()


def _seed_issue(series_root):
    series_root.mkdir(parents=True)
    with db.get_engine().begin() as conn:
        conn.execute(
            comics.insert().values(
                ComicID="160294",
                ComicName="Absolute Batman",
                ComicYear="2024",
                Status="Active",
                Have=0,
                Total=1,
                ComicLocation=str(series_root),
            )
        )
        conn.execute(
            issues.insert().values(
                IssueID="issue-1",
                ComicID="160294",
                ComicName="Absolute Batman",
                Issue_Number="1",
                Int_IssueNumber=1,
                Status=None,
                AcquisitionIntent=None,
                ReleaseDate="2020-01-01",
            )
        )


def _ctx():
    return AppContext(config=SimpleNamespace(ANNUALS_ON=False))


def _ready_search_route(monkeypatch):
    monkeypatch.setattr(
        "comicarr.app.search.health.get_search_health",
        lambda *_args, **_kwargs: {
            "viable_route": True,
            "routes": {"nzb": {"ready": True}, "torrent": {}, "ddl": {}},
        },
    )


def _complete_probes():
    return {route: (lambda _row: "complete") for route in ("torrent", "nzb", "sab", "sabnzbd", "nzbget", "ddl", "DDL")}


def test_bulk_wanted_run_handoff_restart_and_owned_projection(monkeypatch, tmp_path):
    """One Wanted obligation survives the real durable boundaries.

    This is deliberately an integration-level composition rather than a
    journal-only lifecycle test: a canonical series preview is confirmed into
    a durable search run, the accepted work crosses the external handoff
    boundary exactly once, a restart resolves its persisted downloader state,
    and a verified library artifact is reflected by the canonical series
    projection.  Only the external downloader response and physical move are
    faked.
    """
    series_root = tmp_path / "library" / "Absolute Batman"
    download_root = tmp_path / "downloads"
    download_root.mkdir()
    _seed_issue(series_root)
    _ready_search_route(monkeypatch)

    preview = series_service.preview_search_all_missing(
        _ctx(),
        "160294",
        actor="frankie",
        session_id="browser-session",
    )
    assert preview["eligibleCount"] == 1
    assert preview["preview_token"]

    accepted = series_service.search_all_missing(
        _ctx(),
        "160294",
        "frankie",
        confirm=True,
        preview_token=preview["preview_token"],
        fingerprint=preview["fingerprint"],
        session_id="browser-session",
    )
    assert accepted["success"] is True
    assert accepted["status"] == "accepted"
    assert accepted["accepted"] == 1
    run_id = accepted["run_id"]

    queued_search = comicarr.SEARCH_QUEUE.get_nowait()
    assert queued_search == {
        "issueid": "issue-1",
        "comicid": "160294",
        "manual": False,
        "run_id": run_id,
        "comicname": None,
        "seriesyear": None,
        "issuenumber": None,
        "booktype": None,
        "entity_type": "issue",
        "queue_priority": "interactive",
    }
    ledger = RunLedger()
    assert ledger.claim_item(run_id, "issue", "issue-1") is True

    release_key = journal.release_key("issue-1", "sabnzbd", nzbname="Absolute.Batman.001")
    payload = {
        "issueid": "issue-1",
        "comicid": "160294",
        "nzb_name": "Absolute.Batman.001",
        "nzb_folder": str(download_root),
        "provider": "sabnzbd",
        "download_info": {"provider": "sabnzbd", "id": "nzo-1"},
    }
    sender_calls = []

    response, handoff_acceptance = handoff.perform_handoff(
        release_key,
        "sabnzbd",
        lambda: sender_calls.append("submitted") or {"nzo_id": "nzo-1"},
        payload=payload,
        issueid="issue-1",
        provider="sabnzbd",
        nzbname="Absolute.Batman.001",
    )
    assert response == {"nzo_id": "nzo-1"}
    assert handoff_acceptance.restart_safe is True
    assert sender_calls == ["submitted"]
    assert journal.read_one(release_key)["stage"] == journal.SNATCHED

    # This is the same durable in-flight marker that normal snatch handling
    # keeps until post-processing succeeds. It prevents the history-eviction
    # guard from mistaking a live accepted download for completed work.
    with db.get_engine().begin() as conn:
        conn.execute(
            nzblog.insert().values(
                IssueID="issue-1",
                PROVIDER="sabnzbd",
                NZBName="Absolute.Batman.001",
            )
        )

    # Simulate a process restart after the downloader completed. The real
    # recovery pipeline records downloaded before it requeues PP work.
    restarted = recovery.replay_pipeline(probes=_complete_probes())
    assert restarted["actions"] == {"complete-pp-enqueued": 1}
    pp_item = comicarr.PP_QUEUE.get_nowait()
    assert pp_item["journal_release_key"] == release_key
    assert pp_item["issueid"] == "issue-1"
    assert journal.read_one(release_key)["stage"] == journal.DOWNLOADED

    # The real monotonic PP markers describe a completed move. Recovery's
    # moved finalizer then co-commits the terminal journal marker with nzblog
    # cleanup, so a subsequent restart cannot re-run the side effect.
    assert journal.record_transition(release_key, journal.POST_PROCESSING, payload=payload)
    assert journal.record_transition(release_key, journal.MOVED, payload=payload)
    artifact = series_root / "Absolute Batman 001.cbz"
    artifact.write_bytes(b"verified comic")
    with db.get_engine().begin() as conn:
        conn.execute(
            issues.update().where(issues.c.IssueID == "issue-1").values(Status="Downloaded", Location=str(artifact))
        )
    assert postprocessing.recover(release_key).action == "moved-finish-dbfacts"
    assert journal.read_one(release_key)["stage"] == journal.POST_PROCESSED

    # Complete the durable search item only after its physical ownership
    # evidence exists; then prove a second startup does not enqueue it again.
    run = ledger.record_outcome(run_id, "issue", "issue-1", ItemOutcome.SUCCEEDED, reason="verified_library_file")
    assert run["completion_state"] == "completed"
    second_restart = recovery.replay_pipeline(probes=_complete_probes())
    assert second_restart["open"] == 0
    assert comicarr.PP_QUEUE.empty()

    detail = series_service.get_comic_detail(_ctx(), "160294")
    issue = detail["issues"][0]
    assert issue["fulfillment"] == "downloaded"
    assert issue["fulfillmentEvidence"] == "verified_location"
    assert issue["physicalOwned"] is True
    assert detail["summary"] == {
        "total": 1,
        "issues": 1,
        "annuals": 0,
        "owned": 1,
        "covered": 0,
        "physicalOwned": 1,
        "archived": 0,
        "inFlight": 0,
        "missing": 0,
        "monitored": 1,
        "wanted": 0,
        "skipped": 0,
        "ignored": 0,
        "failed": 0,
        "unknown": 0,
        "future": 0,
        "eligible": 0,
        "deferred": 0,
        "completionPercent": 100,
    }

    with db.get_engine().connect() as conn:
        row = (
            conn.execute(select(pipeline_journal).where(pipeline_journal.c.release_key == release_key))
            .mappings()
            .first()
        )
        run_row = conn.execute(select(acquisition_runs).where(acquisition_runs.c.run_id == run_id)).mappings().one()
        run_item = (
            conn.execute(select(acquisition_run_items).where(acquisition_run_items.c.run_id == run_id)).mappings().one()
        )
    assert row is not None
    assert row["stage"] == journal.POST_PROCESSED
    assert row["release_key"] == release_key
    assert run_row["succeeded_count"] == 1
    assert run_item["state"] == ItemOutcome.SUCCEEDED.value


def test_rejected_handoff_has_a_named_terminal_failure(tmp_path):
    """A terminal rejected submission remains visible to the operator.

    The rejection is intentionally a fake downloader response; the
    reservation and terminal transition are real. A future deliberate retry
    is allowed by the durable failed-to-reserved policy, so duplicate-submit
    protection is covered separately for a live accepted obligation.
    """
    _seed_issue(tmp_path / "library" / "Absolute Batman")
    release_key = journal.release_key("issue-1", "sabnzbd", nzbname="rejected")
    calls = []

    response, acceptance = handoff.perform_handoff(
        release_key,
        "sabnzbd",
        lambda: calls.append("submitted") or False,
        payload={"issueid": "issue-1", "comicid": "160294", "nzb_name": "rejected"},
        issueid="issue-1",
        provider="sabnzbd",
        nzbname="rejected",
    )
    assert response is False
    assert acceptance.manual_review is False
    assert acceptance.restart_safe is False
    terminal = journal.read_one(release_key)
    assert terminal["stage"] == journal.FAILED
    assert terminal["fail_reason"] == "submission_rejected"
    assert calls == ["submitted"]

    from comicarr.app.downloads.pp_commands import PostProcessCommandError, validate_postprocess_item

    with pytest.raises(PostProcessCommandError):
        validate_postprocess_item(
            {
                "nzb_name": "",
                "nzb_folder": "",
                "issueid": "issue-1",
            }
        )


def test_duplicate_accepted_handoff_never_resubmits_externally(tmp_path):
    """A live accepted release keeps its reservation and blocks a duplicate sender."""
    _seed_issue(tmp_path / "library" / "Absolute Batman")
    release_key = journal.release_key("issue-1", "sabnzbd", nzbname="already-accepted")
    calls = []
    payload = {"issueid": "issue-1", "comicid": "160294", "nzb_name": "already-accepted"}

    _, acceptance = handoff.perform_handoff(
        release_key,
        "sabnzbd",
        lambda: calls.append("submitted") or {"nzo_id": "nzo-1"},
        payload=payload,
        issueid="issue-1",
        provider="sabnzbd",
        nzbname="already-accepted",
    )
    assert acceptance.restart_safe is True
    assert journal.read_one(release_key)["stage"] == journal.SNATCHED

    with pytest.raises(handoff.HandoffReservationError):
        handoff.perform_handoff(
            release_key,
            "sabnzbd",
            lambda: calls.append("duplicate-submit") or {"nzo_id": "nzo-2"},
            payload=payload,
            issueid="issue-1",
            provider="sabnzbd",
            nzbname="already-accepted",
        )
    assert calls == ["submitted"]
    assert journal.read_one(release_key)["stage"] == journal.SNATCHED


# ---------------------------------------------------------------------------
# SABnzbd scenarios (docs/testing/first-class-targets.md). Each runs the real
# handoff, monitor, completed-download handling and post-processing against
# FakeSabnzbd, which answers with responses recorded from SABnzbd 5.1.3.
# ---------------------------------------------------------------------------


@pytest.fixture
def sab(tmp_path, monkeypatch):
    fake = FakeSabnzbd().install(monkeypatch)
    local_complete = tmp_path / "sab" / "complete"
    local_complete.mkdir(parents=True)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        pipeline.default_config(
            SAB_HOST=fake.host,
            SAB_APIKEY=fake.apikey,
            SAB_CATEGORY=fake.category,
            SAB_VERSION=sab_fake.VERSION,
            SAB_MOVING_DELAY=0,
            SAB_CLIENT_POST_PROCESSING=True,
            SAB_DIRECTORY=str(local_complete),
            MANUAL_PP_FOLDER=str(tmp_path / "downloads"),
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "USE_SABNZBD", True, raising=False)
    monkeypatch.setattr(comicarr, "USE_NZBGET", False, raising=False)
    monkeypatch.setattr(comicarr, "NZB_QUEUE", queue.Queue(), raising=False)
    monkeypatch.setattr(comicarr, "RETURN_THE_NZBQUEUE", queue.Queue(), raising=False)
    monkeypatch.setattr("comicarr.sabnzbd.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("comicarr.app.downloads.service.time.sleep", lambda _seconds: None)
    # Post-processing waits for a file renamed in the last ten seconds to
    # settle. Its clock runs a minute ahead so the wait passes at once.
    monkeypatch.setattr(
        "comicarr.postprocessor.time", SimpleNamespace(time=lambda: time.time() + 60, sleep=lambda _seconds: None)
    )
    series_root = tmp_path / "library" / "Absolute Batman (2024)"
    series_root.mkdir(parents=True)
    with db.get_engine().begin() as conn:
        conn.execute(comics.insert().values(**pipeline.comic_series_row(series_root)))
        conn.execute(issues.insert().values(**pipeline.comic_issue_row()))
    fake.local_complete = local_complete
    fake.series_root = series_root
    fake.nzb = pipeline.cached_nzb(tmp_path)
    return fake


def _download_lands(sab, nzo_id, folder=None):
    """SABnzbd finishes the job: the archive is on disk where Comicarr can read it."""
    return pipeline.write_download((folder or sab.local_complete) / sab.category / pipeline.RELEASE / pipeline.FILENAME)


def _assert_in_library(sab):
    placed = sab.series_root / pipeline.FILENAME
    assert placed.is_file()
    issue, summary = pipeline.library_issue()
    assert issue["fulfillment"] == "downloaded"
    assert summary["owned"] == 1
    assert journal.read_one(pipeline.release_key())["stage"] == journal.POST_PROCESSED


def test_sab_handoff_is_verified_from_sabs_own_response(sab):
    response, item = pipeline.send_to_sab(sab.nzb)

    [nzo_id] = sab.jobs
    assert response["nzo_id"] == nzo_id
    row = journal.read_one(pipeline.release_key())
    assert row["stage"] == journal.SNATCHED
    assert nzo_id in str(row)
    [upload] = [call for call in sab.calls if call["mode"] == "addfile"]
    assert upload["method"] == "POST" and "comicarr" not in str(upload).lower()

    sab.complete(nzo_id, str(_download_lands(sab, nzo_id)))
    assert pipeline.monitor_sab(item)["status"] is True
    assert pipeline.post_process_next().status == "processed"
    _assert_in_library(sab)


def test_sab_rejected_upload_is_a_named_failure(sab, tmp_path):
    bad = tmp_path / "cache" / "broken.nzb"
    bad.write_bytes(b"not an nzb")

    response, item = pipeline.send_to_sab(bad, name="broken")

    assert response == {"status": False}
    assert item is None
    row = journal.read_one(pipeline.release_key("broken"))
    assert row["stage"] == journal.FAILED
    assert row["fail_reason"] == "submission_rejected"
    issue, _summary = pipeline.library_issue()
    assert issue["fulfillment"] != "downloaded"


def test_sab_completed_path_with_remote_path_mapping(sab, monkeypatch):
    """SABnzbd reports its own path; SAB_DIRECTORY maps it to where Comicarr sees the job."""
    monkeypatch.setattr(comicarr.CONFIG, "SAB_DIRECT_UNPACK", True)
    _response, item = pipeline.send_to_sab(sab.nzb)
    [nzo_id] = sab.jobs
    remote = sab.remote_storage(nzo_id, pipeline.FILENAME)
    local = pipeline.write_download(sab.local_complete / pipeline.RELEASE / pipeline.FILENAME)
    sab.complete(nzo_id, remote)

    nzstat = pipeline.monitor_sab(item)

    assert not remote.startswith(str(sab.local_complete))
    assert nzstat["location"] == str(local.parent)
    assert pipeline.post_process_next().status == "processed"
    _assert_in_library(sab)


def test_sab_completed_path_without_remote_path_mapping(sab):
    """SABnzbd and Comicarr share a filesystem: the reported path is opened as-is."""
    _response, item = pipeline.send_to_sab(sab.nzb)
    [nzo_id] = sab.jobs
    archive = _download_lands(sab, nzo_id)
    sab.complete(nzo_id, str(archive))

    nzstat = pipeline.monitor_sab(item)

    assert nzstat["location"] == str(archive.parent)
    assert not any(call["mode"] in ("status", "get_config") for call in sab.calls)
    assert pipeline.post_process_next().status == "processed"
    _assert_in_library(sab)


def test_sab_missing_completed_path_goes_to_manual_review(sab):
    _response, item = pipeline.send_to_sab(sab.nzb)
    [nzo_id] = sab.jobs
    sab.complete(nzo_id, sab.remote_storage(nzo_id, pipeline.FILENAME))

    nzstat = pipeline.monitor_sab(item)

    assert nzstat["status"] == "file not found"
    assert comicarr.PP_QUEUE.empty()
    row = journal.read_one(pipeline.release_key())
    assert row["stage"] == journal.MANUAL_REVIEW
    assert row["fail_reason"] == "sab_completed_file_not_found"
    issue, _summary = pipeline.library_issue()
    assert issue["fulfillment"] != "downloaded"


def test_sab_history_removed_before_comicarr_reads_it(sab):
    _response, item = pipeline.send_to_sab(sab.nzb)
    [nzo_id] = sab.jobs
    sab.forget(nzo_id)

    nzstat = pipeline.monitor_sab(item)

    assert nzstat["status"] == "nzb removed"
    assert comicarr.PP_QUEUE.empty()
    row = journal.read_one(pipeline.release_key())
    assert row["stage"] == journal.MANUAL_REVIEW
    assert row["fail_reason"] == "sab_job_missing_from_client"
    issue, _summary = pipeline.library_issue()
    assert issue["fulfillment"] != "downloaded"


def test_sab_failed_download_leads_to_a_retry(sab, monkeypatch):
    monkeypatch.setattr(comicarr.CONFIG, "FAILED_DOWNLOAD_HANDLING", True)
    monkeypatch.setattr(comicarr.CONFIG, "FAILED_AUTO", True)
    _response, item = pipeline.send_to_sab(sab.nzb)
    [nzo_id] = sab.jobs
    sab.fail(nzo_id)

    nzstat = pipeline.monitor_sab(item)

    assert nzstat["status"] is True and nzstat["failed"] is True
    result = pipeline.post_process_next()
    assert result.status == "processed"
    row = journal.read_one(pipeline.release_key())
    assert row["stage"] == journal.FAILED
    issue, _summary = pipeline.library_issue()
    assert issue["fulfillment"] != "downloaded"
    retry = comicarr.SEARCH_QUEUE.get_nowait()
    assert retry["issueid"] == pipeline.ISSUE_ID


def test_sab_category_routing(sab, monkeypatch):
    """The upload names the category; a job moved out of it is still followed."""
    _response, item = pipeline.send_to_sab(sab.nzb)
    [upload] = [call for call in sab.calls if call["mode"] == "addfile"]
    assert upload["cat"] == "comics"
    [nzo_id] = sab.jobs
    assert sab.jobs[nzo_id]["category"] == "comics"
    sab.jobs[nzo_id]["category"] = "sorted-elsewhere"
    sab.complete(nzo_id, str(_download_lands(sab, nzo_id)))

    pipeline.monitor_sab(item)

    assert pipeline.post_process_next().status == "processed"
    _assert_in_library(sab)


def test_sab_restart_mid_download_resumes_monitoring(sab):
    _response, item = pipeline.send_to_sab(sab.nzb)
    [nzo_id] = sab.jobs
    sab.start(nzo_id)

    restarted = recovery.replay_pipeline()

    assert journal.read_one(pipeline.release_key())["stage"] == journal.SNATCHED
    rebuilt = comicarr.NZB_QUEUE.get_nowait()
    assert rebuilt["nzo_id"] == nzo_id
    assert restarted["open"] == 1
    sab.complete(nzo_id, str(_download_lands(sab, nzo_id)))
    pipeline.monitor_sab(rebuilt)
    assert pipeline.post_process_next().status == "processed"
    _assert_in_library(sab)


def test_sab_wrong_api_key_is_a_connection_failure(sab, monkeypatch):
    from comicarr.app.system import connections

    monkeypatch.setattr(comicarr.CONFIG, "SAB_APIKEY", "a-stale-key")

    response, item = pipeline.send_to_sab(sab.nzb)

    assert response == {"status": False} and item is None
    assert sab.jobs == {}
    assert journal.read_one(pipeline.release_key())["fail_reason"] == "submission_rejected"
    issue, _summary = pipeline.library_issue()
    assert issue["fulfillment"] != "downloaded"
    probe = connections._probe_sabnzbd(comicarr.CONFIG)
    assert probe.ok is False
    assert "API key" in probe.result


def test_sab_unreachable_host_is_a_connection_failure(sab):
    from comicarr.app.downloads import recovery_classify

    _response, item = pipeline.send_to_sab(sab.nzb)
    [nzo_id] = sab.jobs
    sab.reachable = False

    row = journal.read_one(pipeline.release_key())
    assert recovery_classify.classify(row) == "unknown"
    restarted = recovery.replay_pipeline()
    assert journal.read_one(pipeline.release_key())["stage"] == journal.SNATCHED
    assert restarted["open"] == 1

    sab.reachable = True
    sab.complete(nzo_id, str(_download_lands(sab, nzo_id)))
    pipeline.monitor_sab(item)
    assert pipeline.post_process_next().status == "processed"
    _assert_in_library(sab)


@pytest.fixture
def current_comicvine_issue_id(monkeypatch):
    monkeypatch.setattr(pipeline, "ISSUE_ID", "1086215")


@pytest.mark.xfail(
    strict=True,
    reason="IssueIDs at or above 900000 key as one-offs, so a restart finds two rows for one grab: "
    "https://github.com/frankieramirez/comicarr/issues/1261",
)
def test_sab_restart_with_a_current_comicvine_issue_id(current_comicvine_issue_id, sab):
    _response, _item = pipeline.send_to_sab(sab.nzb)
    [nzo_id] = sab.jobs
    sab.start(nzo_id)

    restarted = recovery.replay_pipeline()

    assert restarted["open"] == 1
    with db.get_engine().connect() as conn:
        assert len(conn.execute(select(pipeline_journal)).all()) == 1


@pytest.fixture
def nzb(tmp_path, monkeypatch):
    fake = FakeNzbget().install(monkeypatch)
    local_completed = tmp_path / "nzbget" / "completed"
    local_completed.mkdir(parents=True)
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
            NZBGET_DIRECTORY=str(local_completed),
            MANUAL_PP_FOLDER=str(tmp_path / "downloads"),
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "USE_NZBGET", True, raising=False)
    monkeypatch.setattr(comicarr, "USE_SABNZBD", False, raising=False)
    monkeypatch.setattr(comicarr, "NZB_QUEUE", queue.Queue(), raising=False)
    monkeypatch.setattr(comicarr, "RETURN_THE_NZBQUEUE", queue.Queue(), raising=False)
    monkeypatch.setattr("comicarr.nzbget.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("comicarr.app.downloads.service.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "comicarr.postprocessor.time", SimpleNamespace(time=lambda: time.time() + 60, sleep=lambda _seconds: None)
    )
    series_root = tmp_path / "library" / "Absolute Batman (2024)"
    series_root.mkdir(parents=True)
    with db.get_engine().begin() as conn:
        conn.execute(comics.insert().values(**pipeline.comic_series_row(series_root)))
        conn.execute(issues.insert().values(**pipeline.comic_issue_row()))
    fake.local_completed = local_completed
    fake.series_root = series_root
    fake.nzb = pipeline.cached_nzb(tmp_path)
    return fake


def _nzbget_download_lands(nzb):
    """NZBGet finishes the job; NZBGET_DIRECTORY is where Comicarr sees its DestDir."""
    return pipeline.write_download(nzb.local_completed / nzb.category / pipeline.RELEASE / pipeline.FILENAME)


def test_nzbget_append_handoff_is_verified_from_nzbgets_own_response(nzb):
    response, item = pipeline.send_to_nzbget(nzb.nzb)

    [nzbid] = nzb.jobs
    assert response == {"status": True, "NZBID": nzbid}
    row = journal.read_one(pipeline.release_key())
    assert row["stage"] == journal.SNATCHED
    assert '"NZBID": "%s"' % nzbid in row["payload_json"]
    [append] = [call for call in nzb.calls if call["method"] == "append"]
    assert append["params"][2] == "comics" and "comicarr" not in str(append["params"][1:]).lower()

    nzb.complete(nzbid)
    _nzbget_download_lands(nzb)
    assert pipeline.monitor_nzbget(item)["status"] is True
    assert pipeline.post_process_next().status == "processed"
    _assert_in_library(nzb)


def test_nzbget_history_polling_follows_the_job_into_history(nzb):
    _response, item = pipeline.send_to_nzbget(nzb.nzb)
    [nzbid] = nzb.jobs
    nzb.start(nzbid, polls=2)
    _nzbget_download_lands(nzb)

    nzstat = pipeline.monitor_nzbget(item)

    assert [call["method"] for call in nzb.calls].count("listgroups") == 3
    assert nzstat["status"] is True and nzstat["failed"] is False
    assert pipeline.post_process_next().status == "processed"
    _assert_in_library(nzb)


def test_nzbget_destination_directory_mapping(nzb):
    """NZBGet reports its own DestDir; NZBGET_DIRECTORY maps it to where Comicarr sees the job."""
    _response, item = pipeline.send_to_nzbget(nzb.nzb)
    [nzbid] = nzb.jobs
    nzb.complete(nzbid)
    local = _nzbget_download_lands(nzb)

    nzstat = pipeline.monitor_nzbget(item)

    assert not nzb.remote_dest(nzbid).startswith(str(nzb.local_completed))
    assert str(nzstat["location"]) == str(local.parent)
    assert "config" in [call["method"] for call in nzb.calls]
    assert pipeline.post_process_next().status == "processed"
    _assert_in_library(nzb)


def _nzbget_failure_is_retried(nzb, monkeypatch, how):
    monkeypatch.setattr(comicarr.CONFIG, "FAILED_DOWNLOAD_HANDLING", True)
    monkeypatch.setattr(comicarr.CONFIG, "FAILED_AUTO", True)
    _response, item = pipeline.send_to_nzbget(nzb.nzb)
    [nzbid] = nzb.jobs
    nzb.fail(nzbid, how)

    nzstat = pipeline.monitor_nzbget(item)

    assert nzstat["status"] is True and nzstat["failed"] is True
    assert pipeline.post_process_next().status == "processed"
    row = journal.read_one(pipeline.release_key())
    assert row["stage"] == journal.FAILED
    issue, _summary = pipeline.library_issue()
    assert issue["fulfillment"] != "downloaded"
    retry = comicarr.SEARCH_QUEUE.get_nowait()
    assert retry["issueid"] == pipeline.ISSUE_ID
    return row


def test_nzbget_par_failure_leads_to_a_retry(nzb, monkeypatch):
    _nzbget_failure_is_retried(nzb, monkeypatch, "par")


def test_nzbget_unpack_failure_leads_to_a_retry(nzb, monkeypatch):
    _nzbget_failure_is_retried(nzb, monkeypatch, "unpack")


def test_nzbget_health_failure_leads_to_a_retry(nzb, monkeypatch):
    _nzbget_failure_is_retried(nzb, monkeypatch, "health")


@pytest.mark.xfail(
    strict=True,
    reason="Every NZBGet FAILURE/* status records the same failure reason: "
    "https://github.com/frankieramirez/comicarr/issues/1264",
)
@pytest.mark.parametrize("how", ["par", "unpack", "health"])
def test_nzbget_failure_reason_names_what_failed(nzb, monkeypatch, how):
    row = _nzbget_failure_is_retried(nzb, monkeypatch, how)

    assert how in row["fail_reason"]


@pytest.mark.xfail(
    strict=True,
    reason="The handoff saves NZBID as a string and NZBGet reports an integer, so restart marks the grab gone: "
    "https://github.com/frankieramirez/comicarr/issues/1263",
)
def test_nzbget_restart_after_the_job_finished_resumes_handling(nzb):
    """NZBGet finished the job while Comicarr was down; startup picks it up from history."""
    _response, _item = pipeline.send_to_nzbget(nzb.nzb)
    [nzbid] = nzb.jobs
    nzb.complete(nzbid)
    _nzbget_download_lands(nzb)

    restarted = recovery.replay_pipeline()

    assert restarted["open"] == 1
    rebuilt = comicarr.NZB_QUEUE.get_nowait()
    assert rebuilt["NZBID"] == nzbid
    pipeline.monitor_nzbget(rebuilt)
    assert pipeline.post_process_next().status == "processed"
    _assert_in_library(nzb)


@pytest.mark.xfail(
    strict=True,
    reason="The restart probe misses the saved NZBID and reads only history, so a downloading job is marked gone: "
    "https://github.com/frankieramirez/comicarr/issues/1263",
)
def test_nzbget_restart_mid_download_resumes_monitoring(nzb):
    _response, _item = pipeline.send_to_nzbget(nzb.nzb)
    [nzbid] = nzb.jobs
    nzb.start(nzbid, polls=1)

    restarted = recovery.replay_pipeline()

    assert journal.read_one(pipeline.release_key())["stage"] == journal.SNATCHED
    rebuilt = comicarr.NZB_QUEUE.get_nowait()
    assert rebuilt["NZBID"] == nzbid
    assert restarted["open"] == 1
    _nzbget_download_lands(nzb)
    pipeline.monitor_nzbget(rebuilt)
    assert pipeline.post_process_next().status == "processed"
    _assert_in_library(nzb)


def test_nzbget_wrong_password_is_an_authentication_failure(nzb, monkeypatch):
    from comicarr.app.system import connections

    monkeypatch.setattr(comicarr.CONFIG, "NZBGET_PASSWORD", "a-stale-password")

    response, item = pipeline.send_to_nzbget(nzb.nzb)

    assert response == {"status": False} and item is None
    assert nzb.jobs == {}
    assert journal.read_one(pipeline.release_key())["fail_reason"] == "submission_rejected"
    issue, _summary = pipeline.library_issue()
    assert issue["fulfillment"] != "downloaded"
    probe = connections._probe_nzbget(comicarr.CONFIG)
    assert probe.ok is False
    assert probe.result == "NZBGet rejected the username or password"


# -- manga --------------------------------------------------------------------


@pytest.fixture
def manga(sab, tmp_path, monkeypatch):
    """A MangaDex series with two released volumes, handed off through SABnzbd."""
    manga_dest = tmp_path / "manga"
    series_root = manga_dest / pipeline.MANGA_SERIES
    series_root.mkdir(parents=True)
    monkeypatch.setattr(comicarr.CONFIG, "MANGA_DESTINATION_DIR", str(manga_dest))
    with db.get_engine().begin() as conn:
        conn.execute(comics.insert().values(**pipeline.manga_series_row(series_root)))
        for row in pipeline.manga_chapter_rows():
            conn.execute(issues.insert().values(**row))
    sab.manga_root = series_root
    sab.tmp_path = tmp_path
    return sab


def _manga_series():
    from comicarr.tables import comics as t_comics

    return db.select_one(select(t_comics).where(t_comics.c.ComicID == pipeline.MANGA_ID))


def _set_manga(**values):
    with db.get_engine().begin() as conn:
        conn.execute(comics.update().where(comics.c.ComicID == pipeline.MANGA_ID).values(**values))


def _manga_plan():
    from comicarr.app.manga.acquisition import search_plan_for_series

    return search_plan_for_series(_manga_series(), list(pipeline.manga_issues().values()))


def _grab_manga(sab, target, filename):
    """Search for ``target`` as manga RSS does, hand the release to SABnzbd, and post-process what lands."""
    from comicarr.app.manga.acquisition import search_terms_for_target
    from comicarr.app.manga.ledger import volume_id

    if target["kind"] == "volume":
        issueid = volume_id(pipeline.MANGA_ID, target["number"])
    else:
        issueid = target["id"]
    [term, *_] = search_terms_for_target(pipeline.MANGA_SERIES, target)
    name = term.replace(" ", ".")
    response, item = pipeline.send_to_sab(
        pipeline.cached_nzb(sab.tmp_path, name),
        name,
        issueid=issueid,
        comicid=pipeline.MANGA_ID,
        series=pipeline.MANGA_SERIES,
    )
    [nzo_id] = [nzo for nzo, job in sab.jobs.items() if job["name"] == name]
    landed = pipeline.write_download(sab.local_complete / sab.category / name / filename)
    sab.complete(nzo_id, str(landed))
    pipeline.monitor_sab(item)
    result = pipeline.post_process_next()
    return term, issueid, result


def _downloaded():
    return sorted(
        (row["ChapterNumber"] for row in pipeline.manga_issues().values() if row["Status"] == "Downloaded"),
        key=float,
    )


def _volume_of(chapter):
    return next((volume for volume, chapters in pipeline.MANGA_VOLUMES.items() if chapter in chapters), None)


def test_manga_bare_number_auto_mode_reads_a_volume(manga):
    """``auto``: one bare-numbered file against two volumes and ten chapters is a volume."""
    term, _issueid, result = _grab_manga(manga, {"kind": "volume", "number": "2"}, "Sakamoto Days 02.cbz")

    assert term == "Sakamoto Days v02"
    assert result.status == "processed"
    assert (manga.manga_root / "Sakamoto Days 02.cbz").is_file()
    downloaded = _downloaded()
    assert downloaded and {_volume_of(chapter) for chapter in downloaded} == {"2"}


def test_manga_bare_number_auto_mode_reads_a_number_past_the_volumes_as_a_chapter(manga):
    """``auto``: 9 is past the last of two volumes, so it can only be chapter 9."""
    target = {"kind": "chapter", "id": pipeline.manga_chapter_id("9"), "number": "9"}
    term, _issueid, result = _grab_manga(manga, target, "Sakamoto Days 09.cbz")

    assert term == "Sakamoto Days c009"
    assert result.status == "processed"
    assert _downloaded() == ["9"]


def test_manga_bare_number_volumes_mode_reads_a_volume(manga):
    _set_manga(BareNumberMode="volumes")

    _term, _issueid, result = _grab_manga(manga, {"kind": "volume", "number": "1"}, "Sakamoto Days 01.cbz")

    assert result.status == "processed"
    downloaded = _downloaded()
    assert downloaded and {_volume_of(chapter) for chapter in downloaded} == {"1"}


def test_manga_bare_number_chapters_mode_reads_a_chapter(manga):
    _set_manga(BareNumberMode="chapters")
    target = {"kind": "chapter", "id": pipeline.manga_chapter_id("2"), "number": "2"}

    _term, _issueid, result = _grab_manga(manga, target, "Sakamoto Days 02.cbz")

    assert result.status == "processed"
    assert _downloaded() == ["2"]


def test_manga_v_prefixed_volume_is_a_volume_in_any_mode(manga):
    """``v01`` names a volume even when the series reads bare numbers as chapters."""
    _set_manga(BareNumberMode="chapters")

    term, _issueid, result = _grab_manga(
        manga, {"kind": "volume", "number": "1"}, "Sakamoto Days v01 (2021) (Digital).cbz"
    )

    assert term == "Sakamoto Days v01"
    assert result.status == "processed"
    assert (manga.manga_root / "Sakamoto Days v01 (2021) (Digital).cbz").is_file()
    downloaded = _downloaded()
    assert downloaded and {_volume_of(chapter) for chapter in downloaded} == {"1"}


@pytest.mark.xfail(
    strict=True,
    reason="A manga volume is matched to one of its chapter rows, which is marked Downloaded, and the "
    "other chapters are never covered: https://github.com/frankieramirez/comicarr/issues/1278",
)
def test_manga_volume_covers_its_chapters_without_marking_them_have(manga):
    _grab_manga(manga, {"kind": "volume", "number": "1"}, "Sakamoto Days v01 (2021) (Digital).cbz")

    rows = pipeline.manga_issues()
    volume_one = [rows[pipeline.manga_chapter_id(chapter)] for chapter in pipeline.MANGA_VOLUMES["1"]]
    assert all(row["Status"] != "Downloaded" for row in volume_one)
    chapters, _summary = _manga_detail()
    covered = {row["ChapterNumber"] for row in chapters if row.get("covered")}
    assert covered == set(pipeline.MANGA_VOLUMES["1"])


@pytest.mark.xfail(
    strict=True,
    reason="Recording a manga volume grab looks up an issue row the volume does not have: "
    "https://github.com/frankieramirez/comicarr/issues/1279",
)
def test_manga_volume_grab_is_recorded_as_snatched(manga):
    from comicarr.app.manga.ledger import volume_id

    name = "Sakamoto.Days.v02"
    _response, item = pipeline.send_to_sab(
        pipeline.cached_nzb(manga.tmp_path, name),
        name,
        issueid=volume_id(pipeline.MANGA_ID, "2"),
        comicid=pipeline.MANGA_ID,
        series=pipeline.MANGA_SERIES,
    )

    assert item["snatch_error"] is None


def test_manga_blended_frontier_searches_volumes_then_chapters_beyond(manga):
    from comicarr.app.manga.acquisition import search_terms_for_target

    plan = _manga_plan()
    assert [(target["kind"], target["number"]) for target in plan] == [
        ("volume", "1"),
        ("volume", "2"),
        ("chapter", "9"),
        ("chapter", "10"),
    ]
    assert [search_terms_for_target(pipeline.MANGA_SERIES, target)[0] for target in plan] == [
        "Sakamoto Days v01",
        "Sakamoto Days v02",
        "Sakamoto Days c009",
        "Sakamoto Days c010",
    ]

    _term, _issueid, result = _grab_manga(manga, plan[2], "Sakamoto Days c009 (2021) (Digital).cbz")

    assert result.status == "processed"
    assert _downloaded() == ["9"]
    assert [(target["kind"], target["number"]) for target in _manga_plan()] == [
        ("volume", "1"),
        ("volume", "2"),
        ("chapter", "10"),
    ]


@pytest.mark.xfail(
    strict=True,
    reason="A downloaded manga volume never leaves the blended frontier, so it is searched again: "
    "https://github.com/frankieramirez/comicarr/issues/1278",
)
def test_manga_downloaded_volume_leaves_the_blended_frontier(manga):
    _grab_manga(manga, {"kind": "volume", "number": "1"}, "Sakamoto Days v01 (2021) (Digital).cbz")

    assert ("volume", "1") not in [(target["kind"], target["number"]) for target in _manga_plan()]


def _manga_detail():
    detail = series_service.get_comic_detail(_ctx(), pipeline.MANGA_ID)
    return detail["issues"], detail["summary"]


# ---------------------------------------------------------------------------
# Manga added from recorded answers. Each scenario adds its series through
# the real importer against FakeMangaDex and FakeMyAnimeList, which answer with responses recorded from
# both services (tests/fixtures/mangadex/, tests/fixtures/myanimelist/), then
# runs the handoff, monitor and post-processing against FakeSabnzbd.
# ---------------------------------------------------------------------------

MD_COMIC_ID = "md-" + manga_fake.MANGADEX_ID
MAL_COMIC_ID = "mal-" + manga_fake.MAL_ID


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    from comicarr import helpers, mangadex

    sab = FakeSabnzbd().install(monkeypatch)
    mangadex_api = manga_fake.FakeMangaDex().install(monkeypatch)
    mal_api = manga_fake.FakeMyAnimeList().install(monkeypatch)
    local_complete = tmp_path / "sab" / "complete"
    local_complete.mkdir(parents=True)
    library = tmp_path / "manga"
    library.mkdir()
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        pipeline.default_config(
            MANGADEX_ENABLED=True,
            MAL_ENABLED=True,
            MAL_CLIENT_ID=mal_api.client_id,
            MANGA_DESTINATION_DIR=str(library),
            CREATE_FOLDERS=True,
            CACHE_DIR=str(tmp_path / "cache"),
            SAB_HOST=sab.host,
            SAB_APIKEY=sab.apikey,
            SAB_CATEGORY=sab.category,
            SAB_VERSION=sab_fake.VERSION,
            SAB_MOVING_DELAY=0,
            SAB_CLIENT_POST_PROCESSING=True,
            SAB_DIRECTORY=str(local_complete),
            MANUAL_PP_FOLDER=str(tmp_path / "downloads"),
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "USE_SABNZBD", True, raising=False)
    monkeypatch.setattr(comicarr, "USE_NZBGET", False, raising=False)
    monkeypatch.setattr(comicarr, "NZB_QUEUE", queue.Queue(), raising=False)
    monkeypatch.setattr(comicarr, "RETURN_THE_NZBQUEUE", queue.Queue(), raising=False)
    monkeypatch.setattr(comicarr, "COMICSORT", helpers.ComicSort(sequence="startup"), raising=False)
    monkeypatch.setattr("comicarr.mangadex._rate_limit", lambda: None)
    monkeypatch.setattr("comicarr.myanimelist._rate_limit", lambda: None)
    monkeypatch.setattr("comicarr.sabnzbd.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("comicarr.app.downloads.service.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "comicarr.postprocessor.time", SimpleNamespace(time=lambda: time.time() + 60, sleep=lambda _seconds: None)
    )
    mangadex.clear_cache()
    return SimpleNamespace(
        sab=sab, mangadex=mangadex_api, mal=mal_api, local_complete=local_complete, library=library, tmp=tmp_path
    )


def _grab_chapter(recorded, comic_id, number, source="Digital", want=True):
    """A search result for one chapter goes to SABnzbd, finishes, and is post-processed."""
    if want:
        pipeline.want_recorded_chapter(comic_id, number)
    _response, item = pipeline.send_recorded_chapter(recorded.tmp, comic_id, number, source)
    [nzo_id] = [nzo for nzo, job in recorded.sab.jobs.items() if job["state"] == "Queued"]
    name, filename = pipeline.recorded_release(number, source)
    archive = pipeline.write_download(recorded.local_complete / recorded.sab.category / name / filename)
    recorded.sab.complete(nzo_id, str(archive))
    assert pipeline.monitor_sab(item)["status"] is True
    return pipeline.post_process_next()


def _assert_chapter_in_library(comic_id, number):
    series = pipeline.series_row(comic_id)
    _name, filename = pipeline.recorded_release(number)
    placed = os.path.join(series["ComicLocation"], filename)
    assert os.path.isfile(placed)
    chapter = pipeline.chapters_by_number(comic_id)[str(number)]
    assert chapter["Status"] == "Downloaded"
    assert chapter["Location"] == filename
    key = pipeline.recorded_release_key(comic_id, number)
    assert journal.read_one(key)["stage"] == journal.POST_PROCESSED
    return placed


def _add_events(comic_id):
    from comicarr.app.activity import service as activity_service

    timeline = activity_service.get_timeline(scope_type="series", scope_id=comic_id)
    events = timeline["results"]
    return [event for event in events if event.get("activity") == "add"]


def test_mangadex_ledger_sync_heals_an_empty_ledger(recorded):
    """A series row left with no chapters is rebuilt from MangaDex, then a chapter lands."""
    from comicarr.app.manga import sync

    with db.get_engine().begin() as conn:
        conn.execute(
            comics.insert().values(
                ComicID=MD_COMIC_ID, ComicName=pipeline.RECORDED_SERIES, Status="Active", ContentType="manga"
            )
        )
    assert [row["ComicID"] for row in sync.empty_ledger_series()] == [MD_COMIC_ID]

    assert sync.heal_empty_ledgers() == 1

    assert sync.empty_ledger_series() == []
    chapters = pipeline.chapters_by_number(MD_COMIC_ID)
    assert sorted(chapters, key=float) == recorded.mangadex.chapter_numbers()
    assert {row["VolumeNumber"] for row in chapters.values()} == {"1"}
    assert pipeline.series_row(MD_COMIC_ID)["Total"] == 11
    assert _grab_chapter(recorded, MD_COMIC_ID, 3).status == "processed"
    _assert_chapter_in_library(MD_COMIC_ID, 3)


def test_mal_sourced_series_reaches_the_library(recorded):
    """MAL supplies the metadata, MangaDex the chapters, and a chapter grab lands in the series."""
    result = importer.addMangaToDB_MAL(MAL_COMIC_ID)

    assert result["status"] == "complete"
    series = pipeline.series_row(MAL_COMIC_ID)
    assert series["MetadataSource"] == "mal"
    assert series["MalID"] == manga_fake.MAL_ID
    assert series["MangaDexID"] == manga_fake.MANGADEX_ID
    assert len(pipeline.chapters_by_number(MAL_COMIC_ID)) == 11
    assert any(call["path"] == "/v2/manga/%s" % manga_fake.MAL_ID for call in recorded.mal.calls)
    assert _grab_chapter(recorded, MAL_COMIC_ID, 5).status == "processed"
    _assert_chapter_in_library(MAL_COMIC_ID, 5)


def test_manga_chapter_is_placed_in_its_series_folder(recorded):
    assert importer.addMangaToDB(MD_COMIC_ID)["status"] == "complete"

    assert _grab_chapter(recorded, MD_COMIC_ID, 3).status == "processed"

    placed = _assert_chapter_in_library(MD_COMIC_ID, 3)
    assert os.path.dirname(placed) == str(recorded.library / "Shino-chan Cant Say Her Name (2011)")
    others = {
        number: row["Status"] for number, row in pipeline.chapters_by_number(MD_COMIC_ID).items() if number != "3"
    }
    assert set(others.values()) == {"Skipped"}
    assert not (recorded.local_complete / recorded.sab.category / pipeline.recorded_release(3)[0]).exists()


def test_manga_duplicate_guard_refuses_the_same_work_from_mal(recorded):
    """A MangaDex series whose MAL link is 49017 blocks adding MAL 49017 a second time."""
    assert importer.addMangaToDB(MD_COMIC_ID)["status"] == "complete"

    refused = importer.addMangaToDB_MAL(MAL_COMIC_ID)

    assert refused["status"] == "duplicate"
    assert refused["comicid"] == MD_COMIC_ID
    assert pipeline.series_row(MAL_COMIC_ID) is None
    assert pipeline.chapters_by_number(MAL_COMIC_ID) == {}
    [event] = [event for event in _add_events(MAL_COMIC_ID) if event.get("status") == "failed"]
    assert MD_COMIC_ID in str(event.get("reason_detail"))
    assert _grab_chapter(recorded, MD_COMIC_ID, 3).status == "processed"
    _assert_chapter_in_library(MD_COMIC_ID, 3)


def test_manga_second_release_of_an_owned_chapter_is_not_sent(recorded):
    """Once a chapter is in the library, another release of it never reaches the client."""
    assert importer.addMangaToDB(MD_COMIC_ID)["status"] == "complete"
    assert _grab_chapter(recorded, MD_COMIC_ID, 3).status == "processed"
    placed = _assert_chapter_in_library(MD_COMIC_ID, 3)
    jobs_before = dict(recorded.sab.jobs)

    with pytest.raises(handoff.HandoffReservationError, match="library still holds this issue"):
        pipeline.send_recorded_chapter(recorded.tmp, MD_COMIC_ID, 3, "Scan")

    assert recorded.sab.jobs == jobs_before
    assert [call for call in recorded.sab.calls if call["mode"] == "addfile"][1:] == []
    assert [name for name in os.listdir(os.path.dirname(placed)) if " c003 " in name] == [os.path.basename(placed)]
    assert pipeline.chapters_by_number(MD_COMIC_ID)["3"]["Status"] == "Downloaded"


def test_manga_rss_grabs_and_places_a_wanted_chapter(recorded, monkeypatch):
    """The scheduled manga RSS pass matches an rssdb row, hands it to SABnzbd, and it lands."""
    from comicarr.rsscheck import mangaCheck
    from comicarr.tables import rssdb
    from tests.fakes.newznab import FakeNewznab

    indexer = FakeNewznab().install(monkeypatch)
    monkeypatch.setattr(comicarr.CONFIG, "NEWZNAB", True)
    monkeypatch.setattr(comicarr.CONFIG, "EXTRA_NEWZNABS", [indexer.config_entry()])
    monkeypatch.setattr(comicarr.CONFIG, "ENABLE_RSS", True)
    assert importer.addMangaToDB(MD_COMIC_ID)["status"] == "complete"
    with db.get_engine().begin() as conn:
        conn.execute(comics.update().where(comics.c.ComicID == MD_COMIC_ID).values(MonitorMode="chapters"))
    issue_id = pipeline.want_recorded_chapter(MD_COMIC_ID, 3)
    name, filename = pipeline.recorded_release(3)
    title = filename[: -len(".cbz")]
    link = indexer.publish("shino-c003", title, filename)
    with db.get_engine().begin() as conn:
        conn.execute(
            rssdb.insert().values(
                Title=title, Link=link, Pubdate="Fri, 13 Nov 2026 10:00:00 +0000", Site=indexer.name, Size="4096"
            )
        )

    mangaCheck()

    [nzo_id] = recorded.sab.jobs
    job = recorded.sab.jobs[nzo_id]
    assert job["category"] == recorded.sab.category
    item = comicarr.NZB_QUEUE.get_nowait()
    assert item["issueid"] == issue_id
    archive = pipeline.write_download(recorded.local_complete / recorded.sab.category / job["name"] / filename)
    recorded.sab.complete(nzo_id, str(archive))
    assert pipeline.monitor_sab(item)["status"] is True
    assert pipeline.post_process_next().status == "processed"
    series = pipeline.series_row(MD_COMIC_ID)
    assert os.path.isfile(os.path.join(series["ComicLocation"], filename))
    assert pipeline.chapters_by_number(MD_COMIC_ID)["3"]["Status"] == "Downloaded"


def test_manga_add_failure_is_narrated_in_activity(recorded, monkeypatch):
    """An add MangaDex cannot answer tells the operator why, through the activity channel."""
    from comicarr.app.search.service import add_manga

    monkeypatch.setattr("comicarr.importer.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(comicarr, "ADD_LIST", queue.Queue(), raising=False)
    monkeypatch.setattr(comicarr, "ISSUE_WATCH_LIST", queue.Queue(), raising=False)
    monkeypatch.setattr(comicarr, "MASS_ADD", None, raising=False)
    missing = "md-" + manga_fake.MISSING_MANGADEX_ID

    queued = add_manga(AppContext(config=comicarr.CONFIG), manga_fake.MISSING_MANGADEX_ID)
    comicarr.MASS_ADD.join(timeout=30)

    assert queued["success"] is True and queued["comicid"] == missing
    assert not comicarr.MASS_ADD.is_alive()
    [event] = [event for event in _add_events(missing) if event.get("status") == "failed"]
    assert "MangaDex details fetch failed" in str(event.get("reason_detail"))
    assert any(call["path"] == "/manga/%s" % manga_fake.MISSING_MANGADEX_ID for call in recorded.mangadex.calls)
    assert pipeline.chapters_by_number(missing) == {}
