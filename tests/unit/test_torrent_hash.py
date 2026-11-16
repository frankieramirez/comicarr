#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""Info hashes computed from the raw ``info`` span (#1409, replaces vendored bencode)."""

import hashlib

import pytest

from comicarr.app.common.torrent_hash import TorrentDecodeError, info_hash, info_hash_of_file

INFO = b"d6:lengthi1048576e4:name13:Comic 001.cbz12:piece lengthi262144e6:pieces20:" + bytes(range(20)) + b"e"
TORRENT = b"d8:announce31:http://tracker.example/announce7:comment5:hello4:info" + INFO + b"e"


def test_hash_is_the_uppercase_sha1_of_the_info_dictionary_bytes():
    assert info_hash(TORRENT) == hashlib.sha1(INFO).hexdigest().upper()


def test_keys_after_info_are_ignored():
    later = TORRENT[:-1] + b"8:url-listl23:http://mirror.example/ee"
    assert info_hash(later) == info_hash(TORRENT)


def test_non_canonical_key_order_hashes_the_bytes_as_written():
    # Clients hash the info span exactly as it appears in the file.
    shuffled = b"d4:name13:Comic 001.cbz6:lengthi1048576e12:piece lengthi262144e6:pieces20:" + bytes(range(20)) + b"e"
    data = b"d4:info" + shuffled + b"e"
    assert info_hash(data) == hashlib.sha1(shuffled).hexdigest().upper()


def test_nested_lists_and_dicts_inside_info_are_skipped_correctly():
    info = b"d5:filesld6:lengthi5e4:pathl5:a.cbzeed6:lengthi7e4:pathl5:b.cbzeee4:name4:packe"
    assert info_hash(b"d4:info" + info + b"e") == hashlib.sha1(info).hexdigest().upper()


def test_matches_the_hash_the_vendored_bencode_module_produced():
    # Pinned from comicarr/_vendor/bencode.py (decode, re-encode info, SHA-1) before it was deleted.
    assert info_hash(TORRENT) == "FAE5B2C683C0E323974B1BFB90B461DDEF440E5D"


def test_reading_from_a_file(tmp_path):
    path = tmp_path / "issue.torrent"
    path.write_bytes(TORRENT)
    assert info_hash_of_file(str(path)) == info_hash(TORRENT)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"l4:infoe",
        b"d4:name4:teste",
        b"d4:info4:teste",
        b"d4:infod4:name",
        b"d4:infod4:name99:shorte",
        b"d4:infodi1ee",
    ],
)
def test_malformed_torrents_raise(data):
    with pytest.raises(TorrentDecodeError):
        info_hash(data)
