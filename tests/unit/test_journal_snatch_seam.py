#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""U2 — snatch-seam journal transition tests.

Covers the NZB/torrent snatch seam (updater.foundsearch `down is None`
branch + updater.nzblog) and the DDL snatch seam (service.ddl_downloader
:773). The contract under test:

  * NZB/torrent: the journal `snatched` write is a SEPARATE transaction
    issued STRICTLY LAST — after the standalone snatched/nzblog upserts have
    committed — so a journal failure never rolls back the real snatch and the
    residual window is recoverable by U6 anchor reconstruction.
  * DDL: the `ddl_info status='Downloading'` row + the journal `snatched` row
    are written inside ONE explicit begin() block — atomic, no window.
"""

import queue as queuelib
import types
from unittest.mock import patch

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr import updater
from comicarr.app.downloads import journal, service
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, ddl_info, issues, metadata, nzblog, pipeline_journal, snatched


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own temporary SQLite database (same convention as
    tests/unit/test_pipeline_journal.py)."""
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if not hasattr(comicarr, "LOG_LEVEL") or comicarr.LOG_LEVEL is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    # foundsearch/nzblog touch CONFIG.HIGHCOUNT for one-offs and set
    # GLOBAL_MESSAGES — give them a minimal stub.
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(HIGHCOUNT=0, POST_PROCESSING=False),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "GLOBAL_MESSAGES", None, raising=False)
    engine = get_engine()
    metadata.create_all(engine)
    yield
    shutdown_engine()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _rows(table):
    with get_engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(select(table))]


def _journal_row(key):
    with get_engine().connect() as conn:
        r = conn.execute(select(pipeline_journal).where(pipeline_journal.c.release_key == key)).fetchone()
        return dict(r._mapping) if r else None


def _seed_standard_issue(comicid="C1", issueid="I1"):
    with get_engine().begin() as conn:
        conn.execute(insert(comics).values(ComicID=comicid, ComicName="Saga", ComicYear="2012"))
        conn.execute(
            insert(issues).values(
                IssueID=issueid,
                ComicID=comicid,
                ComicName="Saga",
                Issue_Number="1",
                IssueDate="2012-03-14",
                Status="Wanted",
            )
        )


# ---------------------------------------------------------------------------
# Happy path (NZB) — AE1: journal write strictly AFTER snatched/nzblog commits
# ---------------------------------------------------------------------------


def test_nzb_happy_path_journal_after_snatch_and_nzblog():
    _seed_standard_issue()
    # Snatch seam ordering as it is everywhere in the codebase: nzblog() then
    # foundsearch() (search.py:1679/1707, service.py:1169/1170).
    updater.nzblog("I1", "Saga.001.cbz", "Saga", id="nzbid-1", prov="nzbprov")
    updater.foundsearch("C1", "I1", mode="want", provider="nzbprov", nzbname="Saga.001.cbz")

    # Durable snatch landed.
    snat = _rows(snatched)
    assert len(snat) == 1
    assert snat[0]["Status"] == "Snatched"
    nzl = _rows(nzblog)
    assert len(nzl) == 1
    assert nzl[0]["NZBName"] == "Saga.001.cbz"

    # Journal row written, stage=snatched, with the identity U6 reconstructs.
    rkey = journal.release_key("I1", "nzbprov", nzbname="Saga.001.cbz", hash=None)
    jr = _journal_row(rkey)
    assert jr is not None
    assert jr["stage"] == "snatched"
    assert jr["issueid"] == "I1"
    assert jr["provider"] == "nzbprov"


def test_nzb_journal_write_is_strictly_last_separate_txn():
    """The journal write must be observably ordered AFTER the standalone
    snatched/nzblog upserts have committed (AE1). We assert this by failing
    the journal write: snatched + nzblog must still be durably present."""
    _seed_standard_issue()
    updater.nzblog("I1", "Saga.001.cbz", "Saga", id="nzbid-1", prov="nzbprov")

    boom = RuntimeError("journal down")
    with patch.object(journal, "record_transition", side_effect=boom):
        # Must NOT raise out of foundsearch — a journal failure cannot abort
        # the snatch (the write is separate-LAST, not bundled).
        updater.foundsearch("C1", "I1", mode="want", provider="nzbprov", nzbname="Saga.001.cbz")

    # snatched + nzblog committed independently and survived the journal fail.
    assert len(_rows(snatched)) == 1
    assert _rows(snatched)[0]["Status"] == "Snatched"
    assert len(_rows(nzblog)) == 1
    # No journal row — this is the recoverable residual window for U6.
    assert _rows(pipeline_journal) == []


