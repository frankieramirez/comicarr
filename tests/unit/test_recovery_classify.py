#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""U5 — per-downloader startup classification tests.

Covers the U5 contract: classify() is PURE-VERDICT (never mutates the
journal) and decides still / complete / gone / unknown per downloader, with
the history-eviction guard and the one-off-journal-authoritative rule. The
GONE -> mark_failed mutation (the only journal write U5 owns) is exercised
via the thin apply_verdict() helper.

The real client-query paths (torrentinfo / SAB historycheck / NZBGet
historycheck / ddl_info+link recheck) are exercised through the injectable
`probes=` seam OR by patching the concrete client entry points — no network.
"""

import json
import types
from unittest.mock import patch

import pytest
from sqlalchemy import select

import comicarr
from comicarr.app.downloads import journal, recovery_classify
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import annuals, ddl_info, issues, metadata, nzblog, pipeline_journal


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets its own temporary SQLite database (same convention as
    tests/unit/test_pipeline_journal.py)."""
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


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _insert_journal(release_key, stage, **fields):
    payload = fields.pop("payload", None)
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
    with get_engine().connect() as conn:
        r = conn.execute(select(pipeline_journal).where(pipeline_journal.c.release_key == key)).fetchone()
        return dict(r._mapping) if r else None


def _probe(value):
    return {dt: (lambda row, v=value: v) for dt in ("torrent", "nzb", "sab", "nzbget", "ddl", "DDL")}


# ---------------------------------------------------------------------------
# Happy path: still / complete / gone (SAB)
# ---------------------------------------------------------------------------


def test_sab_still_in_queue_is_still():
    row = _insert_journal("I1|sab|nzb1", journal.SNATCHED, issueid="I1", provider="sab", downloader_type="nzb")
    assert recovery_classify.classify(row, probes=_probe("still")) == recovery_classify.STILL


def test_sab_in_history_complete_is_complete():
    row = _insert_journal("I2|sab|nzb2", journal.SNATCHED, issueid="I2", provider="sab", downloader_type="nzb")
    assert recovery_classify.classify(row, probes=_probe("complete")) == recovery_classify.COMPLETE


def test_string_complete_probe_still_classifies_complete_without_inventing_folder():
    """Existing test-seam contract: a string-only probe returning "complete"
    still classifies COMPLETE. Recovery must not invent a folder the probe
    did not return."""
    row = _insert_journal("I2s|sab|nzb2s", journal.SNATCHED, issueid="I2s", provider="sab", downloader_type="nzb")
    probes = _probe("complete")
    assert recovery_classify.classify(row, probes=probes) == recovery_classify.COMPLETE
    details = recovery_classify.classify_details(row, probes=probes)
    assert details["verdict"] == recovery_classify.COMPLETE
    assert details["location"] is None
    assert details["name"] is None


def test_sab_absent_no_done_signal_reachable_is_gone():
    """Absent AND no done-signal (issue not post-processed, nzblog present)
    AND client reachable ⇒ GONE."""
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="I3", Status="Snatched"))
        conn.execute(nzblog.insert().values(IssueID="I3", PROVIDER="sab"))
    row = _insert_journal("I3|sab|nzb3", journal.SNATCHED, issueid="I3", provider="sab", downloader_type="nzb")
    assert recovery_classify.classify(row, probes=_probe("absent")) == recovery_classify.GONE


# ---------------------------------------------------------------------------
# Edge: history eviction — absent BUT done-signal ⇒ complete, NOT gone
# ---------------------------------------------------------------------------


def test_absent_but_issue_post_processed_is_complete_not_gone():
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="I4", Status="Post-Processed"))
        conn.execute(nzblog.insert().values(IssueID="I4", PROVIDER="sab"))
    row = _insert_journal("I4|sab|nzb4", journal.SNATCHED, issueid="I4", provider="sab", downloader_type="nzb")
    assert recovery_classify.classify(row, probes=_probe("absent")) == recovery_classify.COMPLETE


