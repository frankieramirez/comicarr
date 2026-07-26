#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""U3 — download/PP-seam journal transition tests (ADDITIVE / INERT).

Covers the U3 contract:

  * `cdh_monitor` / `worker_main` write journal `downloaded` immediately
    BEFORE their `PP_QUEUE.put` (ordering asserted via a spy).
  * The DDL "download complete" site co-commits `ddl_info status='Completed'`
    and journal `downloaded` inside ONE explicit begin() block (atomic).
  * The PP-complete sites write `post_processing` (before the destructive
    move), `moved` (after helpers.file_ops / fileop success, before tidyup)
    and `post_processed` (after) — verified end-to-end on the manga path and
    via the PostProcessor `_journal_pp` helper for the other sites.
  * The façade is monotonic: a second `downloaded` after `post_processed` is
    a logged no-op; the PP failure path never writes `post_processed`.

U3 is ADDITIVE ONLY and behavior-neutral: nothing consumes these rows yet,
so the assertions here prove the writes happen at the right seam without any
existing ordering being moved (the destructive reorder is U9).
"""

import queue as queuelib
import types
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.downloads import journal, service
from comicarr.db import get_engine, shutdown_engine
from comicarr import postprocessor
from comicarr.postprocessor import PostProcessor
from comicarr.tables import comics, ddl_info, issues, metadata, pipeline_journal


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own temporary SQLite database (same convention as
    tests/unit/test_journal_snatch_seam.py)."""
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
    engine = get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready
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


# ---------------------------------------------------------------------------
# Download-complete seam: journal `downloaded` BEFORE PP_QUEUE.put
# ---------------------------------------------------------------------------


def test_cdh_monitor_journals_downloaded_before_pp_queue_put(monkeypatch):
    """cdh_monitor must write journal `downloaded` strictly BEFORE it puts the
    item on PP_QUEUE — the ordering U3 guarantees."""
    order = []

    real_record = journal.record_transition

    def _spy_record(*a, **k):
        order.append(("journal", a[1] if len(a) > 1 else k.get("stage")))
        return real_record(*a, **k)

    fake_pp_queue = MagicMock()
    fake_pp_queue.put.side_effect = lambda *a, **k: order.append(("pp_put", None))

    monkeypatch.setattr(comicarr, "PP_QUEUE", fake_pp_queue, raising=False)
    monkeypatch.setattr(comicarr, "USE_SABNZBD", True, raising=False)
    monkeypatch.setattr("comicarr.helpers.check_file_condition", lambda p: {"status": True})

    nzstat = {
        "status": True,
        "failed": False,
        "name": "Saga.001.cbz",
        "location": "/tmp/dl",
        "issueid": "I1",
        "comicid": "C1",
        "apicall": True,
        "download_info": {"provider": "nzbprov", "hash": None, "nzbname": "Saga.001.cbz", "id": "nzbid-1"},
    }
    item = {"nzo_id": "nzo1"}

    with patch.object(journal, "record_transition", side_effect=_spy_record):
        service.cdh_monitor(queuelib.Queue(), item, nzstat)

    assert order == [("journal", journal.DOWNLOADED), ("pp_put", None)]
    rkey = journal.release_key("I1", "nzbprov", nzbname="Saga.001.cbz", hash=None)
    assert _stage_of(rkey) == "downloaded"


def test_cdh_monitor_failed_download_still_journals_downloaded(monkeypatch):
    """A failed download still advances the row to `downloaded` here (it then
    flows to the PP failure path which, per U3, must NOT write
    post_processed). The journal write is not gated on success."""
    fake_pp_queue = MagicMock()
    monkeypatch.setattr(comicarr, "PP_QUEUE", fake_pp_queue, raising=False)
    monkeypatch.setattr(comicarr, "USE_SABNZBD", True, raising=False)
    monkeypatch.setattr("comicarr.helpers.check_file_condition", lambda p: {"status": True})

    nzstat = {
        "status": True,
        "failed": True,
        "name": "Saga.002.cbz",
        "location": "/tmp/dl",
        "issueid": "I2",
        "comicid": "C1",
        "apicall": True,
        "download_info": {"provider": "nzbprov", "hash": None, "nzbname": "Saga.002.cbz", "id": "nzbid-2"},
    }
    service.cdh_monitor(queuelib.Queue(), {"nzo_id": "nzo2"}, nzstat)

    rkey = journal.release_key("I2", "nzbprov", nzbname="Saga.002.cbz", hash=None)
    assert _stage_of(rkey) == "downloaded"
    fake_pp_queue.put.assert_called_once()


