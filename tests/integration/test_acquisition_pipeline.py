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
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import comicarr
from comicarr import db
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.acquisition.models import ItemOutcome
from comicarr.app.acquisition.runs import RunLedger
from comicarr.app.core.context import AppContext
from comicarr.app.downloads import handoff, journal, recovery
from comicarr.app.series import service as series_service
from comicarr.tables import acquisition_run_items, acquisition_runs, comics, issues, metadata, nzblog, pipeline_journal


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
    assert recovery.finalize_post_processing(journal.read_one(release_key), payload=payload) == "moved-finish-dbfacts"
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
