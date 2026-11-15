#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Debug search and evaluation lines (#1017): findable text, read-only observation."""

import logging
import re
import types

import pytest

import comicarr
from comicarr import search
from comicarr.app.search.diagnostics import log_query, quoted, safe_provider_name
from comicarr.app.search.evaluation import EvaluationSession
from tests.unit import test_release_evaluation_integration as evaluation_fixtures

entry = evaluation_fixtures.entry
info = evaluation_fixtures.info
pack = evaluation_fixtures.pack
# The real parser and a SQLite library, shared with the evaluation contract tests.
library = evaluation_fixtures.library

PROVIDERS = {
    "NZBGeek": ("NZBGeek", "https://geek.private.example/", "1", "geek-secret-key", "7030"),
    "DrunkenSlug": ("DrunkenSlug", "https://slug.private.example/", "1", "slug-secret-key", "7030"),
}
SECRETS = ("geek-secret-key", "slug-secret-key", "private.example", "provider.invalid", "private-key", "http")

FEEDS = {
    "geek.private.example": [entry("11"), entry("12", title="Other Series 001 (2024)")],
    "slug.private.example": [pack(), entry("13", title="Example Series 001 (2019)")],
}


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def captured():
    handler = _Capture()
    comicarr_logger = logging.getLogger("comicarr")
    previous = comicarr_logger.level
    comicarr_logger.addHandler(handler)
    yield handler
    comicarr_logger.removeHandler(handler)
    comicarr_logger.setLevel(previous)


@pytest.fixture
def providers(monkeypatch):
    """Stub the network and the handoff; keep the real parser and evaluator."""
    for name, value in dict(ENABLE_TORRENT_SEARCH=False, USENET_RETENTION=None, SEARCH_DELAY=0).items():
        setattr(comicarr.CONFIG, name, value)
    record = types.SimpleNamespace(requests=[], selected=[])
    monkeypatch.setattr(search, "_indexer_cooldowns", {})
    monkeypatch.setattr(search, "last_run_check", lambda **kwargs: {})
    monkeypatch.setattr(search, "_honour_search_delay", lambda *args, **kwargs: None)
    monkeypatch.setattr(search, "check_the_search_delay", lambda *args, **kwargs: False)

    def get(url, **kwargs):
        record.requests.append(url)
        return types.SimpleNamespace(status_code=200, content=url.encode(), headers={}, raise_for_status=lambda: None)

    def parse(data):
        host = re.search(r"https://([^/]+)/", data.decode()).group(1)
        return {"feed": {}, "entries": [dict(candidate) for candidate in FEEDS[host]]}

    def verification(verified_matches, is_info):
        record.selected.append([(match.candidate["title"], match.verdict["reason_code"]) for match in verified_matches])

    monkeypatch.setattr(search, "get_http_session", lambda **kwargs: types.SimpleNamespace(get=get))
    monkeypatch.setattr(search.feedparser, "parse", parse)
    monkeypatch.setattr(search, "verification", verification)
    monkeypatch.setattr(
        search.rsscheck, "nzbdbsearch", lambda *args: {"entries": [entry("21", title="Example Series 001 (2024) RSS")]}
    )
    return record


def _search(name, rss="no"):
    return search.NZB_SEARCH(
        "Example Series",
        "1",
        "2024",
        "2024",
        None,
        "2024-01-01",
        "2024-01-01",
        {"newznab": {"type": "newznab", "id": 300, "lastrun": 0, "active": True, "hits": 0}},
        1,
        "no",
        "i1",
        "1",
        newznab_host=PROVIDERS[name],
        ComicID="series-1",
        cmloopit=3,
        RSS=rss,
        manual=False,
        digitaldate="0000-00-00",
        booktype="Print",
        evaluator=EvaluationSession(),
    )


def _run_everything():
    _search("NZBGeek")
    _search("DrunkenSlug")
    _search("NZBGeek", rss="yes")


def _new_lines(lines):
    return [line for line in lines if line.startswith(("[SEARCH-QUERY]", "[EVALUATION]"))]


