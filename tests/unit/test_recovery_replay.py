#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""U6 — startup recovery replay orchestrator UNIT tests.

Exercises recovery.replay_pipeline() / recovery.finalize_post_processing()
against a real pipeline_journal on a temp DB, with fake downloader probes via
the U5 `probes=` seam and the five queues replaced by real queue.Queue
instances. Covers every U6 scenario from the plan: anchor reconstruction (and
the completed-not-reconstructed disambiguation), the two-marker finalizer
(decided ONLY by `moved`, no file probe), one-off journal-authoritative,
snapshot-then-recheck skip, AE3 cross-replay exactly-once, AE4 gone->failed,
`still` re-enqueue, monotonic no-op, the per-row error path, empty journal,
and the lock-free (no INIT_LOCK) property.
"""

import json
import queue as queue_module
import types

import pytest
from sqlalchemy import select

import comicarr
from comicarr.app.downloads import journal, recovery, recovery_classify
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import issues, metadata, nzblog, pipeline_journal, snatched


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
def queues(monkeypatch):
    pp = queue_module.Queue()
    sn = queue_module.Queue()
    nz = queue_module.Queue()
    monkeypatch.setattr(comicarr, "PP_QUEUE", pp, raising=False)
    monkeypatch.setattr(comicarr, "SNATCHED_QUEUE", sn, raising=False)
    monkeypatch.setattr(comicarr, "NZB_QUEUE", nz, raising=False)
    return {"pp": pp, "snatched": sn, "nzb": nz}


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


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


def _journal_row(key):
    return journal.read_one(key)


def _probe(value):
    return {dt: (lambda row, v=value: v) for dt in ("torrent", "nzb", "sab", "nzbget", "ddl", "DDL")}


# ---------------------------------------------------------------------------
# Empty journal — fast no-op
# ---------------------------------------------------------------------------


def test_empty_journal_is_noop(queues):
    summary = recovery.replay_pipeline(probes=_probe("complete"))
    assert summary["open"] == 0
    assert summary["reconstructed"] == 0
    assert _drain(queues["pp"]) == []


# ---------------------------------------------------------------------------
# Does NOT acquire INIT_LOCK (no deadlock/starvation vs a SIGTERM halt())
# ---------------------------------------------------------------------------


def test_replay_does_not_acquire_init_lock(queues):
    # Hold INIT_LOCK for the entire replay — if replay tried to acquire it
    # this would deadlock. It must complete lock-free.
    with comicarr.INIT_LOCK:
        summary = recovery.replay_pipeline(probes=_probe("complete"))
    assert summary["open"] == 0


# ---------------------------------------------------------------------------
# COMPLETE -> PP enqueue, journal_release_key stamped (U4 propagation)
# ---------------------------------------------------------------------------


def test_complete_enqueues_pp_with_stamped_key(queues):
    rkey = journal.release_key("10", "nzb.su", nzbname="A.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="10", PROVIDER="nzb.su"))
        conn.execute(issues.insert().values(IssueID="10", Status="Snatched"))
    _insert_journal(
        rkey,
        journal.DOWNLOADED,
        payload={"issueid": "10", "comicid": "C1", "nzb_name": "A.cbz", "nzb_folder": "/dl/A"},
        issueid="10",
        provider="nzb.su",
        downloader_type="nzb",
    )
    recovery.replay_pipeline(probes=_probe("complete"))
    items = _drain(queues["pp"])
    assert len(items) == 1
    assert items[0]["journal_release_key"] == rkey
    assert items[0]["issueid"] == "10"


# ---------------------------------------------------------------------------
# STILL -> re-enqueue onto SNATCHED_QUEUE (torrent) / NZB_QUEUE (sab)
# ---------------------------------------------------------------------------


def test_still_torrent_reenqueued_on_snatched_queue(queues):
    rkey = journal.release_key("20", "torznab", hash="deadbeef")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="20", PROVIDER="torznab"))
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload={"issueid": "20", "comicid": "C2", "hash": "deadbeef", "provider": "torznab"},
        issueid="20",
        provider="torznab",
        downloader_type="torrent",
        hash="deadbeef",
    )
    recovery.replay_pipeline(probes=_probe("still"))
    sn = _drain(queues["snatched"])
    assert len(sn) == 1
    assert sn[0]["hash"] == "deadbeef"
    assert sn[0]["issueid"] == "20"
    assert _drain(queues["pp"]) == []


def test_still_nzb_reenqueued_on_nzb_queue(queues):
    rkey = journal.release_key("21", "nzb.su", nzbname="B.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="21", PROVIDER="nzb.su"))
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload={"issueid": "21", "comicid": "C3", "provider": "nzb.su", "download_info": {"nzo_id": "z21"}},
        issueid="21",
        provider="nzb.su",
        downloader_type="nzb",
    )
    recovery.replay_pipeline(probes=_probe("still"))
    nz = _drain(queues["nzb"])
    assert len(nz) == 1
    assert nz[0]["issueid"] == "21"


# ---------------------------------------------------------------------------
# AE4 — GONE -> failed, NOT enqueued, NOT retried
# ---------------------------------------------------------------------------


def test_ae4_gone_marks_failed_not_enqueued(queues):
    rkey = journal.release_key("30", "nzb.su", nzbname="C.cbz")
    # No done-signal: issue not post-processed, nzblog present, client
    # reachable + absent => GONE.
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="30", Status="Snatched"))
        conn.execute(nzblog.insert().values(IssueID="30", PROVIDER="nzb.su"))
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload={"issueid": "30", "provider": "nzb.su"},
        issueid="30",
        provider="nzb.su",
        downloader_type="nzb",
    )
    recovery.replay_pipeline(probes=_probe("absent"))
    assert _drain(queues["pp"]) == []
    assert _drain(queues["snatched"]) == []
    assert _drain(queues["nzb"]) == []
    row = _journal_row(rkey)
    assert row["stage"] == journal.FAILED
    assert row["fail_reason"] == recovery_classify.FAIL_REASON_GONE


# ---------------------------------------------------------------------------
# UNKNOWN -> stage left unchanged
# ---------------------------------------------------------------------------


def test_unknown_leaves_stage_unchanged(queues):
    rkey = journal.release_key("40", "nzb.su", nzbname="D.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="40", PROVIDER="nzb.su"))
    _insert_journal(
        rkey, journal.SNATCHED, payload={"issueid": "40"}, issueid="40", provider="nzb.su", downloader_type="nzb"
    )
    recovery.replay_pipeline(probes=_probe("unreachable"))
    assert _journal_row(rkey)["stage"] == journal.SNATCHED
    assert _drain(queues["pp"]) == []


# ---------------------------------------------------------------------------
# Two-marker finalizer — decided ONLY by `moved`, no file probe
# ---------------------------------------------------------------------------


def test_finalizer_moved_finishes_dbfacts_only_no_reimport(queues, monkeypatch):
    rkey = journal.release_key("50", "nzb.su", nzbname="E.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="50", PROVIDER="nzb.su"))
    _insert_journal(
        rkey,
        journal.MOVED,
        payload={"issueid": "50", "provider": "nzb.su"},
        issueid="50",
        provider="nzb.su",
        downloader_type="nzb",
    )
    # If the finalizer tried to re-import it would construct process.Process —
    # blow up if that happens for the `moved` path.
    import comicarr.process as process_mod

    def _boom(*a, **k):
        raise AssertionError("moved path must NOT re-import (no process.Process)")

    monkeypatch.setattr(process_mod, "Process", _boom)

    recovery.replay_pipeline(probes=_probe("complete"))

    # nzblog deleted + journal advanced to post_processed (U9 atomic DB-fact).
    assert _journal_row(rkey)["stage"] == journal.POST_PROCESSED
    with get_engine().connect() as conn:
        rem = conn.execute(select(nzblog).where(nzblog.c.IssueID == "50")).fetchall()
    assert rem == []
    assert _drain(queues["pp"]) == []


def test_finalizer_post_processing_redrives_in_full(queues, monkeypatch):
    rkey = journal.release_key("51", "nzb.su", nzbname="F.cbz")
    _insert_journal(
        rkey,
        journal.POST_PROCESSING,
        payload={"issueid": "51", "comicid": "C5", "nzb_name": "F.cbz", "nzb_folder": "/dl/F"},
        issueid="51",
        provider="nzb.su",
        downloader_type="nzb",
    )
    calls = {}
    import comicarr.process as process_mod

    class _FakeProc:
        def __init__(self, nzb_name, nzb_folder, *a, journal_release_key=None, **k):
            calls["nzb_name"] = nzb_name
            calls["rkey"] = journal_release_key

        def post_process(self):
            calls["ran"] = True
            return None

    monkeypatch.setattr(process_mod, "Process", _FakeProc)
    recovery.replay_pipeline(probes=_probe("complete"))
    assert calls.get("ran") is True
    # Authoritative release_key threaded so postprocessor markers advance THIS
    # row (single-derivation invariant).
    assert calls["rkey"] == rkey
    assert calls["nzb_name"] == "F.cbz"
    # NOT routed through PP_QUEUE (the U4 claim would lose on a row already at
    # post_processing).
    assert _drain(queues["pp"]) == []


# ---------------------------------------------------------------------------
# Snapshot-then-RECHECK — a row a live worker advanced is skipped
# ---------------------------------------------------------------------------


def test_recheck_skips_row_advanced_between_snapshot_and_act(queues, monkeypatch):
    rkey = journal.release_key("60", "nzb.su", nzbname="G.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="60", PROVIDER="nzb.su"))
    _insert_journal(
        rkey, journal.SNATCHED, payload={"issueid": "60"}, issueid="60", provider="nzb.su", downloader_type="nzb"
    )

    real_read_open = journal.read_open

    def _read_open_then_advance():
        rows = real_read_open()
        # Simulate a live worker advancing the row AFTER the snapshot read but
        # BEFORE _resolve_row's recheck.
        journal.record_transition(rkey, journal.POST_PROCESSED)
        return rows

    monkeypatch.setattr(journal, "read_open", _read_open_then_advance)
    summary = recovery.replay_pipeline(probes=_probe("complete"))
    # Rechecked stage is terminal -> skipped, no redundant re-enqueue.
    assert _drain(queues["pp"]) == []
    assert summary["actions"].get("skip-terminal", 0) == 1


def test_recheck_skips_when_stage_advanced_not_terminal(queues, monkeypatch):
    rkey = journal.release_key("61", "nzb.su", nzbname="H.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="61", PROVIDER="nzb.su"))
    _insert_journal(
        rkey, journal.SNATCHED, payload={"issueid": "61"}, issueid="61", provider="nzb.su", downloader_type="nzb"
    )
    real_read_open = journal.read_open

    def _read_open_then_advance():
        rows = real_read_open()
        journal.record_transition(rkey, journal.DOWNLOADED)
        return rows

    monkeypatch.setattr(journal, "read_open", _read_open_then_advance)
    summary = recovery.replay_pipeline(probes=_probe("still"))
    assert _drain(queues["snatched"]) == []
    assert summary["actions"].get("skip-advanced", 0) == 1


# ---------------------------------------------------------------------------
# Monotonic — worker advanced to post_processed before replay write -> no-op
# ---------------------------------------------------------------------------


def test_monotonic_replay_write_is_noop_when_worker_finished(queues):
    rkey = journal.release_key("70", "nzb.su", nzbname="I.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="70", PROVIDER="nzb.su"))
        conn.execute(issues.insert().values(IssueID="70", Status="Post-Processed"))
    _insert_journal(
        rkey,
        journal.POST_PROCESSED,
        payload={"issueid": "70"},
        issueid="70",
        provider="nzb.su",
        downloader_type="nzb",
    )
    # post_processed is terminal -> excluded from read_open entirely.
    summary = recovery.replay_pipeline(probes=_probe("complete"))
    assert summary["open"] == 0
    assert _drain(queues["pp"]) == []
    assert _journal_row(rkey)["stage"] == journal.POST_PROCESSED


# ---------------------------------------------------------------------------
# Done-check — Status==Post-Processed -> mark_done, skip
# ---------------------------------------------------------------------------


def test_done_check_marks_done_and_skips(queues):
    rkey = journal.release_key("80", "nzb.su", nzbname="J.cbz")
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="80", Status="Post-Processed"))
    _insert_journal(
        rkey, journal.SNATCHED, payload={"issueid": "80"}, issueid="80", provider="nzb.su", downloader_type="nzb"
    )
    recovery.replay_pipeline(probes=_probe("absent"))
    assert _journal_row(rkey)["stage"] == journal.POST_PROCESSED
    assert _drain(queues["pp"]) == []


# ---------------------------------------------------------------------------
# One-off in-flight — synthetic IssueID, nzblog not matchable, kept open
# ---------------------------------------------------------------------------


def test_oneoff_inflight_not_stranded_as_false_done(queues):
    # Synthetic HIGHCOUNT IssueID (>= 900000): nzblog-presence is advisory
    # only; the row must be classified (still) and re-driven, NOT done-checked
    # into a false-complete.
    rkey = journal.release_key(None, "nzb.su", nzbname="K.cbz", discriminant="disc-K")
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload={"issueid": "900123", "provider": "nzb.su", "download_info": {"nzo_id": "zK"}},
        issueid="900123",
        provider="nzb.su",
        downloader_type="nzb",
    )
    recovery.replay_pipeline(probes=_probe("still"))
    # Kept open + re-driven (re-enqueued), NOT marked done.
    assert _journal_row(rkey)["stage"] == journal.SNATCHED
    assert len(_drain(queues["nzb"])) == 1


# ---------------------------------------------------------------------------
# Per-row error path — one bad row logged + skipped, loop continues, rerunnable
# ---------------------------------------------------------------------------


def test_one_bad_row_skipped_loop_continues_and_is_rerunnable(queues, monkeypatch, capture_logs):
    bad = journal.release_key("90", "nzb.su", nzbname="BAD.cbz")
    good = journal.release_key("91", "nzb.su", nzbname="GOOD.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="90", PROVIDER="nzb.su"))
        conn.execute(nzblog.insert().values(IssueID="91", PROVIDER="nzb.su"))
        conn.execute(issues.insert().values(IssueID="90", Status="Snatched"))
        conn.execute(issues.insert().values(IssueID="91", Status="Snatched"))
    _insert_journal(
        bad,
        journal.DOWNLOADED,
        payload={"issueid": "90", "nzb_name": "BAD.cbz", "nzb_folder": "/dl/BAD"},
        issueid="90",
        provider="nzb.su",
        downloader_type="nzb",
    )
    _insert_journal(
        good,
        journal.DOWNLOADED,
        payload={"issueid": "91", "nzb_name": "GOOD.cbz", "nzb_folder": "/dl/GOOD"},
        issueid="91",
        provider="nzb.su",
        downloader_type="nzb",
    )

    real_classify = recovery_classify.classify
    fail_once = {"done": False}

    def _classify(row, probes=None):
        if row.get("release_key") == bad and not fail_once["done"]:
            fail_once["done"] = True
            raise RuntimeError("boom: simulated bad row")
        return real_classify(row, probes=probes)

    monkeypatch.setattr(recovery_classify, "classify", _classify)
    summary = recovery.replay_pipeline(probes=_probe("complete"))
    # Good row still processed despite the bad row raising.
    pp = _drain(queues["pp"])
    assert any(i["journal_release_key"] == good for i in pp)
    assert summary["actions"].get("error", 0) == 1
    assert "[RECOVERY]" in capture_logs.text

    # Re-run replay: the skipped bad row is re-attempted (now succeeds).
    summary2 = recovery.replay_pipeline(probes=_probe("complete"))
    pp2 = _drain(queues["pp"])
    assert any(i["journal_release_key"] == bad for i in pp2)
    assert summary2["actions"].get("error", 0) == 0


# ---------------------------------------------------------------------------
# AE3 — same release interrupted across TWO replays -> completed exactly once
# ---------------------------------------------------------------------------


def test_ae3_two_replays_complete_exactly_once(queues):
    rkey = journal.release_key("100", "nzb.su", nzbname="L.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="100", PROVIDER="nzb.su"))
        conn.execute(issues.insert().values(IssueID="100", Status="Snatched"))
    _insert_journal(
        rkey,
        journal.DOWNLOADED,
        payload={"issueid": "100", "nzb_name": "L.cbz", "nzb_folder": "/dl/L"},
        issueid="100",
        provider="nzb.su",
        downloader_type="nzb",
    )
    # First replay: enqueues PP once.
    recovery.replay_pipeline(probes=_probe("complete"))
    first = _drain(queues["pp"])
    assert len(first) == 1

    # The PP consumer (U4) wins the claim downloaded -> post_processing, then
    # completes -> post_processed. Simulate that durable progression.
    assert journal.record_transition(rkey, journal.POST_PROCESSING) is True
    journal.record_transition(rkey, journal.POST_PROCESSED)

    # Second replay (process restarted again): row is terminal -> NOT
    # re-driven. Exactly once overall.
    recovery.replay_pipeline(probes=_probe("complete"))
    assert _drain(queues["pp"]) == []


# ---------------------------------------------------------------------------
# Anchor reconstruction — rebuild missing journal row from durable state
# ---------------------------------------------------------------------------


def test_anchor_reconstruct_when_no_advanced_sibling_and_nzblog_present(queues):
    # Durable snatched + nzblog exist, but the strictly-last journal write was
    # lost (no journal row). No Downloaded/Post-Processed sibling -> rebuild.
    with get_engine().begin() as conn:
        conn.execute(
            snatched.insert().values(
                IssueID="200",
                ComicID="C200",
                ComicName="Series",
                Issue_Number="1",
                Status="Snatched",
                Provider="nzb.su",
                Hash=None,
            )
        )
        conn.execute(nzblog.insert().values(IssueID="200", PROVIDER="nzb.su"))
        conn.execute(issues.insert().values(IssueID="200", Status="Snatched"))

    summary = recovery.replay_pipeline(probes=_probe("complete"))
    assert summary["reconstructed"] == 1
    rkey = journal.release_key("200", "nzb.su", nzbname=None, hash=None)
    row = _journal_row(rkey)
    assert row is not None
    # Reconstructed then driven (complete -> PP enqueue).
    assert len(_drain(queues["pp"])) == 1


def test_completed_release_with_live_snatched_sibling_not_reconstructed(queues):
    # A fully-completed release: the original Status='Snatched' row is NEVER
    # deleted (snatched UniqueConstraint keys on IssueID,Status,Provider) and
    # lives forever ALONGSIDE the Post-Processed row. nzblog absent (deleted
    # on PP success), journal empty. Must NOT reconstruct / re-drive.
    with get_engine().begin() as conn:
        conn.execute(
            snatched.insert().values(
                IssueID="201",
                ComicID="C201",
                ComicName="S",
                Issue_Number="1",
                Status="Snatched",
                Provider="nzb.su",
            )
        )
        conn.execute(
            snatched.insert().values(
                IssueID="201",
                ComicID="C201",
                ComicName="S",
                Issue_Number="1",
                Status="Post-Processed",
                Provider="nzb.su",
            )
        )
        conn.execute(issues.insert().values(IssueID="201", Status="Post-Processed"))
        # nzblog absent (PP success deleted it).

    summary = recovery.replay_pipeline(probes=_probe("complete"))
    assert summary["reconstructed"] == 0
    rkey = journal.release_key("201", "nzb.su", nzbname=None, hash=None)
    assert _journal_row(rkey) is None
    assert _drain(queues["pp"]) == []


def test_anchor_already_journaled_not_duplicated(queues):
    # A live Status='Snatched' row whose journal row ALREADY exists -> the
    # residual window does not apply; reconstruction is skipped.
    rkey = journal.release_key("202", "nzb.su", nzbname=None, hash=None)
    with get_engine().begin() as conn:
        conn.execute(
            snatched.insert().values(
                IssueID="202",
                ComicID="C202",
                ComicName="S",
                Issue_Number="1",
                Status="Snatched",
                Provider="nzb.su",
            )
        )
        conn.execute(nzblog.insert().values(IssueID="202", PROVIDER="nzb.su"))
        conn.execute(issues.insert().values(IssueID="202", Status="Snatched"))
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload={"issueid": "202"},
        issueid="202",
        provider="nzb.su",
        downloader_type="nzb",
    )
    summary = recovery.replay_pipeline(probes=_probe("still"))
    assert summary["reconstructed"] == 0
    # The existing (not duplicated) row is still resolved normally.
    assert len(_drain(queues["nzb"])) == 1


# ---------------------------------------------------------------------------
# Startup availability cap — excess inline post_processing re-drives deferred
# ---------------------------------------------------------------------------


def test_post_processing_redrive_capped_per_pass_and_rerun_processes_rest(queues, monkeypatch):
    """A backlog of `post_processing` rows must not run unbounded full inline
    PP before the web server binds: replay caps inline re-drives per pass,
    defers the excess (loud log), and a re-run processes the remainder
    (replay is idempotent/re-runnable)."""
    cap = recovery._MAX_INLINE_PP_REDRIVE_PER_PASS
    total = cap + 3
    keys = []
    for i in range(total):
        rkey = journal.release_key("PPC%d" % i, "nzb.su", nzbname="C%d.cbz" % i)
        keys.append(rkey)
        _insert_journal(
            rkey,
            journal.POST_PROCESSING,
            payload={"issueid": "PPC%d" % i, "comicid": "C1", "nzb_name": "C%d.cbz" % i, "nzb_folder": "/dl/C%d" % i},
            issueid="PPC%d" % i,
            provider="nzb.su",
            downloader_type="nzb",
        )

    processed = []
    import comicarr.process as process_mod

    class _FakeProc:
        def __init__(self, nzb_name, nzb_folder, *a, journal_release_key=None, **k):
            self._rkey = journal_release_key

        def post_process(self):
            processed.append(self._rkey)
            # Mark this row terminal so a re-run does not re-drive it (the
            # finalizer's real C3 block does this; the FakeProc must emulate
            # idempotency so the second pass only picks up the deferred rows).
            journal.mark_done(self._rkey)
            return None

    monkeypatch.setattr(process_mod, "Process", _FakeProc)

    # Pass 1: only `cap` rows re-driven inline; the rest deferred.
    s1 = recovery.replay_pipeline(probes=_probe("complete"))
    assert len(processed) == cap
    assert s1["actions"].get("post_processing-redrive") == cap
    assert s1["actions"].get("skip-pp-cap-deferred") == total - cap

    # Pass 2: the deferred rows now resume and are processed.
    s2 = recovery.replay_pipeline(probes=_probe("complete"))
    assert len(processed) == total
    assert s2["actions"].get("post_processing-redrive") == total - cap
    assert "skip-pp-cap-deferred" not in s2["actions"]
    assert sorted(processed) == sorted(keys)
