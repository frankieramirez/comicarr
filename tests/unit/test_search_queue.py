#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Regression tests for the background search queue worker."""

import queue
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import insert

import comicarr
from comicarr.app.acquisition.maintenance import MaintenanceBlocked, MaintenanceController, ensure_acquisition_schema
from comicarr.app.acquisition.models import ItemOutcome
from comicarr.app.acquisition.runs import MAX_RECOVERY_ATTEMPTS, RunLedger
from comicarr.app.search import service
from comicarr.app.search.commands import (
    enqueue_failed_download_retry,
    enqueue_search_command,
    evaluate_search_candidate,
    replay_search_obligations,
)
from comicarr.app.search.queue import FairSearchQueue
from comicarr.app.series import queries as series_queries
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import annuals, comics, issues, metadata


@pytest.fixture
def acquisition_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    shutdown_engine()
    metadata.create_all(get_engine())
    assert ensure_acquisition_schema(get_engine()).ready
    ledger = RunLedger(get_engine())
    yield ledger
    shutdown_engine()


class _FileCheck:
    def walk_the_walk(self):
        return {"status": False}


class _LeaseContext:
    def __enter__(self):
        return SimpleNamespace(lease_id="test", epoch=0)

    def __exit__(self, *_args):
        return False


class _OpenMaintenance:
    def lease(self, *_args, **_kwargs):
        return _LeaseContext()

    def assert_lease_current(self, _lease):
        return True


def _configure_worker(monkeypatch):
    provider_search = MagicMock()
    monkeypatch.setattr(comicarr, "SEARCHLOCK", threading.Lock())
    monkeypatch.setattr(comicarr, "PACK_ISSUEIDS_DONT_QUEUE", {})
    monkeypatch.setattr(comicarr, "DDL_QUEUED", [])
    monkeypatch.setattr(comicarr, "PP_QUEUE", queue.Queue())
    monkeypatch.setattr(comicarr, "filers", SimpleNamespace(FileHandlers=lambda **_kwargs: _FileCheck()))
    monkeypatch.setattr(comicarr, "search", SimpleNamespace(searchforissue=provider_search))
    monkeypatch.setattr(service.time, "sleep", lambda _seconds: None)
    return provider_search


def _command(issue_id="issue-1"):
    return {"comicid": "comic-1", "issueid": issue_id, "manual": False}


def test_fair_search_queue_prioritizes_operator_work_without_starving_recovery():
    work = FairSearchQueue(interactive_burst=3)
    work.put({**_command("recovered"), "queue_priority": "recovery"})
    for issue_id in ("interactive-1", "interactive-2", "interactive-3", "interactive-4"):
        work.put({**_command(issue_id), "queue_priority": "interactive"})

    assert [work.get_nowait()["issueid"] for _ in range(5)] == [
        "interactive-1",
        "interactive-2",
        "interactive-3",
        "recovered",
        "interactive-4",
    ]


def test_fair_search_queue_services_recovery_during_a_routine_backlog():
    work = FairSearchQueue(interactive_burst=3)
    work.put({**_command("recovered"), "queue_priority": "recovery"})
    for issue_id in ("routine-1", "routine-2", "routine-3", "routine-4"):
        work.put({**_command(issue_id), "queue_priority": "routine"})

    assert [work.get_nowait()["issueid"] for _ in range(4)] == [
        "routine-1",
        "routine-2",
        "routine-3",
        "recovered",
    ]


def test_fair_search_queue_prioritizes_shutdown_after_current_command():
    work = FairSearchQueue()
    work.put({**_command("requeued"), "queue_priority": "interactive"})
    work.put("exit")

    assert work.get_nowait() == "exit"


def test_replayed_search_commands_are_marked_lower_priority(acquisition_ledger):
    acquisition_ledger.create_run("replay-priority", "search", "wanted_scan")
    acquisition_ledger.accept_item(
        "replay-priority",
        "issue",
        "issue-1",
        payload={"comicid": "comic-1", "issueid": "issue-1", "manual": False},
    )
    work = FairSearchQueue()

    assert replay_search_obligations(work_queue=work, ledger=acquisition_ledger) == 1
    assert work.get_nowait()["queue_priority"] == "recovery"
    assert acquisition_ledger.get_item("replay-priority", "issue", "issue-1")["queue_priority"] == "recovery"


