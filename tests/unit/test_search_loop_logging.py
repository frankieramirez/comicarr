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


def _torznab_providers(count):
    names = ["nyaa%s" % n for n in range(count)]
    return {
        "prov_order": ["torznab"] * count,
        "torznab_info": [
            {"provider": "torznab", "info": (name, "https://%s.test" % name, "0", "key", "8020")} for name in names
        ],
        "newznab_info": [],
        "totalproviders": count,
    }


def _patch_search_env(monkeypatch, providers):
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(
            ENABLE_RSS=True,
            ENABLE_TORRENT_SEARCH=True,
            SEARCH_DELAY=None,
            USENET_RETENTION=None,
            SNATCHED_HAVETOTAL=False,
        ),
        raising=False,
    )
    monkeypatch.setattr(search, "last_run_check", lambda **kwargs: {})
    monkeypatch.setattr(search, "provider_order", lambda initial_run=False, comic_id=None: _torznab_providers(providers))
    monkeypatch.setattr(search.helpers, "get_issue_title", lambda *args, **kwargs: None)
    monkeypatch.setattr(search.helpers, "block_provider_check", lambda *args, **kwargs: False)


@pytest.fixture
def search_env(monkeypatch):
    calls = []

    def fake_matrix(scarios):
        calls.append({"cmloopit": scarios["cmloopit"], "RSS": scarios["RSS"], "ComicName": scarios["ComicName"]})
        return {"status": False, "lastrun": 0}

    _patch_search_env(monkeypatch, providers=1)
    monkeypatch.setattr(search, "search_the_matrix", fake_matrix)
    return calls


def _run_search_init(alternate_search=None, *, review=False, rsschecker=None):
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
        rsschecker=rsschecker,
        ComicID="comic-1",
        allow_packs=1,
        manual=False,
        booktype=None,
        _ai_expanded=True,
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


def test_issue_search_summary_names_alternates_and_found_provider():
    line = search._issue_search_summary(
        "Batman",
        "42",
        "2016",
        ["nyaa"],
        ["rss"],
        ["Batman", "Dark Knight"],
        found_via="nyaa",
    )
    assert line == "[SEARCH] Batman (2016) #42: found via nyaa after rss; names: Dark Knight"


def test_default_log_file_is_50mb():
    assert REGISTRY["MAX_LOGSIZE"].default == 50_000_000
    assert REGISTRY["MAX_LOGFILES"].default == 5


def test_gen_altnames_emits_no_info(monkeypatch):
    info, debug = _capture_logs(monkeypatch)

    names = search.gen_altnames("Batman", "Dark Knight##Caped Crusader", None, "want")

    assert [x["ComicName"] for x in names] == ["Batman", "Dark Knight", "Caped Crusader"]
    assert info == []
    assert any("re-adjusting to : Dark Knight" in line for line in debug)
    assert any("re-adjusting to : Caped Crusader" in line for line in debug)


@pytest.mark.parametrize(
    ("providers", "alternate_search"),
    [(2, "Alias One##Alias Two"), (3, "Alias One##Alias Two##Alias Three")],
)
def test_rss_search_init_logs_one_info_line_per_issue(monkeypatch, providers, alternate_search):
    _patch_search_env(monkeypatch, providers)
    rss_lookups = []

    def no_results(findcomic, *args, **kwargs):
        rss_lookups.append(findcomic)
        return "no results"

    monkeypatch.setattr(search.rsscheck, "nzbdbsearch", no_results)
    info, debug = _capture_logs(monkeypatch)

    _run_search_init(alternate_search=alternate_search, rsschecker="yes")

    aliases = alternate_search.split("##")
    assert len(rss_lookups) >= providers * (len(aliases) + 1)
    assert len(info) == 1
    assert info[0].startswith("[SEARCH] Example Series (2024) #2: no match after rss across")
    assert "names: %s" % ", ".join(aliases) in info[0]
    for alias in aliases:
        assert any("comicname searched for: %s" % alias in line for line in debug)
    assert any(line.startswith("bb: ") for line in debug)
    assert any("Shhh be very quiet" in line for line in debug)


def test_search_init_found_exit_logs_summary(search_env, monkeypatch):
    monkeypatch.setattr(search, "search_the_matrix", lambda scarios: {"status": True, "lastrun": 0})
    info, _debug = _capture_logs(monkeypatch)

    findit, provider = _run_search_init(alternate_search="Alias One")

    assert findit["status"] is True
    summaries = [line for line in info if line.startswith("[SEARCH] Example Series")]
    assert summaries == ["[SEARCH] Example Series (2024) #2: found via %s after rss" % provider]


def test_search_init_blocked_provider_still_summarizes(search_env, monkeypatch):
    monkeypatch.setattr(search, "provider_order", lambda initial_run=False, comic_id=None: _torznab_providers(2))
    checks = []

    def block_after_first(*args, **kwargs):
        checks.append(1)
        return len(checks) > 1

    monkeypatch.setattr(search.helpers, "block_provider_check", block_after_first)
    info, _debug = _capture_logs(monkeypatch)

    _run_search_init(alternate_search="Alias One")

    summaries = [line for line in info if line.startswith("[SEARCH] Example Series")]
    assert len(summaries) == 1
    assert "no match" in summaries[0]


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
