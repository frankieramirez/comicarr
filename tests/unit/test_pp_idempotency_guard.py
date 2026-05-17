#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""U4 — PP-consumer idempotency guard (atomic claim) tests.

Covers the U4 contract:

  * `postprocess_main` claims a release ATOMICALLY at PP-item dequeue via a
    single conditional monotonic advance `downloaded -> post_processing`
    (a compare-and-set, NOT a read-then-process). Exactly one of N concurrent
    callers wins; every loser drops the item with no second `process.Process`.
  * The release_key is computed ONCE from ONLY the field intersection
    guaranteed on BOTH the 8-arg and 2-arg `process.Process` paths
    ({nzb_name, nzb_folder, failed, issueid, comicid, apicall}) — never
    `download_info`/`ddl`/provider/hash. It is identical on both paths.
  * That exact canonical key is threaded through `process.Process` ->
    `PostProcessor` so U3's `moved`/`post_processed` markers advance the SAME
    journal row this claim advanced (single-derivation invariant), not an
    orphan row.
  * A journal read/write failure inside the guard does NOT crash the worker —
    it falls through to PP (the existing Status guard is the fallback).
  * A genuinely new release (no journal row) wins the insert-if-absent claim
    and is NOT skipped.
"""

import queue as queuelib
import threading
import types
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

import comicarr
from comicarr.app.downloads import journal, service
from comicarr.db import get_engine, shutdown_engine
from comicarr.postprocessor import PostProcessor
from comicarr.tables import metadata, pipeline_journal


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own temporary SQLite database (same convention as
    tests/unit/test_journal_pp_seam.py)."""
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if not hasattr(comicarr, "LOG_LEVEL") or comicarr.LOG_LEVEL is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(HIGHCOUNT=0, POST_PROCESSING=True),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "GLOBAL_MESSAGES", None, raising=False)
    # APILOCK is consulted at the top of the postprocess_main loop.
    fake_lock = MagicMock()
    fake_lock.locked.return_value = False
    monkeypatch.setattr(comicarr, "APILOCK", fake_lock, raising=False)
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


def _stage_of(key):
    jr = _journal_row(key)
    return jr["stage"] if jr else None


def _pp_item(issueid="I1", comicid="C1", nzb_name="Saga.001.cbz", **extra):
    """A PP_QUEUE item with NO `journal_release_key` stamped — i.e. the
    UNJOURNALED shape (manual/API force_process:107 / ComicRN). For these the
    guard derives from the guaranteed intersection {nzb_name, nzb_folder,
    failed, issueid, comicid, apicall} and the advance is insert-if-absent /
    monotonic no-op. Journaled producers instead stamp the propagated key —
    see _stamped_pp_item / the producer/consumer contract tests below."""
    item = {
        "nzb_name": nzb_name,
        "nzb_folder": "/tmp/dl",
        "failed": False,
        "issueid": issueid,
        "comicid": comicid,
        "apicall": True,
        "ddl": False,
        "download_info": None,
    }
    item.update(extra)
    return item


def _run_postprocess_main(items):
    """Drive postprocess_main over a fixed list of items then exit. Returns
    the list of journal_release_key values each constructed process.Process
    received (i.e. the items that WON the claim and reached process.Process)."""
    processed_keys = []

    def _fake_process_factory(*args, **kwargs):
        inst = MagicMock()
        inst.post_process.return_value = None
        processed_keys.append(kwargs.get("journal_release_key"))
        return inst

    q = queuelib.Queue()
    for it in items:
        q.put(it)
    q.put("exit")

    with patch.object(service.process, "Process", side_effect=_fake_process_factory):
        service.postprocess_main(q)

    return processed_keys


# ---------------------------------------------------------------------------
# Happy path / serial duplicates (AE3)
# ---------------------------------------------------------------------------


def test_first_wins_claim_second_identical_is_dropped():
    """First PP item for a key wins the claim and processes; a second
    identical item loses the advance and is dropped — no second
    process.Process. (AE3)"""
    item = _pp_item(issueid="I1")
    processed = _run_postprocess_main([item, dict(item)])

    assert len(processed) == 1  # only the winner reached process.Process
    rkey = journal.derive_release_key({"issueid": "I1", "comicid": "C1", "nzbname": "Saga.001.cbz"})
    assert processed[0] == rkey
    assert _stage_of(rkey) == "post_processing"


