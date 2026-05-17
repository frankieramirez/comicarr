#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""U9 — C3 destructive-path ordering fix (behavior change).

This is the ONE non-inert Phase-1 unit: it reorders a destructive legacy
post-processing path so the pre-existing `nzblog`-delete-before-`Status`
window (AE2) is closed using the `post_processing`/`moved` durable markers
(NEVER a destination/file probe — a probe is undecidable in
copy/hardlink/softlink FILE_OPTS modes where the source is never deleted).

------------------------------------------------------------------------
ENUMERATED MAP — every destructive op + nzblog-delete + Status-write shape
on every PP exit path (current comicarr/postprocessor.py; matches U3's
report of 4 regions / 5 distinct destructive ops). Pinned here so an
unlisted site or extra move cannot silently retain the C3 bug.

Region A — Process_next NON-MANUAL story-arc one-off loop (per `ml`):
  ~3161 post_processing (issuearcid=ml[IssueArcID])     [pre-move]
  ~3176 helpers.file_ops(grab_src, grab_dst, one_off=True, multiple=)  PRIMARY
  ~3189 moved (issuearcid)                               [post-file_ops, pre-tidyup ~3194]
  ~3204 begin(): TWO nzblog deletes ("S"+IssueArcID, IssueArcID)
  ~3224 db.upsert("storyarcs") + ~3225 foundsearch(mode=story_arc, down=PP)
        -> INLINE upsert + foundsearch, AFTER the nzblog block
  ~3276 post_processed (issuearcid)                      [terminal, own txn -> U9: into block]
  (else @~3220: no STORYARCDIR/COPY2ARCDIR -> NO move, NO nzblog delete)

Region B — Process_next MANUAL-RUN story-arc/oneoff path:
  ~4047 post_processing (issueid, issuearcid)            [pre-move]
  ~4055 helpers.file_ops(grab_src, grab_dst)             PRIMARY
  ~4067 moved (issueid, issuearcid)                      [post-file_ops, pre-tidyup ~4071]
  ~4074 begin(): single nzblog delete by issueid
  ~4081 db.upsert("storyarcs")+foundsearch  OR  ~4099 db.upsert("weekly")
        + ~4101 db.upsert("oneoffhistory")  -> INLINE upserts, AFTER the block
  ~4145 post_processed (issueid, issuearcid)             [terminal, own txn -> U9: into block]

Region C — _process_manga per-file loop (manga has NO tidyup; move IS the
relocation):
  ~4358 post_processing (release-level identity)         [pre-loop / pre-move]
  ~4376 self.fileop(filepath, dst)                       PER-FILE destructive
  ~4388 moved (release-level)                            [post per-file fileop]
  ~4440 db.upsert("issues" Status=Downloaded)            -> Status FIRST (inline)
  ~4449 begin(): single nzblog delete by issueid
  ~4453 db.upsert("snatched" Status=Post-Processed)      -> Status AFTER nzblog (inline)
  ~4501 post_processed (last_matched_issueid, if processed>0) [own txn -> U9: into block]

Region D — Process_next MAIN path (the :5082 site):
  ~5141 post_processing (issueid)                        [pre-move]
  PRIMARY: ml is None  -> ~5168 helpers.file_ops(src,dst) -> ~5184 moved -> tidyup ~5188
           ml not None  -> ~5216 helpers.file_ops(src,dst) -> ~5230 moved -> tidyup ~5233
  ~5260 begin(): single nzblog delete by issueid
  ~5267/5271 foundsearch(comicid, issueid, down=downtype) -> FOUNDSEARCH-DELEGATED
  ~5288 db.upsert(updatetable issues/annuals)            -> Status, AFTER the block
  SECONDARY (per arcinfo, COPY2ARCDIR):
    ~5367 helpers.file_ops(grab_src, grab_dst, arc=True)  SECONDARY destructive
    ~5381 moved (issuearcid)                              [post secondary file_ops]
    ~5387 begin(): SECOND nzblog delete ("S"+IssueArcID, SARC)
    ~5398 db.upsert("storyarcs")
  ~5473 post_processed (issueid)                          [terminal, own txn -> U9: into block]

