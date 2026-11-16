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

"""Seedbox delivery over SFTP (moved from the root ftpsshup module, #1405)."""

from types import SimpleNamespace

import pytest

import comicarr
from comicarr.app.downloads import seedbox


class FakeSFTP:
    def __init__(self, failures):
        self.failures = failures
        self.puts = []
        self.closed = False

    def put(self, local, remote):
        if self.failures:
            self.failures.pop()
            raise OSError("connection reset")
        self.puts.append((local, remote))

    def close(self):
        self.closed = True


class FakeParamiko:
    def __init__(self, failures=0):
        self.failures = [True] * failures
        self.transports = []
        self.sftps = []
        outer = self

        class Transport:
            def __init__(self, address):
                self.address = address
                self.closed = False
                outer.transports.append(self)

            def connect(self, username, password):
                self.credentials = (username, password)

            def close(self):
                self.closed = True

        class SFTPClient:
            @staticmethod
            def from_transport(transport):
                sftp = FakeSFTP(outer.failures)
                outer.sftps.append(sftp)
                return sftp

        self.Transport = Transport
        self.SFTPClient = SFTPClient


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        SimpleNamespace(
            SEEDBOX_HOST="seedbox.example",
            SEEDBOX_PORT="2222",
            SEEDBOX_USER="user",
            SEEDBOX_PASS="secret",
            SEEDBOX_WATCHDIR="/watch",
        ),
    )
    monkeypatch.setattr(seedbox.time, "sleep", lambda seconds: None)
    local = tmp_path / "issue.torrent"
    local.write_bytes(b"d4:infod4:name4:testee")
    return str(local)


def test_uploads_the_torrent_into_the_watch_folder(monkeypatch, config):
    fake = FakeParamiko()
    monkeypatch.setattr(seedbox, "_import_paramiko", lambda: fake)

    assert seedbox.put_torrent(config, "Some Issue 001") == "pass"

    assert fake.transports[0].address == ("seedbox.example", 2222)
    assert fake.transports[0].credentials == ("user", "secret")
    assert fake.sftps[0].puts == [(config, "/watch/Some Issue 001.torrent")]
    assert fake.transports[0].closed and fake.sftps[0].closed


def test_a_name_already_ending_in_torrent_is_kept(monkeypatch, config):
    fake = FakeParamiko()
    monkeypatch.setattr(seedbox, "_import_paramiko", lambda: fake)

    seedbox.put_torrent(config, "issue.torrent")

    assert fake.sftps[0].puts[0][1] == "/watch/issue.torrent"


def test_a_failed_upload_reconnects_and_retries(monkeypatch, config):
    fake = FakeParamiko(failures=1)
    monkeypatch.setattr(seedbox, "_import_paramiko", lambda: fake)

    assert seedbox.put_torrent(config, "issue") == "pass"

    assert len(fake.transports) == 2
    assert fake.transports[0].closed


def test_gives_up_after_three_attempts_instead_of_looping_forever(monkeypatch, config):
    fake = FakeParamiko(failures=10)
    monkeypatch.setattr(seedbox, "_import_paramiko", lambda: fake)

    assert seedbox.put_torrent(config, "issue") == "fail"

    assert len(fake.transports) == seedbox.SEND_ATTEMPTS
    assert all(t.closed for t in fake.transports)


def test_a_missing_local_file_is_skipped(monkeypatch, config, tmp_path):
    fake = FakeParamiko()
    monkeypatch.setattr(seedbox, "_import_paramiko", lambda: fake)

    assert seedbox.put_torrent(str(tmp_path / "missing.torrent"), "issue") == "fail"
    assert fake.transports == []


def test_without_paramiko_it_fails_with_an_error(monkeypatch, config):
    errors = []
    monkeypatch.setattr(seedbox, "_import_paramiko", lambda: None)
    monkeypatch.setattr(seedbox.logger, "error", errors.append)

    assert seedbox.put_torrent(config, "issue") == "fail"
    assert "paramiko" in errors[0]