# ---------------------------------------------------------------------------
# Happy path (torrent auto-snatch) — Hash persisted in payload_json for U6
# ---------------------------------------------------------------------------


def test_torrent_autosnatch_hash_in_payload_for_u6_rebuild():
    _seed_standard_issue(comicid="C2", issueid="I2")
    updater.nzblog("I2", "Some.Torrent", "Saga", id="torid", prov="torznab")
    # Mirrors service.py:1170 — torrent auto-snatch passes hash=.
    updater.foundsearch("C2", "I2", mode="want", provider="torznab", hash="abc123hash")

    rkey = journal.release_key("I2", "torznab", nzbname=None, hash="abc123hash")
    jr = _journal_row(rkey)
    assert jr is not None
    assert jr["stage"] == "snatched"
    assert jr["hash"] == "abc123hash"
    payload = journal.load_payload(jr["payload_json"])
    # U6 must be able to rebuild the SNATCHED_QUEUE item
    # ({"issueid","comicid","hash"}, see search.py:3442).
    assert payload["hash"] == "abc123hash"
    assert payload["issueid"] == "I2"
    assert payload["comicid"] == "C2"


def test_oneoff_uses_collision_resistant_discriminant():
    """A synthetic-HIGHCOUNT one-off (pullwant) keys on a collision-resistant
    discriminant so two distinct one-offs cannot coalesce; the journal row is
    authoritative for these (nzblog-presence advisory only — plan)."""
    updater.nzblog(None, "Oneoff.A.cbz", "PullComic", prov="nzbprov", oneoff=True)
    updater.foundsearch(
        "C9",
        comicarr.CONFIG.HIGHCOUNT,
        mode="pullwant",
        provider="nzbprov",
        comicname="PullComic",
        issuenumber="5",
        nzbname="Oneoff.A.cbz",
    )
    jrows = _rows(pipeline_journal)
    assert len(jrows) == 1
    assert jrows[0]["stage"] == "snatched"
    assert jrows[0]["release_key"].startswith("oneoff|nzbprov|")


# ---------------------------------------------------------------------------
# Integration — anchor reconstruction data conditions (U6 consumes these)
# ---------------------------------------------------------------------------


def test_crash_in_residual_window_leaves_reconstructable_state():
    """Crash injected AFTER snatched/nzblog commit but BEFORE the journal
    write → no journal row, but durable snatched + nzblog rows exist. U6 must
    be able to reconstruct ONLY when there is no Downloaded/Post-Processed
    sibling snatched row AND nzblog is still present."""
    _seed_standard_issue()
    updater.nzblog("I1", "Saga.001.cbz", "Saga", id="nzbid-1", prov="nzbprov")
    with patch.object(journal, "record_transition", side_effect=RuntimeError("crash")):
        updater.foundsearch("C1", "I1", mode="want", provider="nzbprov", nzbname="Saga.001.cbz")

    # The exact data conditions U6's anchor reconstruction keys on:
    assert _rows(pipeline_journal) == []  # journal row missing (the window)
    snat = _rows(snatched)
    assert len(snat) == 1
    assert snat[0]["Status"] == "Snatched"  # live Snatched anchor
    # No Downloaded/Post-Processed sibling for (IssueID, Provider) →
    # reconstruction IS warranted.
    siblings = [
        s
        for s in snat
        if s["IssueID"] == "I1" and s["Provider"] == "nzbprov" and s["Status"] in ("Downloaded", "Post-Processed")
    ]
    assert siblings == []
    assert len(_rows(nzblog)) == 1  # nzblog still present