def test_absent_but_nzblog_absent_is_complete_not_gone():
    """nzblog row deleted on PP success ⇒ its ABSENCE is a done-signal for a
    standard (non-one-off) release: absent-in-client ⇒ COMPLETE, NOT GONE."""
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="I5", Status="Snatched"))
        # no nzblog row inserted -> absent
    row = _insert_journal("I5|sab|nzb5", journal.SNATCHED, issueid="I5", provider="sab", downloader_type="nzb")
    assert recovery_classify.classify(row, probes=_probe("absent")) == recovery_classify.COMPLETE


def test_absent_but_journal_stage_post_processing_is_complete():
    row = _insert_journal("I6|sab|nzb6", journal.POST_PROCESSING, issueid="I6", provider="sab", downloader_type="nzb")
    assert recovery_classify.classify(row, probes=_probe("absent")) == recovery_classify.COMPLETE


# ---------------------------------------------------------------------------
# Edge: in-flight one-off — journal authoritative, nzblog-absence NOT done
# ---------------------------------------------------------------------------


def test_inflight_oneoff_nzblog_absence_not_treated_as_done():
    """Synthetic-HIGHCOUNT one-off still downloading across a restart where
    HIGHCOUNT diverged: nzblog is not matchable (absent), but for one-offs
    nzblog-presence is ADVISORY only and the journal stage is authoritative.
    The probe says still -> STILL; it must NOT be false-completed/gone."""
    oneoff_key = "oneoff|ddlprov|file.cbz|abc123"
    row = _insert_journal(
        oneoff_key,
        journal.SNATCHED,
        issueid="900001",  # synthetic HIGHCOUNT
        provider="ddlprov",
        downloader_type="nzb",
    )
    # Even with no nzblog row (absent), a one-off must not be promoted to
    # done via the nzblog-absence signal: the done-signal check returns False.
    assert recovery_classify.has_done_signal(row) is False
    # Probe says still -> STILL (journal-authoritative in-flight).
    assert recovery_classify.classify(row, probes=_probe("still")) == recovery_classify.STILL


def test_inflight_oneoff_absent_with_no_done_signal_is_gone_only_if_truly_absent():
    """Conversely a one-off that is genuinely absent from a reachable client
    with no journal/issue done-signal is still GONE (nzblog-absence is simply
    ignored as a signal, not inverted)."""
    oneoff_key = "oneoff|ddlprov|file2.cbz|def456"
    row = _insert_journal(oneoff_key, journal.SNATCHED, issueid="900002", provider="ddlprov", downloader_type="nzb")
    assert recovery_classify.classify(row, probes=_probe("absent")) == recovery_classify.GONE


# ---------------------------------------------------------------------------
# Edge: torrent hash not in client -> explicit GONE (AE4)
# ---------------------------------------------------------------------------


def test_torrent_hash_not_in_client_is_gone_via_explicit_not_found():
    """The extended torrentinfo() returns an explicit NOT-FOUND marker dict
    (no longer the silent False fall-through). _probe_torrent maps it to
    'absent'; with no done-signal -> GONE (AE4)."""
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="T1", Status="Snatched"))
        conn.execute(nzblog.insert().values(IssueID="T1", PROVIDER="tor"))
    row = _insert_journal(
        "T1|tor|h1", journal.SNATCHED, issueid="T1", provider="tor", downloader_type="torrent", hash="H" * 40
    )

    with patch(
        "comicarr.app.search.service.torrentinfo",
        return_value={"snatch_status": "NOT FOUND", "hash": "H" * 40},
    ):
        assert recovery_classify.classify(row) == recovery_classify.GONE


def test_torrent_in_progress_is_still():
    row = _insert_journal(
        "T2|tor|h2", journal.SNATCHED, issueid="T2", provider="tor", downloader_type="torrent", hash="A" * 40
    )
    with patch(
        "comicarr.app.search.service.torrentinfo",
        return_value={"snatch_status": "IN PROGRESS"},
    ):
        assert recovery_classify.classify(row) == recovery_classify.STILL


# ---------------------------------------------------------------------------
# Edge: DDL status=Downloading with dead source link -> GONE
# ---------------------------------------------------------------------------


