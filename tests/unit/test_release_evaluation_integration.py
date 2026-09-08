#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Evaluation contracts with the real filename parser and library database."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

import comicarr
from comicarr import db
from comicarr.app.search.evaluation import EvaluationSession
from comicarr.app.search.evaluation_handoff import handoff_matches
from comicarr.tables import issues, metadata


@pytest.fixture(autouse=True)
def library(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///%s" % (tmp_path / "library.db"))
    metadata.create_all(engine)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(comicarr, "PACK_ISSUEIDS_DONT_QUEUE", {})
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            IGNORE_SEARCH_WORDS=[],
            USE_MINSIZE=False,
            MINSIZE="10",
            USE_MAXSIZE=False,
            MAXSIZE="1000",
            IGNORE_COVERS=False,
            ANNUALS_ON=False,
            READ2FILENAME=False,
            ENABLE_TORRENTS=False,
        ),
    )
    with engine.begin() as conn:
        conn.execute(
            issues.insert(),
            [
                {
                    "IssueID": f"i{number}",
                    "ComicID": "series-1",
                    "Issue_Number": str(number),
                    "Int_IssueNumber": number * 1000,
                    "Status": "Downloaded" if number == 3 else "Wanted",
                }
                for number in (1, 2, 3)
            ],
        )
    yield engine
    engine.dispose()


def info(**overrides):
    values = {
        "ComicName": "Example Series",
        "nzbprov": "DDL(GetComics)",
        "RSS": "no",
        "UseFuzzy": "1",
        "StoreDate": "2024-01-01",
        "IssueDate": "2024-01-01",
        "digitaldate": "0000-00-00",
        "booktype": "Print",
        "ignore_booktype": False,
        "SeriesYear": "2024",
        "ComicVersion": None,
        "IssDateFix": "no",
        "ComicYear": "2024",
        "IssueID": "i1",
        "ComicID": "series-1",
        "IssueNumber": "1",
        "manual": True,
        "newznab_host": None,
        "torznab_host": None,
        "oneoff": False,
        "tmpprov": "DDL(GetComics)",
        "SARC": None,
        "IssueArcID": None,
        "cmloopit": 3,
        "findcomiciss": "1",
        "intIss": 1000,
        "chktpb": 0,
        "allow_packs": True,
        "provider_stat": {"type": "DDL", "id": 200, "active": True, "hits": 0},
    }
    values.update(overrides)
    return values


def entry(identity="11", **overrides):
    values = {
        "title": "Example Series 001 (2024)",
        "filename": "Example Series 001 (2024)",
        "link": f"https://provider.invalid/{identity}?apikey=private-key",
        "pubdate": "Wed, 10 Jan 2024 12:00:00 +0000",
        "length": "104857600",
        "site": "DDL(GetComics)",
        "id": identity,
        "pack": False,
        "size": "100M",
    }
    values.update(overrides)
    return values


def pack(identity="pack-1"):
    return entry(
        identity,
        title="Example Series 001-003 (2024)",
        pack=True,
        issues="1-3",
        series="Example Series",
        gc_booktype="issue",
        year="2024",
    )


def test_automatic_and_review_share_real_parser_verdicts():
    automatic = EvaluationSession().evaluate([entry()], info(manual=False))
    review = EvaluationSession(review=True).evaluate([entry()], info(manual=True))
    assert automatic.evaluations[0].verdict["accepted"] is True
    assert automatic.evaluations[0].as_dict() == review.evaluations[0].as_dict()
    assert "private-key" not in repr(review.evaluations[0])
    assert handoff_matches(automatic.selected)[0]["downloadit"] is True
    assert handoff_matches(review.selected)[0]["downloadit"] is False


def test_pack_satisfaction_and_claim_timing_use_library_rows():
    target = {"entity_type": "issue", "entity_id": "i1", "issue_number": "1"}
    eligible = {
        ("issue", f"i{n}"): {"entity_type": "issue", "entity_id": f"i{n}", "issue_number": str(n)} for n in (1, 2)
    }
    session = EvaluationSession(review=True, searched_item=target, eligible=eligible)
    result = session.evaluate([pack()], info()).selected[0]
    assert result.verdict["reason_code"] == "accepted.pack"
    assert result.satisfies == list(eligible.values())
    # These claims historically happen during evaluation, before any handoff.
    assert comicarr.PACK_ISSUEIDS_DONT_QUEUE == {"i1": "pack-1", "i2": "pack-1"}
    assert session.evaluations == [result]
    assert handoff_matches([result])[0]["pack_issuelist"]["valid"] is True


def test_duplicate_history_is_local_and_reset_per_batch():
    session = EvaluationSession(review=True)
    first = session.evaluate([entry(), entry()], info())
    assert [e.verdict["reason_code"] for e in first.evaluations] == ["accepted.issue", "blocked.duplicate"]
    # Preferred GetComics selection retains the preceding batch's history.
    assert session.evaluate([entry()], info(), prefer_pack=False).selected == []
    assert len(EvaluationSession().evaluate([entry()], info(), prefer_pack=False).selected) == 1
    assert len(session.evaluate([entry()], info()).selected) == 1
    session.start_search()
    assert len(session.evaluate([entry()], info(), prefer_pack=False).selected) == 1


def test_getcomics_stops_consuming_after_first_preferred_match():
    def entries():
        yield pack()
        yield entry()
        raise AssertionError("Automatic selection consumed past the preferred release")

    selected = EvaluationSession().evaluate(entries(), info(), prefer_pack=False).selected
    assert selected[0].verdict["reason_code"] == "accepted.issue"


