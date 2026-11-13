#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""#482 — complete pipeline_journal terminals for failed-download paths.

Band predicate is UNCHANGED (#457):
  stage IN (failed, manual_review)
  AND (status IS NULL OR status NOT IN (retried, ignored, imported))

These tests pin:
  * terminal Process (FAILED_AUTO off) → band +1, not in read_open()
  * FAILED_AUTO after enqueue stamp → band unchanged (status=retried)
  * handling-disabled process.py path → open stage leaves OPEN_STAGES
  * markFailed terminalizes when release_key is resolvable
"""

import queue as queuelib
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import comicarr
from comicarr import failed as failed_mod
from comicarr.app.downloads import journal
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import comics, issues, metadata, nzblog, pipeline_journal

# Settled needs-attention band predicate (#437 / #457). Do not widen.
_BAND_OFF = ("retried", "ignored", "imported")


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
        SimpleNamespace(FAILED_DOWNLOAD_HANDLING=True, FAILED_AUTO=False, HIGHCOUNT=0),
        raising=False,
    )
    engine = get_engine()
    metadata.create_all(engine)
    yield
    shutdown_engine()


def _row(key):
    with get_engine().connect() as conn:
        r = conn.execute(select(pipeline_journal).where(pipeline_journal.c.release_key == key)).fetchone()
        return dict(r._mapping) if r else None


def _band_rows():
    """Single-table needs-attention band (predicate fixed by #457)."""
    rows = []
    with get_engine().connect() as conn:
        for r in conn.execute(select(pipeline_journal)):
            m = dict(r._mapping)
            if m["stage"] not in (journal.FAILED, journal.MANUAL_REVIEW):
                continue
            if m.get("status") in _BAND_OFF:
                continue
            rows.append(m)
    return rows


def _seed_watchlist_and_nzblog(*, issueid="1001", comicid="C1", nzbname="Saga.001", provider="NZBGeek", nzb_id="nzo-1"):
    with get_engine().begin() as conn:
        conn.execute(
            comics.insert().values(
                ComicID=comicid,
                ComicName="Saga",
                ComicYear="2012",
                Status="Active",
            )
        )
        conn.execute(
            issues.insert().values(
                IssueID=issueid,
                ComicID=comicid,
                ComicName="Saga",
                Issue_Number="1",
                Status="Snatched",
            )
        )
        conn.execute(
            nzblog.insert().values(
                IssueID=issueid,
                NZBName=nzbname,
                PROVIDER=provider,
                ID=nzb_id,
            )
        )


def _open_downloaded(key, *, issueid="1001", provider="NZBGeek", nzbname="Saga.001"):
    journal.record_transition(
        key,
        journal.SNATCHED,
        issueid=issueid,
        provider=provider,
        nzbname=nzbname,
    )
    journal.record_transition(key, journal.DOWNLOADED)
    assert _row(key)["stage"] == journal.DOWNLOADED
    assert key in {r["release_key"] for r in journal.read_open()}


def test_process_terminal_no_auto_lands_on_band_and_leaves_open_stages():
    """FAILED_AUTO off → mark_failed with null status → band +1, not in flight."""
    issueid = "1001"
    provider = "NZBGeek"
    nzbname = "Saga.001"
    key = journal.release_key(issueid, provider)
    _seed_watchlist_and_nzblog(issueid=issueid, provider=provider, nzbname=nzbname)
    _open_downloaded(key, issueid=issueid, provider=provider, nzbname=nzbname)

    band_before = len(_band_rows())
    open_before = len(journal.read_open())

    q = queuelib.Queue()
    proc = failed_mod.FailedProcessor(
        nzb_name=nzbname,
        nzb_folder="/tmp/saga",
        id="nzo-1",
        issueid=issueid,
        comicid="C1",
        prov=provider,
        queue=q,
        journal_release_key=key,
    )
    proc.Process()
    result = q.get()

    assert result[0]["mode"] == "stop"
    row = _row(key)
    assert row["stage"] == journal.FAILED
    assert row["fail_reason"] == failed_mod.FAIL_REASON_NO_AUTO_HANDLING
    assert row["status"] is None
    assert key not in {r["release_key"] for r in journal.read_open()}
    assert len(journal.read_open()) == open_before - 1
    assert len(_band_rows()) == band_before + 1


def test_process_failed_auto_stamps_retried_off_band():
    """FAILED_AUTO on → mark_failed + status=retried in one act → band unchanged."""
    issueid = "1002"
    provider = "NZBGeek"
    nzbname = "Saga.002"
    key = journal.release_key(issueid, provider)
    _seed_watchlist_and_nzblog(issueid=issueid, provider=provider, nzbname=nzbname, nzb_id="nzo-2")
    _open_downloaded(key, issueid=issueid, provider=provider, nzbname=nzbname)

    comicarr.CONFIG.FAILED_AUTO = True
    band_before = len(_band_rows())
    open_before = len(journal.read_open())

    q = queuelib.Queue()
    proc = failed_mod.FailedProcessor(
        nzb_name=nzbname,
        nzb_folder="/tmp/saga",
        id="nzo-2",
        issueid=issueid,
        comicid="C1",
        prov=provider,
        queue=q,
        journal_release_key=key,
    )
    proc.Process()
    result = q.get()

    assert result[0]["mode"] == "retry"
    row = _row(key)
    assert row["stage"] == journal.FAILED
    assert row["fail_reason"] == failed_mod.FAIL_REASON_RESEARCHING
    assert row["status"] == failed_mod.STATUS_RETRIED
    assert key not in {r["release_key"] for r in journal.read_open()}
    assert len(journal.read_open()) == open_before - 1
    assert len(_band_rows()) == band_before  # off-band via status=retried


def test_handling_disabled_process_terminalizes_open_stage(monkeypatch):
    """FAILED_DOWNLOAD_HANDLING off still terminalizes so OPEN_STAGES drain."""
    from comicarr.app.downloads import postprocessing

    issueid = "1003"
    provider = "sabnzbd"
    nzbname = "Batman.001"
    key = journal.release_key(issueid, provider)
    _open_downloaded(key, issueid=issueid, provider=provider, nzbname=nzbname)

    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(FAILED_DOWNLOAD_HANDLING=False, FAILED_AUTO=False, HIGHCOUNT=0),
        raising=False,
    )

    band_before = len(_band_rows())
    open_before = len(journal.read_open())

    result = postprocessing._post_process(
        {
            "nzb_name": nzbname,
            "nzb_folder": "/downloads/Batman",
            "failed": True,
            "issueid": issueid,
            "comicid": "C-bat",
            "download_info": {"id": "nzo-bat", "provider": provider},
            "journal_release_key": key,
        }
    )
    assert result.outcome == postprocessing.FAILED
    assert result.fail_reason == failed_mod.FAIL_REASON_NO_AUTO_HANDLING

    row = _row(key)
    assert row["stage"] == journal.FAILED
    assert row["fail_reason"] == failed_mod.FAIL_REASON_NO_AUTO_HANDLING
    assert row["status"] is None
    assert key not in {r["release_key"] for r in journal.read_open()}
    assert len(journal.read_open()) == open_before - 1
    assert len(_band_rows()) == band_before + 1


def test_mark_failed_path_terminalizes_when_key_resolvable():
    issueid = "1004"
    provider = "NZBGeek"
    nzbname = "Saga.004"
    key = journal.release_key(issueid, provider)
    _seed_watchlist_and_nzblog(issueid=issueid, provider=provider, nzbname=nzbname, nzb_id="nzo-4")
    _open_downloaded(key, issueid=issueid, provider=provider, nzbname=nzbname)

    band_before = len(_band_rows())

    proc = failed_mod.FailedProcessor(
        nzb_name=nzbname,
        id="nzo-4",
        issueid=issueid,
        comicid="C1",
        prov=provider,
        journal_release_key=key,
    )
    proc.markFailed()

    row = _row(key)
    assert row["stage"] == journal.FAILED
    assert row["fail_reason"] == failed_mod.FAIL_REASON_NO_AUTO_HANDLING
    assert row["status"] is None
    assert key not in {r["release_key"] for r in journal.read_open()}
    assert len(_band_rows()) == band_before + 1


def test_terminalize_skips_when_release_key_unresolvable(monkeypatch):
    """No invented keys: unresolvable identity is a no-op, not a collision."""
    called = []

    def _boom(*_a, **_k):
        called.append(True)
        raise AssertionError("mark_failed must not run without a resolvable key")

    monkeypatch.setattr(journal, "mark_failed", _boom)
    assert failed_mod.resolve_failed_release_key() is None
    assert failed_mod.terminalize_failed_download(None, failed_mod.FAIL_REASON_NO_AUTO_HANDLING) is False
    assert called == []


def test_prefer_propagated_journal_release_key_over_rederive():
    canonical = "canonical|key|from|claim"
    assert (
        failed_mod.resolve_failed_release_key(
            journal_release_key=canonical,
            issueid="999",
            provider="other",
        )
        == canonical
    )


def test_fail_reason_tokens_are_token_only_not_exception_text():
    """Producer-contract codes must stay machine tokens (no str(e) concat)."""
    assert failed_mod.FAIL_REASON_RESEARCHING == "download_failed_researching"
    assert failed_mod.FAIL_REASON_NO_AUTO_HANDLING == "download_failed_no_auto_handling"
    assert " " not in failed_mod.FAIL_REASON_RESEARCHING
    assert ":" not in failed_mod.FAIL_REASON_NO_AUTO_HANDLING
