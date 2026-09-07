#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""GetComics Vol. N titles must match a watched volume / one-shot series."""

from types import SimpleNamespace

import pytest

import comicarr
from comicarr import search_filer


@pytest.fixture(autouse=True)
def _search_environment(monkeypatch):
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
    monkeypatch.setattr(comicarr, "COMICINFO", [])
    monkeypatch.setattr(search_filer.search, "generate_id", lambda _provider, identity, _name: str(identity))


def _info(**overrides):
    values = {
        "ComicName": "Shepherdess Warriors",
        "nzbprov": "DDL(GetComics)",
        "RSS": "no",
        "UseFuzzy": "1",
        "StoreDate": "2024-06-19",
        "IssueDate": "2024-06-19",
        "digitaldate": "0000-00-00",
        "booktype": "One-Shot",
        "ignore_booktype": False,
        "SeriesYear": "2024",
        "ComicVersion": None,
        "IssDateFix": "no",
        "ComicYear": "2024",
        "IssueID": "issue-1",
        "ComicID": "comic-1",
        "IssueNumber": None,
        "manual": True,
        "newznab_host": None,
        "torznab_host": None,
        "oneoff": False,
        "tmpprov": "DDL(GetComics)",
        "SARC": None,
        "IssueArcID": None,
        "cmloopit": 4,
        "findcomiciss": None,
        "intIss": None,
        "chktpb": 0,
        "provider_stat": {"type": "DDL", "id": 200, "active": True, "hits": 0},
    }
    values.update(overrides)
    return values


def _entry(**overrides):
    values = {
        "title": "Shepherdess Warriors Vol. 1 (2024)",
        "filename": "Shepherdess Warriors Vol. 1 (2024)",
        "link": "https://getcomics.org/other-comics/shepherdess-warriors-vol-1-2024/",
        "pubdate": "Wed, 19 Jun 2024 12:00:00 +0000",
        "size": "150M",
        "length": "157286400",
        "site": "DDL(GetComics)",
        "id": "31921370",
        "pack": False,
        "series": "Shepherdess Warriors Vol. 1 (2024)",
        "gc_booktype": "issue",
        "issues": None,
        "year": "2024",
        "seeders": "0",
        "peers": "0",
    }
    values.update(overrides)
    return values


def test_getcomics_vol_1_matches_misclassified_oneshot():
    evaluation = search_filer.search_check().evaluate_entry(_entry(), _info())

    assert evaluation.verdict["accepted"] is True
    assert evaluation.verdict["reason_code"] == "accepted.issue"


def test_getcomics_vol_1_matches_tpb_volume():
    evaluation = search_filer.search_check().evaluate_entry(
        _entry(),
        _info(
            booktype="TPB",
            cmloopit=1,
            findcomiciss="1",
            intIss=1000,
            IssueNumber="1",
            chktpb=1,
            ComicVersion=None,
        ),
    )

    assert evaluation.verdict["accepted"] is True
    assert evaluation.verdict["reason_code"] == "accepted.issue"
