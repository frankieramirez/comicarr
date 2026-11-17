#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Generated manga chapter terms are searched once, as-is.

"<series> c002" and "<series> chapter 002" already carry the chapter number.
Running them through the issue-number padding passes sent queries such as
"<series> c002 02" and multiplied the queries per provider for chapters 1-99.
"""

import json
import types

import pytest
import requests

import comicarr
from comicarr import search
from comicarr.app.search import prowlarr
from comicarr.app.search import service as search_service
from comicarr.app.search.evaluation import EvaluationSession
from comicarr.app.series import service as series_service

SERIES = "Example Manga"
CHAPTER_TERMS = ["Example Manga c002", "Example Manga chapter 002"]


@pytest.fixture
def passes(monkeypatch):
    calls = []

    def fake_matrix(scarios):
        calls.append((scarios["ComicName"], scarios["cmloopit"], scarios["RSS"]))
        return {"status": False, "lastrun": 0}

    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(ENABLE_RSS=False, ENABLE_TORRENT_SEARCH=True, SEARCH_DELAY=None, USENET_RETENTION=None),
        raising=False,
    )
    monkeypatch.setattr(search, "search_the_matrix", fake_matrix)
    monkeypatch.setattr(search, "last_run_check", lambda **kwargs: {})
    monkeypatch.setattr(
        search,
        "provider_order",
        lambda initial_run=False, comic_id=None: {
            "prov_order": ["torznab"],
            "torznab_info": [{"provider": "torznab", "info": ("tracker", "https://tracker.test", "0", "key", "8020")}],
            "newznab_info": [],
            "totalproviders": 1,
        },
    )
    monkeypatch.setattr(series_service, "get_issue_title", lambda *args, **kwargs: None)
    monkeypatch.setattr(search_service, "block_provider_check", lambda *args, **kwargs: False)
    return calls


def _use_provider(monkeypatch, kind):
    info = {"provider": kind, "info": ("indexer", "https://indexer.test", "0", "key", "8020")}
    monkeypatch.setattr(
        search,
        "provider_order",
        lambda initial_run=False, comic_id=None: {
            "prov_order": [kind],
            "torznab_info": [info] if kind == "torznab" else [],
            "newznab_info": [info] if kind == "newznab" else [],
            "totalproviders": 1,
        },
    )


def _search_chapter_two(alternate_search=None):
    search.search_init(
        SERIES,
        "2",
        "2024",
        "2024",
        None,
        "2024-01-01",
        "2024-01-01",
        "issue-2",
        AlternateSearch=alternate_search,
        ComicID="comic-1",
        allow_packs=1,
        content_type="manga",
        chapter_number="2",
        evaluator=EvaluationSession(),
    )


NON_LATIN_ALTS = "Exemple Manga##\u30c0\u30f3\u30c0\u30c0\u30f3##\u65b0\u7248##\u062f\u0627\u0646"


def test_usenet_skips_alternate_titles_without_latin_letters(monkeypatch, passes):
    _use_provider(monkeypatch, "newznab")

    _search_chapter_two(NON_LATIN_ALTS)

    api = [(name, loop) for name, loop, rss in passes if rss == "no"]
    assert sorted({name for name, _ in api}) == sorted([SERIES, "Exemple Manga", *CHAPTER_TERMS])
    # Two names x three paddings, plus each chapter term once. The bare pack
    # pass (loop 0) sends no query to a usenet indexer.
    assert len([name for name, loop in api if loop != 0]) == 2 * 3 + 2
    assert search._bare_pack_pass_allowed({"type": "newznab"}) is False


def test_torrents_keep_every_alternate_title(monkeypatch, passes):
    _use_provider(monkeypatch, "torznab")

    _search_chapter_two(NON_LATIN_ALTS)

    names = {name for name, loop, rss in passes if rss == "no"}
    assert len(names) == 2 + 3 + 2


def test_a_non_latin_series_name_is_still_searched_on_usenet(monkeypatch, passes):
    _use_provider(monkeypatch, "newznab")
    name = "\u30c0\u30f3\u30c0\u30c0\u30f3"

    search.search_init(
        name,
        "2",
        "2024",
        "2024",
        None,
        "2024-01-01",
        "2024-01-01",
        "issue-2",
        ComicID="comic-1",
        allow_packs=1,
        content_type="manga",
        chapter_number="2",
        evaluator=EvaluationSession(),
    )

    assert name in {n for n, loop, rss in passes if rss == "no"}


def test_chapter_terms_run_once_per_provider_and_the_plain_name_keeps_its_passes(passes):
    search.search_init(
        SERIES,
        "2",
        "2024",
        "2024",
        None,
        "2024-01-01",
        "2024-01-01",
        "issue-2",
        ComicID="comic-1",
        allow_packs=1,
        content_type="manga",
        chapter_number="2",
        evaluator=EvaluationSession(),
    )

    api = [(name, loop) for name, loop, rss in passes if rss == "no"]
    for term in CHAPTER_TERMS:
        assert [loop for name, loop in api if name == term] == [3], term
    # The plain series name still gets every padding pass plus the pack pass.
    assert [loop for name, loop in api if name == SERIES] == [3, 2, 1, 0]
    assert len(api) == 6


@pytest.fixture
def prowlarr_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "_indexer_cooldowns", {})
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(ENABLE_TORRENT_SEARCH=True, USENET_RETENTION=None, SEARCH_DELAY=5),
    )
    monkeypatch.setattr(search, "last_run_check", lambda **kwargs: {})
    monkeypatch.setattr(search.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        EvaluationSession,
        "evaluate",
        lambda self, entries, is_info=None, **kw: types.SimpleNamespace(selected="no results"),
    )

    def get(url, **kwargs):
        calls.append(url)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps([]).encode()
        return response

    monkeypatch.setattr(search, "get_http_session", lambda **kwargs: types.SimpleNamespace(get=get))
    return calls


@pytest.mark.parametrize("cmloopit", [3, 2, 1])
def test_a_chapter_term_is_sent_without_an_appended_number(prowlarr_calls, cmloopit):
    entry = prowlarr.provider_entry(
        types.SimpleNamespace(
            ENABLE_TORRENT_SEARCH=True,
            ENABLE_PROWLARR=True,
            PROWLARR_HOST="http://prowlarr.test:9696/",
            PROWLARR_APIKEY="key",
            PROWLARR_CATEGORIES="7030",
            PROWLARR_VERIFY=False,
            PROVIDER_ORDER={},
        )
    )
    search.NZB_SEARCH(
        CHAPTER_TERMS[0],
        "2",
        "2024",
        "2024",
        None,
        "2024-01-01",
        "2024-01-01",
        {"Prowlarr": {"type": "torznab", "id": 202, "lastrun": 0, "active": True, "hits": 0}},
        1,
        "no",
        "issue-2",
        "0",
        cmloopit=cmloopit,
        RSS="no",
        manual=True,
        torznab_host=entry,
        manga_chapter_terms=frozenset(CHAPTER_TERMS),
        evaluator=EvaluationSession(),
    )

    assert len(prowlarr_calls) == 1
    assert "query=example%20manga%20c002&" in prowlarr_calls[0]
