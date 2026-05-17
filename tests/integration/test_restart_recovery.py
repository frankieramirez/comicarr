#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""U6 — startup recovery replay orchestrator INTEGRATION tests.

A "process restart" is simulated by building durable journal / snatched /
nzblog state on a temp DB (as if a prior process had written it and then
died), wiring fake downloader probes via the U5 ``probes=`` injection seam,
then calling ``recovery.replay_pipeline()`` exactly as ``Comicarr.py`` does
after ``comicarr.start()`` returns. We assert the in-flight item completes
exactly once and lands.

The capstone scenario is AE1 (covers R1/R4/R5): a release journaled
``snatched`` whose external download COMPLETED during the downtime. After
``replay_pipeline()`` the item must be post-processed exactly once.
"""

import json
import threading
import types

import pytest
from sqlalchemy import select

import comicarr
from comicarr.app.downloads import journal, recovery
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import issues, metadata, nzblog, pipeline_journal, snatched


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own temp SQLite DB with the schema auto-created
    (same convention as tests/unit/test_pipeline_journal.py /
    test_recovery_classify.py)."""
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if not hasattr(comicarr, "LOG_LEVEL") or comicarr.LOG_LEVEL is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(HIGHCOUNT=0, SAB_APIKEY="k", SAB_HOST="http://sab.local"),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "DDL_STUCK_NOTIFIED", set(), raising=False)
    monkeypatch.setattr(comicarr, "USE_SABNZBD", True, raising=False)
    monkeypatch.setattr(comicarr, "USE_NZBGET", False, raising=False)
    engine = get_engine()
    metadata.create_all(engine)
    yield
    shutdown_engine()


@pytest.fixture
def fake_pp_queue(monkeypatch):
    """Replace comicarr.PP_QUEUE with a real queue.Queue we can drain and a
    fake postprocess_main consumer that records every (release_key) it would
    post-process — so we can assert PP runs EXACTLY ONCE."""
    import queue as queue_module

    q = queue_module.Queue()
    monkeypatch.setattr(comicarr, "PP_QUEUE", q, raising=False)
    return q


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


def _probe(value):
    return {dt: (lambda row, v=value: v) for dt in ("torrent", "nzb", "sab", "nzbget", "ddl", "DDL")}


# ---------------------------------------------------------------------------
# AE1 — the behavior-activating capstone (write FIRST, watch fail, implement)
# ---------------------------------------------------------------------------


def test_ae1_snatched_then_externally_completed_pp_exactly_once(fake_pp_queue):
    """AE1 (R1/R4/R5): a release journaled `snatched`; its external download
    completed during the downtime (U5 classify -> complete). After
    replay_pipeline() the item is enqueued for PP EXACTLY ONCE with the
    authoritative release_key stamped so the U4 claim advances THIS row."""
    rkey = journal.release_key("500", "nzb.su", nzbname="Batman_010.cbz")
    payload = {
        "issueid": "500",
        "comicid": "C9",
        "provider": "nzb.su",
        "nzbname": "Batman_010.cbz",
        "nzb_name": "Batman_010.cbz",
        "nzb_folder": "/dl/Batman_010",
    }
    # nzblog row is written at snatch and only DELETED on PP success — so an
    # in-flight snatch still has its nzblog row (its absence is the
    # done-signal the history-eviction guard keys on).
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="500", PROVIDER="nzb.su", NZBName="Batman_010.cbz"))
        conn.execute(issues.insert().values(IssueID="500", ComicID="C9", Status="Snatched"))
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload=payload,
        issueid="500",
        provider="nzb.su",
        downloader_type="nzb",
        nzbname="Batman_010.cbz",
    )

    # External download completed while we were down.
    recovery.replay_pipeline(probes=_probe("complete"))

    # Enqueued for PP exactly once.
    items = []
    while not fake_pp_queue.empty():
        items.append(fake_pp_queue.get_nowait())
    assert len(items) == 1, "AE1: expected exactly one PP enqueue, got %d" % len(items)
    pp_item = items[0]
    assert pp_item["journal_release_key"] == rkey
    assert pp_item["issueid"] == "500"

    # Re-running replay must NOT double-enqueue (idempotent / re-runnable):
    # the U4 claim convergence is simulated by advancing the row as the PP
    # consumer would, then asserting a second replay is a no-op.
    journal.record_transition(rkey, journal.POST_PROCESSED)
    recovery.replay_pipeline(probes=_probe("complete"))
    assert fake_pp_queue.empty(), "AE1: completed row must not be re-driven"


