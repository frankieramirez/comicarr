#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import os
import stat
import xmlrpc.client
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import comicarr
from comicarr.app.common import remote_artifacts
from comicarr.app.core import runtime
from comicarr.app.downloads import getcomics
from comicarr.app.downloads.ddl import mediafire
from comicarr.app.search import engine as search


def _assert_within(root, path):
    assert os.path.commonpath([os.path.realpath(root), os.path.realpath(path)]) == os.path.realpath(root)


@pytest.mark.parametrize("provider", ["DDL(GetComics)", "Newznab"])
def test_nzbname_create_keeps_remote_title_inside_cache(tmp_path, provider):
    cache_dir = tmp_path / "cache"
    generated_name = search.nzbname_create(provider, "../../outside")

    _assert_within(cache_dir, cache_dir / f"{generated_name}.nzb")
    assert "/" not in generated_name
    assert "\\" not in generated_name


def test_search_cache_path_remains_xmlrpc_compatible_string(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    nzb_path = search._nzb_cache_path(cache_dir, "issue.nzb")
    marshalled = xmlrpc.client.dumps((nzb_path,))

    assert isinstance(nzb_path, str)
    assert "<string>" in marshalled


def test_mediafire_content_disposition_cannot_escape_download_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(DDL_LOCATION=str(tmp_path)))
    downloader = mediafire.MediaFire()
    downloader.dl_location = str(tmp_path)
    response = SimpleNamespace(
        headers={
            "Content-Disposition": 'attachment; filename="../../outside.cbz"',
            "Content-Length": "12",
        }
    )
    downloader.session.get = MagicMock(return_value=response)
    monkeypatch.setattr(mediafire.db, "upsert", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        downloader,
        "mediafire_dl",
        lambda url, download_id, fileinfo, issueid: {
            "success": True,
            "filename": fileinfo["filename"],
            "path": os.path.join(downloader.dl_location, fileinfo["filename"]),
        },
    )

    result = downloader.ddl_download("https://example.invalid/file", "download-1", "issue-1")

    _assert_within(tmp_path, result["path"])
    assert "/" not in result["filename"]
    assert "\\" not in result["filename"]


def test_mediafire_download_publishes_sanitized_filename_atomically(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(DDL_LOCATION=str(tmp_path)))
    downloader = mediafire.MediaFire()
    downloader.session.get = MagicMock(
        return_value=SimpleNamespace(iter_content=lambda chunk_size: iter([b"comic-data"]))
    )
    monkeypatch.setattr(mediafire.db, "upsert", lambda *args, **kwargs: None)

    result = downloader.mediafire_dl(
        "https://example.invalid/file",
        "download-1",
        {"filename": "../../outside.cbz", "filesize": len(b"comic-data")},
        "issue-1",
    )

    assert result["success"] is True
    _assert_within(tmp_path, result["path"])
    assert os.path.exists(result["path"])
    with open(result["path"], "rb") as downloaded_file:
        assert downloaded_file.read() == b"comic-data"
    assert list(tmp_path.glob("*.part")) == []


def test_zip_extraction_rejects_suspicious_expansion_ratio(tmp_path, monkeypatch):
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("payload.bin", b"0" * (2 * 1024 * 1024))

    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(DDL_LOCATION=str(tmp_path)))
    downloader = getcomics.GC.__new__(getcomics.GC)

    result = downloader.zip_zip("download-1", str(archive), archive.name)

    assert result == {"success": False, "filename": archive.name, "path": None}
    assert archive.exists()
    assert not (tmp_path / "bomb").exists()


def test_remote_filename_preserves_unicode_while_normalizing_separators():
    assert remote_artifacts.safe_remote_filename("Monstress/藍藍.cbz") == "Monstress-藍藍.cbz"
    with pytest.raises(remote_artifacts.RemoteArtifactError):
        remote_artifacts.safe_remote_filename("../../")