def test_claim_is_cas_not_read_then_process():
    """Two PP-pool threads dequeue the same release_key at stage `downloaded`
    SIMULTANEOUSLY → exactly one wins the conditional advance and processes.
    Asserts the claim is a CAS (driven through the real journal façade with a
    barrier, mirroring test_pipeline_journal's concurrent claim test), not a
    read followed by a separate process call."""
    rkey = journal.derive_release_key({"issueid": "Iccas", "comicid": "C1", "nzbname": "Saga.001.cbz"})
    # Pre-seed the row at `downloaded` (the snatch/download seam wrote it).
    journal.record_transition(rkey, journal.DOWNLOADED, issueid="Iccas")

    results = []
    barrier = threading.Barrier(2)

    def worker():
        q = queuelib.Queue()
        q.put(_pp_item(issueid="Iccas"))
        q.put("exit")

        def _fake_factory(*a, **k):
            inst = MagicMock()
            inst.post_process.return_value = None
            results.append(k.get("journal_release_key"))
            return inst

        barrier.wait()
        with patch.object(service.process, "Process", side_effect=_fake_factory):
            service.postprocess_main(q)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    # Exactly one thread reached process.Process — the CAS winner.
    assert len(results) == 1
    assert results[0] == rkey
    assert _stage_of(rkey) == "post_processing"
    assert len(_rows(pipeline_journal)) == 1


def test_three_sources_one_key_exactly_one_processed():
    """Three duplicate sources for one key (replay re-enqueue + torrent
    self-re-enqueue + natural worker) → exactly one processed."""
    item = _pp_item(issueid="I3src")
    processed = _run_postprocess_main([dict(item), dict(item), dict(item)])

    assert len(processed) == 1
    rkey = journal.derive_release_key({"issueid": "I3src", "comicid": "C1", "nzbname": "Saga.001.cbz"})
    assert _stage_of(rkey) == "post_processing"


# ---------------------------------------------------------------------------
# C3 window integration (AE2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("preset_stage", [journal.POST_PROCESSING, journal.MOVED])
def test_duplicate_after_post_processing_or_moved_is_dropped(preset_stage):
    """C3 window: stage already post_processing/moved → duplicate arrives →
    claim advance fails → dropped, no duplicate import. (AE2)"""
    rkey = journal.derive_release_key({"issueid": "Iwin", "comicid": "C1", "nzbname": "Saga.001.cbz"})
    journal.record_transition(rkey, journal.DOWNLOADED, issueid="Iwin")
    journal.record_transition(rkey, journal.POST_PROCESSING, issueid="Iwin")
    if preset_stage == journal.MOVED:
        journal.record_transition(rkey, journal.MOVED, issueid="Iwin")

    processed = _run_postprocess_main([_pp_item(issueid="Iwin")])

    assert processed == []  # never reached process.Process
    assert _stage_of(rkey) == preset_stage  # not regressed


def test_duplicate_after_terminal_failed_is_dropped():
    """A terminal `failed` row: duplicate PP item dropped, no re-import."""
    rkey = journal.derive_release_key({"issueid": "Ifail", "comicid": "C1", "nzbname": "Saga.001.cbz"})
    journal.mark_failed(rkey, "gone", issueid="Ifail")

    processed = _run_postprocess_main([_pp_item(issueid="Ifail")])

    assert processed == []
    assert _stage_of(rkey) == "failed"


# ---------------------------------------------------------------------------
# Guaranteed-field intersection — no download_info dependence
# ---------------------------------------------------------------------------


def test_release_key_identical_on_8arg_and_2arg_paths():
    """The canonical release_key depends ONLY on the field intersection
    guaranteed on both the 8-arg and 2-arg process.Process paths
    ({nzb_name, nzb_folder, failed, issueid, comicid, apicall}) — NOT on
    download_info / ddl. An 8-arg item (full keys) and a 2-arg-shaped item
    (no download_info, no ddl — the API producer shape) with the same
    identity yield the SAME key."""
    eight_arg = _pp_item(issueid="Isame", download_info={"provider": "DDL", "id": "x"}, ddl=True)
    two_arg_shape = {
        "nzb_name": "Saga.001.cbz",
        "nzb_folder": "/tmp/dl",
        "failed": False,
        "issueid": "Isame",
        "comicid": "C1",
        "apicall": True,
        # NO download_info, NO ddl (API producer shape -> 2-arg fallback)
    }

    k8 = journal.derive_release_key(
        {"issueid": eight_arg["issueid"], "comicid": eight_arg["comicid"], "nzbname": eight_arg["nzb_name"]}
    )
    k2 = journal.derive_release_key(
        {"issueid": two_arg_shape["issueid"], "comicid": two_arg_shape["comicid"], "nzbname": two_arg_shape["nzb_name"]}
    )
    assert k8 == k2

    # And the guard itself produces that key for the 2-arg-shaped item. The
    # API-producer shape has no `download_info`/`ddl`, so the 8-arg
    # construction raises KeyError BEFORE process.Process is reached and the
    # guard's 2-arg fallback path is taken — the canonical key is computed
    # ONCE (before either construction) and threaded into the 2-arg retry.
    captured = []

    def _factory(*a, **k):
        inst = MagicMock()
        inst.post_process.return_value = None
        captured.append(k.get("journal_release_key"))
        return inst

    q = queuelib.Queue()
    q.put(two_arg_shape)
    q.put("exit")
    with patch.object(service.process, "Process", side_effect=_factory):
        service.postprocess_main(q)

    # The 2-arg fallback construction received the canonical key, identical
    # to what the 8-arg path would have computed (computed once, pre-build).
    assert captured == [k2]
    assert _stage_of(k2) == "post_processing"


