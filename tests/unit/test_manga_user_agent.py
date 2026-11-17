#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Manga sources identify as Comicarr, never with the ComicVine user agent.

MangaDex answers a browser User-Agent with a 302 to a bot challenge page, so a
browser string in ``CV_USER_AGENT`` broke every MangaDex call with
"Expecting value: line 1 column 1".
"""

import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import comicarr
from comicarr.app.common.user_agent import app_user_agent

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"


@pytest.fixture
def browser_cv_config(monkeypatch):
    config = SimpleNamespace(
        CV_USER_AGENT=BROWSER_UA,
        MAL_CLIENT_ID="client-id",
        MANGADEX_CONTENT_RATING="safe",
        CACHE_DIR=None,
    )
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)
    return config


def _ok_response():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"result": "ok", "data": []}
    return response


def _sent_user_agent(mock_call):
    return mock_call.call_args.kwargs["headers"]["User-Agent"]


def test_app_user_agent_names_comicarr_and_version():
    assert re.fullmatch(r"Comicarr/[0-9A-Za-z.+-]+", app_user_agent())


def test_mangadex_ignores_cv_user_agent(browser_cv_config):
    from comicarr.app.manga import mangadex

    with (
        patch.object(mangadex, "_rate_limit"),
        patch.object(mangadex.requests, "get", return_value=_ok_response()) as get,
    ):
        mangadex._make_request("/manga", params={"title": "x"})

    assert _sent_user_agent(get) == app_user_agent()
    assert _sent_user_agent(get) != BROWSER_UA


def test_myanimelist_ignores_cv_user_agent(browser_cv_config):
    from comicarr.app.manga import myanimelist

    with (
        patch.object(myanimelist, "_rate_limit"),
        patch.object(myanimelist.requests, "get", return_value=_ok_response()) as get,
    ):
        myanimelist._make_request("/manga", params={"q": "x"})

    assert _sent_user_agent(get) == app_user_agent()


def test_mangaupdates_ignores_cv_user_agent(browser_cv_config):
    from comicarr.app.weekly import mangaupdates

    with (
        patch.object(mangaupdates, "REQUEST_SPACING", 0),
        patch.object(mangaupdates.requests, "request", return_value=_ok_response()) as request,
    ):
        mangaupdates._request("GET", "/series/1")

    assert _sent_user_agent(request) == app_user_agent()