def test_remote_path_rejects_existing_symlink_that_escapes_root(tmp_path):
    download_root = tmp_path / "downloads"
    download_root.mkdir()
    outside = tmp_path / "outside.cbz"
    outside.write_bytes(b"outside")
    (download_root / "issue.cbz").symlink_to(outside)

    with pytest.raises(remote_artifacts.RemoteArtifactError, match="escapes"):
        remote_artifacts.resolve_remote_artifact_path(download_root, "issue.cbz")


def test_atomic_chunk_write_keeps_existing_file_on_stream_failure(tmp_path):
    destination = tmp_path / "issue.cbz"
    destination.write_bytes(b"existing")

    def failing_chunks():
        yield b"partial"
        raise OSError("connection reset")

    with pytest.raises(OSError, match="connection reset"):
        remote_artifacts.write_chunks_atomically(destination, failing_chunks())

    assert destination.read_bytes() == b"existing"
    assert list(tmp_path.glob("*.part")) == []


def test_atomic_chunk_write_preserves_existing_file_mode(tmp_path, monkeypatch):
    destination = tmp_path / "issue.cbz"
    destination.write_bytes(b"existing")
    destination.chmod(0o664)
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(ENFORCE_PERMS=True, CHMOD_FILE="0600"))

    remote_artifacts.write_chunks_atomically(destination, [b"replacement"])

    assert destination.read_bytes() == b"replacement"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o664


@pytest.mark.parametrize("configured_mode", ["0664", "0o664", 0o664, 664])
def test_atomic_chunk_write_applies_configured_mode_to_new_file(tmp_path, monkeypatch, configured_mode):
    destination = tmp_path / "issue.cbz"
    monkeypatch.setattr(
        runtime.current(),
        "config",
        SimpleNamespace(ENFORCE_PERMS=True, CHMOD_FILE=configured_mode),
    )

    remote_artifacts.write_chunks_atomically(destination, [b"new"])

    assert stat.S_IMODE(destination.stat().st_mode) == 0o664


def test_default_permission_policy_uses_captured_umask_without_mutating_it(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runtime.current(),
        "config",
        SimpleNamespace(ENFORCE_PERMS=False, CHMOD_FILE="0660", CHMOD_DIR="0777"),
    )
    monkeypatch.setattr(comicarr, "UMASK", 0o022)
    monkeypatch.setattr(remote_artifacts.os, "umask", lambda value: pytest.fail("must not mutate process umask"))

    file_destination = tmp_path / "issue.cbz"
    remote_artifacts.write_chunks_atomically(file_destination, [b"comic"])
    archive = tmp_path / "default-modes.zip"
    extraction_destination = tmp_path / "default-modes"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("pages/001.jpg", b"page")
    remote_artifacts.extract_zip_atomically(archive, extraction_destination)

    assert stat.S_IMODE(file_destination.stat().st_mode) == 0o644
    assert stat.S_IMODE(extraction_destination.stat().st_mode) == 0o755
    assert stat.S_IMODE((extraction_destination / "pages").stat().st_mode) == 0o755
    assert stat.S_IMODE((extraction_destination / "pages" / "001.jpg").stat().st_mode) == 0o644


@pytest.mark.skipif(not all(hasattr(os, name) for name in ("chown", "getuid", "getgid")), reason="POSIX ownership")
def test_atomic_replacement_reapplies_existing_ownership(tmp_path, monkeypatch):
    destination = tmp_path / "issue.cbz"
    destination.write_bytes(b"existing")
    expected_ownership = (destination.stat().st_uid, destination.stat().st_gid)
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(ENFORCE_PERMS=False))
    monkeypatch.setattr(comicarr, "UMASK", 0o022)
    original_chown = os.chown
    ownership_calls = []

    def record_chown(path, uid, gid, **kwargs):
        ownership_calls.append((os.fspath(path), uid, gid))
        return original_chown(path, uid, gid, **kwargs)

    monkeypatch.setattr(remote_artifacts.os, "chown", record_chown)

    remote_artifacts.write_chunks_atomically(destination, [b"replacement"])

    assert expected_ownership in [(uid, gid) for _, uid, gid in ownership_calls]
    assert (destination.stat().st_uid, destination.stat().st_gid) == expected_ownership


