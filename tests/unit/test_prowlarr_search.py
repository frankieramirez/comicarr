#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import json
import types
from types import SimpleNamespace

import pytest
import requests

import comicarr
from comicarr import search
from comicarr.app.search import prowlarr
from comicarr.app.search.evaluation import EvaluationSession
from comicarr.app.search.providers import effective_provider_plan
from comicarr.app.system import service as system_service
from comicarr.config import Config
from tests.unit.test_system_domain import _make_test_ctx

RESULTS = [
    {
        "protocol": "torrent",
        "title": "Example Series 002 (2024)",
        "downloadUrl": "http://prowlarr.test/3/download?apikey=key&link=abc",
        "guid": "https://tracker.test/torrents/42",
        "publishDate": "2024-01-10T12:00:00Z",
        "size": 52428800,
        "seeders": 12,
        "leechers": 1,
        "indexer": "Tracker",
    },
    {
        "protocol": "torrent",
        "title": "Example Series 002 (2024) (magnet)",
        "magnetUrl": "magnet:?xt=urn:btih:abc",
        "publishDate": "2024-01-11T08:30:00+00:00",
        "size": 1000,
    },
    {
        "protocol": "usenet",
        "title": "Example Series 002 (2024) nzb",
        "downloadUrl": "http://prowlarr.test/7/download?apikey=key",
        "publishDate": "2024-01-10T12:00:00Z",
    },
    {"protocol": "torrent", "title": "No link", "publishDate": "2024-01-10T12:00:00Z"},
    {"protocol": "torrent", "title": "No date", "downloadUrl": "http://prowlarr.test/1/download"},
]


def _config(**overrides):
    values = {
        "ENABLE_TORRENT_SEARCH": True,
        "ENABLE_PROWLARR": True,
        "PROWLARR_HOST": "http://prowlarr.test:9696/",
        "PROWLARR_APIKEY": "key",
        "PROWLARR_CATEGORIES": "7030,7010",
        "PROWLARR_VERIFY": False,
        "PROVIDER_ORDER": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_only_torrent_results_with_a_link_and_date_are_kept():
    entries = prowlarr.entries_from_response(json.dumps(RESULTS))

    assert [entry["title"] for entry in entries] == [
        "Example Series 002 (2024)",
        "Example Series 002 (2024) (magnet)",
    ]
    first, magnet = entries
    assert first["link"] == "http://prowlarr.test/3/download?apikey=key&link=abc"
    assert first["id"] == "https://tracker.test/torrents/42"
    assert first["pubdate"] == "Wed, 10 Jan 2024 12:00:00 +0000"
    assert first.enclosures[0]["length"] == "52428800"
    assert first["seeders"] == 12
    assert "site" not in first
    assert magnet["link"] == "magnet:?xt=urn:btih:abc"
    assert magnet["id"] == "magnet:?xt=urn:btih:abc"


@pytest.mark.parametrize("body", [b"<html>login</html>", b'{"message": "Unauthorized"}'])
def test_a_body_that_is_not_a_result_list_is_an_error(body):
    with pytest.raises(ValueError):
        prowlarr.entries_from_response(body)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("http://prowlarr.test:9696/", "http://prowlarr.test:9696"),
        ("http://prowlarr.test:9696/api/v1/search", "http://prowlarr.test:9696"),
        ("https://example.test/prowlarr/api/v1", "https://example.test/prowlarr"),
        (None, ""),
    ],
)
def test_base_url_drops_a_pasted_api_path(host, expected):
    assert prowlarr.base_url(host) == expected


def test_categories_fall_back_to_comics():
    assert prowlarr.categories("7030, 7010#abc") == ["7030", "7010"]
    assert prowlarr.categories("") == ["7030"]
    assert prowlarr.categories(None) == ["7030"]


def test_plan_runs_prowlarr_as_one_torrent_provider():
    plan = effective_provider_plan(_config())

    assert [(c.name, c.kind, c.execution_name) for c in plan] == [("Prowlarr", "torznab", "torznab: Prowlarr")]
    assert plan[0].route == "torrent"
    assert plan[0].entry == (
        "Prowlarr",
        "http://prowlarr.test:9696/api/v1/search",
        "0",
        "key",
        "7030#7010",
        "1",
        prowlarr.PROWLARR_PROVIDER_ID,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"ENABLE_PROWLARR": False},
        {"ENABLE_TORRENT_SEARCH": False},
        {"PROWLARR_HOST": ""},
        {"PROWLARR_APIKEY": None},
    ],
)
def test_prowlarr_is_left_out_until_fully_configured(overrides):
    assert effective_provider_plan(_config(**overrides)) == []


