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

"""Download one file from a public Mega link, written from Mega's public protocol.

A public file link carries a node handle and a 256-bit key, base64url encoded:
``https://mega.nz/file/<handle>#<key>`` (or the older ``#!<handle>!<key>``).
The key's eight 32-bit words fold into an AES-128 key (words 0-3 XOR 4-7),
a CTR nonce (words 4-5) and the expected meta-MAC (words 6-7).

The API call ``{"a": "g", "g": 1, "p": <handle>}`` answers with the size, the
encrypted attributes (AES-CBC, zero IV, ``MEGA{json}``) and a temporary
download URL. The body is AES-128-CTR ciphertext. Integrity is a CBC-MAC per
chunk (128 KiB growing to 1 MiB), folded into a file MAC whose halves XOR to
the meta-MAC in the key.
"""

import base64
import json
import os
import re
import secrets
import struct
from dataclasses import dataclass
from pathlib import Path

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

API_URL = "https://g.api.mega.co.nz/cs"
TIMEOUT_SECONDS = 60
READ_SIZE = 64 * 1024

_LINK_PATTERNS = (
    re.compile(r"mega(?:\.co)?\.nz/file/([\w-]+)#([\w-]+)"),
    re.compile(r"mega(?:\.co)?\.nz/#!([\w-]+)!([\w-]+)"),
)
_DEAD_LINK_CODES = {-2, -9, -11, -16}
_OVER_QUOTA_CODES = {-17, -18}


class MegaDownloadError(Exception):
    """A public-link download failed. ``reason`` is one of dead_link,
    over_quota, interrupted, integrity, or bad_link."""

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class MegaFile:
    name: str
    size: int
    url: str
    key: bytes
    nonce: bytes
    meta_mac: bytes


@dataclass(frozen=True)
class MegaDownload:
    name: str
    size: int
    path: Path


def _b64url(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b, strict=True))


def parse_link(link):
    """Return ``(handle, key words)`` from a public file link."""
    for pattern in _LINK_PATTERNS:
        match = pattern.search(link or "")
        if match:
            raw_key = _b64url(match.group(2))
            if len(raw_key) == 32:
                return match.group(1), raw_key
    raise MegaDownloadError("bad_link", "not a Mega public file link: %s" % link)


def _api_error(code):
    if code in _DEAD_LINK_CODES:
        return MegaDownloadError("dead_link", "Mega says the file is gone or blocked (error %s)" % code)
    if code in _OVER_QUOTA_CODES:
        return MegaDownloadError("over_quota", "Mega transfer quota exceeded (error %s)" % code)
    return MegaDownloadError("interrupted", "Mega API error %s" % code)


def resolve(link, session=None):
    """Ask Mega's API for a public file's name, size and download URL."""
    handle, raw_key = parse_link(link)
    session = session or requests.Session()
    response = session.post(
        API_URL,
        params={"id": secrets.randbits(31)},
        json=[{"a": "g", "g": 1, "p": handle}],
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    answer = response.json()
    if isinstance(answer, int):
        raise _api_error(answer)
    node = answer[0]
    if isinstance(node, int):
        raise _api_error(node)
    if "g" not in node:
        raise _api_error(node.get("e", -18))

    key = _xor(raw_key[:16], raw_key[16:])
    attributes = Cipher(algorithms.AES(key), modes.CBC(b"\0" * 16)).decryptor()
    plain = attributes.update(_b64url(node["at"])) + attributes.finalize()
    if not plain.startswith(b"MEGA"):
        raise MegaDownloadError("integrity", "Mega file attributes did not decrypt; the link key is wrong")
    name = json.loads(plain[4:].rstrip(b"\0").decode("utf-8"))["n"]
    return MegaFile(
        name=name,
        size=int(node["s"]),
        url=node["g"],
        key=key,
        nonce=raw_key[16:24],
        meta_mac=raw_key[24:32],
    )


def _chunk_sizes():
    size = 128 * 1024
    while True:
        yield size
        size = min(size + 128 * 1024, 1024 * 1024)


class _Mac:
    """Mega's chunked CBC-MAC over the plaintext."""

    def __init__(self, key, nonce):
        self._ecb = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        self._key = key
        self._chunk_iv = nonce + nonce
        self._sizes = _chunk_sizes()
        self._chunk_left = next(self._sizes)
        self._chunk = self._new_chunk()
        self._pending = b""
        self._last = None
        self._file_mac = b"\0" * 16

    def _new_chunk(self):
        return Cipher(algorithms.AES(self._key), modes.CBC(self._chunk_iv)).encryptor()

    def update(self, data):
        while data:
            part, data = data[: self._chunk_left], data[self._chunk_left :]
            self._chunk_left -= len(part)
            self._pending += part
            whole = len(self._pending) - len(self._pending) % 16
            if whole:
                self._last = self._chunk.update(self._pending[:whole])[-16:]
                self._pending = self._pending[whole:]
            if self._chunk_left == 0:
                self._close_chunk()
                self._chunk_left = next(self._sizes)

    def _close_chunk(self):
        if self._pending:
            self._last = self._chunk.update(self._pending.ljust(16, b"\0"))[-16:]
            self._pending = b""
        self._file_mac = self._ecb.update(_xor(self._file_mac, self._last))
        self._chunk = self._new_chunk()
        self._last = None

    def meta_mac(self):
        if self._pending or self._last is not None:
            self._close_chunk()
        words = struct.unpack(">4I", self._file_mac)
        return struct.pack(">2I", words[0] ^ words[1], words[2] ^ words[3])


def download(info, destination, progress=None, session=None):
    """Stream, decrypt and verify ``info`` into ``destination/<name>``.

    The bytes land in ``<name>.part`` first and are renamed only after the size
    and the meta-MAC match. ``progress`` is called with
    ``(written, total, partial_path)`` after each read.
    """
    destination = Path(destination)
    target = destination / os.path.basename(info.name)
    partial = target.with_name(target.name + ".part")
    session = session or requests.Session()
    decryptor = Cipher(algorithms.AES(info.key), modes.CTR(info.nonce + b"\0" * 8)).decryptor()
    mac = _Mac(info.key, info.nonce)
    written = 0
    try:
        with session.get(info.url, stream=True, timeout=TIMEOUT_SECONDS) as response:
            if response.status_code == 509:
                raise MegaDownloadError("over_quota", "Mega transfer quota exceeded (HTTP 509)")
            response.raise_for_status()
            with open(partial, "wb") as handle:
                for block in response.iter_content(READ_SIZE):
                    plain = decryptor.update(block)
                    mac.update(plain)
                    handle.write(plain)
                    written += len(plain)
                    if progress:
                        progress(written, info.size, partial)
    except requests.RequestException as e:
        partial.unlink(missing_ok=True)
        raise MegaDownloadError("interrupted", "Mega download interrupted: %s" % e) from e
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    if written != info.size:
        partial.unlink(missing_ok=True)
        raise MegaDownloadError("interrupted", "Mega download stopped at %d of %d bytes" % (written, info.size))
    if mac.meta_mac() != info.meta_mac:
        partial.unlink(missing_ok=True)
        raise MegaDownloadError("integrity", "Mega download failed its integrity check")
    partial.replace(target)
    return MegaDownload(name=info.name, size=info.size, path=target)
