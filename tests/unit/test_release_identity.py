#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import pytest

from comicarr.app.search._release_identity import generate_id


def test_experimental_identity_matches_legacy_path():
    assert generate_id("experimental", "https://example.test/a/release-1/file", "Series") == "release-1"


def test_direct_provider_identities_are_preserved():
    assert generate_id("32P", "torrent-1", "Series") == "torrent-1"
    assert generate_id("WWT", "torrent-2", "Series") == "torrent-2"
    assert generate_id("DEM", "https://example.test/files/torrent-3.torrent", "Series") == "torrent-3"


def test_newznab_query_id_is_preferred():
    assert generate_id("newznab", "https://indexer.test/api?t=search&id=123&apikey=secret", "Series") == "123"


def test_torznab_query_id_is_preserved():
    assert generate_id("torznab", "https://indexer.test/api?id=456&cat= comics", "Series") == "456"


def test_newznab_query_id_is_read_when_it_is_the_first_parameter():
    # parse_qs on the whole URL keyed the first pair as "https://provider/api?id",
    # so the id was missed and the endpoint path stood in for the release identity.
    assert generate_id("newznab", "https://provider.test/api?id=abc", "Series") == "abc"


def test_torznab_query_id_keeps_its_last_character_without_a_delimiter():
    # find("&") returns -1 with no delimiter, and idtmp[:-1] dropped the last character.
    assert generate_id("torznab", "https://indexer.test/api?id=456", "Series") == "456"


@pytest.mark.parametrize("provider,link", [("unknown", "id"), ("torznab", "https://example.test/")])
def test_unresolvable_identity_keeps_the_existing_failure(provider, link):
    with pytest.raises(UnboundLocalError):
        generate_id(provider, link, "Series")
