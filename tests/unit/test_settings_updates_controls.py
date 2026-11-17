#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Settings → About → Updates: registry exposure and force-check (#471)."""

from unittest.mock import MagicMock, patch

import pytest

import comicarr
from comicarr.app.config.registry import REGISTRY, readable_keys, writable_keys
from comicarr.app.core.context import AppContext
from comicarr.app.system import service as system_service


def test_check_github_is_readable_and_writable():
    key = REGISTRY["CHECK_GITHUB"]
    assert key.default is True
    assert key.readable is True
    assert key.writable is True
    assert "CHECK_GITHUB" in readable_keys()
    assert "CHECK_GITHUB" in writable_keys()


def test_announce_releases_defaults_off_and_is_settings_exposed():
    key = REGISTRY["ANNOUNCE_RELEASES"]
    assert key.default is False
    assert key.readable is True
    assert key.writable is True
    assert "ANNOUNCE_RELEASES" in readable_keys()
    assert "ANNOUNCE_RELEASES" in writable_keys()


def test_check_github_interval_stays_config_ini_only():
    key = REGISTRY["CHECK_GITHUB_INTERVAL"]
    assert key.readable is False
    assert key.writable is False
    assert "CHECK_GITHUB_INTERVAL" not in readable_keys()
    assert "CHECK_GITHUB_INTERVAL" not in writable_keys()


def test_auto_update_absent_from_registry():
    assert "AUTO_UPDATE" not in REGISTRY


def test_get_safe_config_exposes_update_policy_keys():
    """Both toggles are readable over GET /api/config (Settings form)."""
    config = MagicMock()
    config.CHECK_GITHUB = False
    config.ANNOUNCE_RELEASES = True
    # get_safe_config walks every readable key; default MagicMock attrs are truthy
    # and would pollute the result — only the two under test matter here.
    ctx = AppContext(
        prog_dir="/tmp/comicarr_test",
        data_dir="/tmp/comicarr_test/data",
        db_file=":memory:",
        config=config,
    )
    with patch.object(system_service, "get_release_version", return_value="0.21.0"):
        # Real get_safe_config iterates _READABLE_KEYS from the live registry.
        result = system_service.get_safe_config(ctx)

    assert result.get("check_github") is False
    assert result.get("announce_releases") is True


@pytest.fixture
def ctx(monkeypatch):
    config = MagicMock(
        CHECK_GITHUB=False,
        ANNOUNCE_RELEASES=False,
        GIT_TOKEN=None,
    )
    context = AppContext(
        prog_dir="/tmp/comicarr_test",
        data_dir="/tmp/comicarr_test/data",
        db_file=":memory:",
        config=config,
        scheduler=MagicMock(),
        current_version="aaaaaaa",
        latest_version=None,
        update_state="unknown",
        update_reason="never_checked",
    )
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)
    monkeypatch.setattr(comicarr, "INSTALL_TYPE", "docker", raising=False)
    monkeypatch.setattr(comicarr, "CURRENT_VERSION", "aaaaaaa", raising=False)
    with (
        patch("comicarr.app.core.runtime.get_runtime_if_initialized", return_value=context),
        patch.object(system_service, "get_release_version", return_value="0.21.0"),
    ):
        yield context


class TestForceVersionCheck:
    def test_runs_even_when_automatic_check_is_off(self, ctx):
        """Off means no unsolicited traffic — not refuse when the operator asks."""
        assert ctx.config.CHECK_GITHUB is False

        check_payload = {
            "status": "success",
            "update_state": "behind",
            "update_reason": None,
            "latest_version": "0.22.0",
            "release_version": "0.21.0",
            "current_version": "aaaaaaa",
            "install_type": "docker",
            "message": "A new release is available",
        }

        mock_runner = MagicMock()
        mock_runner.run.return_value = check_payload
        mock_cls = MagicMock(return_value=mock_runner)

        with patch.object(comicarr.app.system.versioncheckit, "CheckVersion", mock_cls):
            # Simulate what CheckVersion.run does: persist state via the seam.
            def _run(scheduled_job=True):
                from comicarr.app.system import versioncheck

                versioncheck._set_version_state(
                    update_state="behind",
                    update_reason=None,
                    latest_version="0.22.0",
                )
                return check_payload

            mock_runner.run.side_effect = _run
            result = system_service.force_version_check(ctx)

        mock_runner.run.assert_called_once_with(scheduled_job=False)
        assert result["update_state"] == "behind"
        assert result["latest_version"] == "0.22.0"
        assert result["release_version"] == "0.21.0"
        assert result["update_reason"] is None

    def test_returns_unknown_reason_after_unreachable_check(self, ctx):
        mock_runner = MagicMock()
        mock_cls = MagicMock(return_value=mock_runner)

        with patch.object(comicarr.app.system.versioncheckit, "CheckVersion", mock_cls):

            def _run(scheduled_job=True):
                from comicarr.app.system import versioncheck

                versioncheck._set_version_state(
                    update_state="unknown",
                    update_reason="unreachable",
                )
                return {
                    "status": "failure",
                    "update_state": "unknown",
                    "update_reason": "unreachable",
                }

            mock_runner.run.side_effect = _run
            result = system_service.force_version_check(ctx)

        assert result["update_state"] == "unknown"
        assert result["update_reason"] == "unreachable"