# ---------------------------------------------------------------------------
# AE2 — two-marker finalizer (decided ONLY by `moved`, no file probe)
# ---------------------------------------------------------------------------


def test_ae2_moved_finishes_dbfacts_post_processing_redrives(fake_pp_queue, monkeypatch):
    import comicarr.process as process_mod

    # `moved` row: move physically committed, DB facts uncommitted. Finalizer
    # finishes DB facts only — process.Process must NOT be constructed.
    moved_key = journal.release_key("600", "nzb.su", nzbname="M.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="600", PROVIDER="nzb.su"))
    _insert_journal(
        moved_key,
        journal.MOVED,
        payload={"issueid": "600", "provider": "nzb.su"},
        issueid="600",
        provider="nzb.su",
        downloader_type="nzb",
    )

    # `post_processing` row: move did NOT commit, source intact -> re-drive in
    # full via a direct process.Process (NOT via PP_QUEUE).
    pp_key = journal.release_key("601", "nzb.su", nzbname="N.cbz")
    _insert_journal(
        pp_key,
        journal.POST_PROCESSING,
        payload={"issueid": "601", "comicid": "C6", "nzb_name": "N.cbz", "nzb_folder": "/dl/N"},
        issueid="601",
        provider="nzb.su",
        downloader_type="nzb",
    )

    seen = {"moved_reimport": False, "pp_redrive": None}

    class _FakeProc:
        def __init__(self, nzb_name, *a, journal_release_key=None, **k):
            if journal_release_key == moved_key:
                seen["moved_reimport"] = True
            seen["pp_redrive"] = journal_release_key

        def post_process(self):
            return None

    monkeypatch.setattr(process_mod, "Process", _FakeProc)
    recovery.replay_pipeline(probes=_probe("complete"))

    # moved -> DB facts finished (nzblog deleted, journal post_processed), no
    # re-import, no PP enqueue.
    assert seen["moved_reimport"] is False
    assert journal.read_one(moved_key)["stage"] == journal.POST_PROCESSED
    with get_engine().connect() as conn:
        assert conn.execute(select(nzblog).where(nzblog.c.IssueID == "600")).fetchall() == []
    # post_processing -> re-driven in full with the authoritative key.
    assert seen["pp_redrive"] == pp_key
    items = []
    while not fake_pp_queue.empty():
        items.append(fake_pp_queue.get_nowait())
    assert items == [], "post_processing re-drive must be direct, not via PP_QUEUE"


# ---------------------------------------------------------------------------
# Anchor reconstruction (corrected) — full integration
# ---------------------------------------------------------------------------


def test_anchor_reconstruction_drives_to_completion_and_completed_not_redriven(fake_pp_queue):
    # Residual-window release: durable snatched(Snatched) + nzblog, NO journal
    # row, NO Downloaded/Post-Processed sibling -> reconstruct + drive.
    with get_engine().begin() as conn:
        conn.execute(
            snatched.insert().values(
                IssueID="700",
                ComicID="C700",
                ComicName="Series",
                Issue_Number="3",
                Status="Snatched",
                Provider="nzb.su",
            )
        )
        conn.execute(nzblog.insert().values(IssueID="700", PROVIDER="nzb.su"))
        conn.execute(issues.insert().values(IssueID="700", Status="Snatched"))

        # Completed release: live Snatched sibling + Post-Processed sibling,
        # nzblog absent, journal empty -> must NOT reconstruct / re-drive.
        conn.execute(
            snatched.insert().values(
                IssueID="701",
                ComicID="C701",
                ComicName="Series2",
                Issue_Number="4",
                Status="Snatched",
                Provider="nzb.su",
            )
        )
        conn.execute(
            snatched.insert().values(
                IssueID="701",
                ComicID="C701",
                ComicName="Series2",
                Issue_Number="4",
                Status="Post-Processed",
                Provider="nzb.su",
            )
        )
        conn.execute(issues.insert().values(IssueID="701", Status="Post-Processed"))

    summary = recovery.replay_pipeline(probes=_probe("complete"))
    assert summary["reconstructed"] == 1

    rebuilt = journal.read_one(journal.release_key("700", "nzb.su", nzbname=None, hash=None))
    assert rebuilt is not None
    assert journal.read_one(journal.release_key("701", "nzb.su", nzbname=None, hash=None)) is None

    items = []
    while not fake_pp_queue.empty():
        items.append(fake_pp_queue.get_nowait())
    assert len(items) == 1
    assert items[0]["issueid"] == "700"


# ---------------------------------------------------------------------------
# `still` re-enqueue — live monitor re-owns; not double-driven
# ---------------------------------------------------------------------------


def test_still_reenqueue_lets_live_monitor_resume_no_double_drive(fake_pp_queue, monkeypatch):
    import queue as queue_module

    sn_q = queue_module.Queue()
    monkeypatch.setattr(comicarr, "SNATCHED_QUEUE", sn_q, raising=False)

    rkey = journal.release_key("800", "torznab", hash="cafef00d")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="800", PROVIDER="torznab"))
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload={"issueid": "800", "comicid": "C8", "hash": "cafef00d", "provider": "torznab"},
        issueid="800",
        provider="torznab",
        downloader_type="torrent",
        hash="cafef00d",
    )
    recovery.replay_pipeline(probes=_probe("still"))

    # Re-enqueued for the live torrent monitor; NOT post-processed (download
    # still running). The U4 claim + monotonic guard converge any later
    # double-drive to exactly-once at the PP consumer.
    resumed = []
    while not sn_q.empty():
        resumed.append(sn_q.get_nowait())
    assert len(resumed) == 1
    assert resumed[0]["hash"] == "cafef00d"
    assert fake_pp_queue.empty()
    assert journal.read_one(rkey)["stage"] == journal.SNATCHED