# ---------------------------------------------------------------------------
# Error path — journal failure does not crash the worker
# ---------------------------------------------------------------------------


def test_journal_failure_in_guard_does_not_crash_falls_through():
    """A journal read/write FAILURE inside the guard must NOT crash the PP
    worker — it is caught, logged, and the item still reaches process.Process
    (where the existing Status guard is the defense-in-depth fallback). The
    threaded key is None so PP markers fall back to re-derivation."""
    processed = []

    def _factory(*a, **k):
        inst = MagicMock()
        inst.post_process.return_value = None
        processed.append(k.get("journal_release_key"))
        return inst

    q = queuelib.Queue()
    q.put(_pp_item(issueid="Ierr"))
    q.put("exit")

    with (
        patch.object(journal, "record_transition", side_effect=RuntimeError("journal down")),
        patch.object(service.process, "Process", side_effect=_factory),
    ):
        service.postprocess_main(q)  # must not raise

    assert len(processed) == 1  # fell through to PP, not crashed/dropped
    assert processed[0] is None  # no canonical key threaded -> re-derivation
    assert _rows(pipeline_journal) == []


# ---------------------------------------------------------------------------
# Genuinely new release (no journal row) — insert-if-absent wins
# ---------------------------------------------------------------------------


def test_new_release_with_no_journal_row_wins_and_is_not_skipped():
    """A genuinely new release (no prior journal row): the conditional
    advance inserts-if-absent and returns True (it wins) — it must proceed to
    process.Process, NOT be skipped."""
    rkey = journal.derive_release_key({"issueid": "Inew", "comicid": "C1", "nzbname": "Saga.001.cbz"})
    assert _journal_row(rkey) is None  # no row exists beforehand

    processed = _run_postprocess_main([_pp_item(issueid="Inew")])

    assert len(processed) == 1
    assert processed[0] == rkey
    assert _stage_of(rkey) == "post_processing"  # inserted by the claim


# ---------------------------------------------------------------------------
# Threading integration — postprocessor markers land on the claimed row
# ---------------------------------------------------------------------------


def test_threaded_canonical_key_is_what_pp_markers_use():
    """The canonical release_key computed in postprocess_main is the one
    postprocessor.py's `moved`/`post_processed` markers use — they advance
    the SAME row the claim advanced, NOT an orphan re-derived row."""
    canonical = journal.derive_release_key({"issueid": "Ithr", "comicid": "C1", "nzbname": "Saga.001.cbz"})

    captured_pp = {}

    def _factory(*a, **k):
        # Build a real PostProcessor threaded with the canonical key, like
        # process.Process does, and drive its U3 markers.
        mock_apilock = MagicMock()
        mock_apilock.locked.return_value = False
        cfg = MagicMock()
        cfg.FILE_OPTS = "move"
        cfg.IGNORE_SEARCH_WORDS = []
        with patch.object(comicarr, "APILOCK", mock_apilock), patch.object(comicarr, "CONFIG", cfg):
            pp = PostProcessor(
                nzb_name="Saga.001.cbz",
                nzb_folder="/tmp/dl",
                comicid="C1",
                issueid="Ithr",
                queue=MagicMock(spec=queuelib.Queue),
                journal_release_key=k.get("journal_release_key"),
            )
        captured_pp["pp"] = pp
        # The PP markers (moved/post_processed) advance the threaded row.
        pp._journal_pp("moved", issueid="Ithr")
        pp._journal_pp("post_processed", issueid="Ithr")
        inst = MagicMock()
        inst.post_process.return_value = None
        return inst

    q = queuelib.Queue()
    q.put(_pp_item(issueid="Ithr"))
    q.put("exit")
    with patch.object(service.process, "Process", side_effect=_factory):
        service.postprocess_main(q)

    pp = captured_pp["pp"]
    # The PostProcessor prefers the threaded canonical key over re-derivation.
    assert pp.journal_release_key == canonical
    assert pp._journal_release_key(issueid="Ithr") == canonical
    # The markers advanced the SAME row the claim advanced (no orphan row).
    assert len(_rows(pipeline_journal)) == 1
    assert _stage_of(canonical) == "post_processed"