def test_completed_item_is_not_reconstructed():
    """A completed item keeps its live Snatched row (UniqueConstraint
    IssueID,Status,Provider) alongside a Post-Processed sibling. U6 must NOT
    reconstruct it — assert the sibling-present condition holds."""
    _seed_standard_issue()
    updater.nzblog("I1", "Saga.001.cbz", "Saga", id="nzbid-1", prov="nzbprov")
    with patch.object(journal, "record_transition", side_effect=RuntimeError("crash")):
        updater.foundsearch("C1", "I1", mode="want", provider="nzbprov", nzbname="Saga.001.cbz")

    # Simulate the item having since completed: a Post-Processed sibling row
    # exists for the same (IssueID, Provider).
    with get_engine().begin() as conn:
        conn.execute(
            insert(snatched).values(
                IssueID="I1",
                ComicID="C1",
                ComicName="Saga",
                Issue_Number="1",
                Status="Post-Processed",
                Provider="nzbprov",
            )
        )

    snat = _rows(snatched)
    sibling_done = [
        s
        for s in snat
        if s["IssueID"] == "I1" and s["Provider"] == "nzbprov" and s["Status"] in ("Downloaded", "Post-Processed")
    ]
    # Post-Processed sibling present ⇒ U6 must NOT reconstruct.
    assert len(sibling_done) == 1
    assert _rows(pipeline_journal) == []


# ---------------------------------------------------------------------------
# Integration (DDL atomic) — ddl_downloader:773 begin() block
# ---------------------------------------------------------------------------


def _ddl_item(idv="ddl-1", issueid="DI1"):
    return {
        "id": idv,
        "issueid": issueid,
        "comicid": "DC1",
        "series": "Saga DDL",
        "filename": "Saga.DDL.001.cbz",
        "site": "DDL(GetComics)",
        "link": "http://x/y",
        "mainlink": "http://x",
        "link_type": "GC-Main",
        "resume": None,
        "remote_filesize": 0,
    }


def _run_ddl_once(item):
    """Drive ddl_downloader for exactly one item then make it exit. Binds
    comicarr.DDL_QUEUE to the same local queue so the P1 bounded re-enqueue
    (comicarr.DDL_QUEUE.put on a journal-block failure) is isolated to this
    test and observable (it does NOT leak onto the real global, and a
    re-enqueued item is re-consumed by this same loop)."""
    q = queuelib.Queue()
    q.put(item)
    q.put("exit")
    saved = comicarr.DDL_QUEUE
    comicarr.DDL_QUEUE = q
    try:
        service.ddl_downloader(q)
    finally:
        comicarr.DDL_QUEUE = saved
    return q


def test_ddl_snatch_atomic_rollback_on_journal_failure(monkeypatch, capture_logs):
    """P1-3: failure inside the ddl_downloader snatch begin() block rolls back
    BOTH the status='Downloading' ddl_info row AND the journal row (no
    half-write), AND the ddl_downloader loop SURVIVES (does not propagate the
    raise and permanently kill the DDL worker thread). The item is recoverable
    at startup replay."""
    monkeypatch.setattr(comicarr.DDL_LOCK, "locked", lambda: False, raising=False)

    boom = RuntimeError("journal down inside ddl begin()")
    with patch.object(journal, "record_transition", side_effect=boom):
        # MUST NOT raise out of ddl_downloader — the loop continues and reaches
        # the "exit" sentinel normally (worker thread stays alive).
        _run_ddl_once(_ddl_item())

    # Atomic: NEITHER row may exist (rolled back together).
    assert _rows(ddl_info) == []
    assert _rows(pipeline_journal) == []
    # Loud log, not a silent swallow.
    assert "snatch atomic block failed" in capture_logs.text


def test_ddl_worker_survives_journal_failure_and_processes_next_item(monkeypatch):
    """P1-3: a journal raise on the FIRST item must not kill the worker — a
    SECOND queued item after it is still processed (loop survived)."""
    monkeypatch.setattr(comicarr.DDL_LOCK, "locked", lambda: False, raising=False)

    # Stop the legacy worker right after the (committed) snatch block of the
    # SECOND item so we can assert it was reached.
    class _StopAfterSnatch(Exception):
        pass

    def _boom_gc(*a, **k):
        raise _StopAfterSnatch()

    monkeypatch.setattr(service.getcomics, "GC", _boom_gc)

    call = {"n": 0}
    real_rt = journal.record_transition

    def _flaky(*a, **k):
        call["n"] += 1
        if call["n"] == 1:
            raise RuntimeError("journal down on item 1")
        return real_rt(*a, **k)

    q = queuelib.Queue()
    q.put(_ddl_item(idv="ddl-1", issueid="DI1"))
    q.put(_ddl_item(idv="ddl-2", issueid="DI2"))
    q.put("exit")

    with patch.object(journal, "record_transition", side_effect=_flaky):
        with pytest.raises(_StopAfterSnatch):
            service.ddl_downloader(q)

    # Item 1 rolled back (journal failed); item 2's snatch block committed —
    # proves the loop survived item 1's failure.
    ddl_rows = _rows(ddl_info)
    assert [r["ID"] for r in ddl_rows] == ["ddl-2"]
    jrows = _rows(pipeline_journal)
    assert len(jrows) == 1
    assert jrows[0]["issueid"] == "DI2"


