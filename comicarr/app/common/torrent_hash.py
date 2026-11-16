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

"""Info hashes of .torrent files.

A torrent's info hash is the SHA-1 of the bencoded ``info`` dictionary,
exactly as it appears in the file. This module finds that byte span with a
small bencode scanner and hashes it; it never decodes and re-encodes, so a
file whose keys are not in canonical order still gets the hash the client
computes.
"""

from __future__ import annotations

import hashlib


class TorrentDecodeError(ValueError):
    """The data is not a bencoded torrent with an ``info`` dictionary."""


def _skip(data: bytes, pos: int) -> int:
    """Return the index just past the bencoded value that starts at ``pos``."""
    try:
        lead = data[pos : pos + 1]
        if lead == b"i":
            end = data.index(b"e", pos)
            int(data[pos + 1 : end])
            return end + 1
        if lead in (b"l", b"d"):
            pos += 1
            while data[pos : pos + 1] != b"e":
                if lead == b"d":
                    pos = _skip_string(data, pos)
                pos = _skip(data, pos)
            return pos + 1
        return _skip_string(data, pos)
    except (IndexError, ValueError) as e:
        raise TorrentDecodeError("malformed bencode at byte %d" % pos) from e


def _skip_string(data: bytes, pos: int) -> int:
    colon = data.index(b":", pos)
    length = int(data[pos:colon])
    end = colon + 1 + length
    if length < 0 or end > len(data):
        raise TorrentDecodeError("string runs past the end of the data at byte %d" % pos)
    return end


def _string_at(data: bytes, pos: int) -> tuple[bytes, int]:
    end = _skip_string(data, pos)
    colon = data.index(b":", pos)
    return data[colon + 1 : end], end


def info_hash(data: bytes) -> str:
    """The uppercase hex SHA-1 info hash of the torrent ``data``."""
    if data[:1] != b"d":
        raise TorrentDecodeError("a torrent file starts with a dictionary")
    pos = 1
    try:
        while data[pos : pos + 1] != b"e":
            key, pos = _string_at(data, pos)
            end = _skip(data, pos)
            if key == b"info":
                if data[pos : pos + 1] != b"d":
                    raise TorrentDecodeError("info is not a dictionary")
                return hashlib.sha1(data[pos:end]).hexdigest().upper()
            pos = end
    except (IndexError, ValueError) as e:
        raise TorrentDecodeError("malformed torrent dictionary") from e
    raise TorrentDecodeError("the torrent has no info dictionary")


def info_hash_of_file(path: str) -> str:
    """The uppercase hex SHA-1 info hash of the .torrent file at ``path``."""
    with open(path, "rb") as torrent_file:
        return info_hash(torrent_file.read())