def test_unjournaled_pp_falls_back_to_rederivation():
    """When no canonical key is threaded (manual/API/ComicRN PP with no
    journal row), the PostProcessor falls back to its U3 re-derivation — a
    safe monotonic no-op worst case, backward compatible with U3 behavior."""
    mock_apilock = MagicMock()
    mock_apilock.locked.return_value = False
    cfg = MagicMock()
    cfg.FILE_OPTS = "move"
    cfg.IGNORE_SEARCH_WORDS = []
    with patch.object(comicarr, "APILOCK", mock_apilock), patch.object(comicarr, "CONFIG", cfg):
        pp = PostProcessor(
            nzb_name="Saga.001.cbz",
            nzb_folder="/tmp/dl",
            comicid="C1",
            issueid="Iman",
            queue=MagicMock(spec=queuelib.Queue),
            # journal_release_key omitted (default None) — unjournaled PP
        )
    assert pp.journal_release_key is None
    # Falls back to the U3 derivation over in-scope identity fields.
    expected = journal.derive_release_key(
        {
            "issueid": "Iman",
            "IssueArcID": None,
            "comicid": "C1",
            "nzbname": "Saga.001.cbz",
            "ddl": False,
        }
    )
    assert pp._journal_release_key(issueid="Iman") == expected


# ---------------------------------------------------------------------------
# Producer/consumer key contract — the propagated journal_release_key is
# consumed verbatim, NEVER re-derived for journaled items. These are the
# tests that would have caught the orphan-row defect.
# ---------------------------------------------------------------------------


def _stamped_pp_item(snatch_key, issueid="I1", comicid="C1", nzb_name="Saga.001.cbz", **extra):
    """A PP_QUEUE item as a REAL journaled producer (worker_main torrent put /
    cdh_monitor NZB put / DDL puts) emits it: it carries the EXACT release_key
    string written to the `downloaded` journal row, stamped as
    `journal_release_key`. The item itself carries NO provider/hash/original
    nzbname (a PP_QUEUE item never does), so a re-derivation would diverge."""
    item = _pp_item(issueid=issueid, comicid=comicid, nzb_name=nzb_name, **extra)
    item["journal_release_key"] = snatch_key
    return item


def test_snatch_downloaded_claim_advance_same_row_no_orphan():
    """THE regression test for the orphan-row defect.

    Simulates the real seam: U2 snatch writes K1 (issueid|provider|nzbname),
    U3 `downloaded` writes the SAME K1, the producer stamps K1 onto the PP
    item. postprocess_main MUST consume the stamped K1 and advance THAT row
    `downloaded -> post_processing` — exactly ONE row, the snatch/downloaded
    row, advanced. It must NOT re-derive issueid|None|nzb_name and create a
    DIFFERENT orphan row (which would leave K1 stuck at `downloaded` forever
    and let U6 replay re-drive an already-PP'd item)."""
    # K1 is the canonical key the snatch seam (U2) and downloaded write (U3)
    # use: issueid|provider|nzbname-or-hash. It is NOT the PP-item-derived
    # issueid|None|nzb_name (which is what a buggy re-derivation produces).
    k1 = journal.release_key("I1", "NZB.su", nzbname="Saga.001.nzb", hash="deadbeef", discriminant="deadbeef")
    buggy_rederived = journal.derive_release_key({"issueid": "I1", "comicid": "C1", "nzbname": "Saga.001.cbz"})
    assert k1 != buggy_rederived  # the divergence the defect exploited

    # U2: snatch seam writes K1.
    assert journal.record_transition(k1, journal.SNATCHED, issueid="I1", provider="NZB.su") is True
    # U3: downloaded write advances the SAME K1 row.
    assert journal.record_transition(k1, journal.DOWNLOADED, issueid="I1", provider="NZB.su") is True
    assert len(_rows(pipeline_journal)) == 1
    assert _stage_of(k1) == "downloaded"

    # The producer stamps K1 onto the PP item; postprocess_main consumes it.
    processed = _run_postprocess_main([_stamped_pp_item(k1, issueid="I1")])

    # Exactly the snatch/downloaded row advanced — NOT an orphan row.
    assert len(_rows(pipeline_journal)) == 1, "an orphan row was created — exactly-once is void"
    assert _journal_row(k1) is not None
    assert _stage_of(k1) == "post_processing"  # K1 advanced, not stuck
    assert _journal_row(buggy_rederived) is None  # no divergent orphan row
    # The claim winner threaded the propagated K1 (verbatim, not re-derived).
    assert processed == [k1]