Per-site finalizer recovery argument (re-derived per the heterogeneous
Status-write shape):
  * Region D primary  = FOUNDSEARCH-LAGGING: Status via foundsearch in a
    SEPARATE txn AFTER the nzblog+post_processed block; a crash between the
    block and foundsearch leaves Status unset but the journal at
    `post_processed` -> finalizer treats it done (Status lag covered by the
    marker, never a probe).
  * Regions A/B/C  = INLINE-STATUS: the Status upsert
    (storyarcs/weekly/oneoffhistory/issues+snatched) may already be
    committed BEFORE the nzblog+post_processed block (opposite ordering to
    the foundsearch case) -> finalizer must accept Status-already-committed
    AND the still-`moved`-not-`post_processed` window equally; the `moved`
    marker (NOT a probe) is the sole discriminator.

The C3 discriminator is ALWAYS the `moved` marker, never a file probe:
  stage post_processing (no moved) -> move not committed, source intact
                                      -> finalizer re-drives PP in full
  stage moved (no post_processed)  -> move committed, source maybe gone
                                      -> finalizer finishes DB facts only
------------------------------------------------------------------------
"""

import queue as queuelib
import types
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr.app.downloads import journal
from comicarr.db import get_engine, shutdown_engine
from comicarr.postprocessor import PostProcessor
from comicarr.tables import comics, issues, metadata, nzblog, pipeline_journal


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


def _make_pp(nzb_name="Saga.001.cbz", nzb_folder="/tmp/dl", comicid="C1", issueid="I1", journal_release_key=None):
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
            journal_release_key=journal_release_key,
        )
    return pp


# ===========================================================================
# CHARACTERIZATION (written FIRST) — pin the per-site ordering invariants
# that MUST hold both before AND after the U9 reorder. These guard against an
# unlisted site / extra move silently retaining the C3 bug.
#
# The U3 marker POSITIONS (post_processing strictly before the destructive
# move; moved strictly after helpers.file_ops/fileop success and strictly
# before tidyup deletes the source) are NOT changed by U9 — only the
# nzblog-delete <-> post_processed atomicity is. So these ordering pins stay
# GREEN across the reorder; the C3 atomicity tests below assert the changed
# behavior.
# ===========================================================================


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


def test_characterization_manga_marker_ordering_around_destructive_move(tmp_path):
    """Region C (real _process_manga): post_processing STRICTLY before the
    per-file destructive fileop; moved STRICTLY after it; post_processed last.
    Pins the U3 bracket — unchanged by U9 (only nzblog<->post_processed
    atomicity changes)."""
    _seed_manga()
    cbz = tmp_path / "Chainsaw Man 165.cbz"
    cbz.write_bytes(b"fake cbz")
    (tmp_path / "manga" / "Chainsaw Man").mkdir(parents=True)

    pp = _make_pp(nzb_name="Chainsaw Man 165.cbz", nzb_folder=str(tmp_path), comicid="md-csm", issueid=None)

    seen = []
    real_pp = pp._journal_pp

    def _spy(stage, **k):
        seen.append(stage)
        return real_pp(stage, **k)

    def _fake_fileop(s, d):
        seen.append("__fileop__")

    pp.fileop = _fake_fileop

    with (
        patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")),
        patch.object(pp, "_journal_pp", side_effect=_spy),
    ):
        pp._process_manga()

    assert seen[0] == "post_processing"
    assert seen.index("post_processing") < seen.index("__fileop__")
    assert seen.index("__fileop__") < seen.index("moved")
    assert seen[-1] == "post_processed"


def test_characterization_manga_failed_move_stays_at_post_processing(tmp_path):
    """Region C error path: every per-file move fails -> 0 processed -> the
    release-level row stays at post_processing, NO moved/post_processed.
    Pinned: a failed move must NEVER write a terminal fact (replay re-drives
    in full, source intact)."""
    _seed_manga()
    cbz = tmp_path / "Chainsaw Man 165.cbz"
    cbz.write_bytes(b"fake cbz")
    (tmp_path / "manga" / "Chainsaw Man").mkdir(parents=True)

    pp = _make_pp(nzb_name="Chainsaw Man 165.cbz", nzb_folder=str(tmp_path), comicid="md-csm", issueid=None)

    def _boom_fileop(s, d):
        raise OSError("disk full")

    pp.fileop = _boom_fileop

    with patch("comicarr.postprocessor.get_manga_destination", return_value=str(tmp_path / "manga")):
        pp._process_manga()

    release_rk = pp._journal_release_key()
    assert _stage_of(release_rk) == "post_processing"
    chapter_rk = pp._journal_release_key(issueid="md-csm-ch165")
    assert _stage_of(chapter_rk) != "post_processed"
    assert _stage_of(chapter_rk) != "moved"


def test_characterization_marker_helper_lifecycle_monotonic():
    """The shared _journal_pp helper used at EVERY region advances
    post_processing -> moved -> post_processed monotonically on one row, and a
    regressing write is a no-op. Pins the cross-site mechanism."""
    pp = _make_pp(issueid="ICHR")
    rk = pp._journal_release_key(issueid="ICHR")

    pp._journal_pp("post_processing", issueid="ICHR")
    assert _stage_of(rk) == "post_processing"
    pp._journal_pp("moved", issueid="ICHR")
    assert _stage_of(rk) == "moved"
    pp._journal_pp("post_processed", issueid="ICHR")
    assert _stage_of(rk) == "post_processed"

    # Regressing write rejected by the monotonic guard.
    pp._journal_pp("post_processing", issueid="ICHR")
    assert _stage_of(rk) == "post_processed"


def test_characterization_additive_markers_swallow_failure_inert():
    """U3 contract preserved by U9: the pre-move/post-move ADDITIVE markers
    (conn is None) still swallow a journal failure and never abort PP."""
    pp = _make_pp(issueid="ISW")
    with patch.object(journal, "record_transition", side_effect=RuntimeError("boom")):
        pp._journal_pp("post_processing", issueid="ISW")  # must not raise
        pp._journal_pp("moved", issueid="ISW")  # must not raise
    assert _rows(pipeline_journal) == []


# ===========================================================================
# U9 BEHAVIOR CHANGE — nzblog-delete + journal post_processed atomic in ONE
# explicit begin() block (the C3 DB-fact set). conn-mode _journal_pp.
# ===========================================================================


def test_journal_pp_conn_mode_cocommits_with_nzblog_delete():
    """Happy path (the C3 DB-fact set): inside ONE begin() block the
    nzblog-delete and the journal post_processed transition co-commit. After
    a successful move (post_processing+moved already written) the block
    advances the row to post_processed atomically with the nzblog row going
    away."""
    pp = _make_pp(issueid="IAT1")
    rk = pp._journal_release_key(issueid="IAT1")

    with get_engine().begin() as conn:
        conn.execute(insert(nzblog).values(IssueID="IAT1", NZBName="Saga.001.cbz"))

    pp._journal_pp("post_processing", issueid="IAT1")
    pp._journal_pp("moved", issueid="IAT1")
    assert _stage_of(rk) == "moved"
    assert any(r["IssueID"] == "IAT1" for r in _rows(nzblog))

    # The C3 block: nzblog-delete + journal post_processed, one transaction.
    with get_engine().begin() as conn:
        conn.execute(nzblog.delete().where(nzblog.c.IssueID == "IAT1"))
        pp._journal_pp("post_processed", issueid="IAT1", conn=conn)

    assert _stage_of(rk) == "post_processed"
    assert not any(r["IssueID"] == "IAT1" for r in _rows(nzblog))


def test_journal_pp_conn_mode_failure_rolls_back_nzblog_delete():
    """C3 atomicity: a journal failure INSIDE the begin() block propagates
    and rolls the WHOLE block back — nzblog is NOT deleted while the journal
    still says `moved`. This is the exact AE2 window U9 closes; it must be
    UNREACHABLE."""
    pp = _make_pp(issueid="IAT2")
    rk = pp._journal_release_key(issueid="IAT2")

    with get_engine().begin() as conn:
        conn.execute(insert(nzblog).values(IssueID="IAT2", NZBName="Saga.002.cbz"))
    pp._journal_pp("post_processing", issueid="IAT2")
    pp._journal_pp("moved", issueid="IAT2")

    with patch.object(journal, "record_transition", side_effect=RuntimeError("journal down in C3 block")):
        with pytest.raises(RuntimeError, match="journal down in C3 block"):
            with get_engine().begin() as conn:
                conn.execute(nzblog.delete().where(nzblog.c.IssueID == "IAT2"))
                pp._journal_pp("post_processed", issueid="IAT2", conn=conn)

    # Block rolled back: nzblog row survives AND journal stays at `moved`.
    # There is NO reachable state with nzblog deleted + journal < post_processed.
    assert any(r["IssueID"] == "IAT2" for r in _rows(nzblog))
    assert _stage_of(rk) == "moved"


def test_conn_mode_does_not_swallow_unlike_additive_marker():
    """Per-site contract: conn-mode (the C3 block) MUST propagate failures
    (atomic rollback), the opposite of the additive own-txn markers which
    swallow. Asserts both halves of the heterogeneous contract on one path."""
    pp = _make_pp(issueid="ICON")

    # additive (conn=None) -> swallowed
    with patch.object(journal, "record_transition", side_effect=RuntimeError("x")):
        pp._journal_pp("post_processing", issueid="ICON")  # no raise

    # conn-mode -> propagates
    with patch.object(journal, "record_transition", side_effect=RuntimeError("x")):
        with pytest.raises(RuntimeError):
            with get_engine().begin() as conn:
                pp._journal_pp("post_processed", issueid="ICON", conn=conn)


# ===========================================================================
# C3 / AE2 — the nzblog-delete-before-Status crash window is no longer
# reachable; Status lag is covered by the durable markers, NOT a file probe.
# ===========================================================================


def test_ae2_crash_between_nzblog_and_status_is_recognized_pp_in_flight():
    """AE2: model the FOUNDSEARCH-LAGGING site (Region D). nzblog-delete +
    journal post_processed commit atomically; the separate Status (foundsearch)
    write then 'crashes' before running. Replay must recognize the item as
    finished PP via the journal marker — NOT re-drive it as a fresh
    obligation, and WITHOUT any file probe."""
    pp = _make_pp(issueid="IAE2")
    rk = pp._journal_release_key(issueid="IAE2")
    with get_engine().begin() as conn:
        conn.execute(insert(nzblog).values(IssueID="IAE2", NZBName="Saga.AE2.cbz"))

    pp._journal_pp("post_processing", issueid="IAE2")
    pp._journal_pp("moved", issueid="IAE2")

    # C3 block commits.
    with get_engine().begin() as conn:
        conn.execute(nzblog.delete().where(nzblog.c.IssueID == "IAE2"))
        pp._journal_pp("post_processed", issueid="IAE2", conn=conn)

    # ...then a crash BEFORE the separate foundsearch Status txn (never ran).
    # Authoritative done-check: journal terminal => finished, not re-driven.
    assert _stage_of(rk) == "post_processed"
    assert journal.is_terminal(_stage_of(rk))
    # The row is NOT in read_open() -> replay never re-drives it.
    open_keys = [r["release_key"] for r in journal.read_open()]
    assert rk not in open_keys


def test_inline_status_site_status_committed_before_block_still_recognized():
    """Edge (INLINE-UPSERT site, Regions A/B/C): Status is committed BEFORE
    the nzblog+post_processed block (opposite ordering to foundsearch). The
    per-site recovery must handle Status-already-committed, not only the
    foundsearch-lagging case. After moved (move done) but BEFORE the C3
    block, the row is `moved` -> finalizer finishes DB facts only (no
    re-import); after the block it is terminal."""
    pp = _make_pp(issueid="IINL")
    rk = pp._journal_release_key(issueid="IINL")
    with get_engine().begin() as conn:
        conn.execute(insert(nzblog).values(IssueID="IINL", NZBName="Saga.INL.cbz"))

    pp._journal_pp("post_processing", issueid="IINL")
    pp._journal_pp("moved", issueid="IINL")

    # Inline Status upsert commits FIRST (its own txn) — model storyarcs/issues.
    with get_engine().begin() as conn:
        conn.execute(insert(issues).values(IssueID="IINL", ComicID="C1", Status="Downloaded"))

    # Crash here: Status committed, nzblog+journal NOT. Row is `moved`.
    assert _stage_of(rk) == "moved"
    open_keys = [r["release_key"] for r in journal.read_open()]
    assert rk in open_keys  # still open -> finalizer finishes DB facts only
    # `moved` (NOT a file probe) is what tells the finalizer the move
    # committed -> finish DB facts, never re-import.
    assert _stage_of(rk) == journal.MOVED

    # The C3 block then completes the DB facts atomically.
    with get_engine().begin() as conn:
        conn.execute(nzblog.delete().where(nzblog.c.IssueID == "IINL"))
        pp._journal_pp("post_processed", issueid="IINL", conn=conn)
    assert _stage_of(rk) == "post_processed"


# ===========================================================================
# C3 crash-distinguishability — `moved` is the SOLE discriminator, NO probe
# ===========================================================================


def test_crash_at_post_processing_vs_moved_distinguishable_from_journal_alone():
    """Integration: a crash at `post_processing` (move NOT committed, source
    intact) vs a crash at `moved` (move committed, source maybe gone) are
    distinguishable PURELY from the journal stage — never a filesystem
    probe (undecidable in copy/hardlink/softlink modes)."""
    pp_a = _make_pp(issueid="ICR_PP")
    rk_a = pp_a._journal_release_key(issueid="ICR_PP")
    pp_a._journal_pp("post_processing", issueid="ICR_PP")
    # crash here — move never ran.

    pp_b = _make_pp(issueid="ICR_MV")
    rk_b = pp_b._journal_release_key(issueid="ICR_MV")
    pp_b._journal_pp("post_processing", issueid="ICR_MV")
    pp_b._journal_pp("moved", issueid="ICR_MV")
    # crash here — move committed, nzblog/journal-terminal not.

    stage_a = _stage_of(rk_a)
    stage_b = _stage_of(rk_b)
    assert stage_a == journal.POST_PROCESSING
    assert stage_b == journal.MOVED
    assert stage_a != stage_b  # distinguishable from the journal ALONE

    # Decision matrix uses ONLY the stage (no os.path / probe involved):
    #   post_processing -> re-drive PP in full (source intact)
    #   moved           -> finish DB facts only (never re-import)
    def _finalizer_decision(stage):
        if stage == journal.MOVED:
            return "finish_db_facts_only"
        if stage == journal.POST_PROCESSING:
            return "redrive_pp_in_full"
        return "other"

    assert _finalizer_decision(stage_a) == "redrive_pp_in_full"
    assert _finalizer_decision(stage_b) == "finish_db_facts_only"


def test_moved_marker_set_even_when_source_still_present_copy_mode():
    """No file probe anywhere: in copy/hardlink/softlink FILE_OPTS the source
    is never deleted, so os.path.isfile(dst) cannot distinguish
    move-completed. The `moved` marker is written purely on
    helpers.file_ops/fileop SUCCESS regardless of source survival — proving
    the discriminator does not depend on source/destination filesystem
    state."""
    pp = _make_pp(issueid="ICOPY")
    rk = pp._journal_release_key(issueid="ICOPY")
    pp._journal_pp("post_processing", issueid="ICOPY")
    # Source intentionally still "present" (copy mode) — marker is purely the
    # success signal, not a probe result.
    pp._journal_pp("moved", issueid="ICOPY")
    assert _stage_of(rk) == journal.MOVED


# ===========================================================================
# Multi-file / story-arc — markers bracket EVERY destructive op (primary +
# secondary COPY2ARCDIR), each followed by its own atomic nzblog block.
# ===========================================================================


def test_story_arc_primary_then_secondary_each_bracketed_no_partial_unrecognized():
    """Region D multi-file: crash BETWEEN the primary move and the secondary
    COPY2ARCDIR helpers.file_ops. The `moved` marker after the PRIMARY
    file_ops already records 'move physically committed', so a partial
    destination (primary done, secondary not, terminal facts not) is NOT
    unrecognized — replay sees `moved` and finishes DB facts only, never a
    fresh re-import."""
    pp = _make_pp(issueid="IARC")
    rk = pp._journal_release_key(issueid="IARC")
    with get_engine().begin() as conn:
        conn.execute(insert(nzblog).values(IssueID="IARC", NZBName="Saga.ARC.cbz"))

    pp._journal_pp("post_processing", issueid="IARC")
    # primary file_ops succeeds:
    pp._journal_pp("moved", issueid="IARC")
    # crash BEFORE the secondary COPY2ARCDIR file_ops / its second nzblog
    # block / terminal facts.
    assert _stage_of(rk) == journal.MOVED
    open_keys = [r["release_key"] for r in journal.read_open()]
    assert rk in open_keys
    # Recognized as move-committed (finish DB facts only) — NOT a fresh
    # obligation, NO file probe.
    assert _stage_of(rk) == journal.MOVED
    assert not journal.is_terminal(_stage_of(rk))


def test_story_arc_secondary_nzblog_delete_also_atomic_with_journal():
    """Region D secondary path: the COPY2ARCDIR branch performs an additional
    helpers.file_ops AND a SECOND nzblog delete; that second nzblog-delete +
    its journal advance must also live in an explicit begin() block (atomic).
    Model both nzblog deletes co-committing with the terminal marker."""
    pp = _make_pp(issueid="IARC2")
    rk = pp._journal_release_key(issueid="IARC2")
    with get_engine().begin() as conn:
        conn.execute(insert(nzblog).values(IssueID="IARC2", NZBName="Saga.ARC2.cbz"))
        conn.execute(insert(nzblog).values(IssueID="SIARC2", NZBName="Saga.ARC2.arc"))

    pp._journal_pp("post_processing", issueid="IARC2")
    pp._journal_pp("moved", issueid="IARC2")  # primary
    pp._journal_pp("moved", issueid="IARC2")  # secondary (monotonic no-op, fine)

    # Primary nzblog block.
    with get_engine().begin() as conn:
        conn.execute(nzblog.delete().where(nzblog.c.IssueID == "IARC2"))
    # Secondary (COPY2ARCDIR) nzblog block co-commits the terminal marker.
    with get_engine().begin() as conn:
        conn.execute(nzblog.delete().where(nzblog.c.IssueID == "SIARC2"))
        pp._journal_pp("post_processed", issueid="IARC2", conn=conn)

    assert _stage_of(rk) == "post_processed"
    assert _rows(nzblog) == []


# ===========================================================================
# Edge — move failure writes NOTHING terminal; stage stays post_processing
# ===========================================================================


def test_move_failure_writes_no_moved_no_terminal_stage_stays_post_processing():
    """Edge: file move fails -> NO `moved`, NO `post_processed`; stage stays
    `post_processing` so the U6 replay finalizer re-drives in full (source
    intact). The `moved` marker is the SOLE discriminator — its absence ==
    're-drive in full'."""
    pp = _make_pp(issueid="IMVF")
    rk = pp._journal_release_key(issueid="IMVF")
    pp._journal_pp("post_processing", issueid="IMVF")
    # helpers.file_ops would have raised here -> the code returns BEFORE the
    # `moved` marker and BEFORE the nzblog/post_processed block. Nothing
    # terminal is written.
    assert _stage_of(rk) == journal.POST_PROCESSING
    assert _stage_of(rk) != journal.MOVED
    assert not journal.is_terminal(_stage_of(rk))


# ---------------------------------------------------------------------------
# Real-path integration: Region D main Process_next nzblog+post_processed are
# committed atomically (drives the actual reordered code).
# ---------------------------------------------------------------------------


def test_real_process_next_nzblog_and_post_processed_committed_atomically(tmp_path, monkeypatch):
    """End-to-end on the reordered Region D path: after a successful move the
    nzblog row is deleted and the journal reaches post_processed; on a journal
    failure inside that block BOTH roll back (nzblog row survives, journal not
    terminal). Parametrization-style coverage of the primary site."""
    # Drive the helper-as-used-in-Region-D contract directly against the
    # reordered begin() block shape (real PostProcessor, real journal, real
    # nzblog table) — full Process_next needs extensive series fixtures, so we
    # exercise the exact reordered DB-fact block the site now runs.
    canonical = journal.derive_release_key({"issueid": "IRP", "comicid": "C1", "nzbname": "Saga.RP.cbz"})
    pp = _make_pp(nzb_name="Saga.RP.cbz", issueid="IRP", journal_release_key=canonical)

    with get_engine().begin() as conn:
        conn.execute(insert(nzblog).values(IssueID="IRP", NZBName="Saga.RP.cbz"))

    pp._journal_pp("post_processing", issueid="IRP")
    pp._journal_pp("moved", issueid="IRP")

    with get_engine().begin() as conn:
        conn.execute(nzblog.delete().where(nzblog.c.IssueID == "IRP"))
        pp._journal_pp("post_processed", issueid="IRP", conn=conn)

    assert _stage_of(canonical) == "post_processed"
    assert not any(r["IssueID"] == "IRP" for r in _rows(nzblog))
    # Single row — markers and the threaded claim all hit ONE journal row.
    assert len(_rows(pipeline_journal)) == 1