def test_ddl_downloading_dead_link_is_gone():
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="D1", Status="Snatched"))
        conn.execute(nzblog.insert().values(IssueID="D1", PROVIDER="DDL"))
        conn.execute(
            ddl_info.insert().values(
                ID="ddl-1", issueid="D1", status="Downloading", link="http://dead/x", mainlink="http://dead"
            )
        )
    row = _insert_journal(
        "D1|DDL|x",
        journal.SNATCHED,
        issueid="D1",
        provider="DDL",
        downloader_type="ddl",
        payload={"ddl": True, "download_info": {"provider": "DDL", "id": "ddl-1"}},
    )
    with patch.object(recovery_classify, "_ddl_link_alive", return_value=False):
        assert recovery_classify.classify(row) == recovery_classify.GONE


def test_ddl_downloading_live_link_is_still():
    with get_engine().begin() as conn:
        conn.execute(
            ddl_info.insert().values(
                ID="ddl-2", issueid="D2", status="Downloading", link="http://live/x", mainlink="http://live"
            )
        )
    row = _insert_journal(
        "D2|DDL|y",
        journal.SNATCHED,
        issueid="D2",
        provider="DDL",
        downloader_type="ddl",
        payload={"ddl": True, "download_info": {"provider": "DDL", "id": "ddl-2"}},
    )
    with patch.object(recovery_classify, "_ddl_link_alive", return_value=True):
        assert recovery_classify.classify(row) == recovery_classify.STILL


def test_ddl_completed_is_complete():
    with get_engine().begin() as conn:
        conn.execute(ddl_info.insert().values(ID="ddl-3", issueid="D3", status="Completed"))
    row = _insert_journal(
        "D3|DDL|z",
        journal.SNATCHED,
        issueid="D3",
        provider="DDL",
        downloader_type="ddl",
        payload={"ddl": True, "download_info": {"provider": "DDL", "id": "ddl-3"}},
    )
    assert recovery_classify.classify(row) == recovery_classify.COMPLETE


# ---------------------------------------------------------------------------
# Error path: API unreachable -> UNKNOWN, journal stage UNCHANGED
# ---------------------------------------------------------------------------


def test_api_unreachable_is_unknown_and_journal_unchanged():
    row = _insert_journal("U1|sab|n", journal.SNATCHED, issueid="U1", provider="sab", downloader_type="nzb")
    before = _journal_row("U1|sab|n")
    verdict = recovery_classify.classify(row, probes=_probe("unreachable"))
    assert verdict == recovery_classify.UNKNOWN
    after = _journal_row("U1|sab|n")
    # The classifier is pure: the row is untouched (stage + updated_date).
    assert after == before
    assert after["stage"] == journal.SNATCHED


def test_probe_raises_is_unknown_not_gone():
    row = _insert_journal("U2|sab|n", journal.SNATCHED, issueid="U2", provider="sab", downloader_type="nzb")

    def _boom(_):
        raise RuntimeError("client exploded")

    verdict = recovery_classify.classify(row, probes={"nzb": _boom})
    assert verdict == recovery_classify.UNKNOWN
    assert _journal_row("U2|sab|n")["stage"] == journal.SNATCHED


def test_classify_never_mutates_journal_for_any_verdict():
    """classify() is PURE: assert NO journal write happens for any verdict
    (mark_failed/record_transition are never called from classify())."""
    row = _insert_journal("P1|sab|n", journal.SNATCHED, issueid="P1", provider="sab", downloader_type="nzb")
    with patch.object(journal, "record_transition") as rt:
        for raw in ("still", "complete", "absent", "unreachable"):
            recovery_classify.classify(row, probes=_probe(raw))
        rt.assert_not_called()


# ---------------------------------------------------------------------------
# GONE -> mark_failed via apply_verdict: distinguishable reason + payload kept
# ---------------------------------------------------------------------------


def test_apply_verdict_gone_marks_failed_with_reason_and_retains_payload():
    payload = {"nzb_name": "x.cbz", "issueid": "G1", "download_info": {"provider": "sab"}}
    row = _insert_journal(
        "G1|sab|n", journal.SNATCHED, issueid="G1", provider="sab", downloader_type="nzb", payload=payload
    )
    wrote = recovery_classify.apply_verdict(row, recovery_classify.GONE)
    assert wrote is True
    jr = _journal_row("G1|sab|n")
    assert jr["stage"] == journal.FAILED
    assert jr["fail_reason"] == recovery_classify.FAIL_REASON_GONE
    # R9: payload retained for a future manual retry.
    assert json.loads(jr["payload_json"]) == payload