@pytest.mark.skipif(not all(hasattr(os, name) for name in ("chown", "getuid", "getgid")), reason="POSIX ownership")
def test_atomic_replacement_ownership_failure_keeps_original(tmp_path, monkeypatch):
    destination = tmp_path / "issue.cbz"
    destination.write_bytes(b"existing")
    original_stat = destination.stat()
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(ENFORCE_PERMS=False))
    monkeypatch.setattr(comicarr, "UMASK", 0o022)
    monkeypatch.setattr(
        remote_artifacts.os,
        "chown",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("ownership denied")),
    )

    with pytest.raises(PermissionError, match="ownership denied"):
        remote_artifacts.write_chunks_atomically(destination, [b"replacement"])

    assert destination.read_bytes() == b"existing"
    assert (destination.stat().st_uid, destination.stat().st_gid) == (original_stat.st_uid, original_stat.st_gid)


def test_zip_extraction_accepts_normal_comic_archive(tmp_path):
    archive = tmp_path / "Monstress 藍.zip"
    destination = tmp_path / "Monstress 藍"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("pages/001.jpg", b"page-one")
        zip_file.writestr("ComicInfo.xml", b"<ComicInfo />")

    result = remote_artifacts.extract_zip_atomically(archive, destination)

    assert result == destination
    assert (destination / "pages" / "001.jpg").read_bytes() == b"page-one"
    assert (destination / "ComicInfo.xml").read_bytes() == b"<ComicInfo />"


@pytest.mark.parametrize(
    "member_name",
    [
        "CON.txt",
        "COM¹.log",
        "LPT².cbz",
        "CONIN$.txt",
        "CONOUT$.txt",
        "CLOCK$.txt",
        "pages/001.jpg:metadata",
        "pages/trailing. ",
    ],
)
def test_zip_extraction_rejects_nonportable_component_names(tmp_path, member_name):
    archive = tmp_path / "nonportable.zip"
    destination = tmp_path / "nonportable"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr(member_name, b"page")

    with pytest.raises(remote_artifacts.RemoteArtifactError, match="portable"):
        remote_artifacts.extract_zip_atomically(archive, destination)

    assert not destination.exists()


@pytest.mark.parametrize(
    "member_names",
    [
        ("Page.jpg", "page.jpg"),
        ("café.jpg", "cafe\u0301.jpg"),
        ("Page/a.jpg", "page/b.jpg"),
        ("café/a.jpg", "cafe\u0301/b.jpg"),
    ],
)
def test_zip_extraction_rejects_portable_name_collisions(tmp_path, member_names):
    archive = tmp_path / "collision.zip"
    destination = tmp_path / "collision"
    with zipfile.ZipFile(archive, "w") as zip_file:
        for member_name in member_names:
            zip_file.writestr(member_name, b"page")

    with pytest.raises(remote_artifacts.RemoteArtifactError, match="duplicate"):
        remote_artifacts.extract_zip_atomically(archive, destination)

    assert not destination.exists()


def test_zip_extraction_applies_configured_modes_to_new_tree(tmp_path, monkeypatch):
    archive = tmp_path / "modes.zip"
    destination = tmp_path / "modes"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("pages/001.jpg", b"page")
    monkeypatch.setattr(
        runtime.current(),
        "config",
        SimpleNamespace(ENFORCE_PERMS=True, CHMOD_DIR="0750", CHMOD_FILE="0640"),
    )

    remote_artifacts.extract_zip_atomically(archive, destination)

    assert stat.S_IMODE(destination.stat().st_mode) == 0o750
    assert stat.S_IMODE((destination / "pages").stat().st_mode) == 0o750
    assert stat.S_IMODE((destination / "pages" / "001.jpg").stat().st_mode) == 0o640