def test_cdh_monitor_journal_failure_does_not_block_pp_queue(monkeypatch):
    """A journal failure must NOT block the PP handoff (additive / inert)."""
    fake_pp_queue = MagicMock()
    monkeypatch.setattr(comicarr, "PP_QUEUE", fake_pp_queue, raising=False)
    monkeypatch.setattr(comicarr, "USE_SABNZBD", True, raising=False)
    monkeypatch.setattr("comicarr.helpers.check_file_condition", lambda p: {"status": True})

    nzstat = {
        "status": True,
        "failed": False,
        "name": "Saga.003.cbz",
        "location": "/tmp/dl",
        "issueid": "I3",
        "comicid": "C1",
        "apicall": True,
        "download_info": {"provider": "nzbprov", "hash": None, "nzbname": "Saga.003.cbz", "id": "nzbid-3"},
    }
    with patch.object(journal, "record_transition", side_effect=RuntimeError("journal down")):
        service.cdh_monitor(queuelib.Queue(), {"nzo_id": "nzo3"}, nzstat)

    fake_pp_queue.put.assert_called_once()
    assert _rows(pipeline_journal) == []


def test_worker_main_journals_downloaded_before_pp_queue_put(monkeypatch):
    """worker_main (torrent direct-PP handoff) writes journal `downloaded`
    strictly BEFORE PP_QUEUE.put."""
    order = []
    fake_pp_queue = MagicMock()
    fake_pp_queue.put.side_effect = lambda *a, **k: order.append(("pp_put", None))
    monkeypatch.setattr(comicarr, "PP_QUEUE", fake_pp_queue, raising=False)

    real_record = journal.record_transition

    def _spy_record(*a, **k):
        order.append(("journal", a[1] if len(a) > 1 else k.get("stage")))
        return real_record(*a, **k)

    item = {
        "hash": "abchash",
        "issueid": "I9",
        "comicid": "C9",
        "provider": "torznab",
        "nzbname": "Saga.Torrent",
    }
    q = queuelib.Queue()
    q.put(item)
    q.put("exit")

    fake_snstat = {"snatch_status": "MONITOR COMPLETE", "copied_filepath": "/tmp/dl/Saga.Torrent.cbz"}
    with (
        patch("comicarr.app.search.service.torrentinfo", return_value=fake_snstat),
        patch.object(journal, "record_transition", side_effect=_spy_record),
    ):
        service.worker_main(q)

    assert order == [("journal", journal.DOWNLOADED), ("pp_put", None)]
    rkey = journal.release_key("I9", "torznab", nzbname="Saga.Torrent", hash="abchash")
    assert _stage_of(rkey) == "downloaded"


# ---------------------------------------------------------------------------
# DDL download-complete: ddl_info status='Completed' + journal downloaded
# co-committed in ONE begin() block (atomic)
# ---------------------------------------------------------------------------


def _ddl_item(idv="ddl-1", issueid="DI1"):
    return {
        "id": idv,
        "issueid": issueid,
        "comicid": "DC1",
        "series": "Saga DDL",
        "filename": "Saga.DDL.001.cbz",
        "site": "DDL(External)",
        "link": "http://x/y",
        "mainlink": "http://x",
        "link_type": "GC-Mega",
        "resume": None,
        "remote_filesize": 0,
        "oneoff": False,
        "comicinfo": [{"pack": False}],
        "packinfo": None,
    }