def test_review_materializes_and_evaluates_every_getcomics_entry():
    consumed = []

    def entries():
        for candidate in [pack(), entry("12"), entry("13")]:
            consumed.append(candidate["id"])
            yield candidate

    session = EvaluationSession(review=True)
    selected = session.evaluate(entries(), info(), prefer_pack=False).selected
    assert consumed == ["pack-1", "12", "13"]
    assert len(session.evaluations) == 3
    assert handoff_matches(selected)[0]["nzbid"] == "12"


def test_getcomics_automatic_uses_last_fallback_review_uses_first():
    automatic = EvaluationSession().evaluate([entry("12"), entry("13")], info(), prefer_pack=True)
    review = EvaluationSession(review=True).evaluate([entry("12"), entry("13")], info(), prefer_pack=True)
    assert handoff_matches(automatic.selected)[0]["nzbid"] == "13"
    assert handoff_matches(review.selected)[0]["nzbid"] == "12"


def test_override_stays_local_and_bypasses_only_the_requested_reason():
    comicarr.CONFIG.IGNORE_SEARCH_WORDS = ["REPACK"]
    comicarr.CONFIG.USE_MAXSIZE = True
    comicarr.CONFIG.MAXSIZE = "1"
    candidate = entry(title="Example Series 001 REPACK (2024)")
    normal = EvaluationSession().evaluate([candidate], info()).evaluations[0]
    overridden = EvaluationSession(override_reason="ignored.search_word").evaluate([candidate], info()).evaluations[0]
    assert normal.verdict["reason_code"] == "ignored.search_word"
    assert overridden.verdict["reason_code"] == "rejected.size_above_max"
    assert not overridden.verdict["accepted"]


@pytest.mark.parametrize("review", [False, True])
def test_failed_batch_stops_at_error_and_does_not_publish_partial_review(review):
    def entries():
        yield entry()
        yield {"title": "Malformed"}
        raise AssertionError("Batch continued after an evaluator exception")

    session = EvaluationSession(review=review)
    batch = session.evaluate(entries(), info())
    assert batch.evaluations[-1].exception is not None
    with pytest.raises(type(batch.evaluations[-1].exception)):
        _ = batch.selected
    assert session.evaluations == []


def test_review_preferred_selection_retains_structured_errors():
    session = EvaluationSession(review=True)
    result = session.evaluate([{"title": "Malformed"}, entry()], info(), prefer_pack=False)
    assert len(result.selected) == 1
    assert session.evaluations[0].exception is not None


@pytest.mark.parametrize("volume,accepted", [("7", True), ("8", False), ("107", False)])
def test_manga_volume_query_uses_series_name_and_book_number(volume, accepted):
    result = (
        EvaluationSession()
        .evaluate(
            [entry(title=f"One Piece v{int(volume):02d} (2014) (Digital)")],
            info(
                ComicName="One Piece v07",
                manga_match_name="One Piece",
                ComicVersion="v1",
                booktype="manga",
                IssueNumber="7",
                findcomiciss="7",
                intIss=7000,
                SeriesYear="1997",
                ComicYear="1997",
                StoreDate="2026-01-01",
                IssueDate="2026-01-01",
            ),
        )
        .evaluations[0]
    )
    assert result.verdict["accepted"] is accepted, result.verdict


@pytest.mark.parametrize("review,expected_count", [(False, 2), (True, 3)])
@pytest.mark.parametrize("priority", [False, None])
def test_getcomics_caller_uses_the_supplied_evaluation_session(monkeypatch, review, expected_count, priority):
    from comicarr.getcomics import GC

    comicarr.CONFIG.PACK_PRIORITY = priority
    source = object.__new__(GC)
    source.search_format = ["%s %s"]
    source.query = {"comicname": "Example Series", "issue": "1", "year": "2024"}
    monkeypatch.setattr(source, "cookie_receipt", lambda: None)
    consumed = []

    def query(_queryline):
        for candidate in [pack(), entry("12"), entry("13")]:
            consumed.append(candidate["id"])
            yield candidate

    monkeypatch.setattr(source, "perform_search_queries", query)
    evaluator = EvaluationSession(review=review)
    selected = source.search(info(), evaluator=evaluator)
    assert handoff_matches(selected)[0]["nzbid"] == "12"
    assert len(consumed) == expected_count
    assert len(evaluator.evaluations) == (3 if review else 0)


def test_provider_search_collects_real_evaluations_without_handoff(monkeypatch):
    from comicarr import search

    monkeypatch.setattr(search.rsscheck, "ddl_dbsearch", lambda *_args: {"entries": [entry()]})
    monkeypatch.setattr(search.rsscheck, "ddlrss_pack_detect", lambda *_args: None)
    monkeypatch.setattr(search, "searcher", lambda *_args, **_kwargs: pytest.fail("Review attempted handoff"))
    evaluator = EvaluationSession(review=True)
    result = search.NZB_SEARCH(
        "Example Series",
        "1",
        "2024",
        "2024",
        None,
        "2024-01-01",
        "2024-01-01",
        {"DDL(GetComics)": {"type": "DDL", "id": 200, "active": True, "hits": 0, "lastrun": 0}},
        0,
        "no",
        "i1",
        "1",
        RSS="yes",
        ComicID="series-1",
        cmloopit=3,
        manual=True,
        digitaldate="0000-00-00",
        booktype="Print",
        evaluator=evaluator,
    )
    assert result["status"] is False
    assert len(evaluator.evaluations) == 1
    assert evaluator.evaluations[0].verdict["accepted"] is True
