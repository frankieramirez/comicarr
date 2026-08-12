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
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.attention import RecordOutcome
from comicarr.app.downloads import journal, recovery, recovery_classify
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import ddl_info, issues, metadata, nzblog, pipeline_journal, snatched, storyarcs


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
            MANUAL_PP_FOLDER=str(tmp_path),
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "DDL_STUCK_NOTIFIED", set(), raising=False)
    monkeypatch.setattr(comicarr, "ACQUISITION_WORKERS_BLOCKED", False, raising=False)
    monkeypatch.setattr(comicarr, "ACQUISITION_BLOCK_REASON", None, raising=False)
    monkeypatch.setattr(comicarr, "USE_SABNZBD", True, raising=False)
    monkeypatch.setattr(comicarr, "USE_NZBGET", False, raising=False)
    engine = get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready
    yield
    shutdown_engine()


@pytest.fixture
def queues(monkeypatch):
    pp = queue_module.Queue()
    sn = queue_module.Queue()
    nz = queue_module.Queue()
    dl = queue_module.Queue()
    monkeypatch.setattr(comicarr, "PP_QUEUE", pp, raising=False)
    monkeypatch.setattr(comicarr, "SNATCHED_QUEUE", sn, raising=False)
    monkeypatch.setattr(comicarr, "NZB_QUEUE", nz, raising=False)
    monkeypatch.setattr(comicarr, "DDL_QUEUE", dl, raising=False)
    return {"pp": pp, "snatched": sn, "nzb": nz, "ddl": dl}


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
    return {dt: (lambda row, v=value: v) for dt in ("torrent", "nzb", "sab", "sabnzbd", "nzbget", "ddl", "DDL")}


def _artifact_folder(tmp_path, name):
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    return str(folder)


# ---------------------------------------------------------------------------
# Empty journal — fast no-op
# ---------------------------------------------------------------------------


def test_empty_journal_is_noop(queues):
    summary = recovery.replay_pipeline(probes=_probe("complete"))
    assert summary["open"] == 0
    assert summary["reconstructed"] == 0
    assert _drain(queues["pp"]) == []


def test_startup_replay_is_a_noop_while_acquisition_workers_are_fenced(queues, monkeypatch):
    monkeypatch.setattr(comicarr, "ACQUISITION_WORKERS_BLOCKED", True)
    monkeypatch.setattr(comicarr, "ACQUISITION_BLOCK_REASON", "persistent_maintenance")

    summary = recovery.replay_pipeline(probes=_probe("complete"))

    assert summary["actions"] == {"blocked": 1}
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


def test_complete_enqueues_pp_with_stamped_key(queues, tmp_path):
    rkey = journal.release_key("10", "nzb.su", nzbname="A.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="10", PROVIDER="nzb.su"))
        conn.execute(issues.insert().values(IssueID="10", Status="Snatched"))
    _insert_journal(
        rkey,
        journal.DOWNLOADED,
        payload={
            "issueid": "10",
            "comicid": "C1",
            "nzb_name": "A.cbz",
            "nzb_folder": _artifact_folder(tmp_path, "A"),
        },
        issueid="10",
        provider="nzb.su",
        downloader_type="nzb",
    )
    recovery.replay_pipeline(probes=_probe("complete"))
    items = _drain(queues["pp"])
    assert len(items) == 1
    assert items[0]["journal_release_key"] == rkey
    assert items[0]["issueid"] == "10"


def test_downloaded_with_valid_artifact_command_skips_downloader_probe(queues, tmp_path):
    rkey = journal.release_key("direct-pp", "nzb.su")
    _insert_journal(
        rkey,
        journal.DOWNLOADED,
        payload={
            "issueid": "direct-pp",
            "comicid": "comic-1",
            "nzb_name": "Direct.cbz",
            "nzb_folder": _artifact_folder(tmp_path, "Direct"),
        },
        issueid="direct-pp",
        provider="nzb.su",
        downloader_type="nzb",
    )

    def must_not_probe(*args, **kwargs):
        raise AssertionError("downloaded artifacts are already accepted for PP")

    recovery.replay_pipeline(probes={"nzb": must_not_probe})

    items = _drain(queues["pp"])
    assert len(items) == 1
    assert items[0]["journal_release_key"] == rkey


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


def test_still_sab_rebuilds_monitor_shape_with_current_secret_in_memory_only(queues):
    rkey = journal.release_key("sab-restart", "nzb.su")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="sab-restart", PROVIDER="nzb.su"))
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload={
            "issueid": "sab-restart",
            "comicid": "comic-1",
            "provider": "nzb.su",
            "route": "sabnzbd",
            "nzo_id": "sab-job-restart",
            "download_info": {"provider": "nzb.su", "id": "provider-result"},
        },
        issueid="sab-restart",
        provider="nzb.su",
        downloader_type="sabnzbd",
    )

    recovery.replay_pipeline(probes=_probe("still"))

    item = _drain(queues["nzb"])[0]
    assert item["nzo_id"] == "sab-job-restart"
    assert item["journal_release_key"] == rkey
    assert item["clientmode"] == "sabnzbd"
    assert item["queue"]["apikey"] == "k"
    persisted = journal.load_payload(journal.read_one(rkey)["payload_json"])
    assert "queue" not in persisted
    assert "apikey" not in str(persisted).lower()