@pytest.mark.parametrize(
    ("configured_directory_mode", "configured_file_mode"),
    [("2775", "6775"), (0o2775, 0o6775)],
)
def test_enforced_modes_preserve_directory_setgid_but_strip_file_special_bits(
    tmp_path,
    monkeypatch,
    configured_directory_mode,
    configured_file_mode,
):
    monkeypatch.setattr(
        runtime.current(),
        "config",
        SimpleNamespace(
            ENFORCE_PERMS=True,
            CHMOD_DIR=configured_directory_mode,
            CHMOD_FILE=configured_file_mode,
        ),
    )
    file_destination = tmp_path / "issue.cbz"
    remote_artifacts.write_chunks_atomically(file_destination, [b"comic"])
    archive = tmp_path / "special-modes.zip"
    extraction_destination = tmp_path / "special-modes"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("pages/001.jpg", b"page")

    remote_artifacts.extract_zip_atomically(archive, extraction_destination)

    assert stat.S_IMODE(extraction_destination.stat().st_mode) == 0o2775
    assert stat.S_IMODE((extraction_destination / "pages").stat().st_mode) == 0o2775
    assert stat.S_IMODE(file_destination.stat().st_mode) == 0o775
    assert stat.S_IMODE((extraction_destination / "pages" / "001.jpg").stat().st_mode) == 0o775


def test_new_artifacts_use_secure_modes_when_config_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace())
    monkeypatch.setattr(comicarr, "UMASK", None)
    file_destination = tmp_path / "issue.cbz"
    remote_artifacts.write_chunks_atomically(file_destination, [b"comic"])

    archive = tmp_path / "secure.zip"
    extraction_destination = tmp_path / "secure"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("pages/001.jpg", b"page")
    remote_artifacts.extract_zip_atomically(archive, extraction_destination)

    assert stat.S_IMODE(file_destination.stat().st_mode) == 0o600
    assert stat.S_IMODE(extraction_destination.stat().st_mode) == 0o700
    assert stat.S_IMODE((extraction_destination / "pages").stat().st_mode) == 0o700
    assert stat.S_IMODE((extraction_destination / "pages" / "001.jpg").stat().st_mode) == 0o600


@pytest.mark.skipif(not all(hasattr(os, name) for name in ("chown", "getuid", "getgid")), reason="POSIX ownership")
def test_enforced_new_artifacts_apply_configured_numeric_ownership(tmp_path, monkeypatch):
    expected_ownership = (os.getuid(), os.getgid())
    monkeypatch.setattr(
        runtime.current(),
        "config",
        SimpleNamespace(
            ENFORCE_PERMS=True,
            CHMOD_DIR="0750",
            CHMOD_FILE="0640",
            CHOWNER=str(expected_ownership[0]),
            CHGROUP=str(expected_ownership[1]),
        ),
    )
    original_chown = os.chown
    ownership_calls = []

    def record_chown(path, uid, gid, **kwargs):
        ownership_calls.append((os.fspath(path), uid, gid))
        return original_chown(path, uid, gid, **kwargs)

    monkeypatch.setattr(remote_artifacts.os, "chown", record_chown)
    file_destination = tmp_path / "issue.cbz"
    remote_artifacts.write_chunks_atomically(file_destination, [b"comic"])
    archive = tmp_path / "ownership.zip"
    extraction_destination = tmp_path / "ownership"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("pages/001.jpg", b"page")
    remote_artifacts.extract_zip_atomically(archive, extraction_destination)

    assert ownership_calls
    assert all((uid, gid) == expected_ownership for _, uid, gid in ownership_calls)
    assert (file_destination.stat().st_uid, file_destination.stat().st_gid) == expected_ownership
    assert (extraction_destination.stat().st_uid, extraction_destination.stat().st_gid) == expected_ownership
    extracted_file = extraction_destination / "pages" / "001.jpg"
    assert (extracted_file.stat().st_uid, extracted_file.stat().st_gid) == expected_ownership