def test_replay_counts_each_redrive(acquisition_ledger):
    acquisition_ledger.create_run("replay-count", "search", "wanted_scan")
    acquisition_ledger.accept_item(
        "replay-count",
        "issue",
        "issue-1",
        payload={"comicid": "comic-1", "issueid": "issue-1", "manual": False},
    )

    for expected in (1, 2, 3):
        assert replay_search_obligations(work_queue=FairSearchQueue(), ledger=acquisition_ledger) == 1
        item = acquisition_ledger.get_item("replay-count", "issue", "issue-1")
        assert item["recovery_count"] == expected


def test_replay_quarantines_an_item_that_survives_the_bound(acquisition_ledger):
    """The residue reaper, end to end (#555).

    An item that keeps coming back through replay without ever terminalising
    is stuck, not interrupted. It stops being re-queued and stops counting as
    in-flight work.
    """
    acquisition_ledger.create_run("replay-bound", "search", "wanted_scan")
    acquisition_ledger.accept_item(
        "replay-bound",
        "issue",
        "issue-1",
        payload={"comicid": "comic-1", "issueid": "issue-1", "manual": False},
    )

    for _ in range(MAX_RECOVERY_ATTEMPTS):
        assert replay_search_obligations(work_queue=FairSearchQueue(), ledger=acquisition_ledger) == 1

    work = FairSearchQueue()
    assert replay_search_obligations(work_queue=work, ledger=acquisition_ledger) == 0
    assert work.empty()

    item = acquisition_ledger.get_item("replay-bound", "issue", "issue-1")
    assert item["state"] == ItemOutcome.QUARANTINED.value
    assert item["reason"] == "recovery_attempts_exhausted"
    assert acquisition_ledger.list_recoverable_items("search") == []


def test_unlocked_command_reaches_provider_search_once(monkeypatch):
    provider_search = _configure_worker(monkeypatch)
    work = queue.Queue()
    work.put(_command())
    work.put("exit")

    service.search_queue(work, maintenance=_OpenMaintenance())

    provider_search.assert_called_once_with("issue-1", manual=False, entity_type="issue")


def test_held_lock_requeues_then_processes_one_command(monkeypatch):
    provider_search = _configure_worker(monkeypatch)
    comicarr.SEARCHLOCK.acquire()
    work = queue.Queue()
    work.put(_command())

    second_claim = threading.Event()
    original_get = work.get
    claims = 0

    def tracking_get(*args, **kwargs):
        nonlocal claims
        item = original_get(*args, **kwargs)
        if item != "exit":
            claims += 1
            if claims == 2:
                second_claim.set()
        return item

    monkeypatch.setattr(work, "get", tracking_get)

    def release_lock(_seconds):
        if comicarr.SEARCHLOCK.locked():
            comicarr.SEARCHLOCK.release()

    monkeypatch.setattr(service.time, "sleep", release_lock)

    worker = threading.Thread(
        target=service.search_queue,
        args=(work,),
        kwargs={"maintenance": _OpenMaintenance()},
    )
    worker.start()
    assert second_claim.wait(timeout=1)
    work.put("exit")
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert claims == 2
    provider_search.assert_called_once_with("issue-1", manual=False, entity_type="issue")


def test_malformed_command_does_not_prevent_following_command(monkeypatch):
    provider_search = _configure_worker(monkeypatch)
    work = queue.Queue()
    work.put({"comicid": "comic-1"})
    work.put(_command("issue-2"))
    work.put("exit")

    service.search_queue(work, maintenance=_OpenMaintenance())

    provider_search.assert_called_once_with("issue-2", manual=False, entity_type="issue")


