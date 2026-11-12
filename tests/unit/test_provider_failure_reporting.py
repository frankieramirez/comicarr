#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""An unreachable provider fails fast, once, in words a person can act on.

Reported from the Review releases dialog: every indexer Prowlarr synced
(all at ``prowlarr:9696``) printed a raw urllib3 traceback, once for every
query variant of a manga chapter search.
"""

import errno
import socket
import types

import pytest
import requests
from urllib3.exceptions import MaxRetryError, NewConnectionError

import comicarr
from comicarr import search
from comicarr.app.search import failures, interactive, progress
from comicarr.app.search.evaluation import EvaluationSession


def refused(url="http://prowlarr:9696/9/api"):
    os_error = ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")
    new_conn = NewConnectionError(None, "Failed to establish a new connection: [Errno 111] Connection refused")
    new_conn.__cause__ = os_error
    return requests.exceptions.ConnectionError(MaxRetryError(None, url, new_conn))


@pytest.fixture(autouse=True)
def _clear_memo():
    failures.clear()
    yield
    failures.clear()


def test_host_label_drops_path_query_and_credentials():
    assert failures.host_label("http://user:pw@prowlarr:9696/9/api?apikey=secret") == "prowlarr:9696"
    assert failures.host_label("https://indexer.example/api") == "indexer.example:443"
    assert failures.host_label("not a url") == ""


def test_refused_connection_reads_as_a_sentence():
    message = failures.describe(refused(), "http://prowlarr:9696/9/api?apikey=secret")
    assert message.startswith("Couldn't connect to prowlarr:9696")
    assert "HTTPConnectionPool" not in message
    assert "secret" not in message


def test_dns_failure_names_the_host():
    exc = requests.exceptions.ConnectionError(socket.gaierror(socket.EAI_NONAME, "Name or service not known"))
    assert failures.describe(exc, "http://prowlarr:9696/api").startswith("Couldn't find a host named prowlarr.")


def test_timeout_and_auth_failures():
    assert failures.describe(requests.exceptions.ReadTimeout("x"), "http://a:1/", timeout=30) == (
        "a:1 didn't answer within 30 seconds."
    )
    response = requests.Response()
    response.status_code = 401
    assert "Check the API key" in failures.describe(requests.exceptions.HTTPError(response=response), "http://a:1/")


def test_unreachable_memo_expires(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(failures.time, "monotonic", lambda: clock[0])
    failures.mark_unreachable("http://prowlarr:9696/9/api", "connection_error", "down")
    assert failures.unreachable("http://prowlarr:9696/2/api") == ("connection_error", "down")
    assert failures.unreachable("http://other:9696/2/api") is None
    clock[0] += failures.UNREACHABLE_TTL_SECONDS
    assert failures.unreachable("http://prowlarr:9696/2/api") is None


def test_collector_keeps_one_failure_per_provider_and_code():
    collected = []
    assert interactive._record_failure(collected, "Nyaa.si (Prowlarr)", "connection_error", "down")
    assert not interactive._record_failure(collected, "nyaa.si (prowlarr)", "connection_error", "down")
    assert interactive._record_failure(collected, "Nyaa.si (Prowlarr)", "timeout", "slow")
    assert [item["code"] for item in collected] == ["connection_error", "timeout"]


@pytest.fixture
def refused_env(monkeypatch):
    calls = []
    monkeypatch.setattr(search, "_indexer_cooldowns", {})
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(ENABLE_TORRENT_SEARCH=True, USENET_RETENTION=None, SEARCH_DELAY=5),
    )
    monkeypatch.setattr(search, "last_run_check", lambda **kwargs: {})
    monkeypatch.setattr(search.helpers, "disable_provider", lambda *args, **kwargs: None)
    monkeypatch.setattr(search.time, "sleep", lambda seconds: None)

    def get(url, **kwargs):
        calls.append(url)
        raise refused(url)

    monkeypatch.setattr(search, "get_http_session", lambda **kwargs: types.SimpleNamespace(get=get))
    return calls


def run_indexer(name, host):
    return search.NZB_SEARCH(
        "Magi",
        "1",
        "2009",
        "2009",
        None,
        "2009-01-01",
        "2009-01-01",
        {name: {"type": "torznab", "id": 1, "lastrun": 0, "active": True, "hits": 0}},
        1,
        "no",
        "issue-1",
        "0",
        cmloopit=3,
        RSS="no",
        manual=True,
        torznab_host=(name, host, "0", "key", "7000"),
        evaluator=EvaluationSession(review=True),
    )


def test_second_provider_on_a_refused_host_fails_without_a_request(refused_env):
    reported = []
    with progress.report_progress(on_provider_failure=lambda *failure: reported.append(failure)):
        first = run_indexer("Nyaa.si (Prowlarr)", "http://prowlarr:9696/2/api")
        second = run_indexer("LimeTorrents (Prowlarr)", "http://prowlarr:9696/3/api")

    assert len(refused_env) == 1
    assert first["provider_failed"] is True
    assert second["provider_failed"] is True
    assert [code for _, code, _ in reported] == ["connection_error", "connection_error"]
    assert all(detail.startswith("Couldn't connect to prowlarr:9696") for _, _, detail in reported)
    assert all("apikey" not in detail for _, _, detail in reported)