@pytest.mark.skipif(not all(hasattr(os, name) for name in ("chown", "getuid", "getgid")), reason="POSIX ownership")
def test_enforced_new_artifacts_resolve_named_owner_and_group(tmp_path, monkeypatch):
    pwd = pytest.importorskip("pwd")
    grp = pytest.importorskip("grp")
    expected_ownership = (os.getuid(), os.getgid())
    monkeypatch.setattr(
        runtime.current(),
        "config",
        SimpleNamespace(
            ENFORCE_PERMS=True,
            CHMOD_FILE="0640",
            CHOWNER=pwd.getpwuid(expected_ownership[0]).pw_name,
            CHGROUP=grp.getgrgid(expected_ownership[1]).gr_name,
        ),
    )
    original_chown = os.chown
    ownership_calls = []

    def record_chown(path, uid, gid, **kwargs):
        ownership_calls.append((uid, gid))
        return original_chown(path, uid, gid, **kwargs)

    monkeypatch.setattr(remote_artifacts.os, "chown", record_chown)

    remote_artifacts.write_chunks_atomically(tmp_path / "named-owner.cbz", [b"comic"])

    assert ownership_calls == [expected_ownership]


@pytest.mark.skipif(not all(hasattr(os, name) for name in ("chown", "getuid", "getgid")), reason="POSIX ownership")
def test_zip_swap_reapplies_ownership_to_every_existing_file_and_directory(tmp_path, monkeypatch):
    archive = tmp_path / "existing-tree.zip"
    destination = tmp_path / "existing-tree"
    pages = destination / "pages"
    pages.mkdir(parents=True)
    existing_file = pages / "001.jpg"
    existing_file.write_bytes(b"old")
    expected_paths = {destination, pages, existing_file}
    expected_ownership = {
        path.relative_to(destination): (path.stat().st_uid, path.stat().st_gid) for path in expected_paths
    }
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("pages/001.jpg", b"new")
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(ENFORCE_PERMS=False))
    monkeypatch.setattr(comicarr, "UMASK", 0o022)
    original_chown = os.chown
    ownership_calls = []

    def record_chown(path, uid, gid, **kwargs):
        ownership_calls.append((os.fspath(path), uid, gid))
        return original_chown(path, uid, gid, **kwargs)

    monkeypatch.setattr(remote_artifacts.os, "chown", record_chown)

    remote_artifacts.extract_zip_atomically(archive, destination)

    assert len(ownership_calls) >= len(expected_paths)
    for relative_path, ownership in expected_ownership.items():
        published_path = destination / relative_path
        assert (published_path.stat().st_uid, published_path.stat().st_gid) == ownership


def test_zip_extraction_preserves_existing_destination_contents(tmp_path):
    archive = tmp_path / "updated.zip"
    destination = tmp_path / "updated"
    destination.mkdir()
    (destination / "keep.txt").write_text("keep")
    (destination / "001.jpg").write_bytes(b"old-page")
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("001.jpg", b"new-page")

    remote_artifacts.extract_zip_atomically(archive, destination)

    assert (destination / "keep.txt").read_text() == "keep"
    assert (destination / "001.jpg").read_bytes() == b"new-page"


def test_zip_backup_cleanup_failure_does_not_undo_success(tmp_path, monkeypatch, caplog):
    archive = tmp_path / "updated.zip"
    destination = tmp_path / "updated"
    destination.mkdir()
    (destination / "001.jpg").write_bytes(b"old-page")
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("001.jpg", b"new-page")

    original_remove = remote_artifacts._remove_path

    def fail_backup_cleanup(path):
        if "backup-" in os.fspath(path):
            raise OSError("cleanup denied")
        original_remove(path)

    monkeypatch.setattr(remote_artifacts, "_remove_path", fail_backup_cleanup)

    result = remote_artifacts.extract_zip_atomically(archive, destination)

    assert result == destination
    assert (destination / "001.jpg").read_bytes() == b"new-page"
    assert "cleanup denied" in caplog.text


