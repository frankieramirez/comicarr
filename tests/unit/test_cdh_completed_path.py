#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Completed-download path resolution for NZBGet/SAB CDH."""

import queue as queuelib
import zipfile
from unittest.mock import MagicMock

import comicarr
from comicarr.app.downloads.service import (
    _cdh_monitor_owned,
    check_file_condition,
    resolve_completed_download_file,
)


def _write_zip(path, payload=b"page"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("page.jpg", payload)
    return path


def test_resolve_completed_download_file_picks_archive_inside_job_folder(tmp_path):
    job = tmp_path / "Absolute.Batman.001.2024-GetComics"
    job.mkdir()
    archive = _write_zip(job / "Absolute Batman 001 (2024).cbr")
    doubled = job / job.name
    assert not doubled.exists()

    resolved = resolve_completed_download_file(str(job), job.name)

    assert resolved is not None
    assert resolved.exists()
    assert resolved.is_file()
    assert resolved == archive
    assert resolved != doubled
    condition = check_file_condition(resolved)
    assert condition["status"] is True


def test_resolve_completed_download_file_returns_location_when_it_is_a_file(tmp_path):
    archive = _write_zip(tmp_path / "direct-file.cbz")

    resolved = resolve_completed_download_file(str(archive), "not-a-child")

    assert resolved is not None
    assert resolved.exists()
    assert resolved == archive
    assert check_file_condition(resolved)["status"] is True


def test_resolve_completed_download_file_uses_existing_location_name_child(tmp_path):
    job = tmp_path / "sab-job"
    job.mkdir()
    archive = _write_zip(job / "Saga.001.cbz")
    decoy = _write_zip(job / "extra.cbr", payload=b"x" * 4096)

    resolved = resolve_completed_download_file(str(job), archive.name)

    assert resolved == archive
    assert resolved != decoy
    assert resolved.exists()


def test_resolve_completed_download_file_prefers_largest_archive(tmp_path):
    job = tmp_path / "Some.Release.Name-Group"
    job.mkdir()
    _write_zip(job / "sample.zip", payload=b"tiny")
    larger = _write_zip(job / "Some Release 001.cbz", payload=b"y" * 8192)

    resolved = resolve_completed_download_file(str(job), job.name)

    assert resolved is not None
    assert resolved.exists()
    assert resolved == larger


def test_resolve_completed_download_file_falls_back_to_single_regular_file(tmp_path):
    job = tmp_path / "Dotted.Release.Name"
    job.mkdir()
    only = job / "issue-without-suffix"
    only.write_bytes(b"PK\x03\x04not-a-full-zip")

    resolved = resolve_completed_download_file(str(job), job.name)

    assert resolved is not None
    assert resolved.exists()
    assert resolved == only


def test_cdh_monitor_owned_does_not_fail_when_name_is_not_a_child_file(tmp_path, monkeypatch):
    job = tmp_path / "Absolute.Batman.001.2024-GetComics"
    job.mkdir()
    archive = _write_zip(job / "Absolute Batman 001 (2024).cbr")
    assert not (job / job.name).exists()

    fake_pp = MagicMock()
    monkeypatch.setattr(comicarr, "PP_QUEUE", fake_pp, raising=False)
    monkeypatch.setattr("comicarr.app.downloads.journal.read_one", lambda *a, **k: None)
    monkeypatch.setattr("comicarr.app.downloads.journal.record_transition", lambda *a, **k: True)
    monkeypatch.setattr("comicarr.app.downloads.journal.release_key", lambda *a, **k: "rk-test")

    nzstat = {
        "status": True,
        "failed": False,
        "name": job.name,
        "location": str(job),
        "issueid": "I1",
        "comicid": "C1",
        "apicall": True,
        "download_info": {"provider": "nzb.su", "id": "nzbid-1"},
    }

    _cdh_monitor_owned(queuelib.Queue(), {"nzo_id": "nzb-1"}, nzstat)

    assert nzstat["failed"] is False
    fake_pp.put.assert_called_once()
    queued = fake_pp.put.call_args[0][0]
    assert queued["failed"] is False
    assert queued["nzb_folder"] == str(job)
    assert resolve_completed_download_file(queued["nzb_folder"], queued["nzb_name"]) == archive
