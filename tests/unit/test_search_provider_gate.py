#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The one "is any search provider enabled" test the search gates and health share (#1442)."""

from types import SimpleNamespace

import pytest

from comicarr.app.search.health import build_route_readiness, has_viable_route, search_providers_available


def _config(**overrides):
    values = dict(
        EXTRA_NEWZNABS=[],
        EXTRA_TORZNABS=[],
        ENABLE_DDL=False,
        ENABLE_GETCOMICS=False,
        ENABLE_EXTERNAL_SERVER=False,
        EXPERIMENTAL=False,
        NEWZNAB=False,
        ENABLE_TORRENT_SEARCH=False,
        ENABLE_TORRENTS=False,
        ENABLE_PUBLIC=False,
        ENABLE_32P=False,
        ENABLE_TORZNAB=False,
        ENABLE_PROWLARR=False,
        PROWLARR_HOST=None,
        PROWLARR_APIKEY=None,
        PROWLARR_USENET=False,
        NZB_DOWNLOADER=3,
        TORRENT_DOWNLOADER=0,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


_PROWLARR = dict(ENABLE_PROWLARR=True, PROWLARR_HOST="http://prowlarr.example:9696", PROWLARR_APIKEY="key")


def test_nothing_enabled_is_not_searchable():
    assert search_providers_available(_config()) is False


@pytest.mark.parametrize("downloader", [0, 1, 2])
def test_prowlarr_usenet_alone_is_a_provider_with_an_nzb_client(downloader):
    config = _config(**_PROWLARR, PROWLARR_USENET=True, NZB_DOWNLOADER=downloader)

    assert search_providers_available(config) is True


def test_prowlarr_usenet_needs_an_nzb_client():
    config = _config(**_PROWLARR, PROWLARR_USENET=True, NZB_DOWNLOADER=3)

    assert search_providers_available(config) is False


def test_prowlarr_usenet_needs_the_opt_in():
    config = _config(**_PROWLARR, PROWLARR_USENET=False, NZB_DOWNLOADER=0)

    assert search_providers_available(config) is False


def test_prowlarr_torrents_alone_is_a_provider_with_torrent_search_on():
    config = _config(**_PROWLARR, ENABLE_TORRENT_SEARCH=True, ENABLE_TORRENTS=True)

    assert search_providers_available(config) is True


def test_newznab_rows_still_count():
    row = ("Indexer", "https://indexer.example", "1", "key", "1#7030", "1")
    config = _config(NEWZNAB=True, EXTRA_NEWZNABS=[row], NZB_DOWNLOADER=0)

    assert search_providers_available(config) is True


def test_disabled_newznab_rows_do_not_count():
    row = ("Indexer", "https://indexer.example", "1", "key", "1#7030", "0")
    config = _config(NEWZNAB=True, EXTRA_NEWZNABS=[row], NZB_DOWNLOADER=0)

    assert search_providers_available(config) is False


def test_the_gate_and_health_agree_on_prowlarr_usenet(tmp_path):
    config = _config(
        **_PROWLARR,
        PROWLARR_USENET=True,
        NZB_DOWNLOADER=0,
        SAB_HOST="http://sab.example:8080",
        SAB_APIKEY="key",
        POST_PROCESSING=False,
    )

    routes = build_route_readiness(config)

    assert routes["nzb"]["enabled"] is True
    assert has_viable_route(routes) is True
    assert search_providers_available(config) is True
