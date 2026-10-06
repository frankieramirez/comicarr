#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Search-loop INFO volume (#957): per-iteration chatter is debug; one summary stays."""

import types

import pytest

import comicarr
from comicarr import search
from comicarr.app.config.registry import REGISTRY
from comicarr.app.search.evaluation import EvaluationSession


def _capture_logs(monkeypatch):
    info = []
    debug = []
    monkeypatch.setattr(search.logger, "info", lambda msg, *a, **k: info.append(str(msg)))
    monkeypatch.setattr(search.logger, "fdebug", lambda msg, *a, **k: debug.append(str(msg)))
    return info, debug


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


def _run_search_init(alternate_search=None, *, review=False):
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
        allow_packs=1,
        manual=False,
        booktype=None,
        evaluator=EvaluationSession(review=review),
    )


def test_issue_search_summary_names_providers_and_modes():
    line = search._issue_search_summary(
        "Batman",
        "42",
        "2016",
        ["nyaa", "NZBGeek"],
        ["rss", "api"],
    )
    assert line == "[SEARCH] Batman (2016) #42: no match after rss+api across 2 provider(s) (nyaa, NZBGeek)"


def test_default_log_file_is_50mb():
    assert REGISTRY["MAX_LOGSIZE"].default == 50_000_000
    assert REGISTRY["MAX_LOGFILES"].default == 5


def test_gen_altnames_logs_details_once_per_series(monkeypatch):
    info, debug = _capture_logs(monkeypatch)
    search.reset_gen_altnames_log()

    first = search.gen_altnames("Batman", "Dark Knight##Caped Crusader", None, "want")
    assert [x["ComicName"] for x in first] == ["Batman", "Dark Knight", "Caped Crusader"]
    assert sum("re-adjusting to : Dark Knight" in line for line in info) == 1
    assert sum("re-adjusting to : Caped Crusader" in line for line in info) == 1
    assert any("searchlist:" in line for line in info)
    assert not any("re-adjusting" in line for line in debug)

    info.clear()
    second = search.gen_altnames("Batman", "Dark Knight##Caped Crusader", None, "want")
    assert first == second
    assert not any("re-adjusting" in line for line in info)
    assert any("re-adjusting to : Dark Knight" in line for line in debug)

    search.gen_altnames("Superman", "Man of Steel", None, "want")
    assert any("re-adjusting to : Man of Steel" in line for line in info)


def test_reset_gen_altnames_log_reannounces_the_series(monkeypatch):
    info, _debug = _capture_logs(monkeypatch)
    search.reset_gen_altnames_log()
    search.gen_altnames("Batman", "Dark Knight", None, "want")
    info.clear()
    search.reset_gen_altnames_log()
    search.gen_altnames("Batman", "Dark Knight", None, "want")
    assert any("re-adjusting to : Dark Knight" in line for line in info)


def test_search_init_does_not_info_log_per_iteration(search_env, monkeypatch):
    search.reset_gen_altnames_log()
    info, debug = _capture_logs(monkeypatch)

    _run_search_init(alternate_search="Alias One##Alias Two")

    assert not any("comicname searched for" in line for line in info)
    assert not any("searchmode enabled" in line.lower() for line in info)
    assert not any("Could not find" in line for line in info)
    assert not any(line.startswith("bb:") for line in info)
    assert not any("Shhh be very quiet" in line for line in info)
    summaries = [line for line in info if line.startswith("[SEARCH] Example Series")]
    assert len(summaries) == 1
    assert "no match after rss+api" in summaries[0]
    assert "nyaa" in summaries[0]
    assert any("comicname searched for: Alias One" in line for line in debug)
    assert any("comicname searched for: Alias Two" in line for line in debug)


def test_search_init_calls_gen_altnames_once_per_searchmode(search_env, monkeypatch):
    calls = []
    real = search.gen_altnames

    def wrapped(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(search, "gen_altnames", wrapped)
    _run_search_init(alternate_search="Alias One##Alias Two")
    assert len(calls) == 2
    assert [call["ComicName"] for call in search_env][:3] == ["Example Series", "Alias One", "Alias Two"]