def test_ddl_complete_cocommits_ddl_info_and_journal_downloaded(monkeypatch):
    """On DDL download success the ddl_info status='Completed' row and the
    journal `downloaded` row are committed together in the one begin() block,
    and the journal write precedes PP_QUEUE.put (ordering asserted via a spy
    on record_transition vs PP_QUEUE.put — the U3 download-seam guarantee)."""
    monkeypatch.setattr(comicarr.DDL_LOCK, "locked", lambda: False, raising=False)

    order = []
    real_record = journal.record_transition

    def _spy_record(*a, **k):
        order.append(("journal", a[1] if len(a) > 1 else k.get("stage")))
        return real_record(*a, **k)

    fake_pp_queue = MagicMock()
    fake_pp_queue.put.side_effect = lambda *a, **k: order.append(("pp_put", None))
    monkeypatch.setattr(comicarr, "PP_QUEUE", fake_pp_queue, raising=False)
    monkeypatch.setattr("comicarr.helpers.check_file_condition", lambda p: {"status": True})

    # Seed the Downloading ddl_info row (the U2 snatch block writes this).
    with get_engine().begin() as conn:
        conn.execute(insert(ddl_info).values(ID="ddl-1", status="Downloading"))

    dd_ok = {"success": True, "filename": "Saga.DDL.001.cbz", "path": "/tmp/dl/Saga.DDL.001.cbz"}
    fake_mega = MagicMock()
    fake_mega.ddl_download.return_value = dd_ok
    monkeypatch.setattr(service.mega, "MegaNZ", lambda *a, **k: fake_mega)
    monkeypatch.setattr(service, "ddl_cleanup", lambda *a, **k: None)

    q = queuelib.Queue()
    q.put(_ddl_item())
    q.put("exit")
    with patch.object(journal, "record_transition", side_effect=_spy_record):
        service.ddl_downloader(q)

    ddl_rows = _rows(ddl_info)
    assert len(ddl_rows) == 1
    assert ddl_rows[0]["status"] == "Completed"

    rkey = journal.release_key("DI1", "DDL", nzbname="Saga.DDL.001.cbz", hash=None, discriminant="ddl-1")
    jr = _journal_row(rkey)
    assert jr is not None
    assert jr["stage"] == "downloaded"
    assert jr["provider"] == "DDL"
    assert jr["downloader_type"] == "ddl"
    fake_pp_queue.put.assert_called_once()
    # The journal `downloaded` write must land strictly BEFORE the PP_QUEUE.put
    # handoff — the atomic begin() block commits the `downloaded` row first,
    # then PP is enqueued (the snatch block earlier in ddl_downloader also
    # records `snatched`, so assert relative ordering rather than equality).
    assert ("journal", journal.DOWNLOADED) in order
    assert ("pp_put", None) in order
    assert order.index(("journal", journal.DOWNLOADED)) < order.index(("pp_put", None))
    # Nothing is enqueued for PP before the downloaded write.
    assert order[order.index(("pp_put", None)) - 1] == ("journal", journal.DOWNLOADED)


def test_ddl_complete_journal_failure_quarantines_artifact_without_resubmission(monkeypatch):
    """A post-download persistence failure is visible for review, never retried.

    The reservation and sender already completed, so replaying the DDL command
    could duplicate an external download. The durable DDL row therefore moves
    to Manual Review even if the companion journal quarantine cannot persist.
    """
    monkeypatch.setattr(comicarr.DDL_LOCK, "locked", lambda: False, raising=False)
    fake_pp_queue = MagicMock()
    monkeypatch.setattr(comicarr, "PP_QUEUE", fake_pp_queue, raising=False)
    fake_ddl_queue = MagicMock()
    monkeypatch.setattr(comicarr, "DDL_QUEUE", fake_ddl_queue, raising=False)
    monkeypatch.setattr("comicarr.helpers.check_file_condition", lambda p: {"status": True})

    with get_engine().begin() as conn:
        conn.execute(insert(ddl_info).values(ID="ddl-1", status="Downloading"))

    fake_mega = MagicMock()
    fake_mega.ddl_download.return_value = {
        "success": True,
        "filename": "Saga.DDL.001.cbz",
        "path": "/tmp/dl/Saga.DDL.001.cbz",
    }
    monkeypatch.setattr(service.mega, "MegaNZ", lambda *a, **k: fake_mega)
    monkeypatch.setattr(service, "ddl_cleanup", lambda *a, **k: None)

    real_record = journal.record_transition

    def _fail_downloaded(*args, **kwargs):
        stage = args[1] if len(args) > 1 else kwargs.get("stage")
        if stage == journal.DOWNLOADED:
            raise RuntimeError("journal down inside a ddl atomic begin")
        return real_record(*args, **kwargs)

    q = queuelib.Queue()
    q.put(_ddl_item())
    q.put("exit")
    with patch.object(journal, "record_transition", side_effect=_fail_downloaded):
        service.ddl_downloader(q)

    assert _rows(ddl_info)[0]["status"] == "Manual Review"
    assert _journal_row(journal.release_key("DI1", "DDL", nzbname="Saga.DDL.001.cbz", discriminant="ddl-1"))[
        "stage"
    ] == (journal.MANUAL_REVIEW)
    fake_pp_queue.put.assert_not_called()
    fake_ddl_queue.put.assert_not_called()


# ---------------------------------------------------------------------------
# PP markers — helper-level (covers all PP-complete sites' marker mechanism)
# ---------------------------------------------------------------------------


