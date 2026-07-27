#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Contract tests for Comicarr-owned torrent adapter boundaries."""

import ast
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from unittest.mock import patch

import pytest

from comicarr._vendor import provenance
from comicarr.torrent import contracts
from comicarr.torrent.clients import deluge, qbittorrent, transmission, utorrent


def test_connection_result_normalizer_preserves_failure_details():
    failure = contracts.connection_failure("connection refused")

    assert failure == {"status": False, "error": "connection refused"}
    assert contracts.normalize_connection_result(False, error="connection refused") == failure


def test_monitor_error_always_has_established_status_shape():
    assert contracts.monitor_error("vendor unavailable") == {
        "snatch_status": "MONITOR ERROR",
        "error": "vendor unavailable",
    }


def test_deluge_repeated_connect_returns_existing_client():
    adapter = deluge.TorrentClient()
    existing = object()
    adapter.client = existing
    adapter.conn = existing

    assert adapter.connect("localhost:58846", "user", "password") is existing


def test_deluge_malformed_host_is_connection_failure():
    adapter = deluge.TorrentClient()

    result = adapter.connect("localhost", "user", "password")

    assert result == {"status": False, "error": "invalid host; expected host:port"}


def test_qbittorrent_repeated_connect_returns_existing_client():
    adapter = qbittorrent.TorrentClient()
    existing = object()
    adapter.client = existing
    adapter.conn = existing

    assert adapter.connect("http://localhost:8080", "user", "password") is existing


def test_qbittorrent_connect_exception_is_normalized():
    adapter = qbittorrent.TorrentClient()

    with patch.object(qbittorrent, "Client", side_effect=RuntimeError("boom")):
        result = adapter.connect("http://localhost:8080", "user", "password")

    assert result["status"] is False
    assert "boom" in str(result["error"])


def test_transmission_connect_exception_is_normalized():
    adapter = transmission.TorrentClient()

    with patch.object(transmission, "Client", side_effect=RuntimeError("boom")):
        result = adapter.connect("localhost:9091", "user", "password")

    assert result["status"] is False
    assert "boom" in str(result["error"])


def test_transmission_repeated_connect_returns_existing_connection():
    adapter = transmission.TorrentClient()
    existing = object()
    adapter.conn = existing

    assert adapter.connect("localhost:9091", "user", "password") is existing


def test_utorrent_connect_exception_is_normalized():
    adapter = utorrent.TorrentClient()

    with patch.object(utorrent, "UTorrentClient", side_effect=RuntimeError("boom")):
        result = adapter.connect("http://localhost:8080", "user", "password")

    assert result["status"] is False
    assert "boom" in str(result["error"])


REPO_ROOT = Path(__file__).parents[2]
VENDOR_ROOT = REPO_ROOT / "comicarr" / "_vendor"
RUNTIME_SCAN_EXCLUDED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "frontend",
    "node_modules",
    "tests",
}
REQUIRED_PROVENANCE_FIELDS = {
    "integration_owner",
    "path",
    "custody_source_url",
    "custody_source_path",
    "custody_revision",
    "upstream_source_url",
    "upstream_revision",
    "import_revision",
    "upstream_version",
    "version_evidence",
    "license_expression",
    "license_evidence",
    "license_conflict_evidence",
    "notice_files",
    "origin_candidates",
    "replacement_candidates",
    "partial_attributions",
    "redistribution_status",
    "unresolved_reasons",
    "local_modifications",
    "packaged_snapshot_sha256",
}


def _source_vendor_roots():
    packages = {path.name for path in VENDOR_ROOT.iterdir() if path.is_dir() and (path / "__init__.py").exists()}
    modules = {path.stem for path in VENDOR_ROOT.glob("*.py") if path.name not in {"__init__.py", "provenance.py"}}
    return packages | modules


def _packaged_snapshot_digest(member_contents, relative_path):
    target = PurePosixPath(relative_path)
    if target.suffix:
        files = [target.as_posix()]
        base = target.parent
    else:
        prefix = f"{target.as_posix()}/"
        files = [name for name in member_contents if name.startswith(prefix)]
        base = target

    digest = hashlib.sha256()
    for name in sorted(files):
        path = PurePosixPath(name)
        digest.update(path.relative_to(base).as_posix().encode())
        digest.update(b"\0")
        digest.update(member_contents[name])
        digest.update(b"\0")
    return digest.hexdigest()


def _classify_vendor_imports(tree, relative_path):
    namespaced = set()
    legacy = {}
    vendor_names = set(provenance.VENDOR_PROVENANCE)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "comicarr._vendor":
                namespaced.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif module.startswith("comicarr._vendor."):
                namespaced.add(module.split(".")[2])
            else:
                root = module.split(".", 1)[0]
                if root in vendor_names:
                    legacy.setdefault(root, set()).add(relative_path)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("comicarr._vendor."):
                    namespaced.add(alias.name.split(".")[2])
                else:
                    root = alias.name.split(".", 1)[0]
                    if root in vendor_names:
                        legacy.setdefault(root, set()).add(relative_path)
    return namespaced, legacy


