#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
import requests

import comicarr
from comicarr import search
from comicarr.app.search.evaluation import EvaluationSession


@pytest.fixture
def indexer_env(monkeypatch):
    calls = []
    clock = [1000.0]
    monkeypatch.setattr(search, "_indexer_cooldowns", {})
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(
            ENABLE_TORRENT_SEARCH=True,
            USENET_RETENTION=None,
            SEARCH_DELAY=5,
        ),
    )
    monkeypatch.setattr(search.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(search, "last_run_check", lambda **kwargs: {})
    monkeypatch.setattr(search.time, "sleep", lambda seconds: pytest.fail(f"search slept for {seconds}s"))

    def get(url, **kwargs):
        calls.append(url)
        response = requests.Response()
        response.status_code = 429
        response.headers["Retry-After"] = "70129"
        return response

    monkeypatch.setattr(search, "get_http_session", lambda **kwargs: types.SimpleNamespace(get=get))
    return calls, clock, get


def run_indexer(kind="torznab", host="http://indexer.test/9/api", *, review=False):
    return search.NZB_SEARCH(
        "Example Series",
        "2",
        "2024",
        "2024",
        None,
        "2024-01-01",
        "2024-01-01",
        {"example": {"type": kind, "id": 1, "lastrun": 0, "active": True, "hits": 0}},
        1,
        "no",
        "issue-1",
        "0",
        cmloopit=3,
        RSS="no",
        manual=True,
        **{f"{kind}_host": ("example", host, "0", "key", "7030")},
        evaluator=EvaluationSession(review=review),
    )


@pytest.mark.parametrize("kind", ["torznab", "newznab"])
@pytest.mark.parametrize("review", [False, True])
def test_rate_limited_indexer_is_skipped_until_deadline(indexer_env, monkeypatch, kind, review):
    calls, clock, _ = indexer_env
    warnings = []
    monkeypatch.setattr(search.logger, "warn", warnings.append)
    assert run_indexer(kind, review=review)["status"] is False
    clock[0] = 71128
    run_indexer(kind, review=review)
    assert len(calls) == 1
    assert any("cooldown" in line and "Skipping" in line for line in warnings)
    clock[0] = 71129
    run_indexer(kind, review=review)
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("header", "duration"),
    [("Thu, 01 Jan 1970 00:18:20 GMT", 100), (None, 60), ("broken", 60), ("-5", 60), ("9" * 400, 60)],
)
def test_retry_after_date_and_fallback(indexer_env, monkeypatch, header, duration):
    calls, clock, get = indexer_env
    monkeypatch.setattr(search.time, "time", lambda: 1000)

    def response(url, **kwargs):
        result = get(url, **kwargs)
        result.headers.clear()
        if header is not None:
            result.headers["Retry-After"] = header
        return result

    monkeypatch.setattr(search, "get_http_session", lambda **kwargs: types.SimpleNamespace(get=response))
    run_indexer()
    clock[0] = 1000 + duration - 1
    run_indexer()
    assert len(calls) == 1
    clock[0] += 1
    run_indexer()
    assert len(calls) == 2


def test_cooldown_is_scoped_to_indexer_endpoint(indexer_env):
    calls, _, _ = indexer_env
    run_indexer(host="http://prowlarr.test/9/api")
    run_indexer(host="http://prowlarr.test/10/api")
    run_indexer(host="http://prowlarr.test/9/api")
    assert len(calls) == 2


@pytest.mark.parametrize("review", [False, True])
def test_search_continues_to_next_provider(indexer_env, monkeypatch, review):
    calls, _, get = indexer_env
    monkeypatch.setattr(comicarr.CONFIG, "ENABLE_RSS", False, raising=False)
    monkeypatch.setattr(search.helpers, "get_issue_title", lambda *args, **kwargs: None)
    monkeypatch.setattr(search.helpers, "block_provider_check", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        search,
        "provider_order",
        lambda **kwargs: {
            "prov_order": ["torznab1", "torznab2"],
            "torznab_info": [
                {
                    "provider": f"torznab{i}",
                    "info": (f"provider{i}", f"http://prowlarr.test/{i}/api", "0", "key", "7030"),
                }
                for i in (1, 2)
            ],
            "newznab_info": [],
            "totalproviders": 2,
        },
    )

    def response(url, **kwargs):
        result = get(url, **kwargs)
        if "/2/api" in url:
            result.status_code = 200
            result._content = b"<rss><channel></channel></rss>"
        return result

    monkeypatch.setattr(search, "get_http_session", lambda **kwargs: types.SimpleNamespace(get=response))
    request_counts = []
    for _ in range(2):
        search.search_init(
            "Example Series",
            "2",
            "2024",
            "2024",
            None,
            "2024-01-01",
            "2024-01-01",
            "issue-1",
            ComicID="comic-1",
            allow_packs=0,
            manual=True,
            evaluator=EvaluationSession(review=review),
        )
        request_counts.append(len(calls))
    endpoints = [url.split("?")[0] for url in calls]
    assert endpoints[:2] == ["http://prowlarr.test/1/api", "http://prowlarr.test/2/api"]
    assert endpoints.count("http://prowlarr.test/1/api") == 1
    assert request_counts[1] > request_counts[0]
    assert set(endpoints[request_counts[0] :]) == {"http://prowlarr.test/2/api"}


def test_real_transport_large_retry_after_completes_promptly(indexer_env, monkeypatch):
    class RateLimited(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(429)
            self.send_header("Retry-After", "70129")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), RateLimited)
    thread = Thread(target=server.serve_forever, daemon=True)
    session = None
    thread.start()
    try:
        monkeypatch.undo()
        monkeypatch.setattr(search, "_indexer_http_session", None)
        monkeypatch.setattr(search, "_indexer_cooldowns", {})
        monkeypatch.setattr(
            comicarr,
            "CONFIG",
            types.SimpleNamespace(
                ENABLE_TORRENT_SEARCH=True,
                USENET_RETENTION=None,
                SEARCH_DELAY=5,
            ),
        )
        monkeypatch.setattr(search, "last_run_check", lambda **kwargs: {})
        monkeypatch.setattr(search.time, "sleep", lambda seconds: pytest.fail(f"transport slept for {seconds}s"))
        session = search.get_http_session(indexer=True)
        session.trust_env = False
        assert run_indexer(host=f"http://127.0.0.1:{server.server_port}/api")["status"] is False
    finally:
        if session is not None:
            session.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_indexer_transport_returns_rate_limit_without_retrying(monkeypatch):
    monkeypatch.setattr(search, "_indexer_http_session", None)
    retry = search.get_http_session(indexer=True).get_adapter("https://indexer.test").max_retries
    assert retry.is_retry("GET", 429, has_retry_after=True) is False
    assert retry.is_retry("GET", 503, has_retry_after=True) is True
    assert retry.respect_retry_after_header is False


def test_download_transport_keeps_retry_after_policy(monkeypatch):
    monkeypatch.setattr(search, "_http_session", None)
    session = search.get_http_session()
    retry = session.get_adapter("https://indexer.test").max_retries
    assert retry.is_retry("GET", 429, has_retry_after=True) is True
    assert retry.is_retry("GET", 503, has_retry_after=True) is True
    assert retry.respect_retry_after_header is True
    assert session is not search.get_http_session(indexer=True)