def _make_pp(nzb_name="Saga.001.cbz", nzb_folder="/tmp/dl", comicid="C1", issueid="I1"):
    mock_apilock = MagicMock()
    mock_apilock.locked.return_value = False
    cfg = MagicMock()
    cfg.FILE_OPTS = "move"
    cfg.IGNORE_SEARCH_WORDS = []
    with patch.object(comicarr, "APILOCK", mock_apilock), patch.object(comicarr, "CONFIG", cfg):
        pp = PostProcessor(
            nzb_name=nzb_name,
            nzb_folder=nzb_folder,
            comicid=comicid,
            issueid=issueid,
            queue=MagicMock(spec=queuelib.Queue),
        )
    return pp


@pytest.mark.parametrize(
    "stage",
    [journal.POST_PROCESSING, journal.MOVED, journal.POST_PROCESSED],
)
def test_pp_marker_helper_writes_each_stage(stage):
    """The PostProcessor._journal_pp helper (used at every PP-complete site)
    writes each PP stage and reaches the requested stage."""
    pp = _make_pp(issueid="IH1")
    # Drive the lattice in order so a later stage is reachable.
    for s in (journal.POST_PROCESSING, journal.MOVED, journal.POST_PROCESSED):
        pp._journal_pp(s, issueid="IH1")
        if s == stage:
            break
    rkey = pp._journal_release_key(issueid="IH1")
    assert _stage_of(rkey) == stage


def test_pp_markers_full_lifecycle_ordering():
    """post_processing -> moved -> post_processed advances the same row in
    order (the additive bracket around the destructive move)."""
    pp = _make_pp(issueid="IL1")
    rkey = pp._journal_release_key(issueid="IL1")

    pp._journal_pp("post_processing", issueid="IL1")
    assert _stage_of(rkey) == "post_processing"
    pp._journal_pp("moved", issueid="IL1")
    assert _stage_of(rkey) == "moved"
    pp._journal_pp("post_processed", issueid="IL1")
    assert _stage_of(rkey) == "post_processed"


def test_pp_marker_helper_swallows_failure_inert():
    """A journal failure inside _journal_pp must never propagate (additive /
    inert) — PP must continue."""
    pp = _make_pp(issueid="IE1")
    with patch.object(journal, "record_transition", side_effect=RuntimeError("boom")):
        pp._journal_pp("post_processing", issueid="IE1")  # must not raise
    assert _rows(pipeline_journal) == []


# ---------------------------------------------------------------------------
# Monotonic guard — second `downloaded` after `post_processed` is a no-op
# ---------------------------------------------------------------------------


def test_second_downloaded_after_post_processed_is_noop():
    """Once a row reaches the terminal `post_processed`, a later `downloaded`
    write is rejected by the façade's monotonic guard (logged no-op)."""
    rkey = journal.release_key("IM1", "nzbprov", nzbname="x.cbz", hash=None)
    assert journal.record_transition(rkey, journal.DOWNLOADED, issueid="IM1") is True
    assert journal.record_transition(rkey, journal.POST_PROCESSING, issueid="IM1") is True
    assert journal.record_transition(rkey, journal.MOVED, issueid="IM1") is True
    assert journal.record_transition(rkey, journal.POST_PROCESSED, issueid="IM1") is True

    # Regressing write — must be a no-op, row stays terminal.
    won = journal.record_transition(rkey, journal.DOWNLOADED, issueid="IM1")
    assert won is False
    assert _stage_of(rkey) == "post_processed"


# ---------------------------------------------------------------------------
# Secondary story-arc write must NOT ride the threaded primary key
# ---------------------------------------------------------------------------


def test_secondary_arc_write_advances_arc_row_not_primary_claimed_row():
    """The secondary COPY2ARCDIR writes pass an explicit `issuearcid` and must
    terminalize the ARC row (whose own "S<IssueArcID>" nzblog entry is being
    deleted), NOT the primary claimed ISSUE row.

    With a threaded U4 release_key present, a `_journal_pp(...,
    issuearcid=...)` write must re-derive an ARC-scoped key (anchored on the
    arc id, matching the arc's durable snatched row IssueID==IssueArcID) and
    advance that distinct row — leaving the primary threaded row untouched.
    The PRIMARY path (no explicit issuearcid) must still return the single
    threaded key, preserving the U4 single-derivation invariant."""
    threaded = "I1|nzbprov"  # the canonical key from postprocess_main's claim
    pp = _make_pp(issueid="I1", comicid="C1")
    pp.journal_release_key = threaded

    # Primary path: no explicit arc override → returns the threaded key
    # (U4 single-derivation invariant intact).
    assert pp._journal_release_key() == threaded
    assert pp._journal_release_key(issueid="I1") == threaded

    # Secondary story-arc write: explicit issuearcid → re-derived ARC key,
    # distinct from the primary threaded key.
    arc_key = pp._journal_release_key(issuearcid="ARC9")
    assert arc_key != threaded
    assert arc_key == journal.release_key("ARC9", "")

    # Drive the primary row to terminal on the threaded key.
    pp._journal_pp("post_processing", issueid="I1")
    pp._journal_pp("moved", issueid="I1")
    pp._journal_pp("post_processed", issueid="I1")
    assert _stage_of(threaded) == "post_processed"

    # The secondary arc write advances the ARC row, NOT the primary row.
    pp._journal_pp("post_processing", issuearcid="ARC9")
    pp._journal_pp("moved", issuearcid="ARC9")
    pp._journal_pp("post_processed", issuearcid="ARC9")
    assert _stage_of(arc_key) == "post_processed"

    # Two distinct rows — the primary claimed row was never advanced by the
    # secondary arc write.
    assert arc_key != threaded
    assert _journal_row(threaded) is not None
    assert _journal_row(arc_key) is not None