def _is_nested_checkout(directory):
    """True when ``directory`` is the root of its own git checkout.

    Linked worktrees carry a ``.git`` file rather than a directory, and they
    may sit anywhere under the repo — ``.worktrees/`` by convention, but the
    name is the author's choice. Detecting the marker catches them all, so a
    sibling branch's sources are never scanned as if they were this tree's.
    """
    return (directory / ".git").exists()


def _first_party_runtime_python_files():
    for path in REPO_ROOT.rglob("*.py"):
        relative = path.relative_to(REPO_ROOT)
        if VENDOR_ROOT in path.parents:
            continue
        if any(part in RUNTIME_SCAN_EXCLUDED_DIRECTORIES for part in relative.parts[:-1]):
            continue
        if any(_is_nested_checkout(parent) for parent in path.parents if REPO_ROOT in parent.parents):
            continue
        yield path


@pytest.mark.parametrize("marker_is_directory", [False, True])
def test_nested_checkouts_are_excluded_but_ordinary_directories_are_scanned(tmp_path, monkeypatch, marker_is_directory):
    """A linked worktree carries a ``.git`` file, a clone a ``.git`` directory."""
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "VENDOR_ROOT", tmp_path / "comicarr" / "_vendor")

    checkout = tmp_path / ".worktrees" / "feature"
    checkout.mkdir(parents=True)
    if marker_is_directory:
        (checkout / ".git").mkdir()
    else:
        (checkout / ".git").write_text("gitdir: /elsewhere\n")
    (checkout / "sibling.py").write_text("import os\n")

    ordinary = tmp_path / "comicarr"
    ordinary.mkdir()
    (ordinary / "runtime.py").write_text("import os\n")

    assert set(_first_party_runtime_python_files()) == {ordinary / "runtime.py"}


def _vendor_imports():
    namespaced = set()
    legacy = {}
    for path in _first_party_runtime_python_files():
        # Bytes, not text: ast.parse honours the file's PEP 263 coding
        # declaration, while read_text(encoding="utf-8") would reject a
        # legitimately latin-1 source outright.
        tree = ast.parse(path.read_bytes(), filename=str(path))
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        file_namespaced, file_legacy = _classify_vendor_imports(tree, relative_path)
        namespaced.update(file_namespaced)
        for name, paths in file_legacy.items():
            legacy.setdefault(name, set()).update(paths)
    return namespaced, legacy


def _assert_evidence_reference(reference):
    if reference.startswith("https://"):
        return
    assert (REPO_ROOT / reference).is_file(), reference


def test_vendor_manifest_exactly_covers_packaged_vendor_roots():
    assert _source_vendor_roots() == set(provenance.VENDOR_PROVENANCE)


def test_vendor_manifest_schema_and_evidence_are_complete():
    paths = []
    for name, record in provenance.VENDOR_PROVENANCE.items():
        assert set(record) == REQUIRED_PROVENANCE_FIELDS, name
        assert record["integration_owner"] == "Comicarr"
        assert record["redistribution_status"] in provenance.ALLOWED_REDISTRIBUTION_STATUSES
        assert record["import_revision"] == provenance.COMICARR_IMPORT_REVISION
        assert record["custody_source_url"] == "https://github.com/mylar3/mylar3"
        assert record["custody_source_path"]
        assert PurePosixPath(record["path"]).stem == name
        assert (REPO_ROOT / record["path"]).exists()
        paths.append(record["path"])
        assert len(record["packaged_snapshot_sha256"]) == 64
        int(record["packaged_snapshot_sha256"], 16)
        for field in (
            "version_evidence",
            "license_evidence",
            "license_conflict_evidence",
            "notice_files",
            "origin_candidates",
            "replacement_candidates",
            "partial_attributions",
            "unresolved_reasons",
        ):
            assert isinstance(record[field], tuple), (name, field)
        for reference in (
            *record["version_evidence"],
            *record["license_evidence"],
            *record["license_conflict_evidence"],
            *record["notice_files"],
        ):
            _assert_evidence_reference(reference)
        for candidate in record["origin_candidates"]:
            assert set(candidate) == {"url", "revision", "paths", "relationship", "confidence", "evidence"}
            assert candidate["url"].startswith("https://")
            assert len(candidate["revision"]) == 40
            assert candidate["paths"] and candidate["evidence"]
        assert all(url.startswith("https://") for url in record["replacement_candidates"])
        for attribution in record["partial_attributions"]:
            assert set(attribution) == {"url", "applies_to", "relationship"}
            assert attribution["applies_to"]

    assert len(paths) == len(set(paths))


def test_evidence_recorded_status_requires_positive_license_evidence():
    for name, record in provenance.VENDOR_PROVENANCE.items():
        if record["redistribution_status"] != "evidence-recorded":
            continue
        assert record["license_expression"] != "NOASSERTION", name
        assert record["license_evidence"], name
        assert record["unresolved_reasons"] == (), name

    rtorrent_record = provenance.VENDOR_PROVENANCE["rtorrent"]
    assert rtorrent_record["license_expression"] == (
        "MIT AND (GPL-2.0-or-later WITH OpenSSL-exception) AND LicenseRef-Secret-Labs"
    )
    assert {
        "comicarr/_vendor/rtorrent/lib/xmlrpc/clients/scgi.py",
        "comicarr/_vendor/rtorrent/lib/xmlrpc/transports/scgi.py",
    } <= set(rtorrent_record["license_evidence"])