def test_bounded_staging_names_support_near_limit_destinations(tmp_path):
    long_filename = "f" * 245
    file_destination = tmp_path / long_filename
    remote_artifacts.write_chunks_atomically(file_destination, [b"file"])

    archive = tmp_path / "long.zip"
    extraction_destination = tmp_path / ("d" * 245)
    extraction_destination.mkdir()
    (extraction_destination / "old.txt").write_text("old")
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("new.txt", b"new")

    remote_artifacts.extract_zip_atomically(archive, extraction_destination)

    assert file_destination.read_bytes() == b"file"
    assert (extraction_destination / "new.txt").read_bytes() == b"new"


def test_zip_zip_preserves_string_path_for_non_archive(tmp_path, monkeypatch):
    comic_file = tmp_path / "issue.cbz"
    comic_file.write_bytes(b"comic")
    monkeypatch.setattr(runtime.current(), "config", SimpleNamespace(DDL_LOCATION=str(tmp_path)))
    downloader = getcomics.GC.__new__(getcomics.GC)

    result = downloader.zip_zip("download-1", str(comic_file), comic_file.name)

    assert result == {"success": True, "filename": comic_file.name, "path": str(comic_file)}
    assert isinstance(result["path"], str)


def test_zip_preflight_enforces_member_count(tmp_path, monkeypatch):
    archive = tmp_path / "too-many.zip"
    destination = tmp_path / "too-many"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("001.jpg", b"one")
        zip_file.writestr("002.jpg", b"two")
    monkeypatch.setattr(remote_artifacts, "MAX_ZIP_MEMBERS", 1)

    with pytest.raises(remote_artifacts.RemoteArtifactError, match="too many members"):
        remote_artifacts.extract_zip_atomically(archive, destination)

    assert not destination.exists()


def test_zip_preflight_enforces_aggregate_uncompressed_size(tmp_path, monkeypatch):
    archive = tmp_path / "too-large.zip"
    destination = tmp_path / "too-large"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("001.jpg", b"1" * 16)
        zip_file.writestr("002.jpg", b"2" * 16)
    monkeypatch.setattr(remote_artifacts, "MAX_ZIP_UNCOMPRESSED_BYTES", 20)

    with pytest.raises(remote_artifacts.RemoteArtifactError, match="size limit"):
        remote_artifacts.extract_zip_atomically(archive, destination)

    assert not destination.exists()


def test_zip_preflight_reserves_available_disk_space(tmp_path, monkeypatch):
    archive = tmp_path / "no-space.zip"
    destination = tmp_path / "no-space"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("001.jpg", b"1" * 32)
    monkeypatch.setattr(
        remote_artifacts.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=remote_artifacts.ZIP_DISK_RESERVE_BYTES + 16),
    )

    with pytest.raises(remote_artifacts.RemoteArtifactError, match="free disk space"):
        remote_artifacts.extract_zip_atomically(archive, destination)

    assert not destination.exists()


def test_zip_extraction_cleans_staging_after_member_failure(tmp_path, monkeypatch):
    archive = tmp_path / "interrupted.zip"
    destination = tmp_path / "interrupted"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("001.jpg", b"one")
        zip_file.writestr("002.jpg", b"two")

    original_extract = remote_artifacts._extract_zip_member
    calls = 0

    def fail_second_member(zip_file, member, member_destination, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk write failed")
        original_extract(zip_file, member, member_destination, **kwargs)

    monkeypatch.setattr(remote_artifacts, "_extract_zip_member", fail_second_member)

    with pytest.raises(OSError, match="disk write failed"):
        remote_artifacts.extract_zip_atomically(archive, destination)

    assert not destination.exists()
    assert list(tmp_path.glob(".comicarr-extract-*")) == []
