#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Mega public-link downloads against recorded API and storage responses (#1230)."""

import base64
import json
import struct

import pytest
import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from comicarr.downloaders import mega_public
from comicarr.downloaders.mega_public import MegaDownloadError

HANDLE = "AbCdEfGh"
NAME = "Saga 001 (2012).cbz"
PLAINTEXT = bytes(range(256)) * 1200 + b"tail-not-16-aligned"
AES_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
NONCE = bytes.fromhex("0102030405060708")
DOWNLOAD_URL = "https://gfs.example.mega/dl/abc"


def _b64url(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _aes_block(block):
    """AES on one 16-byte block (CBC with a zero IV over one block)."""
    encryptor = Cipher(algorithms.AES(AES_KEY), modes.CBC(b"\0" * 16)).encryptor()
    return encryptor.update(block) + encryptor.finalize()


def _reference_meta_mac(data):
    """Mega's MAC, spelled out block by block, independent of the module."""
    boundaries, position, size = [], 0, 128 * 1024
    while position < len(data):
        boundaries.append((position, min(position + size, len(data))))
        position += size
        size = min(size + 128 * 1024, 1024 * 1024)
    file_mac = b"\0" * 16
    for start, end in boundaries:
        chunk_mac = NONCE + NONCE
        chunk = data[start:end]
        for offset in range(0, len(chunk), 16):
            block = chunk[offset : offset + 16].ljust(16, b"\0")
            chunk_mac = _aes_block(bytes(a ^ b for a, b in zip(chunk_mac, block)))
        file_mac = _aes_block(bytes(a ^ b for a, b in zip(file_mac, chunk_mac)))
    words = struct.unpack(">4I", file_mac)
    return struct.pack(">2I", words[0] ^ words[1], words[2] ^ words[3])


META_MAC = _reference_meta_mac(PLAINTEXT)
RAW_KEY = bytes(a ^ b for a, b in zip(AES_KEY, NONCE + META_MAC)) + NONCE + META_MAC
LINK = "https://mega.nz/file/%s#%s" % (HANDLE, _b64url(RAW_KEY))


def _attributes(name):
    plain = b"MEGA" + json.dumps({"n": name}).encode()
    plain = plain.ljust(-(-len(plain) // 16) * 16, b"\0")
    encryptor = Cipher(algorithms.AES(AES_KEY), modes.CBC(b"\0" * 16)).encryptor()
    return _b64url(encryptor.update(plain) + encryptor.finalize())


def _ciphertext(data):
    encryptor = Cipher(algorithms.AES(AES_KEY), modes.CTR(NONCE + b"\0" * 8)).encryptor()
    return encryptor.update(data) + encryptor.finalize()


API_OK = [{"s": len(PLAINTEXT), "at": _attributes(NAME), "g": DOWNLOAD_URL}]


class _Response:
    def __init__(self, status=200, payload=None, chunks=(), fail_after=None):
        self.status_code = status
        self._payload = payload
        self._chunks = chunks
        self._fail_after = fail_after

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("%s error" % self.status_code)

    def iter_content(self, _size):
        for index, chunk in enumerate(self._chunks):
            if self._fail_after is not None and index >= self._fail_after:
                raise requests.ConnectionError("connection reset")
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Session:
    def __init__(self, api=API_OK, body=None, status=200, fail_after=None):
        self.api = api
        self.body = _ciphertext(PLAINTEXT) if body is None else body
        self.status = status
        self.fail_after = fail_after
        self.posts = []
        self.gets = []

    def post(self, url, params=None, json=None, timeout=None):
        self.posts.append((url, json))
        return _Response(payload=self.api)

    def get(self, url, stream=False, timeout=None):
        self.gets.append(url)
        chunks = [self.body[i : i + 50000] for i in range(0, len(self.body), 50000)]
        return _Response(status=self.status, chunks=chunks, fail_after=self.fail_after)


def test_parse_link_accepts_new_and_legacy_forms():
    legacy = "https://mega.co.nz/#!%s!%s" % (HANDLE, _b64url(RAW_KEY))

    assert mega_public.parse_link(LINK) == (HANDLE, RAW_KEY)
    assert mega_public.parse_link(legacy) == (HANDLE, RAW_KEY)


def test_parse_link_rejects_folder_and_garbage_links():
    for link in ("https://mega.nz/folder/AbCd#key", "not a link", None):
        with pytest.raises(MegaDownloadError) as error:
            mega_public.parse_link(link)
        assert error.value.reason == "bad_link"


def test_resolve_reads_name_size_and_url():
    session = _Session()

    info = mega_public.resolve(LINK, session=session)

    assert (info.name, info.size, info.url) == (NAME, len(PLAINTEXT), DOWNLOAD_URL)
    assert session.posts == [(mega_public.API_URL, [{"a": "g", "g": 1, "p": HANDLE}])]


def test_download_decrypts_and_verifies_fixture(tmp_path):
    session = _Session()
    seen = []

    info = mega_public.resolve(LINK, session=session)
    result = mega_public.download(info, tmp_path, lambda done, total, part: seen.append((done, total)), session)

    assert result.path == tmp_path / NAME
    assert result.path.read_bytes() == PLAINTEXT
    assert seen[-1] == (len(PLAINTEXT), len(PLAINTEXT))
    assert session.gets == [DOWNLOAD_URL]
    assert list(tmp_path.iterdir()) == [result.path]


@pytest.mark.parametrize("answer", [[-9], -9, [-16]])
def test_dead_link_is_classified(answer):
    with pytest.raises(MegaDownloadError) as error:
        mega_public.resolve(LINK, session=_Session(api=answer))

    assert error.value.reason == "dead_link"


@pytest.mark.parametrize("answer", [[-17], [{"s": 10, "at": "x", "e": -17}]])
def test_over_quota_api_answer_is_classified(answer):
    with pytest.raises(MegaDownloadError) as error:
        mega_public.resolve(LINK, session=_Session(api=answer))

    assert error.value.reason == "over_quota"


def test_over_quota_storage_response_is_classified(tmp_path):
    session = _Session(status=509)
    info = mega_public.resolve(LINK, session=session)

    with pytest.raises(MegaDownloadError) as error:
        mega_public.download(info, tmp_path, session=session)

    assert error.value.reason == "over_quota"
    assert list(tmp_path.iterdir()) == []


def test_truncated_stream_is_interrupted_and_leaves_nothing(tmp_path):
    session = _Session(body=_ciphertext(PLAINTEXT)[:100000])
    info = mega_public.resolve(LINK, session=session)

    with pytest.raises(MegaDownloadError) as error:
        mega_public.download(info, tmp_path, session=session)

    assert error.value.reason == "interrupted"
    assert list(tmp_path.iterdir()) == []


def test_connection_reset_is_interrupted_and_leaves_nothing(tmp_path):
    session = _Session(fail_after=2)
    info = mega_public.resolve(LINK, session=session)

    with pytest.raises(MegaDownloadError) as error:
        mega_public.download(info, tmp_path, session=session)

    assert error.value.reason == "interrupted"
    assert list(tmp_path.iterdir()) == []


def test_corrupted_stream_fails_integrity_check(tmp_path):
    body = bytearray(_ciphertext(PLAINTEXT))
    body[200000] ^= 0xFF
    session = _Session(body=bytes(body))
    info = mega_public.resolve(LINK, session=session)

    with pytest.raises(MegaDownloadError) as error:
        mega_public.download(info, tmp_path, session=session)

    assert error.value.reason == "integrity"
    assert list(tmp_path.iterdir()) == []


def test_wrong_key_fails_before_download():
    wrong = bytearray(RAW_KEY)
    wrong[0] ^= 0xFF
    link = "https://mega.nz/file/%s#%s" % (HANDLE, _b64url(bytes(wrong)))
    session = _Session()

    with pytest.raises(MegaDownloadError) as error:
        mega_public.resolve(link, session=session)

    assert error.value.reason == "integrity"
    assert session.gets == []


@pytest.fixture
def meganz(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import comicarr
    from comicarr.downloaders import mega

    writes = []
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace(DDL_LOCATION=str(tmp_path)), raising=False)
    monkeypatch.setattr(mega.db, "upsert", lambda table, values, keys: writes.append((table, values, keys)))
    (tmp_path / "mega").mkdir()
    return mega.MegaNZ(), writes, tmp_path / "mega"


def test_meganz_downloads_renames_and_records_progress(meganz, monkeypatch):
    downloader, writes, folder = meganz
    monkeypatch.setattr(mega_public.requests, "Session", lambda: _Session())

    result = downloader.ddl_download(LINK, None, 7, issueid="42", site="GC-Mega")

    expected = folder / "Saga 001 (2012)[__42__].cbz"
    assert result == {"success": True, "filename": expected.name, "path": str(expected)}
    assert expected.read_bytes() == PLAINTEXT
    assert writes[0] == (
        "ddl_info",
        {"filename": NAME, "remote_filesize": str(len(PLAINTEXT)), "size": writes[0][1]["size"]},
        {"ID": 7},
    )
    assert writes[1] == ("ddl_info", {"tmp_filename": str(folder / (NAME + ".part"))}, {"ID": 7})
    assert len(writes) == 2


@pytest.mark.parametrize(
    "session",
    [_Session(api=[-9]), _Session(api=[-17]), _Session(body=_ciphertext(PLAINTEXT)[:1000])],
    ids=["dead-link", "over-quota", "truncated"],
)
def test_meganz_failures_return_the_link_type_failure(meganz, monkeypatch, session):
    downloader, _writes, folder = meganz
    monkeypatch.setattr(mega_public.requests, "Session", lambda: session)

    result = downloader.ddl_download(LINK, "wanted.cbz", 7, issueid="42", site="GC-Mega")

    assert result["success"] is False
    assert result["path"] is None
    assert result["link_type_failure"] == "GC-Mega"
    assert list(folder.iterdir()) == []