def test_multi_provider_search_logs_query_counts_and_reasons(providers, captured):
    logging.getLogger("comicarr").setLevel(logging.DEBUG)

    _run_everything()

    lines = _new_lines(captured.lines)
    queries = [line for line in lines if line.startswith("[SEARCH-QUERY]")]
    assert queries == [
        '[SEARCH-QUERY] series=series-1 issue=i1 number=1 provider="NZBGeek" source=api '
        'query="example series 001" returned=2 kept=2',
        '[SEARCH-QUERY] series=series-1 issue=i1 number=1 provider="DrunkenSlug" source=api '
        'query="example series 001" returned=2 kept=2',
        '[SEARCH-QUERY] series=series-1 issue=i1 number=1 provider="NZBGeek" source=rss '
        'query="Example Series 001" returned=1 kept=1',
    ]
    summaries = [line for line in lines if " consumed=" in line]
    assert summaries[0] == (
        '[EVALUATION] series=series-1 issue=i1 provider="NZBGeek" consumed=2 accepted=1 selected=1 stopped=end'
    )
    assert len(summaries) == 3
    verdicts = [line for line in lines if line.startswith("[EVALUATION] candidate=")]
    assert verdicts[:2] == [
        '[EVALUATION] candidate="Example Series 001 (2024)" verdict=accepted reason=accepted.issue kind=standard',
        '[EVALUATION] candidate="Other Series 001 (2024)" verdict=rejected reason=rejected.series_mismatch kind=none',
    ]
    assert len(verdicts) == 5
    for line in lines:
        for secret in SECRETS:
            assert secret not in line


def test_search_behaves_the_same_at_log_level_0_and_2(providers, captured):
    runs = []
    for level in (logging.WARNING, logging.DEBUG):
        logging.getLogger("comicarr").setLevel(level)
        providers.requests.clear()
        providers.selected.clear()
        comicarr.PACK_ISSUEIDS_DONT_QUEUE.clear()
        captured.lines.clear()
        _run_everything()
        runs.append(
            (
                list(providers.requests),
                list(providers.selected),
                dict(comicarr.PACK_ISSUEIDS_DONT_QUEUE),
                list(captured.lines),
            )
        )

    quiet, debug = runs
    assert quiet[:3] == debug[:3]
    assert debug[1], "the stub search selected nothing, so it proves nothing"
    assert _new_lines(quiet[3]) == []
    assert _new_lines(debug[3])


def test_getcomics_consumes_as_much_at_level_2_as_at_level_0(captured):
    def consumed_at(level):
        logging.getLogger("comicarr").setLevel(level)
        seen = []

        def entries():
            for candidate in (pack(), entry(), entry("12")):
                seen.append(candidate["id"])
                yield candidate

        EvaluationSession().evaluate(entries(), info(), prefer_pack=False).selected
        return seen

    assert consumed_at(logging.WARNING) == consumed_at(logging.DEBUG) == ["pack-1", "11"]
    assert '" verdict=accepted reason=accepted.issue' in captured.lines[-1]
    assert "stopped=preferred" in captured.lines[-3]


def test_getcomics_query_line_has_no_counts(captured):
    logging.getLogger("comicarr").setLevel(logging.DEBUG)
    log_query(info(), "getcomics", "Example Series 001 2024")
    assert captured.lines[-1] == (
        '[SEARCH-QUERY] series=series-1 issue=i1 number=1 provider="DDL(GetComics)" source=getcomics '
        'query="Example Series 001 2024"'
    )


def test_provider_names_that_look_like_urls_are_replaced():
    assert safe_provider_name(info(nzbprov="newznab", newznab_host=("https://u:p@host/api?apikey=x", "", "1", "", "")))[
        0
    ] == ("Usenet provider")


def test_quoted_text_escapes_quotes_and_redacts_keys():
    assert quoted('C:\\x "hi" apikey=abc123') == '"C:\\\\x \\"hi\\" apikey=[redacted]"'