def test_ddl_snatch_atomic_cocommit_success(monkeypatch):
    """On success the ddl_info status='Downloading' row and the journal
    snatched row are committed together inside the one begin() block."""
    monkeypatch.setattr(comicarr.DDL_LOCK, "locked", lambda: False, raising=False)

    # The atomic snatch block runs BEFORE the download dispatch. Make the
    # download dispatch raise a sentinel so the worker stops immediately after
    # the (already committed) snatch block — we only assert the snatch block's
    # co-commit here, not the rest of the legacy worker.
    class _StopAfterSnatch(Exception):
        pass

    def _boom_gc(*a, **k):
        raise _StopAfterSnatch()

    monkeypatch.setattr(service.getcomics, "GC", _boom_gc)

    with pytest.raises(_StopAfterSnatch):
        _run_ddl_once(_ddl_item())

    ddl_rows = _rows(ddl_info)
    assert len(ddl_rows) == 1
    assert ddl_rows[0]["status"] == "Downloading"
    assert ddl_rows[0]["ID"] == "ddl-1"

    rkey = journal.release_key("DI1", "DDL", nzbname="Saga.DDL.001.cbz", hash=None, discriminant="ddl-1")
    jr = _journal_row(rkey)
    assert jr is not None
    assert jr["stage"] == "snatched"
    assert jr["provider"] == "DDL"
    assert jr["downloader_type"] == "ddl"
    payload = journal.load_payload(jr["payload_json"])
    assert payload["id"] == "ddl-1"
    assert payload["ddl"] is True


# ---------------------------------------------------------------------------
# P1-4 — worker_main NOT FOUND: loud log + journal mark_failed, not a silent
# drop. The torrent row is journaled snatched; NOT FOUND must advance it to
# the terminal `failed` stage (recoverable/visible), never leave it stuck.
# ---------------------------------------------------------------------------


def test_worker_main_not_found_marks_failed_not_silent_drop(monkeypatch, capture_logs):
    _seed_standard_issue(comicid="CT", issueid="IT")
    # The torrent was journaled `snatched` by the foundsearch snatch seam.
    updater.nzblog("IT", "T.cbr", "Saga", id="tid", prov="torznab")
    updater.foundsearch("CT", "IT", mode="want", provider="torznab", hash="hh", nzbname="T.cbr")
    snatched_rows = _rows(pipeline_journal)
    assert len(snatched_rows) == 1
    assert snatched_rows[0]["stage"] == "snatched"
    snatch_key = snatched_rows[0]["release_key"]

    def _fake_torrentinfo(torrent_hash=None, download=False, monitor=False):
        return {"snatch_status": "NOT FOUND", "hash": torrent_hash}

    monkeypatch.setattr("comicarr.app.search.service.torrentinfo", _fake_torrentinfo)

    q = queuelib.Queue()
    q.put({"issueid": "IT", "comicid": "CT", "hash": "hh", "provider": "torznab", "nzbname": "T.cbr"})
    q.put("exit")
    service.worker_main(q)

    # Loud log (not silent), and the SAME journal row advanced to failed.
    assert "torrent hash not found in client" in capture_logs.text
    rows = _rows(pipeline_journal)
    assert len(rows) == 1
    assert rows[0]["release_key"] == snatch_key
    assert rows[0]["stage"] == "failed"
    assert rows[0]["fail_reason"] == "torrent_hash_not_in_client"


# ---------------------------------------------------------------------------
# Error path (NZB) — retry-cap failure logs loudly, does not roll back snatch
# ---------------------------------------------------------------------------


def test_nzb_journal_retry_cap_failure_logs_and_keeps_snatch(capture_logs):
    from sqlalchemy.exc import OperationalError

    _seed_standard_issue()
    updater.nzblog("I1", "Saga.001.cbz", "Saga", id="nzbid-1", prov="nzbprov")

    cap_err = OperationalError("locked retries exhausted", None, None)
    with patch.object(journal, "record_transition", side_effect=cap_err):
        updater.foundsearch("C1", "I1", mode="want", provider="nzbprov", nzbname="Saga.001.cbz")

    # Loud error logged, snatch state intact, no journal row.
    assert "Journal snatched transition failed" in capture_logs.text
    assert len(_rows(snatched)) == 1
    assert _rows(snatched)[0]["Status"] == "Snatched"
    assert len(_rows(nzblog)) == 1
    assert _rows(pipeline_journal) == []