def test_enqueue_persists_obligation_before_queue_handoff(acquisition_ledger):
    class InspectingQueue(queue.Queue):
        def put(self, item, *args, **kwargs):
            persisted = acquisition_ledger.get_item(item["run_id"], "issue", item["issueid"])
            assert persisted["state"] == ItemOutcome.ACCEPTED.value
            super().put(item, *args, **kwargs)

    work = InspectingQueue()

    command = enqueue_search_command(
        _command(),
        trigger="test",
        work_queue=work,
        ledger=acquisition_ledger,
        run_id="search-run",
    )

    assert command.run_id == "search-run"
    assert acquisition_ledger.get_run("search-run")["accepted_count"] == 1


@pytest.mark.parametrize(
    ("annchk", "issue_id", "entity_type"),
    (("no", "issue-1", "issue"), ("yes", "annual-1", "annual")),
)
def test_failed_download_retry_persists_manual_command(acquisition_ledger, annchk, issue_id, entity_type):
    work = queue.Queue()

    command = enqueue_failed_download_retry(
        {
            "comicid": "comic-1",
            "issueid": issue_id,
            "comicname": "Saga",
            "issuenumber": "1",
            "annchk": annchk,
        },
        work_queue=work,
        ledger=acquisition_ledger,
        run_id="failed-download-retry",
    )

    queued = work.get_nowait()
    assert command.entity_type == entity_type
    assert command.manual is True
    assert queued["entity_type"] == entity_type
    assert queued["manual"] is True
    assert acquisition_ledger.get_item("failed-download-retry", entity_type, issue_id)["state"] == "accepted"


def test_fast_worker_terminal_state_does_not_fail_queue_handoff(acquisition_ledger):
    class TerminalizingQueue(queue.Queue):
        def put(self, item, *args, **kwargs):
            if isinstance(item, dict) and item.get("run_id"):
                assert acquisition_ledger.claim_item(item["run_id"], item["entity_type"], item["issueid"])
                acquisition_ledger.record_outcome(
                    item["run_id"], item["entity_type"], item["issueid"], ItemOutcome.SUCCEEDED
                )
            super().put(item, *args, **kwargs)

    command = enqueue_search_command(
        _command(),
        trigger="test",
        work_queue=TerminalizingQueue(),
        ledger=acquisition_ledger,
        run_id="fast-search-run",
    )

    item = acquisition_ledger.get_item(command.run_id, "issue", "issue-1")
    assert item["state"] == ItemOutcome.SUCCEEDED.value


def test_annual_command_retains_its_durable_entity_identity(monkeypatch, acquisition_ledger):
    provider_search = _configure_worker(monkeypatch)
    work = queue.Queue()
    enqueue_search_command(
        {"comicid": "comic-1", "issueid": "annual-1", "annual": True},
        trigger="test",
        work_queue=work,
        ledger=acquisition_ledger,
        run_id="annual-search-run",
    )
    work.put("exit")

    service.search_queue(work, ledger=acquisition_ledger, maintenance=_OpenMaintenance())

    provider_search.assert_called_once_with("annual-1", manual=False, entity_type="annual")
    assert acquisition_ledger.get_item("annual-search-run", "annual", "annual-1") is not None


def test_annual_command_preserves_entity_type_through_worker(monkeypatch):
    provider_search = _configure_worker(monkeypatch)
    captured = {}

    class AnnualFileCheck:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def walk_the_walk(self):
            return {"status": False}

    monkeypatch.setattr(comicarr, "filers", SimpleNamespace(FileHandlers=AnnualFileCheck))
    work = queue.Queue()
    work.put({**_command("annual-1"), "entity_type": "annual"})
    work.put("exit")

    service.search_queue(work, maintenance=_OpenMaintenance())

    assert captured["entity_type"] == "annual"
    provider_search.assert_called_once_with("annual-1", manual=False, entity_type="annual")