# ---------------------------------------------------------------------------
# Concurrency — replay (lock-free) with workers + a SIGTERM halt(): no
# INIT_LOCK deadlock/starvation. We assert replay does NOT acquire INIT_LOCK.
# ---------------------------------------------------------------------------


def test_replay_is_lockfree_concurrent_with_held_init_lock(fake_pp_queue):
    rkey = journal.release_key("900", "nzb.su", nzbname="P.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="900", PROVIDER="nzb.su"))
        conn.execute(issues.insert().values(IssueID="900", Status="Snatched"))
    _insert_journal(
        rkey,
        journal.DOWNLOADED,
        payload={"issueid": "900", "nzb_name": "P.cbz", "nzb_folder": "/dl/P"},
        issueid="900",
        provider="nzb.su",
        downloader_type="nzb",
    )

    done = threading.Event()
    result = {}

    def _run():
        # INIT_LOCK is held by the main thread for the whole replay — if
        # replay tried to acquire it this would block forever and the event
        # would never be set.
        result["summary"] = recovery.replay_pipeline(probes=_probe("complete"))
        done.set()

    with comicarr.INIT_LOCK:
        t = threading.Thread(target=_run)
        t.start()
        finished = done.wait(timeout=10)
        t.join(timeout=5)

    assert finished, "replay blocked while INIT_LOCK was held — it must be lock-free"
    assert result["summary"]["open"] == 1
    items = []
    while not fake_pp_queue.empty():
        items.append(fake_pp_queue.get_nowait())
    assert len(items) == 1
