#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Contract tests for the modern Support bundle generator."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import insert

import comicarr
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.core import runtime
from comicarr.app.core.context import AppContext
from comicarr.app.core.db import get_engine, shutdown_engine
from comicarr.app.core.tables import annuals, comics, issues, metadata
from comicarr.app.system import support_bundle as sb
from comicarr.app.system.support_bundle_contract import read_contract_bytes

FIXED_CLOCK = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)

COMPLETE_DIAGNOSTICS = {
    "build": {
        "identity": "unverified",
        "install_method": "docker",
        "release_version": "0.27.0",
    },
    "configuration": {
        "acquisition": {
            "ddl": {"client": "local", "enabled": "enabled"},
            "nzb": {"client": "sabnzbd", "enabled": "enabled"},
            "torrent": {"client": "disabled", "enabled": "disabled"},
        },
        "automation": {
            "post_processing": "enabled",
            "rss": "enabled",
            "update_checks": "enabled",
        },
        "integrations": {
            "ai": "not_configured",
            "comicvine": "configured",
            "mangadex": "configured",
            "metron": "disabled",
            "myanimelist": "disabled",
        },
    },
    "database": {
        "acquisition_schema_state": "ready",
        "acquisition_schema_version": 7,
        "count_buckets": {
            "annuals": "10_99",
            "in_flight": "2_9",
            "issues": "1k_9k",
            "recovery_pending": "one",
            "series": "100_999",
            "wanted": "10_99",
        },
    },
    "health": {
        "maintenance": "clear",
        "overall": "healthy",
        "routes": {
            "ddl": {"last_success_age": "30m_2h", "state": "ready"},
            "nzb": {"last_success_age": "lt_5m", "state": "ready"},
            "torrent": {"last_success_age": "never", "state": "disabled"},
        },
        "scheduler": {
            "import_scan": "waiting",
            "rss": "waiting",
            "search": "waiting",
            "weekly": "waiting",
        },
        "search_worker": "healthy",
        "viable_route": True,
    },
    "runtime": {
        "architecture": "x86_64",
        "database_dialect": "sqlite",
        "dependencies": {
            "apscheduler": "3.11.0",
            "fastapi": "0.115.0",
            "sqlalchemy": "2.0.42",
            "starlette": "0.46.2",
            "urllib3": "2.7.0",
            "uvicorn": "0.34.0",
        },
        "os_family": "linux",
        "python_version": "3.12.4",
    },
}

PARTIAL_DIAGNOSTICS = {
    "build": COMPLETE_DIAGNOSTICS["build"],
    "configuration": COMPLETE_DIAGNOSTICS["configuration"],
    "runtime": COMPLETE_DIAGNOSTICS["runtime"],
}


