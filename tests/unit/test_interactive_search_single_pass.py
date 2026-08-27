#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Interactive review collection fires one live query per provider (#768).

The automatic search flow retries on purpose: RSS cache first, then padded
issue-number variants, with a backoff sleep between provider queries. When an
operator is reviewing results interactively, those layers only add latency, so
collection runs exactly one numbered API query per provider (plus the
bare-title pack pass that pack discovery depends on, #744) and never sleeps.
"""

import time
import types

import pytest

import comicarr
from comicarr import search, search_filer


def _noop_collection():
    return search_filer.interactive_collection(
        on_evaluations=lambda values: None,
        on_provider_complete=lambda provider: None,
        on_provider_failure=lambda provider, code, detail: None,
    )


def test_interactive_collection_active_only_inside_context():
    assert search_filer.interactive_collection_active() is False
    with _noop_collection():
        assert search_filer.interactive_collection_active() is True
    assert search_filer.interactive_collection_active() is False


@pytest.fixture
def search_env(monkeypatch):
    calls = []

    def fake_matrix(scarios):
        calls.append({"cmloopit": scarios["cmloopit"], "RSS": scarios["RSS"], "ComicName": scarios["ComicName"]})
        return {"status": False, "lastrun": 0}

    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(
            ENABLE_RSS=True,
            ENABLE_TORRENT_SEARCH=True,
            SEARCH_DELAY=None,
            USENET_RETENTION=None,
        ),
        raising=False,
    )
    monkeypatch.setattr(comicarr, "COMICINFO", [], raising=False)
    monkeypatch.setattr(search, "search_the_matrix", fake_matrix)
    monkeypatch.setattr(search, "last_run_check", lambda **kwargs: {})
    monkeypatch.setattr(
        search,
        "provider_order",
        lambda initial_run=False: {
            "prov_order": ["torznab"],
            "torznab_info": [{"provider": "torznab", "info": ("nyaa", "https://nyaa.test", "0", "key", "8020")}],
            "newznab_info": [],
            "totalproviders": 1,
        },
    )
    monkeypatch.setattr(search.helpers, "get_issue_title", lambda *args, **kwargs: None)
    monkeypatch.setattr(search.helpers, "block_provider_check", lambda *args, **kwargs: False)
    return calls


def _run_search_init(allow_packs=1, alternate_search=None):
    return search.search_init(
        "Example Series",
        "2",
        "2024",
        "2024",
        None,
        "2024-01-01",
        "2024-01-01",
        "issue-1",
        AlternateSearch=alternate_search,
        smode=None,
        ComicID="comic-1",
        allow_packs=allow_packs,
        manual=True,
        booktype=None,
    )


def test_automatic_search_keeps_rss_and_variant_passes(search_env):
    _run_search_init()

    rss_passes = [call for call in search_env if call["RSS"] == "yes"]
    api_passes = [call for call in search_env if call["RSS"] == "no"]
    assert rss_passes, "automatic search must still run the RSS cache pass"
    assert [call["cmloopit"] for call in api_passes] == [3, 2, 1, 0]


def test_interactive_search_runs_single_query_plus_pack_pass(search_env):
    with _noop_collection():
        _run_search_init()

    assert all(call["RSS"] == "no" for call in search_env), "interactive search must not run the RSS pass"
    assert [call["cmloopit"] for call in search_env] == [3, 0]


def test_interactive_search_without_packs_runs_exactly_one_query(search_env):
    with _noop_collection():
        _run_search_init(allow_packs=0)

    assert [call["cmloopit"] for call in search_env] == [3]


def test_interactive_search_keeps_alternate_names_but_stays_bounded(search_env):
    # Alternate names are distinct titles (aliases, manga chapter forms), not
    # padding retries: each still gets its own query, so total interactive
    # queries per provider are bounded at names x passes (at most two passes).
    with _noop_collection():
        _run_search_init(alternate_search="Alias One##Alias Two")

    assert [call["cmloopit"] for call in search_env] == [3, 3, 3, 0, 0, 0]
    names = [call["ComicName"] for call in search_env]
    assert names[:3] == ["Example Series", "Alias One", "Alias Two"]
    assert names[3:] == ["Example Series", "Alias One", "Alias Two"]


def test_search_delay_sleeps_for_automatic_search(monkeypatch):
    slept = []
    monkeypatch.setattr(search.time, "sleep", lambda seconds: slept.append(seconds))

    search._honour_search_delay("nyaa", 30, time.time())

    assert len(slept) == 1


def test_search_delay_never_sleeps_for_interactive_search(monkeypatch):
    slept = []
    monkeypatch.setattr(search.time, "sleep", lambda seconds: slept.append(seconds))

    with _noop_collection():
        search._honour_search_delay("nyaa", 30, time.time())

    assert slept == []


def test_search_delay_noop_outside_backoff_window(monkeypatch):
    slept = []
    monkeypatch.setattr(search.time, "sleep", lambda seconds: slept.append(seconds))

    search._honour_search_delay("nyaa", 30, 0)
    search._honour_search_delay("nyaa", 30, time.time() - 3600)

    assert slept == []