def test_explicit_annual_candidate_ignores_same_id_issue(acquisition_ledger):
    with get_engine().begin() as conn:
        conn.execute(comics.insert().values(ComicID="comic-1", Status="Active"))
        conn.execute(
            issues.insert().values(
                IssueID="shared-id",
                ComicID="comic-1",
                Status="Downloaded",
            )
        )
        conn.execute(
            annuals.insert().values(
                IssueID="shared-id",
                ComicID="comic-1",
                Status="Wanted",
                AcquisitionIntent="wanted",
                Deleted=None,
            )
        )

    candidate = series_queries.get_search_candidate_state("shared-id", entity_type="annual")

    assert candidate["LegacyStatus"] == "Wanted"
    assert candidate["AcquisitionIntent"] == "wanted"


def test_active_maintenance_blocks_new_queue_handoff_but_keeps_obligation(acquisition_ledger):
    controller = MaintenanceController(get_engine())
    controller.acquire_fence("owner", "repair-1", reason="repair apply")
    work = queue.Queue()

    with pytest.raises(MaintenanceBlocked):
        enqueue_search_command(
            _command(),
            trigger="test",
            work_queue=work,
            ledger=acquisition_ledger,
            run_id="search-blocked",
            maintenance=controller,
        )

    assert work.empty()
    assert acquisition_ledger.get_item("search-blocked", "issue", "issue-1")["state"] == "accepted"


def test_legacy_queue_item_cannot_bypass_active_maintenance(monkeypatch, acquisition_ledger):
    provider_search = _configure_worker(monkeypatch)
    controller = MaintenanceController(get_engine())
    controller.acquire_fence("owner", "repair-1", reason="repair apply")
    work = queue.Queue()
    work.put(_command())
    original_put = work.put
    sleep = MagicMock()
    monkeypatch.setattr(service.time, "sleep", sleep)

    def stop_before_requeued_item(item, *args, **kwargs):
        original_put("exit")
        original_put(item, *args, **kwargs)

    monkeypatch.setattr(work, "put", stop_before_requeued_item)

    service.search_queue(work, maintenance=controller)

    provider_search.assert_not_called()
    assert work.get_nowait()["issueid"] == "issue-1"
    sleep.assert_called_once_with(5)


def test_durable_maintenance_requeue_uses_attempt_backoff(monkeypatch, acquisition_ledger):
    provider_search = _configure_worker(monkeypatch)
    controller = MaintenanceController(get_engine())
    controller.acquire_fence("owner", "repair-1", reason="repair apply")
    work = queue.Queue()
    acquisition_ledger.create_run("search-backoff", "search", "test")
    acquisition_ledger.accept_item(
        "search-backoff",
        "issue",
        "issue-1",
        payload={"comicid": "comic-1", "issueid": "issue-1", "manual": False},
    )
    work.put({**_command(), "run_id": "search-backoff"})
    original_put = work.put

    def stop_after_requeue(item, *args, **kwargs):
        original_put("exit")
        original_put(item, *args, **kwargs)

    work.put = stop_after_requeue
    sleep = MagicMock()
    monkeypatch.setattr(service.time, "sleep", sleep)

    service.search_queue(work, ledger=acquisition_ledger, maintenance=controller)

    provider_search.assert_not_called()
    assert acquisition_ledger.get_item("search-backoff", "issue", "issue-1")["attempt_count"] == 1
    sleep.assert_called_once_with(5)


def test_replay_resets_running_item_without_count_inflation(acquisition_ledger):
    acquisition_ledger.create_run("search-replay", "search", "test")
    acquisition_ledger.accept_item(
        "search-replay",
        "issue",
        "issue-1",
        payload={"comicid": "comic-1", "issueid": "issue-1", "manual": False},
    )
    assert acquisition_ledger.claim_item("search-replay", "issue", "issue-1") is True
    work = queue.Queue()

    replayed = replay_search_obligations(work_queue=work, ledger=acquisition_ledger)

    assert replayed == 1
    assert work.get_nowait()["run_id"] == "search-replay"
    assert acquisition_ledger.get_item("search-replay", "issue", "issue-1")["state"] == "accepted"
    assert acquisition_ledger.get_run("search-replay")["accepted_count"] == 1


