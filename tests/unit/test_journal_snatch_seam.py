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
    """Drive ddl_downloader for exactly one item then make it exit."""
    q = queuelib.Queue()
    q.put(item)
    q.put("exit")
    service.ddl_downloader(q)


def test_ddl_snatch_atomic_rollback_on_journal_failure(monkeypatch):
    """Failure inside the ddl_downloader:773 begin() block rolls back BOTH the
    status='Downloading' ddl_info row AND the journal row (no half-write)."""
    monkeypatch.setattr(comicarr.DDL_LOCK, "locked", lambda: False, raising=False)

    boom = RuntimeError("journal down inside ddl begin()")
    with patch.object(journal, "record_transition", side_effect=boom):
        with pytest.raises(RuntimeError, match="journal down inside ddl begin"):
            _run_ddl_once(_ddl_item())

    # Atomic: NEITHER row may exist (rolled back together).
    assert _rows(ddl_info) == []
    assert _rows(pipeline_journal) == []


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
