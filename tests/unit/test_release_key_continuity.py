#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""P0-1 — release_key single-derivation invariant (cross-seam continuity).

These tests drive the REAL snatch path (updater.foundsearch + updater.nzblog)
and the REAL downloaded path (service.cdh_monitor for NZB, service.worker_main
for torrent) for the SAME simulated snatch, and assert the journal `snatched`
row and the journal `downloaded` row share ONE release_key / ONE row (the
stage advanced snatched -> downloaded, exactly one pipeline_journal row).

Also covers U6 anchor reconstruction: durable snatched+nzblog rows, journal
row missing, real NZBName in nzblog -> the reconstructed key == the runtime
downloaded key (no phantom second row), and a completed item (Post-Processed
sibling) is NOT reconstructed.

Before the P0-1 fix the snatch seam derived issueid|provider|"" and the
downloaded seam derived issueid|provider|<sab-name-or-hash>, so these would
produce TWO rows / TWO keys — the tests fail before, pass after.
"""

import queue as queuelib
import types
from unittest.mock import patch

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr import updater
from comicarr.app.downloads import journal, recovery, service
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, issues, metadata, nzblog, pipeline_journal, snatched


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
        types.SimpleNamespace(HIGHCOUNT=0, POST_PROCESSING=False),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "GLOBAL_MESSAGES", None, raising=False)
    monkeypatch.setattr(comicarr, "USE_SABNZBD", True, raising=False)
    engine = get_engine()
    metadata.create_all(engine)
    yield
    shutdown_engine()


def _rows(table):
    with get_engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(select(table))]


def _seed(comicid="C1", issueid="I1"):
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
# NZB: snatch seam (foundsearch+nzblog) vs downloaded seam (cdh_monitor)
# ---------------------------------------------------------------------------


def test_nzb_snatch_and_downloaded_share_one_release_key_one_row():
    _seed()
    # REAL snatch seam: nzblog() then foundsearch() — provider here is the
    # RSS-stripped tmpprov (search.py:1678).
    updater.nzblog("I1", "Saga.001.cbz", "Saga", id="nzbid-1", prov="nzb.su")
    updater.foundsearch("C1", "I1", mode="want", provider="nzb.su [RSS]", nzbname="Saga.001.cbz")

    snatch_rows = _rows(pipeline_journal)
    assert len(snatch_rows) == 1
    assert snatch_rows[0]["stage"] == "snatched"

    # REAL downloaded seam: cdh_monitor. nzstat["name"] is the SAB-reported
    # name which DIFFERS from the search-time nzbname; download_info carries
    # only {provider,id} (no nzbname, no hash) — exactly the production shape.
    nzstat = {
        "status": True,
        "failed": False,
        "name": "Saga.S01.DIFFERENT.SAB.NAME",
        "location": "/downloads/Saga",
        "issueid": "I1",
        "comicid": "C1",
        "apicall": True,
        "download_info": {"provider": "nzb.su", "id": "nzbid-1"},
    }
    with patch("comicarr.app.downloads.service.check_file_condition", return_value={"status": True}):
        service.cdh_monitor(queuelib.Queue(), {"nzo_id": "nzo-1"}, nzstat)

    rows = _rows(pipeline_journal)
    # EXACTLY ONE row — the snatched row was ADVANCED to downloaded, not
    # orphaned with a separate downloaded row inserted alongside it.
    assert len(rows) == 1, "snatch & downloaded diverged into separate rows (P0-1 regression)"
    assert rows[0]["stage"] == "downloaded"
    assert rows[0]["release_key"] == snatch_rows[0]["release_key"]


# ---------------------------------------------------------------------------
# Torrent: snatch seam (foundsearch) vs downloaded seam (worker_main)
# ---------------------------------------------------------------------------


def test_torrent_snatch_and_downloaded_share_one_release_key_one_row(monkeypatch):
    _seed(comicid="C2", issueid="I2")
    updater.nzblog("I2", "Some.Torrent.cbr", "Saga", id="torid", prov="torznab")
    updater.foundsearch(
        "C2", "I2", mode="want", provider="torznab [RSS]", hash="deadbeefhash", nzbname="Some.Torrent.cbr"
    )

    snatch_rows = _rows(pipeline_journal)
    assert len(snatch_rows) == 1
    assert snatch_rows[0]["stage"] == "snatched"

    # REAL downloaded seam: worker_main. The SNATCHED_QUEUE torrent item now
    # carries provider+nzbname (search.py auto-snatch fix). torrentinfo is
    # stubbed to report a completed copy.
    def _fake_torrentinfo(torrent_hash=None, download=False, monitor=False):
        return {
            "snatch_status": "MONITOR COMPLETE",
            "copied_filepath": "/downloads/Some.Torrent.cbr",
            "hash": torrent_hash,
        }

    monkeypatch.setattr("comicarr.app.search.service.torrentinfo", _fake_torrentinfo)

    q = queuelib.Queue()
    q.put(
        {
            "issueid": "I2",
            "comicid": "C2",
            "hash": "deadbeefhash",
            "provider": "torznab",
            "nzbname": "Some.Torrent.cbr",
        }
    )
    q.put("exit")
    service.worker_main(q)

    rows = _rows(pipeline_journal)
    assert len(rows) == 1, "torrent snatch & downloaded diverged (P0-1 regression)"
    assert rows[0]["stage"] == "downloaded"
    assert rows[0]["release_key"] == snatch_rows[0]["release_key"]


# ---------------------------------------------------------------------------
# Anchor reconstruction: nzblog.NZBName is the durable name; no phantom row
# ---------------------------------------------------------------------------


def test_anchor_reconstruction_key_matches_runtime_downloaded_key():
    """Durable snatched+nzblog rows, journal row missing (the U2 residual
    window). Anchor reconstruction must rebuild the SAME key the runtime
    downloaded seam would derive — no phantom second row."""
    _seed()
    # Snatch committed durably but the strictly-last journal write was lost.
    updater.nzblog("I1", "Saga.001.cbz", "Saga", id="nzbid-1", prov="nzb.su")
    with patch.object(journal, "record_transition", side_effect=RuntimeError("crash")):
        updater.foundsearch("C1", "I1", mode="want", provider="nzb.su", nzbname="Saga.001.cbz")
    assert _rows(pipeline_journal) == []

    reconstructed = recovery._reconstruct_anchors()
    assert reconstructed == 1
    jrows = _rows(pipeline_journal)
    assert len(jrows) == 1
    anchor_key = jrows[0]["release_key"]

    # The runtime downloaded key for the SAME (issueid, provider) must be
    # byte-identical to the reconstructed anchor key.
    runtime_downloaded_key = journal.release_key(
        "I1", "nzb.su", nzbname="totally.different.sab.name", hash=None
    )
    assert anchor_key == runtime_downloaded_key

    # And advancing the runtime downloaded seam advances THIS row (no phantom).
    nzstat = {
        "status": True,
        "failed": False,
        "name": "totally.different.sab.name",
        "location": "/downloads/Saga",
        "issueid": "I1",
        "comicid": "C1",
        "apicall": True,
        "download_info": {"provider": "nzb.su", "id": "nzbid-1"},
    }
    with patch("comicarr.app.downloads.service.check_file_condition", return_value={"status": True}):
        service.cdh_monitor(queuelib.Queue(), {"nzo_id": "nzo-1"}, nzstat)

    rows = _rows(pipeline_journal)
    assert len(rows) == 1
    assert rows[0]["stage"] == "downloaded"


def test_completed_item_is_not_reconstructed():
    """A completed item keeps its never-deleted live Snatched row alongside a
    Post-Processed sibling; nzblog deleted on PP success. Anchor
    reconstruction must NOT rebuild it."""
    _seed()
    updater.nzblog("I1", "Saga.001.cbz", "Saga", id="nzbid-1", prov="nzb.su")
    with patch.object(journal, "record_transition", side_effect=RuntimeError("crash")):
        updater.foundsearch("C1", "I1", mode="want", provider="nzb.su", nzbname="Saga.001.cbz")

    # Completed: Post-Processed sibling row added, nzblog removed (PP success).
    with get_engine().begin() as conn:
        conn.execute(
            insert(snatched).values(
                IssueID="I1",
                ComicID="C1",
                ComicName="Saga",
                Issue_Number="1",
                Status="Post-Processed",
                Provider="nzb.su",
            )
        )
        conn.execute(nzblog.delete())

    reconstructed = recovery._reconstruct_anchors()
    assert reconstructed == 0
    assert _rows(pipeline_journal) == []