def test_live_duplicate_does_not_reclaim_a_running_search_obligation(monkeypatch, acquisition_ledger):
    provider_search = _configure_worker(monkeypatch)
    acquisition_ledger.create_run("search-running", "search", "test")
    acquisition_ledger.accept_item(
        "search-running",
        "issue",
        "issue-1",
        payload={"comicid": "comic-1", "issueid": "issue-1", "manual": False},
    )
    assert acquisition_ledger.claim_item("search-running", "issue", "issue-1") is True
    work = queue.Queue()
    work.put({**_command(), "run_id": "search-running"})
    work.put("exit")

    service.search_queue(work, ledger=acquisition_ledger, maintenance=_OpenMaintenance())

    provider_search.assert_not_called()
    assert acquisition_ledger.get_item("search-running", "issue", "issue-1")["state"] == "running"


def test_in_progress_result_requeues_same_obligation(monkeypatch, acquisition_ledger):
    provider_search = _configure_worker(monkeypatch)
    provider_search.side_effect = [{"status": "IN PROGRESS"}, {"status": False}]
    work = queue.Queue()
    enqueue_search_command(
        _command(),
        trigger="test",
        work_queue=work,
        ledger=acquisition_ledger,
        run_id="search-in-progress",
    )
    original_put = work.put
    requeues = []

    def put_then_stop(item, *args, **kwargs):
        original_put(item, *args, **kwargs)
        if isinstance(item, dict) and item.get("run_id") == "search-in-progress":
            requeues.append(item)
            original_put("exit")

    monkeypatch.setattr(work, "put", put_then_stop)

    service.search_queue(work, ledger=acquisition_ledger)

    item = acquisition_ledger.get_item("search-in-progress", "issue", "issue-1")
    assert len(requeues) == 1
    assert item["attempt_count"] == 2
    assert item["state"] == ItemOutcome.NO_MATCH.value
    assert acquisition_ledger.get_run("search-in-progress")["accepted_count"] == 1


def test_unknown_provider_result_is_failed_not_no_match(monkeypatch, acquisition_ledger):
    provider_search = _configure_worker(monkeypatch)
    provider_search.return_value = None
    work = queue.Queue()
    enqueue_search_command(
        _command(),
        trigger="test",
        work_queue=work,
        ledger=acquisition_ledger,
        run_id="search-unknown",
    )
    work.put("exit")

    service.search_queue(work, ledger=acquisition_ledger)

    item = acquisition_ledger.get_item("search-unknown", "issue", "issue-1")
    assert item["state"] == ItemOutcome.FAILED.value
    assert item["reason"] == "search returned no explicit outcome"
    assert acquisition_ledger.get_run("search-unknown")["no_match_count"] == 0


@pytest.mark.parametrize(
    ("release_date", "expected", "reason"),
    [
        ("2020-01-01", True, None),
        ("2999-01-01", False, "future"),
        ("0000-00-00", False, "invalid_date"),
    ],
)
def test_search_candidate_uses_shared_release_eligibility(release_date, expected, reason):
    result = evaluate_search_candidate(
        {"LegacyStatus": "Wanted", "AcquisitionIntent": "wanted", "SeriesStatus": "Active"},
        release_date=release_date,
        digital_date=None,
        issue_date=None,
    )

    assert result == {"status": expected, "reason": reason}


@pytest.mark.parametrize(
    ("series_status", "reason"),
    [("Paused", "paused"), ("Ended", "series_inactive")],
)
def test_search_candidate_requires_explicit_active_series(series_status, reason):
    result = evaluate_search_candidate(
        {"LegacyStatus": "Wanted", "AcquisitionIntent": "wanted", "SeriesStatus": series_status},
        release_date="2020-01-01",
        digital_date=None,
        issue_date=None,
    )

    assert result == {"status": False, "reason": reason}