def test_legacy_ddl_downloading_without_exact_anchor_becomes_manual_review(queues):
    with get_engine().begin() as conn:
        conn.execute(
            ddl_info.insert().values(
                ID="legacy-ddl",
                issueid="legacy-issue",
                comicid="legacy-comic",
                filename="Legacy.cbz",
                status="Downloading",
            )
        )

    summary = recovery.replay_pipeline(probes=_probe("still"))

    assert summary["legacy_ddl_review"] == 1
    row = journal.read_one(journal.release_key("legacy-issue", "DDL", discriminant="legacy-ddl"))
    assert row["stage"] == journal.MANUAL_REVIEW
    with get_engine().connect() as conn:
        durable = conn.execute(select(ddl_info).where(ddl_info.c.ID == "legacy-ddl")).mappings().one()
    assert durable["status"] == "Manual Review"


# ---------------------------------------------------------------------------
# DDL `still` is quarantined after restart because the direct sender has no
# durable acceptance identity and cannot be safely replayed.
# ---------------------------------------------------------------------------


def test_still_ddl_is_quarantined_without_duplicate_sender_call(queues):
    rkey = journal.release_key("40", "DDL", nzbname="Saga.DDL.cbz", discriminant="ddl-9")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="40", PROVIDER="DDL"))
        conn.execute(issues.insert().values(IssueID="40", ComicID="C4", Status="Snatched"))
        conn.execute(
            ddl_info.insert().values(
                ID="ddl-9",
                issueid="40",
                comicid="C4",
                filename="Saga.DDL.cbz",
                status="Downloading",
            )
        )
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload={
            "issueid": "40",
            "comicid": "C4",
            "provider": "DDL",
            "id": "ddl-9",
            "series": "Saga DDL",
            "filename": "Saga.DDL.cbz",
            "ddl": True,
        },
        issueid="40",
        provider="DDL",
        downloader_type="ddl",
    )
    recovery.replay_pipeline(probes=_probe("still"))
    dl = _drain(queues["ddl"])
    assert dl == []
    attention_row = journal.read_one(rkey)
    assert attention_row["stage"] == journal.MANUAL_REVIEW
    assert attention_row["fail_reason"] == "ambiguous_ddl_acceptance_after_restart"
    with get_engine().connect() as conn:
        issue = conn.execute(select(issues).where(issues.c.IssueID == "40")).mappings().one()
        durable = conn.execute(select(ddl_info).where(ddl_info.c.ID == "ddl-9")).mappings().one()
    assert issue["Status"] == "Wanted"
    assert durable["status"] == "Manual Review"
    assert _drain(queues["nzb"]) == []
    assert _drain(queues["snatched"]) == []


# ---------------------------------------------------------------------------
# P2-5(b) — DDL `complete` rebuilds a PP item with non-None nzb paths
# ---------------------------------------------------------------------------