# ---------------------------------------------------------------------------
# P1 #3 — DDL begin()-block failure must be RECOVERABLE (bounded requeue),
# not permanently lost. The GetComics DDL path writes ddl_info+DDL_QUEUE.put
# with NO prior journal/foundsearch row, so a rolled-back begin() block leaves
# nothing for replay/_reconstruct_anchors to rescan: the item is lost forever
# unless it is re-enqueued.
# ---------------------------------------------------------------------------


def test_ddl_snatch_failure_reenqueues_item_for_recovery(monkeypatch, capture_logs):
    """A journal raise inside the DDL snatch begin()-block must re-put the item
    onto DDL_QUEUE (genuinely recoverable — idempotent upsert + journal write),
    log loudly, and let the loop survive."""
    monkeypatch.setattr(comicarr.DDL_LOCK, "locked", lambda: False, raising=False)

    boom = RuntimeError("journal down inside ddl begin()")
    item = _ddl_item(idv="ddl-rq", issueid="DRQ1")
    with patch.object(journal, "record_transition", side_effect=boom):
        q = _run_ddl_once(item)

    # Rolled back atomically.
    assert _rows(ddl_info) == []
    assert _rows(pipeline_journal) == []
    # The item was re-enqueued (recoverable), not silently dropped.
    requeued = []
    while not q.empty():
        x = q.get_nowait()
        if x != "exit":
            requeued.append(x)
    assert len(requeued) == 1
    assert requeued[0]["id"] == "ddl-rq"
    assert requeued[0]["_journal_retry"] == 1
    assert "re-enqueued on DDL_QUEUE" in capture_logs.text


def test_ddl_snatch_failure_stops_requeue_after_cap_no_infinite_loop(monkeypatch, capture_logs):
    """A PERSISTENT journal failure must NOT hot-loop forever: after the
    bounded cap is exceeded the item is dropped with a loud system-down error
    and is NOT requeued again."""
    monkeypatch.setattr(comicarr.DDL_LOCK, "locked", lambda: False, raising=False)

    # A drive-controlled queue: qsize() always reports work so the loop never
    # parks in its `time.sleep(5)` idle branch; get() serves the item while
    # one is queued, then serves "exit" so the loop terminates the moment the
    # item is NO LONGER requeued (cap reached). A hard ceiling makes a
    # hot-loop regression FAIL (the assertion) instead of hanging the suite.
    class _DriveQueue:
        def __init__(self, first):
            self._items = [first]
            self.gets = 0

        def qsize(self):
            return 1  # always "has work" so the idle sleep branch is skipped

        def get(self, *a, **k):
            self.gets += 1
            if self.gets > 25:
                return "exit"  # regression backstop — must NOT be reached
            if self._items:
                return self._items.pop(0)
            return "exit"  # nothing requeued => cap stopped the requeue

        def put(self, x):
            self._items.append(x)

        def empty(self):
            return not self._items

    q = _DriveQueue(_ddl_item(idv="ddl-cap", issueid="DCAP"))
    saved = comicarr.DDL_QUEUE
    comicarr.DDL_QUEUE = q
    try:
        with patch.object(journal, "record_transition", side_effect=RuntimeError("DB permanently down")):
            service.ddl_downloader(q)
    finally:
        comicarr.DDL_QUEUE = saved

    # cap = _DDL_JOURNAL_REQUEUE_CAP (3): attempts 1..3 requeue (retry
    # 1,2,3 <= 3), attempt 4 has _journal_retry==4 > cap so it is dropped
    # (NOT requeued) with a loud system-down error. That is 4 gets of the
    # item + 1 "exit" = 5 gets total; the backstop (25) must never trigger.
    assert q.gets <= 25, "ddl_downloader hot-looped (cap did not stop requeueing)"
    assert q.gets == 5
    assert q.empty()  # final attempt was NOT requeued
    assert "exceeded requeue cap" in capture_logs.text
    assert "system down" in capture_logs.text
    assert _rows(ddl_info) == []
    assert _rows(pipeline_journal) == []