# ---------------------------------------------------------------------------
# Manga PP path — end-to-end markers + failure path (parametrized site D=C)
# ---------------------------------------------------------------------------


def _seed_manga(comicid="md-csm", issueid="md-csm-ch165"):
    with get_engine().begin() as conn:
        conn.execute(insert(comics).values(ComicID=comicid, ComicName="Chainsaw Man"))
        conn.execute(
            insert(issues).values(
                IssueID=issueid,
                ComicID=comicid,
                ComicName="Chainsaw Man",
                Issue_Number="165",
                ChapterNumber="165",
                Status="Wanted",
            )
        )


def test_manga_pp_writes_processing_moved_processed_in_order(tmp_path, monkeypatch):
    """Real _process_manga run: post_processing before the move, moved after
    the per-file fileop success, post_processed at the terminal end — in
    order, on one row."""
    _seed_manga()
    cbz = tmp_path / "Chainsaw Man 165.cbz"
    cbz.write_bytes(b"fake cbz")
    dest = tmp_path / "manga" / "Chainsaw Man"
    dest.mkdir(parents=True)

    pp = _make_pp(nzb_name="Chainsaw Man 165.cbz", nzb_folder=str(tmp_path), comicid="md-csm", issueid=None)

    seen = []
    real_pp = pp._journal_pp

    def _spy(stage, **k):
        seen.append(stage)
        return real_pp(stage, **k)

    moved_calls = []

    def _fake_fileop(s, d):
        moved_calls.append(("fileop", s, d))
        seen.append("__fileop__")
        return True

    monkeypatch.setattr(postprocessor.helpers, "file_ops", _fake_fileop)

    with (
        patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")),
        patch.object(pp, "_journal_pp", side_effect=_spy),
    ):
        pp._process_manga()

    # post_processing strictly before the destructive fileop; moved strictly
    # after it; post_processed last.
    assert seen[0] == "post_processing"
    assert seen.index("post_processing") < seen.index("__fileop__")
    assert seen.index("__fileop__") < seen.index("moved")
    assert seen[-1] == "post_processed"
    assert moved_calls  # the move actually happened

    rkey = pp._journal_release_key(issueid="md-csm-ch165")
    # Terminal post_processed keyed on the matched chapter IssueID.
    assert _stage_of(rkey) == "post_processed"


def test_manga_pp_failure_path_does_not_write_post_processed(tmp_path, monkeypatch):
    """Error path: when the manga move fails for every file, the run finishes
    with 0 processed and the row must NOT reach post_processed via the matched
    IssueID (it stays at post_processing for replay re-drive)."""
    _seed_manga()
    cbz = tmp_path / "Chainsaw Man 165.cbz"
    cbz.write_bytes(b"fake cbz")
    dest = tmp_path / "manga" / "Chainsaw Man"
    dest.mkdir(parents=True)

    pp = _make_pp(nzb_name="Chainsaw Man 165.cbz", nzb_folder=str(tmp_path), comicid="md-csm", issueid=None)

    def _boom_fileop(s, d):
        raise OSError("disk full")

    monkeypatch.setattr(postprocessor.helpers, "file_ops", _boom_fileop)

    with patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")):
        pp._process_manga()

    # No file matched/processed → the per-chapter release_key never reached
    # post_processed; the release-level row stays at post_processing.
    chapter_key = pp._journal_release_key(issueid="md-csm-ch165")
    assert _stage_of(chapter_key) != "post_processed"
    release_key = pp._journal_release_key()
    assert _stage_of(release_key) == "post_processing"