def test_complete_ddl_rebuilds_pp_item_with_paths(queues, tmp_path):
    rkey = journal.release_key("41", "DDL", nzbname="Saga.DDL.041.cbz", discriminant="ddl-11")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="41", PROVIDER="DDL"))
        conn.execute(issues.insert().values(IssueID="41", Status="Snatched"))
    # The enriched ddlc_payload (P2-5b) carries nzb_folder/nzb_name.
    artifact_folder = _artifact_folder(tmp_path, "Saga.DDL.041")
    _insert_journal(
        rkey,
        journal.DOWNLOADED,
        payload={
            "issueid": "41",
            "comicid": "C5",
            "provider": "DDL",
            "id": "ddl-11",
            "ddl": True,
            "nzb_folder": artifact_folder,
            "nzb_name": "Saga.DDL.041.cbz",
            "download_info": {"provider": "DDL", "id": "ddl-11"},
        },
        issueid="41",
        provider="DDL",
        downloader_type="ddl",
    )
    recovery.replay_pipeline(probes=_probe("complete"))
    items = _drain(queues["pp"])
    assert len(items) == 1
    assert items[0]["nzb_folder"] == artifact_folder
    assert items[0]["nzb_name"] == "Saga.DDL.041.cbz"
    assert items[0]["nzb_folder"] is not None and items[0]["nzb_name"] is not None
    assert items[0]["journal_release_key"] == rkey


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


def test_apply_verdict_lost_transition_reports_no_write_and_makes_no_claim(monkeypatch):
    """A lost journal transition is not a write. apply_verdict() must report
    False (its docstring: "Returns True iff a journal write occurred") and must
    NOT log the blocklisted/re-wanted claim for work another writer did."""
    rkey = journal.release_key("31", "nzb.su", nzbname="L.cbz")
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload={"issueid": "31", "provider": "nzb.su"},
        issueid="31",
        provider="nzb.su",
        downloader_type="nzb",
    )
    row = _journal_row(rkey)

    monkeypatch.setattr(
        recovery_classify,
        "record",
        lambda entry, conn=None: RecordOutcome(
            transition_won=False,
            base_reason=recovery_classify.FAIL_REASON_GONE,
            actionable=True,
            reconciliation="noop",
        ),
    )
    warnings = []
    monkeypatch.setattr(recovery_classify.logger, "warn", lambda message: warnings.append(message))

    assert recovery_classify.apply_verdict(row, recovery_classify.GONE) is False
    assert not any("release blocklisted and" in message for message in warnings)


def test_apply_verdict_won_transition_reports_write_and_makes_the_claim(monkeypatch):
    """The winner of the transition does report True and does make the claim."""
    rkey = journal.release_key("32", "nzb.su", nzbname="W.cbz")
    _insert_journal(
        rkey,
        journal.SNATCHED,
        payload={"issueid": "32", "provider": "nzb.su"},
        issueid="32",
        provider="nzb.su",
        downloader_type="nzb",
    )
    row = _journal_row(rkey)

    warnings = []
    monkeypatch.setattr(recovery_classify.logger, "warn", lambda message: warnings.append(message))

    assert recovery_classify.apply_verdict(row, recovery_classify.GONE) is True
    assert any("release blocklisted and" in message for message in warnings)


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


