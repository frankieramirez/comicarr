#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The weekly pull list comes from a configurable release provider.

walksoftly.itsaninja.party went offline (Cloudflare 523 on every request).
Mylar3 moved to the same API at talkhard.notaninja.party and made the base
URL a setting; RELEASE_PROVIDER_URL does the same here.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import comicarr
from comicarr import locg
from comicarr.app.config.registry import REGISTRY


def _key(name):
    return REGISTRY[name]


def test_the_default_is_the_new_provider():
    assert _key("RELEASE_PROVIDER_URL").default == "https://talkhard.notaninja.party"
    assert locg.DEFAULT_RELEASE_PROVIDER_URL == "https://talkhard.notaninja.party"


@pytest.mark.parametrize(
    "configured, expected",
    [
        ("https://pull.example.org", "https://pull.example.org"),
        ("https://pull.example.org/", "https://pull.example.org"),
        ("  https://pull.example.org//  ", "https://pull.example.org"),
        (None, "https://talkhard.notaninja.party"),
        ("", "https://talkhard.notaninja.party"),
        ("   ", "https://talkhard.notaninja.party"),
        ("None", "https://talkhard.notaninja.party"),
        (MagicMock(), "https://talkhard.notaninja.party"),
    ],
)
def test_release_provider_url(configured, expected):
    assert locg.release_provider_url(SimpleNamespace(RELEASE_PROVIDER_URL=configured)) == expected


def test_a_config_without_the_key_uses_the_default():
    assert locg.release_provider_url(SimpleNamespace()) == "https://talkhard.notaninja.party"


@pytest.mark.parametrize(
    "configured, url",
    [
        (None, "https://talkhard.notaninja.party/newcomics.php"),
        ("https://pull.example.org/", "https://pull.example.org/newcomics.php"),
    ],
)
def test_the_pull_list_is_requested_from_the_provider(monkeypatch, configured, url):
    monkeypatch.setattr(comicarr, "USER_AGENT", "Comicarr/1.0.0 (comicarr)")
    monkeypatch.setattr(comicarr, "BACKENDSTATUS_WS", "up", raising=False)
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(RELEASE_PROVIDER_URL=configured), raising=False)
    monkeypatch.setattr(locg.logger, "warn", lambda message: None)
    response = MagicMock()
    response.status_code = 523
    response.headers = {}
    get = MagicMock(return_value=response)
    monkeypatch.setattr(locg.requests, "get", get)

    locg.locg(weeknumber="30", year="2026")

    assert get.call_args.args[0] == url
    assert get.call_args.kwargs["params"] == {"week": "30", "year": "2026"}