def test_manga_multichapter_shared_key_not_terminalized_midloop(tmp_path, monkeypatch):
    """P2-6: a multi-chapter manga pack shares ONE release_key (the
    release-level propagated key from postprocess_main's atomic claim). The
    terminal `post_processed` MUST NOT be written per-chapter — otherwise a
    mid-loop restart after chapter 1 terminalizes the shared row and replay
    skip-terminal STRANDS chapters 2..N.

    Simulate a mid-loop crash: chapter 1 moved+matched, then the run is
    interrupted before the post-loop terminal write. The shared release_key
    row must still be NON-terminal (post_processing/moved) so replay
    re-drives the remaining chapters."""
    comicid = "mc-csm"
    rkey = "mc-csm|ddl"  # the single release-level propagated key
    with get_engine().begin() as conn:
        conn.execute(insert(comics).values(ComicID=comicid, ComicName="Chainsaw Man"))
        for ch in ("165", "166"):
            conn.execute(
                insert(issues).values(
                    IssueID="%s-ch%s" % (comicid, ch),
                    ComicID=comicid,
                    ComicName="Chainsaw Man",
                    Issue_Number=ch,
                    ChapterNumber=ch,
                    Status="Wanted",
                )
            )

    src = tmp_path / "dl"
    src.mkdir()
    (src / "Chainsaw Man 165.cbz").write_bytes(b"c1")
    (src / "Chainsaw Man 166.cbz").write_bytes(b"c2")
    (tmp_path / "manga" / "Chainsaw Man").mkdir(parents=True)

    mock_apilock = MagicMock()
    mock_apilock.locked.return_value = False
    cfg = MagicMock()
    cfg.FILE_OPTS = "move"
    cfg.IGNORE_SEARCH_WORDS = []
    with patch.object(comicarr, "APILOCK", mock_apilock), patch.object(comicarr, "CONFIG", cfg):
        pp = PostProcessor(
            nzb_name="Chainsaw Man Pack",
            nzb_folder=str(src),
            comicid=comicid,
            issueid=None,
            queue=MagicMock(spec=queuelib.Queue),
            journal_release_key=rkey,
        )

    # Crash AFTER the first chapter is moved+matched but BEFORE the loop
    # finishes (so the post-loop terminal write never runs). We interrupt by
    # raising on the SECOND fileop call.
    calls = {"n": 0}
    real_fileop_target = tmp_path / "manga" / "Chainsaw Man"

    def _fileop(s, d):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise KeyboardInterrupt("simulated mid-loop restart after chapter 1")
        import shutil

        shutil.copy(s, d)
        return True

    monkeypatch.setattr(postprocessor.helpers, "file_ops", _fileop)
    assert real_fileop_target.exists()

    with patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")):
        with pytest.raises(KeyboardInterrupt):
            pp._process_manga()

    # The shared release_key row must NOT be terminal — chapter 1's match must
    # not have written `post_processed` on the shared key. Replay sees a
    # non-terminal row and re-drives the remaining chapters (exactly-once per
    # chapter on re-run), instead of skip-terminal stranding 2..N.
    stage = _stage_of(rkey)
    assert stage != "post_processed", "shared manga release_key terminalized mid-loop — chapters 2..N stranded (P2-6)"
    # P1: the per-file `moved` was REMOVED from the multi-chapter loop (it
    # advanced the shared row to `moved` after chapter 1, making the replay
    # finalizer "finish DB facts only, never re-import" — stranding chapters
    # 2..N). The shared row must now be exactly `post_processing` so the
    # finalizer re-drives the manga in FULL on a mid-loop crash. `moved` is
    # written EXACTLY ONCE after the loop completes.
    assert stage == "post_processing", (
        "shared manga release_key must stay at post_processing on a mid-loop "
        "crash (so replay re-drives in full); a premature `moved` makes the "
        "finalizer skip chapters 2..N (P1)"
    )