def test_finalizer_post_processing_redrives_in_full(queues, monkeypatch, tmp_path):
    rkey = journal.release_key("51", "nzb.su", nzbname="F.cbz")
    _insert_journal(
        rkey,
        journal.POST_PROCESSING,
        payload={
            "issueid": "51",
            "comicid": "C5",
            "nzb_name": "F.cbz",
            "nzb_folder": _artifact_folder(tmp_path, "F"),
        },
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


def test_one_bad_row_skipped_loop_continues_and_is_rerunnable(queues, monkeypatch, capture_logs, tmp_path):
    bad = journal.release_key("90", "nzb.su", nzbname="BAD.cbz")
    good = journal.release_key("91", "nzb.su", nzbname="GOOD.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="90", PROVIDER="nzb.su"))
        conn.execute(nzblog.insert().values(IssueID="91", PROVIDER="nzb.su"))
        conn.execute(issues.insert().values(IssueID="90", Status="Snatched"))
        conn.execute(issues.insert().values(IssueID="91", Status="Snatched"))
    _insert_journal(
        bad,
        journal.SNATCHED,
        payload={"issueid": "90", "provider": "nzb.su", "nzo_id": "bad-90", "route": "sabnzbd"},
        issueid="90",
        provider="nzb.su",
        downloader_type="nzb",
    )
    _insert_journal(
        good,
        journal.DOWNLOADED,
        payload={
            "issueid": "91",
            "nzb_name": "GOOD.cbz",
            "nzb_folder": _artifact_folder(tmp_path, "GOOD"),
        },
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


def test_ae3_two_replays_complete_exactly_once(queues, tmp_path):
    rkey = journal.release_key("100", "nzb.su", nzbname="L.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="100", PROVIDER="nzb.su"))
        conn.execute(issues.insert().values(IssueID="100", Status="Snatched"))
    _insert_journal(
        rkey,
        journal.DOWNLOADED,
        payload={
            "issueid": "100",
            "nzb_name": "L.cbz",
            "nzb_folder": _artifact_folder(tmp_path, "L"),
        },
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


def test_post_processing_redrive_capped_per_pass_and_rerun_processes_rest(queues, monkeypatch, tmp_path):
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
            payload={
                "issueid": "PPC%d" % i,
                "comicid": "C1",
                "nzb_name": "C%d.cbz" % i,
                "nzb_folder": _artifact_folder(tmp_path, "C%d" % i),
            },
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


# ---------------------------------------------------------------------------
# Story-arc nzblog "S"+IssueArcID vs plain issueid (P1 #2)
# ---------------------------------------------------------------------------
#
# updater.nzblog() stores story-arc rows with IssueID = "S" + str(IssueArcID),
# while the snatched table / journal use the un-prefixed IssueArcID. Recovery
# must match EITHER form or it silently drops in-flight story-arc obligations
# (anchor reconstruction, _nzblog_present presence gate) and orphans story-arc
# nzblog rows on finalize.


def test_anchor_reconstruct_story_arc_nzblog_S_prefixed(queues):
    """In-flight story-arc obligation: snatched IssueID=IssueArcID, nzblog
    IssueID="S"+IssueArcID (same PROVIDER), NO journal row. Anchor
    reconstruction must REBUILD it (not skip it as nzblog-absent/done) and the
    rebuilt row must carry the durable NZBName from the "S"-prefixed nzblog
    row."""
    arcid = "300"  # below HIGHCOUNT floor -> NOT a synthetic one-off
    with get_engine().begin() as conn:
        conn.execute(
            snatched.insert().values(
                IssueID=arcid,
                ComicID="C300",
                ComicName="Arc Series",
                Issue_Number="1",
                Status="Snatched",
                Provider="nzb.su",
                Hash=None,
            )
        )
        # Story-arc nzblog row is "S"-prefixed and carries the durable name.
        conn.execute(
            nzblog.insert().values(
                IssueID="S" + arcid,
                PROVIDER="nzb.su",
                NZBName="Arc.Issue.001.cbz",
                SARC="My Story Arc",
            )
        )
        conn.execute(issues.insert().values(IssueID=arcid, Status="Snatched"))
        # Durable story-arc discriminator: updater.foundsearch ALWAYS upserts
        # a storyarcs row keyed IssueArcID for a story-arc snatch, and the
        # snatched IssueID IS that IssueArcID — this is what makes the row a
        # *real* story-arc obligation (so the "S"+id nzblog arm is scoped to
        # arcs only and a plain/arc id collision cannot occur).
        conn.execute(storyarcs.insert().values(IssueArcID=arcid, StoryArc="My Story Arc"))

    summary = recovery.replay_pipeline(probes=_probe("still"))
    assert summary["reconstructed"] == 1
    rkey = journal.release_key(arcid, "nzb.su", nzbname="Arc.Issue.001.cbz", hash=None)
    row = _journal_row(rkey)
    assert row is not None, "story-arc obligation was NOT reconstructed (S-prefix miss)"
    # The durable NZBName came from the "S"-prefixed nzblog row, so a STILL
    # re-drive has a usable name.
    payload = journal.load_payload(row.get("payload_json"))
    assert payload.get("nzbname") == "Arc.Issue.001.cbz"


def test_anchor_reconstruct_plain_issue_still_works_regression(queues):
    """Regression guard for P1 #2: a plain (non-arc) issue whose nzblog row is
    the un-prefixed IssueID must still reconstruct exactly as before."""
    with get_engine().begin() as conn:
        conn.execute(
            snatched.insert().values(
                IssueID="301",
                ComicID="C301",
                ComicName="Plain Series",
                Issue_Number="1",
                Status="Snatched",
                Provider="nzb.su",
                Hash=None,
            )
        )
        conn.execute(nzblog.insert().values(IssueID="301", PROVIDER="nzb.su", NZBName="Plain.001.cbz"))
        conn.execute(issues.insert().values(IssueID="301", Status="Snatched"))

    summary = recovery.replay_pipeline(probes=_probe("still"))
    assert summary["reconstructed"] == 1
    rkey = journal.release_key("301", "nzb.su", nzbname="Plain.001.cbz", hash=None)
    assert _journal_row(rkey) is not None


def test_nzblog_present_matches_S_prefixed_story_arc():
    """_nzblog_present must answer True for a story-arc obligation whose
    nzblog row is "S"+IssueArcID — otherwise the anchor-skip presence gate
    reads "nzblog absent => PP done" and silently drops the in-flight arc."""
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="S302", PROVIDER="nzb.su"))
    assert recovery_classify._nzblog_present("302", "nzb.su", story_arc=True) is True
    # Plain issueid still matched (regression).
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="303", PROVIDER="nzb.su"))
    assert recovery_classify._nzblog_present("303", "nzb.su") is True
    # Genuinely absent stays absent.
    assert recovery_classify._nzblog_present("999", "nzb.su") is False


def test_finalizer_moved_deletes_S_prefixed_story_arc_nzblog(queues, monkeypatch):
    """finalize_post_processing on a `moved` story-arc row must delete the
    "S"+IssueArcID nzblog row (PROVIDER-scoped) — not orphan it."""
    arcid = "304"
    rkey = journal.release_key(arcid, "nzb.su", nzbname="Arc.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="S" + arcid, PROVIDER="nzb.su", SARC="Arc"))
        # Real story-arc obligation: storyarcs row keyed IssueArcID == the
        # journal/snatched IssueID (the durable arc discriminator).
        conn.execute(storyarcs.insert().values(IssueArcID=arcid, StoryArc="Arc"))
    _insert_journal(
        rkey,
        journal.MOVED,
        payload={"issueid": arcid, "provider": "nzb.su", "mode": "story_arc"},
        issueid=arcid,
        provider="nzb.su",
        downloader_type="nzb",
    )
    import comicarr.process as process_mod

    def _boom(*a, **k):
        raise AssertionError("moved path must NOT re-import")

    monkeypatch.setattr(process_mod, "Process", _boom)

    recovery.replay_pipeline(probes=_probe("complete"))

    assert _journal_row(rkey)["stage"] == journal.POST_PROCESSED
    with get_engine().connect() as conn:
        rem = conn.execute(select(nzblog).where(nzblog.c.IssueID == "S" + arcid)).fetchall()
    assert rem == [], "S-prefixed story-arc nzblog row leaked on finalize"


def test_finalizer_moved_deletes_plain_nzblog_regression(queues, monkeypatch):
    """Regression guard: the `moved` finalizer still deletes a plain
    (un-prefixed) nzblog row."""
    rkey = journal.release_key("305", "nzb.su", nzbname="P.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="305", PROVIDER="nzb.su"))
    _insert_journal(
        rkey,
        journal.MOVED,
        payload={"issueid": "305", "provider": "nzb.su"},
        issueid="305",
        provider="nzb.su",
        downloader_type="nzb",
    )
    import comicarr.process as process_mod

    monkeypatch.setattr(process_mod, "Process", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no reimport")))

    recovery.replay_pipeline(probes=_probe("complete"))

    assert _journal_row(rkey)["stage"] == journal.POST_PROCESSED
    with get_engine().connect() as conn:
        rem = conn.execute(select(nzblog).where(nzblog.c.IssueID == "305")).fetchall()
    assert rem == []


# ---------------------------------------------------------------------------
# Adversarial plain/arc id collision (round-2 correctness completion of #2)
# ---------------------------------------------------------------------------
#
# A PLAIN issue obligation IssueID="302" and an UNRELATED story arc whose
# nzblog row is IssueID="S302" exist under the SAME PROVIDER. The bare
# `IssueID == str(id) OR == "S"+str(id)` widening (incomplete fix #2) would
# let the plain issue read / delete the unrelated arc's "S302" row. The
# completed fix scopes the "S"+id arm to story-arc obligations only (durable
# payload["mode"]/storyarcs discriminator) with an NZBName-pinned fallback,
# so the plain issue must NOT touch the arc row, while a real story-arc
# obligation still matches its own "S"+IssueArcID row (the #2 positives).


def test_plain_issue_does_not_read_unrelated_arc_S_row_in_nzblog_present():
    """has_done_signal/_nzblog_present for a PLAIN issue 302 must NOT read an
    unrelated arc's S302 nzblog presence (no plain 302 row exists; the arc's
    S302 row must not be consumed as the plain issue's presence)."""
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="S302", PROVIDER="nzb.su", SARC="Other Arc"))
    # Explicit plain-issue signal (the journal payload's mode for a plain
    # issue is NOT "story_arc"): the S302 row must be invisible.
    assert recovery_classify._nzblog_present("302", "nzb.su", story_arc=False) is False
    # And via has_done_signal: a plain-issue journal row whose payload mode is
    # not story_arc ⇒ nzblog treated ABSENT ⇒ done-signal True (plain PP
    # completed), NOT a false-presence keeping it open.
    row = {
        "release_key": "rk-302",
        "issueid": "302",
        "provider": "nzb.su",
        "stage": journal.SNATCHED,
        "payload_json": json.dumps({"issueid": "302", "provider": "nzb.su", "mode": "want"}),
    }
    assert recovery_classify.has_done_signal(row) is True


def test_plain_issue_anchor_does_not_pick_unrelated_arc_S_nzbname(queues):
    """_reconstruct_anchors for a PLAIN issue 302 (no storyarcs row) must not
    pick an unrelated arc's S302 NZBName, and must not be mis-skipped by the
    arc row's presence."""
    with get_engine().begin() as conn:
        conn.execute(
            snatched.insert().values(
                IssueID="302",
                ComicID="C302",
                ComicName="Plain Series",
                Issue_Number="1",
                Status="Snatched",
                Provider="nzb.su",
                Hash=None,
            )
        )
        conn.execute(issues.insert().values(IssueID="302", Status="Snatched"))
        # The plain issue has its OWN plain nzblog row...
        conn.execute(nzblog.insert().values(IssueID="302", PROVIDER="nzb.su", NZBName="Plain.302.cbz"))
        # ...and an UNRELATED arc has S302 under the SAME provider.
        conn.execute(
            nzblog.insert().values(IssueID="S302", PROVIDER="nzb.su", NZBName="UnrelatedArc.cbz", SARC="Other Arc")
        )

    summary = recovery.replay_pipeline(probes=_probe("still"))
    assert summary["reconstructed"] == 1
    rkey = journal.release_key("302", "nzb.su", nzbname="Plain.302.cbz", hash=None)
    row = _journal_row(rkey)
    assert row is not None, "plain issue must reconstruct off its OWN plain nzblog row"
    payload = journal.load_payload(row.get("payload_json"))
    assert payload.get("nzbname") == "Plain.302.cbz", "must NOT pick the unrelated arc's S302 NZBName"


def test_plain_issue_finalize_does_not_delete_unrelated_arc_S_row(queues, monkeypatch):
    """finalize_post_processing for a PLAIN issue 302 (mode != story_arc, no
    storyarcs row) must NOT delete an unrelated arc's S302 nzblog row."""
    rkey = journal.release_key("302", "nzb.su", nzbname="Plain.302.cbz")
    with get_engine().begin() as conn:
        conn.execute(nzblog.insert().values(IssueID="302", PROVIDER="nzb.su", NZBName="Plain.302.cbz"))
        conn.execute(
            nzblog.insert().values(IssueID="S302", PROVIDER="nzb.su", NZBName="UnrelatedArc.cbz", SARC="Other Arc")
        )
    _insert_journal(
        rkey,
        journal.MOVED,
        payload={"issueid": "302", "provider": "nzb.su", "mode": "want", "nzbname": "Plain.302.cbz"},
        issueid="302",
        provider="nzb.su",
        downloader_type="nzb",
    )
    import comicarr.process as process_mod

    monkeypatch.setattr(process_mod, "Process", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no reimport")))

    recovery.replay_pipeline(probes=_probe("complete"))

    assert _journal_row(rkey)["stage"] == journal.POST_PROCESSED
    with get_engine().connect() as conn:
        plain = conn.execute(select(nzblog).where(nzblog.c.IssueID == "302")).fetchall()
        arc = conn.execute(select(nzblog).where(nzblog.c.IssueID == "S302")).fetchall()
    assert plain == [], "the plain issue's own nzblog row must still be deleted"
    assert len(arc) == 1, "the UNRELATED arc's S302 row must NOT be deleted by a plain finalize"
