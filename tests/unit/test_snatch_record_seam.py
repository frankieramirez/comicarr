#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Characterization tests for snatch bookkeeping (#1206).

Pins what ``updater.nzblog`` and ``updater.foundsearch`` write today, reached
through the ``comicarr.app.downloads.snatch_record`` seam where its shape
allows and directly where the case needs story-arc arguments the seam does not
take yet. Each case asserts the rows written and the status set.
"""

import types
from unittest.mock import MagicMock

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr import updater
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.downloads import journal, service, snatch_record
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import (
    annuals,
    comics,
    issues,
    metadata,
    nzblog,
    oneoffhistory,
    pipeline_journal,
    snatched,
    storyarcs,
    weekly,
)


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
        types.SimpleNamespace(HIGHCOUNT=0, POST_PROCESSING=False, PACK_0DAY_WATCHLIST_ONLY=False),
        raising=False,
    )
    engine = get_engine()
    metadata.create_all(engine)
    assert ensure_acquisition_schema(engine).ready
    yield
    shutdown_engine()


def _rows(table):
    with get_engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(select(table))]


def _insert(table, **values):
    with get_engine().begin() as conn:
        conn.execute(insert(table).values(**values))


def _journal_stages():
    return {(r["issueid"], r["provider"]): r["stage"] for r in _rows(pipeline_journal)}


def test_library_issue_snatch_through_the_seam():
    _insert(comics, ComicID="C1", ComicName="Saga", ComicYear="2012")
    _insert(
        issues,
        IssueID="I1",
        ComicID="C1",
        ComicName="Saga",
        Issue_Number="1",
        IssueDate="2012-03-14",
        Status="Wanted",
    )

    link = snatch_record.record_release_link("I1", "Saga.001.cbz", "Saga", provider="nzbprov", nzb_id="nzb-1")
    snatch_record.record_snatch("C1", "I1", mode="want", provider="nzbprov", hash="abc")

    assert link == {"IssueID": "I1", "NZBName": "Saga.001.cbz", "PROVIDER": "nzbprov"}
    [log] = _rows(nzblog)
    assert (log["IssueID"], log["NZBName"], log["PROVIDER"], log["ID"]) == ("I1", "Saga.001.cbz", "nzbprov", "nzb-1")
    assert log["SARC"] is None and log["OneOff"] is None
    assert _rows(issues)[0]["Status"] == "Snatched"
    [snat] = _rows(snatched)
    assert (snat["IssueID"], snat["ComicID"], snat["ComicName"], snat["Issue_Number"]) == ("I1", "C1", "Saga", "1")
    assert (snat["Status"], snat["Provider"], snat["Hash"]) == ("Snatched", "nzbprov", "abc")
    assert _journal_stages() == {("I1", "nzbprov"): journal.SNATCHED}
    assert _rows(oneoffhistory) == []


def test_annual_snatch_marks_the_annual_row():
    _insert(comics, ComicID="C1", ComicName="Saga", ComicYear="2012")
    _insert(
        annuals,
        IssueID="A1",
        ComicID="C1",
        Issue_Number="1",
        IssueDate="2014-01-01",
        Status="Wanted",
        ReleaseComicName="Saga Annual",
    )

    updater.nzblog("A1", "Saga.Annual.001.cbz", "Saga", id="nzb-2", prov="nzbprov")
    updater.foundsearch("C1", "A1", mode="want_ann", provider="nzbprov", nzbname="Saga.Annual.001.cbz")

    assert _rows(annuals)[0]["Status"] == "Snatched"
    assert _rows(issues) == []
    assert [(r["IssueID"], r["NZBName"]) for r in _rows(nzblog)] == [("A1", "Saga.Annual.001.cbz")]
    [snat] = _rows(snatched)
    # ReleaseComicName differs from "<series> Annual", so the history row takes
    # the release name and the bare number, without an "Annual " prefix.
    assert (snat["IssueID"], snat["ComicName"], snat["Issue_Number"]) == ("A1", "Saga Annual", "1")
    assert (snat["Status"], snat["Provider"]) == ("Snatched", "nzbprov")
    assert _journal_stages() == {("A1", "nzbprov"): journal.SNATCHED}


def test_manga_chapter_snatch_follows_the_issue_path():
    _insert(comics, ComicID="md-1", ComicName="Berserk", ComicYear="1989", ContentType="manga")
    _insert(
        issues,
        IssueID="md-1-ch-42",
        ComicID="md-1",
        ComicName="Berserk",
        Issue_Number="42",
        ChapterNumber="42",
        IssueDate="1992-01-01",
        Status="Wanted",
    )

    snatch_record.record_release_link("md-1-ch-42", "Berserk.c042.cbz", "Berserk", provider="torznab")
    snatch_record.record_snatch("md-1", "md-1-ch-42", mode="want", provider="torznab", hash="h42")

    assert _rows(issues)[0]["Status"] == "Snatched"
    [log] = _rows(nzblog)
    assert (log["IssueID"], log["PROVIDER"], log["ID"]) == ("md-1-ch-42", "torznab", None)
    [snat] = _rows(snatched)
    assert (snat["IssueID"], snat["ComicName"], snat["Issue_Number"], snat["Hash"]) == (
        "md-1-ch-42",
        "Berserk",
        "42",
        "h42",
    )
    assert _journal_stages() == {("md-1-ch-42", "torznab"): journal.SNATCHED}


def test_story_arc_one_off_snatch_keys_on_the_arc_issue():
    # The series is not in the library: no comics or issues row exists.
    _insert(
        storyarcs,
        StoryArcID="SA1",
        StoryArc="War of Kings",
        IssueArcID="IA7",
        ComicID="C9",
        ComicName="Nova",
        IssueNumber="23",
        IssueYEAR="2009",
        Status="Wanted",
    )

    link = updater.nzblog(
        None, "Nova.023.cbz", "Nova", SARC="War of Kings", IssueArcID="IA7", prov="nzbprov", oneoff=True
    )
    updater.foundsearch(
        "C9", None, mode="story_arc", provider="nzbprov", SARC="War of Kings", IssueArcID="IA7", nzbname="Nova.023.cbz"
    )

    assert link["IssueID"] == "SIA7"
    [log] = _rows(nzblog)
    assert (log["IssueID"], log["SARC"], log["OneOff"]) == ("SIA7", "War of Kings", "1")
    assert _rows(storyarcs)[0]["Status"] == "Snatched"
    [snat] = _rows(snatched)
    assert (snat["IssueID"], snat["ComicID"], snat["ComicName"], snat["Issue_Number"]) == ("IA7", "C9", "Nova", "23")
    assert snat["Status"] == "Snatched"
    assert _journal_stages() == {("IA7", "nzbprov"): journal.SNATCHED}


def test_pull_list_one_off_snatch_through_the_seam():
    _insert(
        weekly,
        COMIC="Nova",
        ISSUE="5",
        STATUS="Wanted",
        ComicID="C5",
        IssueID="I5",
        weeknumber="38",
        year="2026",
    )

    snatch_record.record_release_link("I5", "0-Day.Pack", "Nova", provider="ddl", one_off=True)
    snatch_record.record_snatch("C5", "I5", mode="pullwant", provider="ddl", journal_managed=True)

    assert _rows(nzblog)[0]["OneOff"] == "1"
    assert _rows(issues) == []
    assert _rows(weekly)[0]["STATUS"] == "Snatched"
    [snat] = _rows(snatched)
    assert (snat["IssueID"], snat["ComicName"], snat["Issue_Number"], snat["Status"]) == ("I5", "Nova", "5", "Snatched")
    [hist] = _rows(oneoffhistory)
    assert (hist["ComicID"], hist["IssueID"], hist["Status"]) == ("C5", "I5", "Snatched")
    assert (hist["ComicName"], hist["IssueNumber"], hist["weeknumber"], hist["year"]) == ("Nova", "5", "38", "2026")
    # journal_managed: the accepted handoff owns the journal row.
    assert _rows(pipeline_journal) == []


def test_pack_match_records_through_the_seam(monkeypatch):
    _insert(
        weekly,
        COMIC="Nova",
        ISSUE="5",
        STATUS="Wanted",
        ComicID="C5",
        IssueID="I5",
        DynamicName="nova",
        weeknumber="38",
        year="2026",
    )
    parsed = {"parse_status": "success", "dynamic_name": "Nova"}
    monkeypatch.setattr(
        service.comicarr.filechecker,
        "FileChecker",
        lambda **kw: types.SimpleNamespace(listFiles=lambda: parsed),
    )
    monkeypatch.setattr("comicarr.app.series.service.listLibrary", lambda: {})
    link, snatch = MagicMock(), MagicMock()
    monkeypatch.setattr(snatch_record, "record_release_link", link)
    monkeypatch.setattr(snatch_record, "record_snatch", snatch)

    service.lookupthebitches(
        ["/dl/Nova 005.cbz"], "/dl/", "0-Day.Pack", "nzb-9", "ddl", "h9", "2026-09-20", journal_release_key="rk"
    )

    link.assert_called_once_with("I5", "0-Day.Pack", "Nova", provider="ddl", nzb_id="nzb-9", one_off=True)
    snatch.assert_called_once_with(
        "C5", "I5", mode="pullwant", provider="ddl", hash="h9", journal_release_key="rk", journal_managed=False
    )
