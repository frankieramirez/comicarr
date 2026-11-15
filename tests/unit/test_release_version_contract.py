#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Single build-version contract across release manifests and the API.

Regression for #412: UI chrome and Settings/About must never disagree because
frontend package.json, root package.json, and pyproject.toml drifted, or
because config.version fell back to a git SHA / stale install metadata.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from comicarr.app.core.context import AppContext
from comicarr.app.system import service as system_service

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _read_json_version(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data.get("version")
    assert isinstance(version, str) and version, f"missing version in {path}"
    return version


def _read_pyproject_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    assert isinstance(version, str) and version, "missing [project].version in pyproject.toml"
    return version


def _manifest_versions() -> dict[str, str]:
    return {
        "root package.json": _read_json_version(ROOT / "package.json"),
        "frontend/package.json": _read_json_version(ROOT / "frontend" / "package.json"),
        "pyproject.toml": _read_pyproject_version(),
    }


@pytest.fixture
def release_version() -> str:
    versions = _manifest_versions()
    unique = set(versions.values())
    assert len(unique) == 1, f"release version drift between manifests: {versions}"
    version = next(iter(unique))
    assert SEMVER.fullmatch(version), f"invalid release version {version!r}"
    return version


class TestReleaseVersionContract:
    def test_all_release_manifests_share_one_version(self, release_version):
        """Changesets + sync-version must keep every release surface aligned."""
        versions = _manifest_versions()
        assert versions == {
            "root package.json": release_version,
            "frontend/package.json": release_version,
            "pyproject.toml": release_version,
        }

    def test_get_release_version_matches_manifests(self, release_version):
        """Backend display/API version must resolve to the same release SSOT."""
        assert system_service.get_release_version() == release_version

    def test_get_safe_config_version_matches_manifests_not_git_sha(self, release_version):
        """config.version must not surface install/git identity."""
        config = MagicMock()
        # Minimal attrs so get_safe_config can run without real Config.
        for key in (
            "API_KEY",
            "COMICVINE_API",
            "AI_API_KEY",
            "METRON_PASSWORD",
            "MAL_CLIENT_ID",
            "PROWL_KEYS",
            "SLACK_WEBHOOK_URL",
            "MATTERMOST_WEBHOOK_URL",
            "DISCORD_WEBHOOK_URL",
            "NZB_DOWNLOADER",
            "TORRENT_DOWNLOADER",
        ):
            setattr(config, key, None)
        ctx = AppContext(
            prog_dir="/tmp/comicarr_test",
            data_dir="/tmp/comicarr_test/data",
            db_file=":memory:",
            config=config,
            scheduler=MagicMock(),
            current_version="a1b2c3d4e5f6789012345678",
            current_version_name="v0.19.13",
        )
        result = system_service.get_safe_config(ctx)
        assert result["version"] == release_version
        assert result["version"] != ctx.current_version
        assert result["version"] != "0.19.13"
        assert result["version"] != "v0.19.13"

    def test_get_release_version_ignores_stale_importlib_when_pyproject_present(self, release_version):
        """pyproject wins so a stale egg-info cannot reintroduce the mismatch."""
        with patch("importlib.metadata.version", return_value="0.19.13") as mock_meta:
            assert system_service.get_release_version() == release_version
            mock_meta.assert_not_called()


def test_get_safe_config_reports_where_this_install_keeps_its_files(monkeypatch, tmp_path):
    """Settings and About fell back to a Docker-shaped path when these were missing."""
    config = MagicMock()
    config._config_file = str(tmp_path / "config.ini")
    for key in ("NZB_DOWNLOADER", "TORRENT_DOWNLOADER"):
        setattr(config, key, None)
    ctx = AppContext(
        prog_dir=str(tmp_path),
        data_dir=str(tmp_path / "data"),
        db_file=":memory:",
        config=config,
        scheduler=MagicMock(),
    )
    result = system_service.get_safe_config(ctx)
    assert result["config_path"] == str(tmp_path / "config.ini")
    assert result["data_dir"] == str(tmp_path / "data")
    assert result["python_version"].count(".") == 2
