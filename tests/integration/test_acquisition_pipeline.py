#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""End-to-end acquisition stage contracts with fake external boundaries."""

import queue
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import comicarr
from comicarr import db
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.acquisition.models import ItemOutcome
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.core.context import AppContext
from comicarr.app.downloads import handoff, journal, postprocessing, recovery
from comicarr.app.series import service as series_service
from comicarr.tables import acquisition_run_items, acquisition_runs, comics, issues, metadata, nzblog, pipeline_journal
from tests.fakes import pipeline
from tests.fakes import sabnzbd as sab_fake
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


@pytest.mark.xfail(
    strict=True,
    reason="SABnzbd 5 answers a wrong key with HTTP 403 text, which the probe reads as Reachable: "
    "https://github.com/frankieramirez/comicarr/issues/1260",
)
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