def test_bulk_candidate_state_avoids_per_issue_eligibility_query(monkeypatch):
    from comicarr import search as legacy_search

    lookup = MagicMock(side_effect=AssertionError("bulk candidate should avoid a per-item query"))
    monkeypatch.setattr(series_queries, "get_search_candidate_state", lookup)

    result = legacy_search.searchforissue_checker(
        "issue-1",
        "2020-01-01",
        None,
        None,
        {
            "ComicName": "Absolute Batman",
            "Issue_Number": "1",
            "ComicID": "comic-1",
            "candidate": {
                "LegacyStatus": "Wanted",
                "AcquisitionIntent": "wanted",
                "SeriesStatus": "Active",
            },
        },
    )

    assert result == {"status": True, "reason": None}
    lookup.assert_not_called()


def test_manual_wanted_scan_queues_eligible_backlog_outside_automatic_tier(acquisition_ledger, monkeypatch):
    from comicarr import search as legacy_search

    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            EXTRA_NEWZNABS=[],
            EXTRA_TORZNABS=[],
            ENABLE_DDL=True,
            ENABLE_GETCOMICS=True,
            ENABLE_EXTERNAL_SERVER=False,
            EXPERIMENTAL=False,
            NEWZNAB=False,
            ENABLE_TORRENT_SEARCH=False,
            ENABLE_TORRENTS=False,
            ANNUALS_ON=False,
            FAILED_DOWNLOAD_HANDLING=False,
            FAILED_AUTO=False,
            SEARCH_STORYARCS=False,
        ),
    )
    monkeypatch.setattr(comicarr, "SEARCH_TIER_DATE", "2026-01-01")
    monkeypatch.setattr(comicarr, "SEARCHLOCK", threading.Lock())
    work = queue.Queue()
    monkeypatch.setattr(comicarr, "SEARCH_QUEUE", work)
    with get_engine().begin() as conn:
        conn.execute(
            comics.insert().values(
                ComicID="160294",
                ComicName="Absolute Batman",
                ComicName_Filesafe="Absolute_Batman",
                ComicYear="2024",
                ComicPublisher="DC",
                Status="Active",
                Type="Comic",
            )
        )
        conn.execute(
            issues.insert().values(
                IssueID="old-wanted",
                ComicID="160294",
                ComicName="Absolute Batman",
                Issue_Number="1",
                Status="Wanted",
                AcquisitionIntent="wanted",
                ReleaseDate="2020-01-01",
                DateAdded="2000-01-01",
            )
        )

    result = legacy_search.searchforissue(
        acquisition_run_id="manual-backlog",
        acquisition_trigger="manual_wanted_scan",
    )

    assert result == {
        "status": "QUEUED",
        "queued_count": 1,
        "error_count": 0,
        "run_id": "manual-backlog",
    }
    assert work.get_nowait()["run_id"] == "manual-backlog"
    assert acquisition_ledger.get_run("manual-backlog")["accepted_count"] == 1


@pytest.mark.parametrize(("deleted", "found"), [(None, True), (0, True), (1, False)])
def test_annual_eligibility_treats_null_deleted_as_not_deleted(acquisition_ledger, deleted, found):
    with get_engine().begin() as conn:
        conn.execute(insert(comics).values(ComicID="comic-1", Status="Active"))
        conn.execute(
            insert(annuals).values(
                IssueID="annual-1",
                ComicID="comic-1",
                Status="Wanted",
                AcquisitionIntent="wanted",
                Deleted=deleted,
            )
        )

    candidate = series_queries.get_search_candidate_state("annual-1")

    assert (candidate is not None) is found


def test_startup_replays_search_and_refresh_before_workers(monkeypatch):
    from comicarr import importer
    from comicarr.app.search import commands

    search_replay = MagicMock(return_value=2)
    refresh_replay = MagicMock(return_value=3)
    monkeypatch.setattr(commands, "replay_search_obligations", search_replay)
    monkeypatch.setattr(importer, "replay_refresh_obligations", refresh_replay)

    result = comicarr.replay_acquisition_obligations()

    assert result == {"search": 2, "refresh": 3}
    search_replay.assert_called_once_with(work_queue=comicarr.SEARCH_QUEUE)
    refresh_replay.assert_called_once_with(start_worker=True)