def test_end_to_end_key_continuity_one_row_whole_lifecycle():
    """End-to-end key continuity: the release_key written at the snatch seam,
    the `downloaded` write, the U4 claim, and the threaded PP markers
    (moved/post_processed) are ALL the same string and operate on ONE journal
    row across the full snatch -> downloaded -> claim -> post_processed
    lifecycle."""
    k1 = journal.release_key("Ie2e", "Torznab", nzbname="Bone.012.nzb", hash="cafef00d", discriminant="cafef00d")

    # U2 snatch + U3 downloaded — same K1.
    journal.record_transition(k1, journal.SNATCHED, issueid="Ie2e", provider="Torznab")
    journal.record_transition(k1, journal.DOWNLOADED, issueid="Ie2e", provider="Torznab")

    captured = {}

    def _factory(*a, **k):
        threaded = k.get("journal_release_key")
        captured["threaded"] = threaded
        # Build a real PostProcessor threaded with the propagated key (as
        # process.Process does) and drive its U3 moved/post_processed markers.
        mock_apilock = MagicMock()
        mock_apilock.locked.return_value = False
        cfg = MagicMock()
        cfg.FILE_OPTS = "move"
        cfg.IGNORE_SEARCH_WORDS = []
        with patch.object(comicarr, "APILOCK", mock_apilock), patch.object(comicarr, "CONFIG", cfg):
            pp = PostProcessor(
                nzb_name="Bone.012.cbz",
                nzb_folder="/tmp/dl",
                comicid="C1",
                issueid="Ie2e",
                queue=MagicMock(spec=queuelib.Queue),
                journal_release_key=threaded,
            )
        captured["marker_key"] = pp._journal_release_key(issueid="Ie2e")
        pp._journal_pp("moved", issueid="Ie2e")
        pp._journal_pp("post_processed", issueid="Ie2e")
        inst = MagicMock()
        inst.post_process.return_value = None
        return inst

    q = queuelib.Queue()
    q.put(_stamped_pp_item(k1, issueid="Ie2e", nzb_name="Bone.012.cbz"))
    q.put("exit")
    with patch.object(service.process, "Process", side_effect=_factory):
        service.postprocess_main(q)

    # Every key in the lifecycle is byte-identical to K1.
    assert captured["threaded"] == k1  # claim threaded the propagated K1
    assert captured["marker_key"] == k1  # PP markers used the SAME K1
    # ONE row across snatch -> downloaded -> post_processing -> moved ->
    # post_processed. No orphan ever created.
    assert len(_rows(pipeline_journal)) == 1
    assert _stage_of(k1) == "post_processed"


def test_propagated_key_consumed_verbatim_not_rederived():
    """When the item carries `journal_release_key`, the guard consumes it
    VERBATIM and never calls derive_release_key for that item — proving the
    journaled path can never re-derive a divergent (orphaning) key."""
    k1 = journal.release_key("Iverb", "DDL", nzbname="Akira.v1.cbz", hash=None, discriminant="ddlid-77")
    journal.record_transition(k1, journal.DOWNLOADED, issueid="Iverb", provider="DDL")

    real_derive = journal.derive_release_key
    with patch.object(journal, "derive_release_key", wraps=real_derive) as spy:
        processed = _run_postprocess_main([_stamped_pp_item(k1, issueid="Iverb", nzb_name="Akira.v1.cbz")])

    spy.assert_not_called()  # journaled item: NEVER re-derived
    assert processed == [k1]  # propagated key threaded verbatim
    assert _stage_of(k1) == "post_processing"
    assert len(_rows(pipeline_journal)) == 1


def test_duplicate_with_stamped_key_after_downloaded_claims_once():
    """Two duplicate journaled PP items both stamped with the SAME K1 (replay
    re-enqueue + natural handoff): exactly one wins the claim, the K1 row
    advances once, no orphan, the loser is dropped."""
    k1 = journal.release_key("Idup", "NZB.su", nzbname="Y.001.nzb", hash="abc", discriminant="abc")
    journal.record_transition(k1, journal.DOWNLOADED, issueid="Idup", provider="NZB.su")

    item = _stamped_pp_item(k1, issueid="Idup")
    processed = _run_postprocess_main([dict(item), dict(item)])

    assert processed == [k1]  # exactly one winner, threaded K1
    assert len(_rows(pipeline_journal)) == 1
    assert _stage_of(k1) == "post_processing"