def test_series_override_can_exclude_prowlarr():
    plan = effective_provider_plan(_config(), override={"exclude": ["Prowlarr"]})

    assert plan == []


def test_prowlarr_has_a_fixed_provider_search_identity():
    assert Config._provider_search_identity("Prowlarr", [], []) == ("Prowlarr", "torznab", 202)


def test_a_saved_indexer_cannot_take_the_prowlarr_name_while_prowlarr_is_on():
    flags = {"ENABLE_32P": False, "EXPERIMENTAL": False, "ENABLE_DDL": False}
    torznab = [("prowlarr", "http://prowlarr.test:9696/1/api", "0", "key", "7030", "1", 5)]

    with pytest.raises(ValueError, match="unique"):
        Config._validate_provider_names(torznab, Config._reserved_provider_names(_config(**flags)))
    Config._validate_provider_names(torznab, Config._reserved_provider_names(_config(ENABLE_PROWLARR=False, **flags)))


@pytest.fixture
def prowlarr_env(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "_indexer_cooldowns", {})
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(ENABLE_TORRENT_SEARCH=True, USENET_RETENTION=None, SEARCH_DELAY=5),
    )
    monkeypatch.setattr(search, "last_run_check", lambda **kwargs: {})
    monkeypatch.setattr(search.time, "sleep", lambda seconds: None)
    evaluated = []

    def evaluate(self, entries, is_info=None, **kwargs):
        evaluated.append(list(entries))
        return types.SimpleNamespace(selected="no results")

    monkeypatch.setattr(EvaluationSession, "evaluate", evaluate)
    responses = {"status": 200, "body": json.dumps(RESULTS).encode()}

    def get(url, **kwargs):
        calls.append(url)
        response = requests.Response()
        response.status_code = responses["status"]
        response._content = responses["body"]
        return response

    monkeypatch.setattr(search, "get_http_session", lambda **kwargs: types.SimpleNamespace(get=get))
    return SimpleNamespace(calls=calls, evaluated=evaluated, responses=responses)


def _run(entry):
    return search.NZB_SEARCH(
        "Example Series",
        "2",
        "2024",
        "2024",
        None,
        "2024-01-01",
        "2024-01-01",
        {"Prowlarr": {"type": "torznab", "id": 202, "lastrun": 0, "active": True, "hits": 0}},
        1,
        "no",
        "issue-1",
        "0",
        cmloopit=3,
        RSS="no",
        manual=True,
        torznab_host=entry,
        evaluator=EvaluationSession(),
    )


def test_search_asks_prowlarr_once_and_evaluates_its_torrent_results(prowlarr_env):
    _run(prowlarr.provider_entry(_config()))

    assert prowlarr_env.calls == [
        "http://prowlarr.test:9696/api/v1/search?type=search&limit=100&query=example%20series%20002"
        "&categories=7030&categories=7010&apikey=key"
    ]
    assert [entry["title"] for entry in prowlarr_env.evaluated[0]] == [
        "Example Series 002 (2024)",
        "Example Series 002 (2024) (magnet)",
    ]


def test_a_torznab_indexer_still_gets_a_torznab_query(prowlarr_env):
    prowlarr_env.responses["body"] = b"<rss><channel></channel></rss>"

    _run(("Tracker", "http://prowlarr.test:9696/3/api", "0", "key", "7030"))

    assert prowlarr_env.calls == [
        "http://prowlarr.test:9696/3/api?t=search&q=example%20series%20002&cat=7030&apikey=key"
    ]


def test_an_unreadable_prowlarr_answer_is_reported_not_evaluated(prowlarr_env, monkeypatch):
    failures = []
    monkeypatch.setattr(search.progress, "report_provider_failure", lambda *args: failures.append(args))
    prowlarr_env.responses["body"] = b"<html>Sign in</html>"

    result = _run(prowlarr.provider_entry(_config()))

    assert result["status"] is False
    assert prowlarr_env.evaluated == []
    assert failures and failures[0][1] == "request_error"


@pytest.fixture(autouse=True)
def _restore_global_config(monkeypatch):
    # A successful settings save publishes ctx.config as comicarr.CONFIG.
    monkeypatch.setattr(comicarr, "CONFIG", comicarr.CONFIG)


