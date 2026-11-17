#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Security regressions for durable Fernet key authority."""

import errno
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet, InvalidToken

from comicarr.app.core import encrypted


@pytest.fixture(autouse=True)
def reset_fernet_cache():
    with encrypted._fernet_lock:
        encrypted._fernet_instance = None
        encrypted._fernet_secure_dir = None
    yield
    with encrypted._fernet_lock:
        encrypted._fernet_instance = None
        encrypted._fernet_secure_dir = None


def test_concurrent_first_use_publishes_one_owner_only_master_key(tmp_path):
    secure_dir = tmp_path / "secure"
    secure_dir.mkdir()
    workers = 16
    barrier = threading.Barrier(workers)

    def encrypt_after_barrier(index):
        barrier.wait()
        instance = encrypted._get_fernet(str(secure_dir))
        token = instance.encrypt(("payload-%s" % index).encode())
        return instance, token

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(encrypt_after_barrier, range(workers)))

    instances = [instance for instance, _token in results]
    assert len({id(instance) for instance in instances}) == 1

    key_path = secure_dir / "master.key"
    durable_fernet = Fernet(key_path.read_bytes())
    for index, (_instance, token) in enumerate(results):
        assert durable_fernet.decrypt(token) == ("payload-%s" % index).encode()

    if os.name != "nt":
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    assert list(secure_dir.glob("%s*" % encrypted._MASTER_KEY_TEMP_PREFIX)) == []


def test_concurrent_explicit_directories_never_cross_key_authority(tmp_path):
    secure_dirs = [tmp_path / "secure-a", tmp_path / "secure-b"]
    for secure_dir in secure_dirs:
        secure_dir.mkdir()

    workers = 20
    barrier = threading.Barrier(workers)

    def encrypt_for_directory(index):
        secure_dir = secure_dirs[index % len(secure_dirs)]
        barrier.wait()
        results = []
        for iteration in range(20):
            payload = ("%s:%s:%s" % (secure_dir.name, index, iteration)).encode()
            token = encrypted._get_fernet(str(secure_dir)).encrypt(payload)
            results.append((secure_dir, payload, token))
        return results

    with ThreadPoolExecutor(max_workers=workers) as executor:
        batches = list(executor.map(encrypt_for_directory, range(workers)))

    authorities = {secure_dir: Fernet((secure_dir / "master.key").read_bytes()) for secure_dir in secure_dirs}
    for batch in batches:
        for secure_dir, payload, token in batch:
            assert authorities[secure_dir].decrypt(token) == payload
            other_dir = next(candidate for candidate in secure_dirs if candidate != secure_dir)
            with pytest.raises(InvalidToken):
                authorities[other_dir].decrypt(token)


@pytest.mark.parametrize("failure", ("missing", "not-implemented", "unsupported"))
def test_first_use_falls_back_when_hard_links_are_unavailable(tmp_path, monkeypatch, failure):
    secure_dir = tmp_path / "secure"
    secure_dir.mkdir()
    if failure == "missing":
        monkeypatch.delattr(encrypted.os, "link")
    else:
        error = NotImplementedError() if failure == "not-implemented" else OSError(errno.EPERM, "unavailable")

        def unavailable_link(*_args):
            raise error

        monkeypatch.setattr(encrypted.os, "link", unavailable_link)

    authority = encrypted._get_fernet(str(secure_dir))
    token = authority.encrypt(b"fallback-payload")

    assert Fernet((secure_dir / "master.key").read_bytes()).decrypt(token) == b"fallback-payload"
    if os.name != "nt":
        assert stat.S_IMODE((secure_dir / "master.key").stat().st_mode) == 0o600


def test_existing_master_key_permissions_are_repaired_before_use(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX permission bits are not authoritative on Windows")
    secure_dir = tmp_path / "secure"
    secure_dir.mkdir()
    key_path = secure_dir / "master.key"
    key_path.write_bytes(Fernet.generate_key())
    key_path.chmod(0o644)

    assert encrypted._get_fernet(str(secure_dir)) is not None

    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


@pytest.mark.parametrize("token", ("^~$z$AAAA", "^~$z$!!!!"))
def test_malformed_legacy_tokens_fail_instead_of_erasing_credentials(token):
    assert encrypted.Encryptor(token).decrypt_it() == {"status": False}


def test_decrypt_with_missing_master_key_does_not_create_replacement_authority(tmp_path):
    secure_dir = tmp_path / "secure"
    secure_dir.mkdir()
    token = Fernet(Fernet.generate_key()).encrypt(b"unrecoverable").decode()

    result = encrypted.Encryptor(token, secure_dir=str(secure_dir)).decrypt_it()

    assert result == {"status": False}
    assert not (secure_dir / "master.key").exists()