def _canon(value) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _config(**overrides):
    base = {
        "POST_PROCESSING": True,
        "ENABLE_RSS": True,
        "CHECK_GITHUB": True,
        "COMICVINE_ENABLED": True,
        "COMICVINE_API": "canary-cv-api-key-NOT-FOR-BUNDLE",
        "USE_METRON_SEARCH": False,
        "METRON_USERNAME": None,
        "METRON_PASSWORD": None,
        "MANGADEX_ENABLED": True,
        "MAL_ENABLED": False,
        "MAL_CLIENT_ID": None,
        "AI_BASE_URL": None,
        "AI_API_KEY": None,
        "AI_MODEL": None,
        "ENABLE_DDL": True,
        "ENABLE_GETCOMICS": True,
        "ENABLE_EXTERNAL_SERVER": False,
        "EXPERIMENTAL": False,
        "NEWZNAB": True,
        "EXTRA_NEWZNABS": [["nn", "http://canary-nzb.example/api", "secret", 1, "cat", "1"]],
        "NZB_DOWNLOADER": 0,
        "SAB_HOST": "http://canary-sab.example:8080",
        "SAB_APIKEY": "canary-sab-key",
        "SAB_DIRECTORY": "/canary/sab/download",
        "ENABLE_PUBLIC": False,
        "ENABLE_32P": False,
        "ENABLE_TORZNAB": False,
        "EXTRA_TORZNABS": [],
        "ENABLE_TORRENT_SEARCH": False,
        "ENABLE_TORRENTS": False,
        "TORRENT_DOWNLOADER": 0,
        "DDL_LOCATION": "/canary/ddl",
        "BLACKHOLE_DIR": None,
        "NZBGET_HOST": None,
        "NZBGET_DIRECTORY": None,
        "LOCAL_WATCHDIR": None,
        "UTORRENT_HOST": None,
        "RTORRENT_HOST": None,
        "RTORRENT_DIRECTORY": None,
        "TRANSMISSION_HOST": None,
        "TRANSMISSION_DIRECTORY": None,
        "DELUGE_HOST": None,
        "DELUGE_DOWNLOAD_DIRECTORY": None,
        "QBITTORRENT_HOST": None,
        "QBITTORRENT_FOLDER": None,
        "LOG_DIR": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _ctx(tmp_path, **config_overrides):
    config = _config(**config_overrides)
    return AppContext(
        prog_dir=str(tmp_path / "prog"),
        data_dir=str(tmp_path / "data"),
        db_file=str(tmp_path / "data" / "comicarr.db"),
        config=config,
        current_version_name="0.27.0",
        install_type="docker",
        scheduler=SimpleNamespace(get_jobs=lambda: []),
        disposed=False,
    )


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "data_dir", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.setattr(comicarr, "INSTALL_TYPE", "docker", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("COMICARR_BUILD_ID", raising=False)
    monkeypatch.delenv("COMICARR_BUILD_COMMIT", raising=False)
    shutdown_engine()
    metadata.create_all(get_engine())
    assert ensure_acquisition_schema(get_engine()).ready
    yield
    shutdown_engine()


def _open_bundle(artifact: sb.SupportBundleArtifact):
    zf = zipfile.ZipFile(io.BytesIO(artifact.content))
    return zf


def test_readme_bytes_match_locked_contract():
    data = read_contract_bytes("README.txt")
    assert len(data) == 965
    assert hashlib.sha256(data).hexdigest() == ("7a568b84ac627e0f5504d15d407ae550e841241efd11a17db1250022c7ff1ae7")


def test_fixture_hashes_locked():
    complete = _canon(COMPLETE_DIAGNOSTICS)
    partial = _canon(PARTIAL_DIAGNOSTICS)
    assert len(complete) == 1310
    assert hashlib.sha256(complete).hexdigest() == ("7d9de3ea15a1b5601426d96529240a79c579c98b90a1b13648af6ee781d73eeb")
    assert len(partial) == 736
    assert hashlib.sha256(partial).hexdigest() == ("e25df55d5fa9a8a1cc6fb1116bbcc14e140b4ee1a3cf0401ca33930e7aa19255")


def test_generate_support_bundle_complete_shape(tmp_path):
    ctx = _ctx(tmp_path)
    with patch.object(sb, "_collect_diagnostics") as collect:
        sources = {
            "build": {"status": "available"},
            "runtime": {"status": "available"},
            "configuration": {"status": "available"},
            "database": {"status": "available"},
            "health": {"status": "available"},
        }
        collect.return_value = (COMPLETE_DIAGNOSTICS, sources)
        artifact = sb.generate_support_bundle(ctx, clock=lambda: FIXED_CLOCK)

    assert artifact.contract_version == 1
    assert artifact.filename == "comicarr-support-bundle-v1.zip"
    assert artifact.status == "complete"
    assert 1 <= len(artifact.content) <= 512 * 1024

    with _open_bundle(artifact) as zf:
        assert zf.namelist() == ["README.txt", "manifest.json", "diagnostics.json"]
        assert zf.comment == b""
        for name in zf.namelist():
            info = zf.getinfo(name)
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.comment == b""
            assert not (info.flag_bits & 0x1)
        readme = zf.read("README.txt")
        assert readme == read_contract_bytes("README.txt")
        manifest = json.loads(zf.read("manifest.json"))
        diagnostics = json.loads(zf.read("diagnostics.json"))
        assert manifest["operator_review_required"] is True
        assert manifest["bundle_status"] == "complete"
        assert manifest["contract_version"] == 1
        assert manifest["product"] == "Comicarr"
        assert manifest["generated_at"] == "2026-08-09T12:00:00Z"
        assert diagnostics == COMPLETE_DIAGNOSTICS
        Draft202012Validator(json.loads(read_contract_bytes("manifest.schema.json"))).validate(manifest)
        Draft202012Validator(json.loads(read_contract_bytes("diagnostics.schema.json"))).validate(diagnostics)


def test_generate_support_bundle_partial_shape(tmp_path):
    ctx = _ctx(tmp_path)
    with patch.object(sb, "_collect_diagnostics") as collect:
        sources = {
            "build": {"status": "available"},
            "runtime": {"status": "available"},
            "configuration": {"status": "available"},
            "database": {"status": "unavailable", "reason": "query_failed"},
            "health": {"status": "unavailable", "reason": "dependency_unavailable"},
        }
        collect.return_value = (PARTIAL_DIAGNOSTICS, sources)
        artifact = sb.generate_support_bundle(ctx, clock=lambda: FIXED_CLOCK)

    assert artifact.status == "partial"
    with _open_bundle(artifact) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        diagnostics = json.loads(zf.read("diagnostics.json"))
        assert manifest["bundle_status"] == "partial"
        assert "database" not in diagnostics
        assert "health" not in diagnostics
        assert manifest["sources"]["database"]["reason"] == "query_failed"


def test_live_generation_succeeds_and_buckets(tmp_path):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(insert(comics).values(ComicID="c1", ComicName="Canary Title NEVER IN BUNDLE"))
        conn.execute(
            insert(issues).values(
                IssueID="i1",
                ComicID="c1",
                ComicName="Canary Title NEVER IN BUNDLE",
                Status="Wanted",
            )
        )
        for i in range(12):
            conn.execute(
                insert(annuals).values(
                    IssueID=f"a{i}",
                    ComicID="c1",
                    ComicName="Canary Annual",
                    Status="Downloaded",
                )
            )

    ctx = _ctx(tmp_path)
    artifact = sb.generate_support_bundle(ctx, clock=lambda: FIXED_CLOCK)
    assert artifact.status in {"complete", "partial"}
    with _open_bundle(artifact) as zf:
        body = zf.read("diagnostics.json") + zf.read("manifest.json") + zf.read("README.txt")
        assert b"Canary Title NEVER IN BUNDLE" not in body
        assert b"Canary Annual" not in body
        diagnostics = json.loads(zf.read("diagnostics.json"))
        if "database" in diagnostics:
            buckets = diagnostics["database"]["count_buckets"]
            assert buckets["series"] == "one"
            assert buckets["issues"] == "one"
            assert buckets["annuals"] == "10_99"
            assert buckets["wanted"] == "one"


def test_closed_schema_rejects_extra_field():
    schema = json.loads(read_contract_bytes("diagnostics.schema.json"))
    bad = dict(COMPLETE_DIAGNOSTICS)
    bad = json.loads(_canon(bad))
    bad["extra"] = "nope"
    with pytest.raises(Exception):
        Draft202012Validator(schema).validate(bad)


def test_field_manifest_parity_with_schemas():
    field_manifest = json.loads(read_contract_bytes("field-manifest.json"))
    assert field_manifest["contract_version"] == 1
    pointers = {(f["schema"], f["pointer"]) for f in field_manifest["fields"]}
    assert len(pointers) == len(field_manifest["fields"])

    # Spot-check mandatory leaves exist.
    assert ("manifest", "/contract_version") in pointers
    assert ("diagnostics", "/build/release_version") in pointers
    assert ("diagnostics", "/database/count_buckets/series") in pointers
    assert ("diagnostics", "/health/routes/ddl/state") in pointers

    # Sorted by schema then pointer.
    ordered = sorted(field_manifest["fields"], key=lambda f: (f["schema"], f["pointer"]))
    assert field_manifest["fields"] == ordered


def test_count_bucket_mapping():
    assert sb._bucket_count(0) == "zero"
    assert sb._bucket_count(1) == "one"
    assert sb._bucket_count(2) == "2_9"
    assert sb._bucket_count(9) == "2_9"
    assert sb._bucket_count(10) == "10_99"
    assert sb._bucket_count(100) == "100_999"
    assert sb._bucket_count(1000) == "1k_9k"
    assert sb._bucket_count(10000) == "10k_99k"
    assert sb._bucket_count(100000) == "100k_plus"


def test_normalize_version_rejects_prerelease_and_paths():
    assert sb._normalize_version("0.27.0") == "0.27.0"
    assert sb._normalize_version("v0.27") == "0.27.0"
    assert sb._normalize_version("0.27.0-dev") == "unknown"
    assert sb._normalize_version("1.2.3+local") == "unknown"
    assert sb._normalize_version("/tmp/canary") == "unknown"
    assert sb._normalize_version(None) == "unknown"


def test_single_flight_lock(tmp_path):
    ctx = _ctx(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    results = []

    def slow_collect(*args, **kwargs):
        entered.set()
        release.wait(timeout=5)
        sources = {
            "build": {"status": "available"},
            "runtime": {"status": "available"},
            "configuration": {"status": "available"},
            "database": {"status": "unavailable", "reason": "query_failed"},
            "health": {"status": "unavailable", "reason": "dependency_unavailable"},
        }
        return PARTIAL_DIAGNOSTICS, sources

    def worker():
        try:
            with patch.object(sb, "_collect_diagnostics", side_effect=slow_collect):
                results.append(sb.generate_support_bundle(ctx, clock=lambda: FIXED_CLOCK))
        except Exception as e:
            results.append(e)

    t = threading.Thread(target=worker)
    t.start()
    assert entered.wait(timeout=5)
    with pytest.raises(sb.SupportBundleInProgress):
        sb.generate_support_bundle(ctx, clock=lambda: FIXED_CLOCK)
    release.set()
    t.join(timeout=5)
    assert len(results) == 1
    assert isinstance(results[0], sb.SupportBundleArtifact)


def test_lock_releases_on_failure(tmp_path):
    ctx = _ctx(tmp_path)
    with patch.object(sb, "_collect_diagnostics", side_effect=RuntimeError("boom")):
        with pytest.raises(sb.SupportBundleGenerationFailed):
            sb.generate_support_bundle(ctx, clock=lambda: FIXED_CLOCK)
    # Fresh attempt works.
    artifact = sb.generate_support_bundle(ctx, clock=lambda: FIXED_CLOCK)
    assert isinstance(artifact, sb.SupportBundleArtifact)


def test_disposed_context_unavailable(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.disposed = True
    with pytest.raises(sb.SupportBundleUnavailable):
        sb.generate_support_bundle(ctx, clock=lambda: FIXED_CLOCK)


def test_canary_values_never_enter_archive(tmp_path, monkeypatch):
    canaries = [
        "canary-password-s3cret",
        "canary-jwt-token-abcdef",
        "gAAAAA-canary-fernet",
        "https://user:canary-url-pass@evil.example/path?token=abc",
        "/Users/canary/custom-config-dir",
        "C:\\Users\\canary\\Windows\\path",
        "canary-hostname.local",
        "canary-branch-name",
        "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        "Canary Library Title",
        "chat prompt canary text",
        "Traceback (most recent call last): canary",
        "provider-canary-name",
    ]
    config = _config(
        COMICVINE_API=canaries[0],
        SAB_HOST=canaries[3],
        SAB_APIKEY=canaries[1],
        SAB_DIRECTORY=canaries[4],
        DDL_LOCATION=canaries[5],
        AI_API_KEY=canaries[1],
        AI_BASE_URL=canaries[3],
        AI_MODEL="canary-model-name",
        METRON_USERNAME="canary-user",
        METRON_PASSWORD=canaries[0],
        LOG_DIR=str(tmp_path / "logs-canary"),
    )
    (tmp_path / "logs-canary").mkdir()
    (tmp_path / "logs-canary" / "comicarr.log").write_text("\n".join(canaries) + "\n", encoding="utf-8")
    monkeypatch.setenv("CANARY_ENV_SECRET", canaries[0])
    monkeypatch.setenv("COMICARR_BUILD_ID", "canary-build-id")
    monkeypatch.setenv("COMICARR_BUILD_COMMIT", canaries[8])

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(insert(comics).values(ComicID="cv-canary", ComicName=canaries[9]))
        conn.execute(
            insert(issues).values(
                IssueID="issue-canary",
                ComicID="cv-canary",
                ComicName=canaries[9],
                Status="Wanted",
            )
        )

    ctx = AppContext(
        prog_dir=str(tmp_path / "prog-canary"),
        data_dir=str(tmp_path / "data-canary"),
        db_file=str(tmp_path / "data-canary" / "comicarr.db"),
        config=config,
        current_version_name="0.27.0",
        install_type="docker",
        scheduler=SimpleNamespace(get_jobs=lambda: []),
        disposed=False,
    )
    # Prove canaries exist in sources first.
    assert config.COMICVINE_API == canaries[0]
    assert canaries[9] in str(
        engine.connect().execute(comics.select().where(comics.c.ComicID == "cv-canary")).mappings().first()
    )

    artifact = sb.generate_support_bundle(ctx, clock=lambda: FIXED_CLOCK)
    assert artifact.filename == "comicarr-support-bundle-v1.zip"
    assert "canary" not in artifact.filename.lower()

    with _open_bundle(artifact) as zf:
        blob = artifact.content + b"".join(zf.read(n) for n in zf.namelist())
        blob += zf.comment
        for info in zf.infolist():
            blob += info.filename.encode("utf-8") + info.comment
        text = blob.decode("utf-8", errors="replace")
        for canary in canaries:
            assert canary not in text, f"canary leaked: {canary}"
        assert "canary-user" not in text
        assert "canary-model-name" not in text
        assert "canary-build-id" not in text
        assert "CANARY_ENV_SECRET" not in text
        # No redaction markers as admission mechanism.
        assert "[redacted]" not in text.lower()


def test_no_disk_artifact_after_generation(tmp_path):
    ctx = _ctx(tmp_path)
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()}
    sb.generate_support_bundle(ctx, clock=lambda: FIXED_CLOCK)
    after = {p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()}
    # Only pre-existing sqlite/log noise may appear from the engine; no zip.
    new_files = after - before
    for path in new_files:
        assert not str(path).endswith(".zip")
        assert "support-bundle" not in str(path).lower()
        assert "carepackage" not in str(path).lower()


def test_packaged_assets_match_source_tree():
    package = importlib.import_module("comicarr.app.system.support_bundle_contract")
    source_root = Path(__file__).resolve().parents[2] / "comicarr" / "app" / "system" / "support_bundle_contract" / "v1"
    for name in (
        "README.txt",
        "manifest.schema.json",
        "diagnostics.schema.json",
        "field-manifest.json",
    ):
        packaged = read_contract_bytes(name)
        source = (source_root / name).read_bytes()
        assert packaged == source
    assert package is not None


def test_modern_module_does_not_import_carepackage():
    source = Path(sb.__file__).read_text(encoding="utf-8")
    # No import/instantiation of the legacy module or class.
    assert "from comicarr.carepackage" not in source
    assert "import comicarr.carepackage" not in source
    assert "carePackage" not in source
    assert "carepackage import" not in source.lower()


def test_safe_error_details_are_fixed():
    body = sb.error_body("support_bundle_in_progress")
    assert body == {
        "detail": "Another support bundle is already being created. Try again in a moment.",
        "code": "support_bundle_in_progress",
        "retryable": True,
    }
    body = sb.error_body("support_bundle_validation_failed")
    assert body["retryable"] is False
    assert "safety checks" in body["detail"]


def test_validation_failure_on_tampered_diagnostics(tmp_path):
    ctx = _ctx(tmp_path)
    bad = dict(COMPLETE_DIAGNOSTICS)
    bad = json.loads(_canon(bad))
    bad["build"]["identity"] = "not-an-enum"
    with patch.object(sb, "_collect_diagnostics") as collect:
        sources = {
            "build": {"status": "available"},
            "runtime": {"status": "available"},
            "configuration": {"status": "available"},
            "database": {"status": "available"},
            "health": {"status": "available"},
        }
        collect.return_value = (bad, sources)
        with pytest.raises(sb.SupportBundleValidationFailed):
            sb.generate_support_bundle(ctx, clock=lambda: FIXED_CLOCK)


def test_recency_buckets():
    gen = FIXED_CLOCK.timestamp()
    assert sb._recency(None, gen) == "never"
    assert sb._recency(gen - 10, gen) == "lt_5m"
    assert sb._recency(gen - 400, gen) == "5m_30m"
    assert sb._recency(gen - 2000, gen) == "30m_2h"
    assert sb._recency(gen - 10000, gen) == "2h_24h"
    assert sb._recency(gen - 100000, gen) == "1d_7d"
    assert sb._recency(gen - 700000, gen) == "gt_7d"
    assert sb._recency(gen + 30, gen) == "lt_5m"  # clamp small future skew
    assert sb._recency(gen + 120, gen) == "unknown"