def test_apply_verdict_noop_for_non_gone_verdicts():
    row = _insert_journal("G2|sab|n", journal.SNATCHED, issueid="G2", provider="sab", downloader_type="nzb")
    for v in (recovery_classify.STILL, recovery_classify.COMPLETE, recovery_classify.UNKNOWN):
        assert recovery_classify.apply_verdict(row, v) is False
    assert _journal_row("G2|sab|n")["stage"] == journal.SNATCHED


def test_apply_verdict_gone_reconciles_ddl_stuck_notified():
    """When U5 marks a DDL row GONE it registers the DDL id into
    comicarr.DDL_STUCK_NOTIFIED so ddl_health_check does not double-report."""
    payload = {"ddl": True, "download_info": {"provider": "DDL", "id": "ddl-99"}}
    row = _insert_journal(
        "DG|DDL|n", journal.SNATCHED, issueid="DG", provider="DDL", downloader_type="ddl", payload=payload
    )
    recovery_classify.apply_verdict(row, recovery_classify.GONE)
    assert "ddl-99" in comicarr.DDL_STUCK_NOTIFIED


def test_gone_failed_row_is_terminal_not_reenqueued_by_replay():
    """A row marked failed is terminal: read_open() (what replay iterates)
    excludes it, so replay never re-queues it (R6/R9)."""
    payload = {"issueid": "F1"}
    row = _insert_journal(
        "F1|sab|n", journal.SNATCHED, issueid="F1", provider="sab", downloader_type="nzb", payload=payload
    )
    recovery_classify.apply_verdict(row, recovery_classify.GONE)
    open_keys = [r["release_key"] for r in journal.read_open()]
    assert "F1|sab|n" not in open_keys
    assert journal.is_terminal(_journal_row("F1|sab|n")["stage"]) is True


# ---------------------------------------------------------------------------
# Real SAB historycheck path mapping (no network) — exercises _probe_nzb
# ---------------------------------------------------------------------------


def test_sab_real_historycheck_status_true_maps_complete():
    row = _insert_journal(
        "S1|sab|n",
        journal.SNATCHED,
        issueid="S1",
        provider="sab",
        downloader_type="nzb",
        payload={"comicid": "C1", "download_info": {"nzo_id": "nzoX"}},
    )
    with patch("comicarr.sabnzbd.SABnzbd.historycheck", return_value={"status": True, "failed": False}):
        assert recovery_classify.classify(row) == recovery_classify.COMPLETE


def test_sab_historycheck_keeps_completion_location():
    """Built-in SAB probe must not collapse historycheck to the string
    "complete" and drop the folder it already resolved."""
    location = "/downloads/Spawn.344"
    nzb_name = "Spawn.344.cbz"
    row = _insert_journal(
        "S1loc|sab|n",
        journal.SNATCHED,
        issueid="S1loc",
        provider="sab",
        downloader_type="sabnzbd",
        payload={
            "comicid": "C1",
            "route": "sabnzbd",
            "nzo_id": "nzoSpawn",
            "nzb_name": nzb_name,
            "download_info": {"nzo_id": "nzoSpawn"},
        },
    )
    nzstat = {"status": True, "location": location, "name": nzb_name, "failed": False}
    with patch("comicarr.sabnzbd.SABnzbd.historycheck", return_value=nzstat):
        details = recovery_classify.classify_details(row)
        assert recovery_classify.classify(row) == recovery_classify.COMPLETE
    assert details["verdict"] == recovery_classify.COMPLETE
    assert details["location"] == location
    assert details["name"] == nzb_name
    assert details["failed"] is False


def test_dict_probe_with_location_classifies_complete_and_keeps_folder():
    """Richer injectable probes (historycheck-shaped dicts) are accepted
    without breaking the string-returning test seam."""
    location = "/downloads/Spawn.344"
    nzb_name = "Spawn.344.cbz"
    row = _insert_journal("S1dict|sab|n", journal.SNATCHED, issueid="S1dict", provider="sab", downloader_type="nzb")
    probes = _probe({"status": True, "location": location, "name": nzb_name, "failed": False})
    details = recovery_classify.classify_details(row, probes=probes)
    assert details["verdict"] == recovery_classify.COMPLETE
    assert details["location"] == location
    assert details["name"] == nzb_name
    assert recovery_classify.classify(row, probes=probes) == recovery_classify.COMPLETE