def test_manga_multichapter_per_file_marker_is_post_processing_not_moved(tmp_path, monkeypatch):
    """P1: in the multi-chapter manga loop the per-file marker is
    `post_processing` (idempotent, monotonic no-op after the first), NOT
    `moved`. The single authoritative `moved` is written EXACTLY ONCE after
    the full loop, immediately before the terminal `post_processed` block, so
    the lifecycle is post_processing -> moved -> post_processed and the shared
    row is never advanced to `moved` mid-loop (which would make the replay
    finalizer skip chapters 2..N)."""
    comicid = "mc3"
    rkey = "mc3|ddl"
    with get_engine().begin() as conn:
        conn.execute(insert(comics).values(ComicID=comicid, ComicName="Vinland"))
        for ch in ("1", "2", "3"):
            conn.execute(
                insert(issues).values(
                    IssueID="%s-ch%s" % (comicid, ch),
                    ComicID=comicid,
                    ComicName="Vinland",
                    Issue_Number=ch,
                    ChapterNumber=ch,
                    Status="Wanted",
                )
            )

    src = tmp_path / "dl"
    src.mkdir()
    for ch in ("1", "2", "3"):
        (src / ("Vinland %s.cbz" % ch)).write_bytes(b"c")
    (tmp_path / "manga" / "Vinland").mkdir(parents=True)

    mock_apilock = MagicMock()
    mock_apilock.locked.return_value = False
    cfg = MagicMock()
    cfg.FILE_OPTS = "move"
    cfg.IGNORE_SEARCH_WORDS = []
    with patch.object(comicarr, "APILOCK", mock_apilock), patch.object(comicarr, "CONFIG", cfg):
        pp = PostProcessor(
            nzb_name="Vinland Pack",
            nzb_folder=str(src),
            comicid=comicid,
            issueid=None,
            queue=MagicMock(spec=queuelib.Queue),
            journal_release_key=rkey,
        )

    seen = []
    real_pp = pp._journal_pp

    def _spy(stage, **k):
        seen.append(stage)
        return real_pp(stage, **k)

    def _fileop(s, d):
        seen.append("__fileop__")
        import shutil

        shutil.copy(s, d)
        return True

    monkeypatch.setattr(postprocessor.helpers, "file_ops", _fileop)

    with (
        patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")),
        patch.object(pp, "_journal_pp", side_effect=_spy),
    ):
        pp._process_manga()

    # Three fileops, no per-file `moved` interleaved with them — only
    # `post_processing` per file.
    assert seen.count("__fileop__") == 3
    # Exactly ONE `moved`, and it comes AFTER every fileop (post-loop).
    assert seen.count("moved") == 1
    last_fileop = max(i for i, s in enumerate(seen) if s == "__fileop__")
    assert seen.index("moved") > last_fileop
    # Lifecycle order on the shared row: post_processing -> moved ->
    # post_processed, and never `moved` before the final fileop.
    assert seen[0] == "post_processing"
    assert seen.index("moved") < seen.index("post_processed")
    assert seen[-1] == "post_processed"
    assert _stage_of(rkey) == "post_processed"


def test_manga_multichapter_replay_redrives_in_full_after_midloop_crash(tmp_path, monkeypatch):
    """P1: after a mid-loop crash the shared row is `post_processing` (not
    `moved`/`post_processed`); the replay finalizer therefore re-drives PP in
    FULL. Chapter 1's source file is already gone (moved on the first pass) so
    it does not re-match/double-import; only the unmoved chapters get
    processed, and the run then terminalizes the shared row exactly once."""
    from comicarr.app.downloads import recovery
    from comicarr.tables import nzblog

    comicid = "mc4"
    rkey = "mc4|ddl"
    with get_engine().begin() as conn:
        conn.execute(insert(comics).values(ComicID=comicid, ComicName="Gantz"))
        for ch in ("1", "2"):
            conn.execute(
                insert(issues).values(
                    IssueID="%s-ch%s" % (comicid, ch),
                    ComicID=comicid,
                    ComicName="Gantz",
                    Issue_Number=ch,
                    ChapterNumber=ch,
                    Status="Wanted",
                )
            )
            conn.execute(insert(nzblog).values(IssueID="%s-ch%s" % (comicid, ch), PROVIDER="DDL"))

    src = tmp_path / "dl"
    src.mkdir()
    (src / "Gantz 1.cbz").write_bytes(b"c1")
    (src / "Gantz 2.cbz").write_bytes(b"c2")
    (tmp_path / "manga" / "Gantz").mkdir(parents=True)

    mock_apilock = MagicMock()
    mock_apilock.locked.return_value = False
    cfg = MagicMock()
    cfg.FILE_OPTS = "move"
    cfg.IGNORE_SEARCH_WORDS = []

    def _build_pp():
        with patch.object(comicarr, "APILOCK", mock_apilock), patch.object(comicarr, "CONFIG", cfg):
            return PostProcessor(
                nzb_name="Gantz Pack",
                nzb_folder=str(src),
                comicid=comicid,
                issueid=None,
                queue=MagicMock(spec=queuelib.Queue),
                journal_release_key=rkey,
            )

    # --- pass 1: crash on the 2nd fileop (real move so chapter 1's source
    #     file is gone afterwards) -------------------------------------------
    pp1 = _build_pp()
    calls = {"n": 0}

    def _crashing_fileop(s, d):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise KeyboardInterrupt("simulated mid-loop restart after chapter 1")
        import shutil

        shutil.move(s, d)
        return True

    monkeypatch.setattr(postprocessor.helpers, "file_ops", _crashing_fileop)
    with patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")):
        with pytest.raises(KeyboardInterrupt):
            pp1._process_manga()

    assert _stage_of(rkey) == "post_processing"
    assert not (src / "Gantz 1.cbz").exists()  # chapter 1 moved
    assert (src / "Gantz 2.cbz").exists()  # chapter 2 still pending

    # --- the replay finalizer takes the `post_processing` BRANCH (re-drive
    #     PP in FULL), NOT the `moved` finish-DB-facts-only branch. This is
    #     the whole point of P1: per-file `moved` was removed so the shared
    #     row stays `post_processing` on a mid-loop crash and the finalizer
    #     re-imports the remaining chapters instead of skipping them. We mock
    #     process.Process so the unit test asserts the routing decision
    #     without running a full real PP (the end-to-end re-drive is covered
    #     by the integration AE suite). -------------------------------------
    row = journal.read_one(rkey)
    assert row["stage"] == "post_processing"
    fake_proc = MagicMock()
    with (
        patch.object(comicarr, "CONFIG", types.SimpleNamespace(DDL_LOCATION=str(src))),
        patch("comicarr.process.Process", return_value=fake_proc) as mk,
    ):
        action = recovery.finalize_post_processing(row)

    assert action == "post_processing-redrive"
    # Finalizer constructed a real PP and drove it (full re-import path),
    # threading the authoritative release_key so the markers advance THIS row.
    assert mk.called
    assert mk.call_args.kwargs.get("journal_release_key") == rkey
    fake_proc.post_process.assert_called_once()
    # It did NOT take the `moved` finish-only path (nzblog untouched here —
    # that happens in the real PP terminal block, not the finalizer).
    assert len(_rows(nzblog)) == 2