def test_every_packaged_notice_is_claimed_exactly_once():
    actual_notices = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in VENDOR_ROOT.rglob("*")
        if path.is_file() and path.name in {"LICENSE", "COPYING", "NOTICE"}
    }
    claimed_notices = [
        notice_path for record in provenance.VENDOR_PROVENANCE.values() for notice_path in record["notice_files"]
    ]

    assert len(claimed_notices) == len(set(claimed_notices))
    assert set(claimed_notices) == actual_notices


def test_unresolved_vendor_status_cannot_imply_redistribution_clearance():
    unresolved = {
        name for name, record in provenance.VENDOR_PROVENANCE.items() if record["redistribution_status"] == "unresolved"
    }

    assert unresolved == {"mega", "utorrent"}
    for name in unresolved:
        record = provenance.VENDOR_PROVENANCE[name]
        assert record["license_expression"] == "NOASSERTION"
        assert record["license_evidence"] == ()
        assert record["unresolved_reasons"]

    mega = provenance.VENDOR_PROVENANCE["mega"]
    assert mega["upstream_source_url"] == "https://github.com/odwyersoftware/mega.py"
    assert mega["upstream_revision"] == "34f3e7335992589eed8f08e675c5fb3038139355"
    assert mega["upstream_version"] == "1.0.8"
    assert mega["license_conflict_evidence"]

    utorrent_record = provenance.VENDOR_PROVENANCE["utorrent"]
    assert utorrent_record["upstream_source_url"] is None
    assert utorrent_record["upstream_revision"] is None
    assert utorrent_record["upstream_version"] is None
    assert utorrent_record["origin_candidates"]


def test_unresolved_notices_preserve_non_clearance_language():
    required_text = {
        "mega": (),
        "utorrent": ("compatibility, not the version",),
    }
    for name, phrases in required_text.items():
        notice = (VENDOR_ROOT / name / "NOTICE").read_text(encoding="utf-8")
        assert "Redistribution status: unresolved" in notice
        assert "not a license grant" in notice
        for phrase in phrases:
            assert phrase in notice


def test_vendor_imports_are_declared_and_legacy_top_level_imports_are_explicit():
    namespaced, legacy = _vendor_imports()

    assert namespaced <= set(provenance.VENDOR_PROVENANCE)
    assert {name: tuple(sorted(paths)) for name, paths in legacy.items()} == provenance.LEGACY_TOP_LEVEL_VENDOR_IMPORTS


def test_vendor_import_classifier_catches_exact_and_dotted_top_level_imports():
    tree = ast.parse(
        "import mega.crypto\nfrom qbittorrent.client import Client\nfrom comicarr._vendor import rtorrent\n"
    )

    namespaced, legacy = _classify_vendor_imports(tree, "synthetic.py")

    assert namespaced == {"rtorrent"}
    assert legacy == {"mega": {"synthetic.py"}, "qbittorrent": {"synthetic.py"}}


def test_vendor_import_scan_includes_root_runtime_entry_points():
    scanned = {path.relative_to(REPO_ROOT).as_posix() for path in _first_party_runtime_python_files()}

    assert {"Comicarr.py", "comictagger.py"} <= scanned


def test_built_wheel_vendor_inventory_and_notices_match_manifest(tmp_path):
    build_root = tmp_path / "source"
    wheel_dir = tmp_path / "wheel"
    shutil.copytree(
        REPO_ROOT / "comicarr", build_root / "comicarr", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    for filename in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(REPO_ROOT / filename, build_root / filename)

    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir), str(build_root)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    wheel_path = next(wheel_dir.glob("*.whl"))
    with zipfile.ZipFile(wheel_path) as wheel:
        member_contents = {name: wheel.read(name) for name in wheel.namelist()}
    members = set(member_contents)

    vendor_prefix = "comicarr/_vendor/"
    wheel_roots = set()
    for member in members:
        if not member.startswith(vendor_prefix):
            continue
        relative = member.removeprefix(vendor_prefix)
        first_segment = relative.split("/", 1)[0]
        if first_segment in {"__init__.py", "provenance.py"}:
            continue
        wheel_roots.add(Path(first_segment).stem if "/" not in relative else first_segment)

    assert wheel_roots == set(provenance.VENDOR_PROVENANCE)
    for record in provenance.VENDOR_PROVENANCE.values():
        assert set(record["notice_files"]) <= members
        assert record["packaged_snapshot_sha256"] == _packaged_snapshot_digest(member_contents, record["path"])


@pytest.mark.parametrize(
    "adapter_module",
    [deluge, qbittorrent, transmission],
)
def test_adapters_do_not_import_top_level_vendor_names(adapter_module):
    source = Path(adapter_module.__file__).read_text(encoding="utf-8")

    assert "comicarr._vendor" in source
    assert "from deluge_client" not in source
    assert "from qbittorrent" not in source
    assert "from transmissionrpc" not in source
