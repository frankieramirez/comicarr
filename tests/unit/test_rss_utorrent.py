#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
"""The RSS-path uTorrent sender (moved from the root utorrent.py, #1520)."""

from base64 import b16encode, b32encode

from comicarr.app.search.rss_utorrent import utorrentclient


def _client():
    # calculate_torrent_hash never touches the connection state set up in __init__.
    return utorrentclient.__new__(utorrentclient)


def test_hex_magnet_hash_is_returned_upper_case():
    hex_hash = "ab" * 20
    link = "magnet:?xt=urn:btih:%s&dn=Example" % hex_hash
    assert _client().calculate_torrent_hash(link=link) == hex_hash.upper()


def test_base32_magnet_hash_is_converted_to_hex():
    raw = bytes(range(20))
    link = "magnet:?xt=urn:btih:%s&dn=Example" % b32encode(raw).decode("ascii")
    assert _client().calculate_torrent_hash(link=link) == b16encode(raw).decode("ascii").upper()