def test_manga_multichapter_terminalizes_once_after_full_loop(tmp_path, monkeypatch):
    """P2-6 happy path: when the full chapter loop completes, the shared
    release_key reaches `post_processed` exactly once and every matched
    chapter's nzblog row is deleted (U9 atomic co-commit preserved)."""
    from comicarr.tables import nzblog

    comicid = "mc2"
    rkey = "mc2|ddl"
    with get_engine().begin() as conn:
        conn.execute(insert(comics).values(ComicID=comicid, ComicName="Berserk"))
        for ch in ("1", "2"):
            conn.execute(
                insert(issues).values(
                    IssueID="%s-ch%s" % (comicid, ch),
                    ComicID=comicid,
                    ComicName="Berserk",
                    Issue_Number=ch,
                    ChapterNumber=ch,
                    Status="Wanted",
                )
            )
            conn.execute(insert(nzblog).values(IssueID="%s-ch%s" % (comicid, ch), PROVIDER="DDL"))

    src = tmp_path / "dl"
    src.mkdir()
    (src / "Berserk 1.cbz").write_bytes(b"c1")
    (src / "Berserk 2.cbz").write_bytes(b"c2")
    (tmp_path / "manga" / "Berserk").mkdir(parents=True)

    mock_apilock = MagicMock()
    mock_apilock.locked.return_value = False
    cfg = MagicMock()
    cfg.FILE_OPTS = "move"
    cfg.IGNORE_SEARCH_WORDS = []
    with patch.object(comicarr, "APILOCK", mock_apilock), patch.object(comicarr, "CONFIG", cfg):
        pp = PostProcessor(
            nzb_name="Berserk Pack",
            nzb_folder=str(src),
            comicid=comicid,
            issueid=None,
            queue=MagicMock(spec=queuelib.Queue),
            journal_release_key=rkey,
        )

    def _fileop(s, d):
        import shutil

        shutil.copy(s, d)
        return True

    monkeypatch.setattr(postprocessor.helpers, "file_ops", _fileop)

    with patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")):
        pp._process_manga()

    assert _stage_of(rkey) == "post_processed"
    # Both matched chapters' nzblog rows deleted in the post-loop atomic block.
    assert _rows(nzblog) == []


def test_pp_failure_before_terminal_leaves_row_at_post_processing():
    """Generic PP error path: a row that reached post_processing but whose
    move failed must NOT be advanced to post_processed (stays for replay)."""
    pp = _make_pp(issueid="IF1")
    rkey = pp._journal_release_key(issueid="IF1")
    pp._journal_pp("post_processing", issueid="IF1")
    # Move failed → no `moved`/`post_processed` written.
    assert _stage_of(rkey) == "post_processing"