def test_sab_real_historycheck_status_false_is_absent_then_gone():
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="S2", Status="Snatched"))
        conn.execute(nzblog.insert().values(IssueID="S2", PROVIDER="sab"))
    row = _insert_journal(
        "S2|sab|n",
        journal.SNATCHED,
        issueid="S2",
        provider="sab",
        downloader_type="nzb",
        payload={"comicid": "C2", "download_info": {"nzo_id": "nzoY"}},
    )
    with patch("comicarr.sabnzbd.SABnzbd.historycheck", return_value={"status": False}):
        assert recovery_classify.classify(row) == recovery_classify.GONE


# ---------------------------------------------------------------------------
# has_library_placement — the import-evidence cross-check (#734). A done-signal
# proves the DOWNLOAD finished; only the library row (Location / a
# Downloaded/Post-Processed status written by successful placement) proves the
# IMPORT happened.
# ---------------------------------------------------------------------------


def test_placement_false_when_no_library_row_exists():
    row = _insert_journal("P1|nzb.su|n", journal.SNATCHED, issueid="P1", provider="nzb.su", downloader_type="nzb")
    assert recovery_classify.has_library_placement(row) is False


def test_placement_false_for_snatched_issue_without_location():
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="P2", Status="Snatched", Location=None))
    row = _insert_journal("P2|nzb.su|n", journal.SNATCHED, issueid="P2", provider="nzb.su", downloader_type="nzb")
    assert recovery_classify.has_library_placement(row) is False


def test_placement_true_when_issue_has_location():
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="P3", Status="Snatched", Location="Spawn 344 (2024).cbz"))
    row = _insert_journal("P3|nzb.su|n", journal.SNATCHED, issueid="P3", provider="nzb.su", downloader_type="nzb")
    assert recovery_classify.has_library_placement(row) is True


def test_placement_true_when_issue_status_downloaded_or_post_processed():
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="P4", Status="Downloaded"))
        conn.execute(issues.insert().values(IssueID="P5", Status="Post-Processed"))
    row4 = _insert_journal("P4|nzb.su|n", journal.SNATCHED, issueid="P4", provider="nzb.su", downloader_type="nzb")
    row5 = _insert_journal("P5|nzb.su|n", journal.SNATCHED, issueid="P5", provider="nzb.su", downloader_type="nzb")
    assert recovery_classify.has_library_placement(row4) is True
    assert recovery_classify.has_library_placement(row5) is True


def test_placement_true_for_annual_with_location():
    from comicarr.tables import annuals

    with get_engine().begin() as conn:
        conn.execute(annuals.insert().values(IssueID="P6", Status="Snatched", Location="Ann 2024.cbz"))
    row = _insert_journal("P6|nzb.su|n", journal.SNATCHED, issueid="P6", provider="nzb.su", downloader_type="nzb")
    assert recovery_classify.has_library_placement(row) is True


def test_placement_for_story_arc_obligation_uses_storyarcs_row():
    from comicarr.tables import storyarcs

    with get_engine().begin() as conn:
        conn.execute(storyarcs.insert().values(IssueArcID="P7", StoryArc="Arc", Status="Downloaded"))
    placed = _insert_journal(
        "P7|nzb.su|n",
        journal.SNATCHED,
        issueid="P7",
        provider="nzb.su",
        downloader_type="nzb",
        payload={"mode": "story_arc"},
    )
    assert recovery_classify.has_library_placement(placed) is True
    unplaced = _insert_journal(
        "P8|nzb.su|n",
        journal.SNATCHED,
        issueid="P8",
        provider="nzb.su",
        downloader_type="nzb",
        payload={"mode": "story_arc"},
    )
    assert recovery_classify.has_library_placement(unplaced) is False


# ---------------------------------------------------------------------------
# false_terminal_reopen_candidate — the #742 backfill's evidence check. A
# terminal `post_processed` row is reopenable ONLY when the library still
# tracks the obligation, shows NO placement evidence, and carries no
# operator-intent status. Anything unverifiable stays terminal.
# ---------------------------------------------------------------------------