def _ctx(**config):
    ctx = _make_test_ctx()
    values = {
        "EXTRA_NEWZNABS": [],
        "EXTRA_TORZNABS": [],
        "PROWLARR_HOST": "http://prowlarr.test:9696",
        "PROWLARR_APIKEY": "stored-key",
        "PROWLARR_VERIFY": True,
        "ENABLE_PROWLARR": False,
    }
    values.update(config)
    for key, value in values.items():
        setattr(ctx.config, key, value)
    ctx.config.apply_transaction.return_value = True
    return ctx


def test_moving_prowlarr_to_another_server_needs_its_key():
    ctx = _ctx()

    result = system_service.update_config(ctx, {"prowlarr_host": "http://elsewhere.test:9696"})

    assert result == {"success": False, "error": "Prowlarr API key is required when changing the server origin"}
    ctx.config.apply_transaction.assert_not_called()


def test_prowlarr_categories_are_normalized_on_save():
    ctx = _ctx()

    assert system_service.update_config(ctx, {"prowlarr_categories": "7030 7010, junk"})["success"] is True

    assert ctx.config.apply_transaction.call_args.args[0]["PROWLARR_CATEGORIES"] == "7030,7010"


def test_turning_on_prowlarr_is_refused_while_an_indexer_is_named_prowlarr():
    ctx = _ctx(EXTRA_TORZNABS=[("Prowlarr", "http://prowlarr.test:9696/1/api", "0", "key", "7030", "1", 5)])

    result = system_service.update_config(ctx, {"enable_prowlarr": True})

    assert result["success"] is False
    assert "Rename the indexer" in result["error"]


def test_an_indexer_cannot_take_the_prowlarr_name_while_prowlarr_is_on():
    ctx = _ctx(ENABLE_PROWLARR=True)
    providers = [
        {
            "name": "prowlarr",
            "host": "http://prowlarr.test:9696/1/api",
            "verify": True,
            "api_key": "key",
            "categories": "7030",
            "enabled": True,
        }
    ]

    result = system_service.update_providers(ctx, {"type": "torznab", "providers": providers})

    assert result["success"] is False


def test_get_config_never_returns_the_prowlarr_key():
    ctx = _ctx(PROWLARR_HOST="http://user:pass@prowlarr.test:9696")

    result = system_service.get_safe_config(ctx)

    assert result["prowlarr_apikey_set"] is True
    assert "prowlarr_apikey" not in result
    assert result["prowlarr_host"] == "http://prowlarr.test:9696"


class _Response:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def test_connection_test_uses_the_stored_key_and_counts_torrent_indexers(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, allow_redirects=True, verify=None, timeout=None):
        seen.update(url=url, headers=headers, allow_redirects=allow_redirects, verify=verify)
        return _Response(
            200,
            [
                {"protocol": "torrent", "enable": True},
                {"protocol": "torrent", "enable": False},
                {"protocol": "usenet", "enable": True},
            ],
        )

    monkeypatch.setattr(prowlarr.requests, "get", fake_get)

    result = system_service.check_prowlarr_connection(_ctx(), {"host": "http://prowlarr.test:9696", "api_key": ""})

    assert result == {"success": True, "torrent_indexers": 1, "indexers": 3}
    assert seen == {
        "url": "http://prowlarr.test:9696/api/v1/indexer",
        "headers": {"X-Api-Key": "stored-key"},
        "allow_redirects": False,
        "verify": True,
    }


def test_connection_test_never_sends_the_stored_key_to_another_server(monkeypatch):
    monkeypatch.setattr(prowlarr.requests, "get", lambda *a, **k: pytest.fail("contacted another server"))

    result = system_service.check_prowlarr_connection(_ctx(), {"host": "http://elsewhere.test:9696"})

    assert result == {"success": False, "error": "Enter the Prowlarr URL and API key"}


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (_Response(401, []), "Prowlarr rejected the API key"),
        (_Response(500, []), "Prowlarr answered with HTTP 500"),
        (_Response(302, []), "Prowlarr answered with HTTP 302"),
        (_Response(200, ValueError("html")), "That URL did not answer like Prowlarr"),
    ],
)
def test_connection_test_explains_failures(monkeypatch, response, error):
    monkeypatch.setattr(prowlarr.requests, "get", lambda *a, **k: response)

    assert prowlarr.check_connection("http://prowlarr.test", "key") == {"success": False, "error": error}
