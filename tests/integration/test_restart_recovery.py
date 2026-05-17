#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""U8 — End-to-end acceptance verification: the explicit AE1–AE5 matrix.

Each test below is one origin acceptance example, driven against the
INTEGRATED system: the real ``comicarr.app.downloads.journal`` /
``recovery`` / ``recovery_classify`` modules over a real temp SQLite DB
with the real ``pipeline_journal`` / ``snatched`` / ``nzblog`` tables. A
"process restart" is simulated by building durable journal/snatched/nzblog
state (as if a prior process had written it and then died), then calling
``recovery.replay_pipeline()`` exactly as ``Comicarr.py`` does after
``comicarr.start()`` returns (AE1–AE4), or by driving the real U7 FastAPI
lifespan ordered drain and then a subsequent ``replay_pipeline()`` (AE5).

ONLY the external downloader clients (via the U5 ``probes=`` injection
seam) and the actual ``process.Process`` file-move side effect are faked —
every journal state transition, queue put, ``mark_failed``/``mark_done``
and the exactly-once ``process.Process``/PP invocation count is asserted
against the real production code.

Success Criteria asserted by every test (origin requirements doc):

  * every snatched-but-unfinished issue completes EXACTLY ONCE with no
    manual action;
  * no duplicate download / post-processing results from recovery;
  * an unrecoverable item is always visible as a ``failed`` record,
    never silently dropped.

Traceability: each test names its AE id and the R-/AE- requirement it
covers in its docstring.

  AE1  test_ae1_*                R1/R4/R5  snatched + externally-completed
  AE2  test_ae2_*                R4/R5     PP'd-but-not-recorded (2 markers)
  AE3  test_ae3_*                R3/R5     interrupted across two restarts
  AE4  test_ae4_*                R6        download gone -> failed
  AE5  test_ae5_*                R7/R8     mid-pipeline restart drain