def _terminal_row(release_key, issueid, payload=None):
    return _insert_journal(
        release_key,
        journal.POST_PROCESSED,
        issueid=issueid,
        provider="nzb.su",
        downloader_type="nzb",
        payload=payload,
    )


def test_reopen_candidate_true_for_snatched_issue_without_location():
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="R1", Status="Snatched", Location=None))
    row = _terminal_row("R1|nzb.su", "R1")
    assert recovery_classify.false_terminal_reopen_candidate(row) is True


def test_reopen_candidate_false_with_placement_evidence():
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="R2", Status="Snatched", Location="Placed.cbz"))
        conn.execute(issues.insert().values(IssueID="R3", Status="Downloaded", Location=None))
    assert recovery_classify.false_terminal_reopen_candidate(_terminal_row("R2|nzb.su", "R2")) is False
    assert recovery_classify.false_terminal_reopen_candidate(_terminal_row("R3|nzb.su", "R3")) is False


def test_reopen_candidate_false_without_library_row():
    row = _terminal_row("R4|nzb.su", "R4")
    assert recovery_classify.false_terminal_reopen_candidate(row) is False


def test_reopen_candidate_false_for_oneoff_and_missing_issueid():
    oneoff = _terminal_row("oneoff|nzb.su|x|d", "900001")
    assert recovery_classify.false_terminal_reopen_candidate(oneoff) is False
    orphan = _terminal_row("R5|nzb.su", None)
    assert recovery_classify.false_terminal_reopen_candidate(orphan) is False


def test_reopen_candidate_false_for_operator_intent_status():
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="R6", Status="Ignored", Location=None))
        conn.execute(issues.insert().values(IssueID="R7", Status="Skipped", Location=None))
        conn.execute(issues.insert().values(IssueID="R8", Status="Archived", Location=None))
    for issueid in ("R6", "R7", "R8"):
        row = _terminal_row("%s|nzb.su" % issueid, issueid)
        assert recovery_classify.false_terminal_reopen_candidate(row) is False


def test_reopen_candidate_false_for_non_terminal_stage():
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID="R9", Status="Snatched", Location=None))
    row = _insert_journal("R9|nzb.su", journal.SNATCHED, issueid="R9", provider="nzb.su", downloader_type="nzb")
    assert recovery_classify.false_terminal_reopen_candidate(row) is False


def test_reopen_candidate_story_arc_scoped_to_storyarcs_row():
    from comicarr.tables import storyarcs

    with get_engine().begin() as conn:
        conn.execute(storyarcs.insert().values(IssueArcID="R10", StoryArc="Arc", Status="Wanted", Location=None))
        conn.execute(storyarcs.insert().values(IssueArcID="R11", StoryArc="Arc", Status="Downloaded"))
    reopenable = _terminal_row("R10|nzb.su", "R10", payload={"mode": "story_arc"})
    assert recovery_classify.false_terminal_reopen_candidate(reopenable) is True
    placed = _terminal_row("R11|nzb.su", "R11", payload={"mode": "story_arc"})
    assert recovery_classify.false_terminal_reopen_candidate(placed) is False


# ---------------------------------------------------------------------------
# Regression: the issues done-signal must recognise the status post-processing
# actually writes to the issues table ('Downloaded'), not the snatched-table
# status ('Post-Processed').
# ---------------------------------------------------------------------------


def _imported_oneoff(issueid="1099554", provider="nzbgeek", status="Downloaded", location="v30.cbz"):
    """A synthetic-HIGHCOUNT one-off whose file post-processing already placed.

    Mirrors what postprocessor writes on success: 'Downloaded' + Location onto
    issues (the 'Post-Processed' half of that same write goes to *snatched*).
    The nzblog row is left PRESENT so nzblog-absence cannot supply the
    done-signal, and the stage stays `snatched` so stage-rank cannot either —
    isolating the issues test as the only remaining signal.
    """
    with get_engine().begin() as conn:
        conn.execute(issues.insert().values(IssueID=issueid, Status=status, Location=location))
        conn.execute(nzblog.insert().values(IssueID=issueid, PROVIDER=provider))
    return _insert_journal(
        "oneoff|%s|One-Punch.Man.v30.2025.Digital.LuCaZ|One-Punch.Man.v30.2025.Digital.LuCaZ" % provider,
        journal.SNATCHED,
        issueid=issueid,
        provider=provider,
        downloader_type="nzb",
    )


def test_oneoff_issue_downloaded_is_a_done_signal():
    """An imported one-off must read as done.

    is_synthetic_oneoff('1099554') is True (>= HIGHCOUNT_FLOOR), so
    nzblog-presence is advisory only and the issues row is the ONLY
    done-signal available while the stage is still `snatched`.
    """
    row = _imported_oneoff()
    assert recovery_classify.has_done_signal(row) is True
    assert recovery_classify.classify(row, probes=_probe("absent")) == recovery_classify.COMPLETE


def test_issue_post_processed_status_still_a_done_signal():
    """The pre-existing 'Post-Processed' acceptance must not regress."""
    row = _imported_oneoff(status="Post-Processed", location=None)
    assert recovery_classify.has_done_signal(row) is True


# --- controls: these must STILL NOT be done-signals -------------------------


@pytest.mark.parametrize("status", ["Wanted", "Snatched", "Failed"])
def test_oneoff_issue_not_placed_is_not_a_done_signal(status):
    """Widening the accepted statuses must not turn an in-flight or failed
    one-off into "done" — otherwise the fix is indistinguishable from
    deleting the check.

    Probed as "absent" rather than "still": absent is the only verdict that
    reaches the done-signal cross-check at all, so GONE here is the exact
    mirror of the happy path's COMPLETE. A "still" probe returns STILL before
    has_done_signal is consulted, and so would pass even if this status were
    wrongly read as placed.
    """
    row = _imported_oneoff(status=status, location=None)
    assert recovery_classify.has_done_signal(row) is False
    assert recovery_classify.classify(row, probes=_probe("absent")) == recovery_classify.GONE


def test_oneoff_with_no_issues_row_is_not_a_done_signal():
    """No library row at all ⇒ no placement evidence ⇒ not done."""
    row = _insert_journal(
        "oneoff|nzbgeek|missing|missing",
        journal.SNATCHED,
        issueid="1099555",
        provider="nzbgeek",
        downloader_type="nzb",
    )
    assert recovery_classify.has_done_signal(row) is False


# --- annuals: completion is written to a DIFFERENT table --------------------


def _imported_annual(issueid="1099556", provider="nzbgeek", status="Downloaded"):
    """An imported annual, written exactly as updater.foundsearch writes one.

    mode='want_ann' upserts Status onto *annuals*, never onto *issues*, so an
    issues-only done-signal lookup cannot see this row. The IssueID is a real
    ComicVine id above HIGHCOUNT_FLOOR — which is the ordinary case, not a
    contrived one — so is_synthetic_oneoff() reads True and suppresses the
    nzblog fallback. The nzblog row is left present and the stage left at
    `snatched` so neither of the other two done-signals can fire either,
    isolating the library lookup as the only one available.
    """
    with get_engine().begin() as conn:
        conn.execute(annuals.insert().values(IssueID=issueid, Status=status))
        conn.execute(nzblog.insert().values(IssueID=issueid, PROVIDER=provider))
    return _insert_journal(
        "annual|%s|Saga.Annual.2025.Digital.LuCaZ|Saga.Annual.2025.Digital.LuCaZ" % provider,
        journal.SNATCHED,
        issueid=issueid,
        provider=provider,
        downloader_type="nzb",
    )


def test_imported_annual_is_a_done_signal():
    """An annual that imported cleanly must not be re-classified GONE.

    Before the library lookup walked annuals, the row's completion was
    invisible: every restart re-probed it, found the history evicted, and
    failed it — while the library plainly showed the annual Downloaded.
    """
    row = _imported_annual()
    assert recovery_classify.has_done_signal(row) is True
    assert recovery_classify.classify(row, probes=_probe("absent")) == recovery_classify.COMPLETE


@pytest.mark.parametrize("status", ["Wanted", "Snatched", "Failed"])
def test_annual_not_placed_is_not_a_done_signal(status):
    """Reading annuals must not make every annual look done."""
    row = _imported_annual(status=status)
    assert recovery_classify.has_done_signal(row) is False
    assert recovery_classify.classify(row, probes=_probe("absent")) == recovery_classify.GONE