"""

import json
import threading
import types
from unittest.mock import patch

import pytest
from sqlalchemy import select

import comicarr
from comicarr.app.downloads import journal, recovery, recovery_classify
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
    # comicarr.SIGNAL is process-global; the AE5 lifespan-drain test mutates
    # it (restart intent) — isolate every test so it cannot leak.
    saved_signal = getattr(comicarr, "SIGNAL", None)
    comicarr.SIGNAL = None
    engine = get_engine()
    metadata.create_all(engine)
    yield
    comicarr.SIGNAL = saved_signal
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


def _drain(q):
    """Drain a queue.Queue into a list (PP/SNATCHED/NZB enqueue assertions)."""
    items = []
    while not q.empty():
        items.append(q.get_nowait())
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


def _probe(value):
    return {dt: (lambda row, v=value: v) for dt in ("torrent", "nzb", "sab", "nzbget", "ddl", "DDL")}


# ===========================================================================
# AE1 — Covers R1, R4, R5.
# "Given an issue has been snatched and the download completed while Comicarr
#  was stopped, when Comicarr restarts, then the item is post-processed and
#  lands in the library exactly once with no operator action."
# ===========================================================================


def test_ae1_snatched_then_externally_completed_pp_exactly_once(fake_pp_queue):
    """AE1 (R1/R4/R5): a release journaled `snatched`; its external download
    completed during the downtime (U5 classify -> complete). After
    replay_pipeline() the item is enqueued for PP EXACTLY ONCE with the
    authoritative release_key stamped so the U4 claim advances THIS row, and
    a second restart (re-running replay) does NOT double-drive it.

    Exactly-once property: PP_QUEUE put count == 1 on first replay, == 0 on
    the second (the journal terminal-state guard converges)."""
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
    items = _drain(fake_pp_queue)
    assert len(items) == 1, "AE1: expected exactly one PP enqueue, got %d" % len(items)
    pp_item = items[0]
    assert pp_item["journal_release_key"] == rkey
    assert pp_item["issueid"] == "500"

    # Re-running replay (second restart) must NOT double-enqueue
    # (idempotent / re-runnable): the U4 claim convergence is simulated by
    # advancing the row as the PP consumer would, then asserting a second
    # replay is a no-op.
    journal.record_transition(rkey, journal.POST_PROCESSED)
    recovery.replay_pipeline(probes=_probe("complete"))
    assert _drain(fake_pp_queue) == [], "AE1: completed row must not be re-driven"
    assert journal.read_one(rkey)["stage"] == journal.POST_PROCESSED


def test_ae1_anchor_reconstruction_drives_residual_window_completed_not_redriven(fake_pp_queue):
    """AE1 (R1/R4/R5): the U2 residual window — snatch committed durably
    (snatched + nzblog) but the strictly-last journal write was lost, NO
    journal row exists. Replay must reconstruct the anchor and drive the item
    to PP EXACTLY ONCE, while a genuinely-completed release (Post-Processed
    sibling, nzblog gone) must NOT be reconstructed or re-driven.

    Exactly-once / no-silent-drop: reconstructed count == 1, the in-flight
    issue gets exactly one PP enqueue, the completed one zero."""
    with get_engine().begin() as conn:
        # Residual-window release: durable snatched(Snatched) + nzblog, NO
        # journal row, NO Downloaded/Post-Processed sibling -> reconstruct.
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

    items = _drain(fake_pp_queue)
    assert len(items) == 1
    assert items[0]["issueid"] == "700"


def test_ae1_still_downloading_reenqueued_for_live_monitor_no_double_drive(fake_pp_queue, monkeypatch):
    """AE1 (R4/R5): the download was STILL running across the restart. Replay
    reconstructs the payload and re-enqueues it onto SNATCHED_QUEUE so the
    live torrent monitor (whose in-memory tracking did not survive restart)
    re-owns it — it is NOT post-processed (download not done) and NOT
    double-driven (stage stays `snatched`; the U4 claim + monotonic guard
    converge any later double to exactly-once at the PP consumer)."""
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

    resumed = _drain(sn_q)
    assert len(resumed) == 1
    assert resumed[0]["hash"] == "cafef00d"
    assert fake_pp_queue.empty()
    assert journal.read_one(rkey)["stage"] == journal.SNATCHED


# ===========================================================================
# AE2 — Covers R4, R5.
# "Given an item was fully post-processed immediately before a crash but not
#  yet recorded complete, when Comicarr restarts and replays it, then it is
#  recognized as already done and is not post-processed a second time (no
#  duplicate import/move)."
#
# Both C3-window markers, distinguished SOLELY by the `moved` marker (no file
# probe): stage `moved` -> finish DB facts only; stage `post_processing` ->
# re-drive in full (source intact).
# ===========================================================================


def test_ae2_moved_finishes_dbfacts_only_post_processing_redrives_in_full(fake_pp_queue, monkeypatch):
    """AE2 (R4/R5): the two-marker finalizer. A `moved` row (destructive move
    committed, DB facts uncommitted) must finish DB facts ONLY — NO duplicate
    import/move, process.Process must NEVER be constructed for it. A
    `post_processing` row (move did NOT commit, source intact) must re-drive
    PP in full via a DIRECT process.Process (NOT via PP_QUEUE — a row already
    at post_processing would lose the U4 downloaded->post_processing claim).
    The decision is made on the `moved` marker ALONE, with no file probe.

    Exactly-once: process.Process constructed exactly ONCE total, and only
    for the post_processing row's authoritative release_key; the moved row
    reaches terminal post_processed with its nzblog deleted."""
    import comicarr.process as process_mod

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

    pp_key = journal.release_key("601", "nzb.su", nzbname="N.cbz")
    _insert_journal(
        pp_key,
        journal.POST_PROCESSING,
        payload={"issueid": "601", "comicid": "C6", "nzb_name": "N.cbz", "nzb_folder": "/dl/N"},
        issueid="601",
        provider="nzb.su",
        downloader_type="nzb",
    )

    proc_calls = []

    class _FakeProc:
        def __init__(self, nzb_name, *a, journal_release_key=None, **k):
            proc_calls.append(journal_release_key)

        def post_process(self):
            return None

    monkeypatch.setattr(process_mod, "Process", _FakeProc)
    recovery.replay_pipeline(probes=_probe("complete"))

    # `moved` -> DB facts finished (nzblog deleted, journal terminal
    # post_processed), no re-import, no PP enqueue. process.Process was NOT
    # constructed for the moved key.
    assert moved_key not in proc_calls, "AE2: `moved` row must NEVER be re-imported"
    assert journal.read_one(moved_key)["stage"] == journal.POST_PROCESSED
    with get_engine().connect() as conn:
        assert conn.execute(select(nzblog).where(nzblog.c.IssueID == "600")).fetchall() == []

    # `post_processing` -> re-driven in full EXACTLY ONCE with the
    # authoritative key, and NOT via PP_QUEUE.
    assert proc_calls == [pp_key], "AE2: post_processing re-drive must be exactly one direct process.Process"
    assert _drain(fake_pp_queue) == [], "AE2: post_processing re-drive must be direct, not via PP_QUEUE"


def test_ae2_already_post_processed_recognized_done_not_redriven(fake_pp_queue, monkeypatch):
    """AE2 (R4/R5): an item fully post-processed (nzblog already deleted,
    issues.Status == Post-Processed) but the journal still says `snatched`
    (the completion fact was not recorded before the crash). Replay's
    authoritative done-check must recognize it as already complete via the
    history-eviction-safe done-signal, mark_done it, and NOT post-process it
    a second time — even though the downloader probe says `absent` (history
    evicted while down).

    Exactly-once / no duplicate import: zero PP enqueues, zero
    process.Process, journal converges to terminal post_processed."""
    import comicarr.process as process_mod

    proc_calls = []

    class _FakeProc:
        def __init__(self, *a, journal_release_key=None, **k):
            proc_calls.append(journal_release_key)

        def post_process(self):
            return None

    monkeypatch.setattr(process_mod, "Process", _FakeProc)

    rkey = journal.release_key("650", "nzb.su", nzbname="Done.cbz")
    # nzblog ABSENT (deleted on PP success) + issues.Status Post-Processed:
    # authoritative done-signals that survive downloader history eviction.
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="650", ComicID="C65", Status="Post-Processed"))
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload={"issueid": "650", "provider": "nzb.su", "nzb_name": "Done.cbz"},
        issueid="650",
        provider="nzb.su",
        downloader_type="nzb",
    )

    # Downloader says absent (history evicted while down) — done-signal must
    # win, classifying COMPLETE, but the done-check fires first => mark_done.
    recovery.replay_pipeline(probes=_probe("absent"))

    assert _drain(fake_pp_queue) == [], "AE2: already-done item must NOT be re-enqueued for PP"
    assert proc_calls == [], "AE2: already-done item must NOT be re-imported"
    assert journal.read_one(rkey)["stage"] == journal.POST_PROCESSED, "AE2: done item converges to terminal"


# ===========================================================================
# AE3 — Covers R3, R5.
# "Given the same release is snatched and the pipeline is interrupted twice
#  across two restarts, when recovery runs, then the release is completed
#  exactly once and never grabbed or post-processed in duplicate."
# ===========================================================================


def test_ae3_same_release_interrupted_across_two_restarts_completes_exactly_once(fake_pp_queue):
    """AE3 (R3/R5): the SAME release is interrupted twice — two sequential
    replay_pipeline() runs, each simulating a separate process restart.
    Restart #1 replays the `snatched` row and re-enqueues it for PP; the live
    PP consumer then wins the real U4 atomic claim (downloaded ->
    post_processing) and completes it, but the process crashes AGAIN before
    the live `Snatched` row matters. Restart #2 replays the SAME release.
    Because the journal row has advanced past the snapshot stage, replay's
    snapshot-then-recheck guard + the terminal-state guard converge so the
    release is grabbed/post-processed EXACTLY ONCE across BOTH restarts and
    never duplicated.

    Exactly-once property: total PP_QUEUE puts across the two replays == 1;
    once the consumer's atomic claim advances the row, the second restart is
    a no-op (no duplicate grab/PP)."""
    rkey = journal.release_key("550", "nzb.su", nzbname="Flash_001.cbz")
    payload = {
        "issueid": "550",
        "comicid": "C55",
        "provider": "nzb.su",
        "nzb_name": "Flash_001.cbz",
        "nzb_folder": "/dl/Flash_001",
    }
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="550", PROVIDER="nzb.su", NZBName="Flash_001.cbz"))
        conn.execute(issues.insert().values(IssueID="550", ComicID="C55", Status="Snatched"))
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload=payload,
        issueid="550",
        provider="nzb.su",
        downloader_type="nzb",
        nzbname="Flash_001.cbz",
    )

    total_pp = []

    # ---- Restart #1: replay re-enqueues for PP. --------------------------
    recovery.replay_pipeline(probes=_probe("complete"))
    total_pp += _drain(fake_pp_queue)
    assert len(total_pp) == 1, "AE3: restart #1 enqueues the release once"
    assert total_pp[0]["journal_release_key"] == rkey

    # ---- The live PP consumer wins the REAL U4 atomic claim and completes
    # the item; then the process crashes AGAIN (the journal is now terminal,
    # but the never-deleted live `Snatched` row still exists). Replay's
    # COMPLETE branch already advanced the row to `downloaded` before the
    # PP_QUEUE.put, so the consumer's claim is purely downloaded->post_processing.
    assert journal.read_one(rkey)["stage"] == journal.DOWNLOADED
    assert journal.record_transition(rkey, journal.POST_PROCESSING) is True, (
        "AE3: the real downloaded->post_processing atomic claim must succeed once"
    )
    journal.record_transition(rkey, journal.POST_PROCESSED)

    # ---- Restart #2: SAME release replayed again — must be a pure no-op
    # (terminal-state / advanced-stage guard), no duplicate grab/PP. --------
    recovery.replay_pipeline(probes=_probe("complete"))
    total_pp += _drain(fake_pp_queue)

    assert len(total_pp) == 1, "AE3: duplicate PP across two restarts (got %d)" % len(total_pp)
    assert journal.read_one(rkey)["stage"] == journal.POST_PROCESSED

    # ---- A third restart is still a no-op (idempotent, never re-driven). --
    recovery.replay_pipeline(probes=_probe("complete"))
    assert _drain(fake_pp_queue) == [], "AE3: terminal row must never be re-driven on a later restart"
    assert journal.read_one(rkey)["stage"] == journal.POST_PROCESSED


def test_ae3_two_concurrent_pp_threads_only_one_wins_the_atomic_claim():
    """AE3 (R3/R5): the U4 two-thread atomic claim — two PP-pool threads
    dequeue the SAME release_key at stage `downloaded` simultaneously (the
    replay-plus-live-worker convergence case). The real monotonic
    record_transition(downloaded -> post_processing) is a conditional advance;
    EXACTLY ONE thread may win it, the loser is a logged no-op and must NOT
    process. This is the integration-level proof underpinning AE3 exactly-once
    when replay re-enqueues an item a live worker is also handling."""
    rkey = journal.release_key("560", "nzb.su", nzbname="Arrow_001.cbz")
    _insert_journal(
        rkey,
        journal.DOWNLOADED,
        payload={"issueid": "560", "provider": "nzb.su"},
        issueid="560",
        provider="nzb.su",
        downloader_type="nzb",
    )

    barrier = threading.Barrier(2)
    results = {}

    def _claim(name):
        barrier.wait()
        results[name] = journal.record_transition(rkey, journal.POST_PROCESSING)

    t1 = threading.Thread(target=_claim, args=("a",))
    t2 = threading.Thread(target=_claim, args=("b",))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    wins = [k for k, v in results.items() if v is True]
    assert len(wins) == 1, "AE3: exactly one thread may win the downloaded->post_processing claim, got %r" % results
    assert journal.read_one(rkey)["stage"] == journal.POST_PROCESSING


def test_ae3_replay_is_lockfree_concurrent_with_held_init_lock(fake_pp_queue):
    """AE3 (R3/R5): replay must be lock-free (it does NOT acquire INIT_LOCK)
    so a concurrent SIGTERM halt() / a still-held startup lock can never
    deadlock or starve recovery. INIT_LOCK is held by the main thread for the
    whole replay; if replay tried to acquire it the worker would block
    forever and the done event would never be set. Underpins AE3's
    cross-restart convergence (replay always runs to completion)."""
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
        result["summary"] = recovery.replay_pipeline(probes=_probe("complete"))
        done.set()

    with comicarr.INIT_LOCK:
        t = threading.Thread(target=_run)
        t.start()
        finished = done.wait(timeout=10)
        t.join(timeout=5)

    assert finished, "replay blocked while INIT_LOCK was held — it must be lock-free"
    assert result["summary"]["open"] == 1
    items = _drain(fake_pp_queue)
    assert len(items) == 1


# ===========================================================================
# AE4 — Covers R6.
# "Given an item was snatched but the external download no longer exists on
#  restart, when recovery runs, then the item is recorded as failed
#  (distinguishable from complete) rather than retried indefinitely or
#  silently dropped."
# ===========================================================================


def test_ae4_download_gone_recorded_failed_not_retried_not_enqueued(fake_pp_queue, monkeypatch):
    """AE4 (R6): the download is GONE on restart — torrent hash absent from a
    REACHABLE client with NO done-signal. Replay must write a DISTINGUISHABLE
    terminal `failed` journal record with the payload RETAINED and the
    distinguishable fail_reason, and must NOT enqueue it for PP, NOT
    re-enqueue it for the monitor, NOT retry it. The `failed` record must be
    distinguishable from `post_processed` (different terminal stage) so the
    item is visible, never silently dropped.

    Distinguishability: stage == failed != post_processed; fail_reason ==
    recovery_classify.FAIL_REASON_GONE; payload_json preserved; re-running
    replay does NOT re-queue or change the failed row."""
    import queue as queue_module

    sn_q = queue_module.Queue()
    nzb_q = queue_module.Queue()
    monkeypatch.setattr(comicarr, "SNATCHED_QUEUE", sn_q, raising=False)
    monkeypatch.setattr(comicarr, "NZB_QUEUE", nzb_q, raising=False)

    rkey = journal.release_key("404", "torznab", hash="deadbeef")
    gone_payload = {"issueid": "404", "comicid": "C404", "hash": "deadbeef", "provider": "torznab"}
    # nzblog row PRESENT (snatch wrote it; PP never deleted it ⇒ NO
    # done-signal) and NOT a one-off and NO issues.Status row: absent in a
    # reachable client + no done-signal ⇒ authoritatively GONE.
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="404", PROVIDER="torznab"))
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload=gone_payload,
        issueid="404",
        provider="torznab",
        downloader_type="torrent",
        hash="deadbeef",
    )

    recovery.replay_pipeline(probes=_probe("absent"))

    failed_row = journal.read_one(rkey)
    assert failed_row["stage"] == journal.FAILED, "AE4: gone item must be terminal `failed`"
    assert failed_row["stage"] != journal.POST_PROCESSED, "AE4: `failed` MUST be distinguishable from complete"
    assert failed_row["fail_reason"] == recovery_classify.FAIL_REASON_GONE
    # Payload retained for a future manual-retry layer (R9) — never dropped.
    assert json.loads(failed_row["payload_json"])["hash"] == "deadbeef"

    # Not retried / not enqueued anywhere.
    assert _drain(fake_pp_queue) == [], "AE4: gone item must NOT be enqueued for PP"
    assert _drain(sn_q) == [], "AE4: gone item must NOT be re-enqueued for the monitor"
    assert _drain(nzb_q) == []

    # Re-running replay (next restart) leaves the failed terminal row
    # untouched and still does not re-queue — visible, not silently dropped,
    # not retried indefinitely.
    recovery.replay_pipeline(probes=_probe("absent"))
    again = journal.read_one(rkey)
    assert again["stage"] == journal.FAILED
    assert again["fail_reason"] == recovery_classify.FAIL_REASON_GONE
    assert _drain(fake_pp_queue) == []
    assert _drain(sn_q) == []


def test_ae4_transient_outage_is_unknown_not_falsely_failed(fake_pp_queue):
    """AE4 (R6): the boundary the failed-vs-transient distinction protects —
    an UNREACHABLE downloader API at restart (transient outage) must NOT be
    buried as `failed` (that would be silent data loss). Stage is left
    UNCHANGED so the row is reclassified next start; only an authoritatively
    gone result ever writes `failed`. Asserts `failed` is reserved for true
    loss so it stays a trustworthy distinguishable signal for AE4."""
    rkey = journal.release_key("503", "torznab", hash="beefdead")
    # nzblog PRESENT ⇒ no done-signal, so the authoritative done-check does
    # not fire and resolution falls through to classify -> UNKNOWN.
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="503", PROVIDER="torznab"))
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload={"issueid": "503", "hash": "beefdead", "provider": "torznab"},
        issueid="503",
        provider="torznab",
        downloader_type="torrent",
        hash="beefdead",
    )

    recovery.replay_pipeline(probes=_probe("unreachable"))

    row = journal.read_one(rkey)
    assert row["stage"] == journal.SNATCHED, "AE4: transient outage must leave stage UNCHANGED"
    assert row["stage"] != journal.FAILED, "AE4: a transient outage must NEVER be false-failed"
    assert row["fail_reason"] is None
    assert _drain(fake_pp_queue) == []


# ===========================================================================
# AE5 — Covers R7, R8.
# "Given items are mid-pipeline when a restart is initiated, when shutdown
#  runs, then in-flight pipeline-state writes complete before exit and the
#  next startup reads a consistent record."
#
# Integration level: the REAL U7 FastAPI lifespan ordered drain over a real
# journal table, then a subsequent real replay_pipeline() that completes the
# recovered consistent record. (The unit-level shape lives in
# tests/unit/test_shutdown_drain.py::TestAE5InFlightJournal.)
# ===========================================================================


@pytest.mark.asyncio
async def test_ae5_inflight_write_completes_before_dispose_then_replay_finishes(fake_pp_queue):
    """AE5 (R7/R8): an item is mid-pipeline (a worker writing a journal
    transition) when a restart is initiated. Driving the REAL U7 lifespan
    ordered drain: the in-flight journal write MUST land BEFORE
    engine.dispose() (U7 relocated bounded join before dispose). The next
    startup's real journal.read_open() must return a CONSISTENT (non-partial)
    record, and a subsequent real replay_pipeline() must then complete that
    recovered obligation EXACTLY ONCE. Restart intent must survive the drain
    (NOT degrade to a plain stop).

    Real vs faked: real lifespan drain ordering, real journal table + façade,
    real read_open(), real replay_pipeline(); faked = the worker pool object
    (its join() stands in for the worker's synchronous in-flight write) and
    the external downloader probe."""
    import queue as queue_module

    from comicarr.app.core.context import AppContext
    from comicarr.app.main import lifespan

    comicarr.SIGNAL = "restart"  # restart initiated mid-pipeline

    rkey = journal.release_key("4711", "nzb.su", nzbname="Series 001")
    payload = {
        "issueid": "4711",
        "comicid": "C47",
        "provider": "nzb.su",
        "nzb_name": "Series 001",
        "nzb_folder": "/dl/Series_001",
    }
    # Pre-seed an in-flight (snatched) obligation a worker is mid-advancing.
    journal.record_transition(
        rkey,
        journal.SNATCHED,
        payload=payload,
        issueid="4711",
        provider="nzb.su",
        downloader_type="nzb",
        nzbname="Series 001",
    )
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="4711", PROVIDER="nzb.su", NZBName="Series 001"))
        conn.execute(issues.insert().values(IssueID="4711", ComicID="C47", Status="Snatched"))

    write_done = threading.Event()

    class _SlowWorkerPool:
        """The worker finishes its synchronous in-flight journal write while
        the U7 bounded drain waits for it (join == final flush guarantee)."""

        def is_alive(self):
            return not write_done.is_set()

        def join(self, timeout=None):
            journal.record_transition(
                rkey,
                journal.DOWNLOADED,
                payload=payload,
                issueid="4711",
                provider="nzb.su",
                downloader_type="nzb",
            )
            write_done.set()

    dispose_seen = {}
    real_dispose = get_engine().dispose

    def _capture_then_dispose():
        # Snapshot the journal row state AT engine.dispose() time.
        with get_engine().connect() as conn:
            rows = [
                dict(r._mapping)
                for r in conn.execute(select(pipeline_journal).where(pipeline_journal.c.release_key == rkey))
            ]
        dispose_seen["rows"] = rows
        return real_dispose()

    ctx = AppContext(
        scheduler=None,
        snatched_queue=queue_module.Queue(),
        nzb_queue=queue_module.Queue(),
        pp_queue=queue_module.Queue(),
        search_queue=queue_module.Queue(),
        ddl_queue=queue_module.Queue(),
    )
    ctx.ai_async_client = None
    ctx.cv_session = None

    from unittest.mock import MagicMock

    app = MagicMock()
    app.state = MagicMock()
    cm = lifespan(app)
    pool = _SlowWorkerPool()
    with (
        patch("comicarr.app.main._build_context_from_globals", return_value=ctx),
        patch.object(comicarr, "SNPOOL", pool, create=True),
        patch.object(comicarr, "NZBPOOL", None, create=True),
        patch.object(comicarr, "SEARCHPOOL", None, create=True),
        patch.object(comicarr, "PPPOOL", None, create=True),
        patch.object(comicarr, "DDLPOOL", None, create=True),
        patch.object(get_engine(), "dispose", side_effect=_capture_then_dispose),
    ):
        await cm.__aenter__()
        await cm.__aexit__(None, None, None)

    # 1. The in-flight write landed BEFORE engine.dispose() (U7 ordering).
    assert dispose_seen["rows"], "AE5: in-flight journal write must precede engine.dispose()"
    assert dispose_seen["rows"][0]["stage"] == journal.DOWNLOADED

    # 2. Next startup reads a CONSISTENT, non-partial record.
    new_engine = get_engine()
    metadata.create_all(new_engine)
    open_rows = journal.read_open()
    match = [r for r in open_rows if r["release_key"] == rkey]
    assert len(match) == 1, "AE5: next startup must read exactly one consistent open record"
    assert match[0]["stage"] == journal.DOWNLOADED
    assert match[0]["issueid"] == "4711"

    # 3. Restart intent survived the full drain (NOT clobbered to shutdown).
    assert comicarr.SIGNAL == "restart"

    # 4. The subsequent real replay_pipeline() completes the recovered
    #    obligation EXACTLY ONCE (no manual action, no silent drop).
    recovery.replay_pipeline(probes=_probe("complete"))
    items = _drain(fake_pp_queue)
    assert len(items) == 1, "AE5: recovered record must be driven to PP exactly once"
    assert items[0]["journal_release_key"] == rkey
    assert items[0]["issueid"] == "4711"
