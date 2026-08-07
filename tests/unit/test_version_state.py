#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Semver release check state must reach GET /api/system/version.

Update availability is the Changesets release line (not git commit lag). The
runtime context is built once from module globals, so every write after boot
must go through ``_set_version_state`` or the API never moves.
"""

from unittest.mock import MagicMock, patch

import pytest

import comicarr
from comicarr import versioncheck
from comicarr.app.config.registry import REGISTRY
from comicarr.app.core.context import AppContext
from comicarr.app.system import service as system_service


def test_git_user_default_is_project_owner():
    """Out-of-box owner constant remains frankieramirez (identity elsewhere).

    Update checks no longer read GIT_USER, but other git tooling still does.
    Regression for #456.
    """
    assert REGISTRY["GIT_USER"].default == "frankieramirez"


def test_check_github_defaults_on():
    assert REGISTRY["CHECK_GITHUB"].default is True
    # 16 is where the CHECK_GITHUB default-on migration landed. This test is
    # about that default, not about the current schema version, so it asserts
    # the migration has shipped rather than re-pinning the exact number — which
    # test_config_version_migrations.py already owns and every later bump would
    # otherwise break here for no reason.
    assert REGISTRY["CONFIG_VERSION"].default >= 16
    assert "AUTO_UPDATE" not in REGISTRY
    assert "CHECK_GITHUB_ON_STARTUP" not in REGISTRY


@pytest.fixture
def ctx(monkeypatch):
    config = MagicMock(GIT_USER="wrong-user", GIT_BRANCH="main", GIT_TOKEN=None, CHECK_GITHUB=True)
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
    monkeypatch.setattr(comicarr, "INSTALL_TYPE", "git", raising=False)
    monkeypatch.setattr(comicarr, "CURRENT_VERSION", "aaaaaaa", raising=False)
    with (
        patch("comicarr.app.core.runtime.get_runtime_if_initialized", return_value=context),
        patch.object(system_service, "get_release_version", return_value="0.20.0"),
    ):
        yield context


def _github_response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


class TestSemverReleaseCheck:
    def test_behind_when_remote_is_newer(self, ctx):
        with patch.object(
            versioncheck.requests,
            "get",
            return_value=_github_response({"tag_name": "v0.21.0"}),
        ) as mock_get:
            result = versioncheck.checkGithub(current_version="aaaaaaa")

        info = system_service.get_version_info(ctx)
        assert result["update_state"] == "behind"
        assert info["update_state"] == "behind"
        assert info["update_reason"] is None
        assert info["latest_version"] == "0.21.0"
        assert info["release_version"] == "0.20.0"
        assert "commits_behind" not in info
        # Constant owner/repo — never GIT_USER from config.
        assert mock_get.call_args.args[0] == versioncheck._GITHUB_RELEASES_LATEST
        assert "wrong-user" not in mock_get.call_args.args[0]
        assert "frankieramirez/comicarr" in mock_get.call_args.args[0]

    def test_current_when_versions_match(self, ctx):
        with patch.object(
            versioncheck.requests,
            "get",
            return_value=_github_response({"tag_name": "v0.20.0"}),
        ):
            versioncheck.checkGithub()

        info = system_service.get_version_info(ctx)
        assert info["update_state"] == "current"
        assert info["update_reason"] is None
        assert info["latest_version"] == "0.20.0"

    def test_ahead_collapses_to_current(self, ctx):
        with (
            patch.object(system_service, "get_release_version", return_value="0.22.0"),
            patch.object(
                versioncheck.requests,
                "get",
                return_value=_github_response({"tag_name": "v0.21.0"}),
            ),
        ):
            versioncheck.checkGithub()

        assert system_service.get_version_info(ctx)["update_state"] == "current"

    def test_strips_single_leading_v_only(self, ctx):
        with patch.object(
            versioncheck.requests,
            "get",
            return_value=_github_response({"tag_name": "v0.21.0"}),
        ):
            versioncheck.checkGithub()
        assert system_service.get_version_info(ctx)["latest_version"] == "0.21.0"

    def test_legacy_globals_stay_in_step(self, ctx):
        with patch.object(
            versioncheck.requests,
            "get",
            return_value=_github_response({"tag_name": "v0.21.0"}),
        ):
            versioncheck.checkGithub()

        assert comicarr.LATEST_VERSION == "0.21.0"
        assert comicarr.UPDATE_STATE == "behind"
        assert ctx.latest_version == comicarr.LATEST_VERSION
        assert ctx.update_state == comicarr.UPDATE_STATE


class TestUnknownReasons:
    def test_network_failure_is_unreachable_not_current(self, ctx):
        with patch.object(versioncheck.requests, "get", side_effect=RuntimeError("no network")):
            result = versioncheck.checkGithub()

        info = system_service.get_version_info(ctx)
        assert result["update_state"] == "unknown"
        assert info["update_state"] == "unknown"
        assert info["update_reason"] == "unreachable"
        assert info["update_state"] != "current"

    def test_rate_limited_is_not_up_to_date(self, ctx):
        with patch.object(
            versioncheck.requests,
            "get",
            return_value=_github_response({}, status_code=403),
        ):
            versioncheck.checkGithub()

        info = system_service.get_version_info(ctx)
        assert info["update_state"] == "unknown"
        assert info["update_reason"] == "rate_limited"

    def test_http_429_is_rate_limited(self, ctx):
        with patch.object(
            versioncheck.requests,
            "get",
            return_value=_github_response({}, status_code=429),
        ):
            versioncheck.checkGithub()

        assert system_service.get_version_info(ctx)["update_reason"] == "rate_limited"

    def test_unparseable_local_is_unknown(self, ctx):
        with (
            patch.object(system_service, "get_release_version", return_value="not-a-version"),
            patch.object(
                versioncheck.requests,
                "get",
                return_value=_github_response({"tag_name": "v0.21.0"}),
            ),
        ):
            versioncheck.checkGithub()

        info = system_service.get_version_info(ctx)
        assert info["update_state"] == "unknown"
        assert info["update_reason"] == "unreachable"

    def test_failed_check_does_not_clear_to_current(self, ctx):
        with patch.object(
            versioncheck.requests,
            "get",
            return_value=_github_response({"tag_name": "v0.21.0"}),
        ):
            versioncheck.checkGithub()
        assert system_service.get_version_info(ctx)["update_state"] == "behind"

        with patch.object(versioncheck.requests, "get", side_effect=RuntimeError("no network")):
            versioncheck.checkGithub()

        info = system_service.get_version_info(ctx)
        assert info["update_state"] == "unknown"
        assert info["update_reason"] == "unreachable"


class TestGithubRequestTimeout:
    """Update checks must bound connect/read so a dropped SYN cannot hang forever.

    Issue #455 / #446: failed checks keep retrying on the 360-minute schedule.
    That policy is only safe when each attempt has a hard timeout (10s, 10s).
    """

    def test_check_github_passes_timeout_on_every_request(self, ctx):
        with patch.object(
            versioncheck.requests,
            "get",
            return_value=_github_response({"tag_name": "v0.21.0"}),
        ) as mock_get:
            versioncheck.checkGithub()

        assert mock_get.call_count == 1
        assert mock_get.call_args.kwargs.get("timeout") == versioncheck._GITHUB_REQUEST_TIMEOUT
        assert versioncheck._GITHUB_REQUEST_TIMEOUT == (10, 10)

    def test_check_github_preserves_auth_with_timeout(self, ctx):
        token = ("ghp_test", "x-oauth-basic")
        comicarr.CONFIG.GIT_TOKEN = token
        with patch.object(
            versioncheck.requests,
            "get",
            return_value=_github_response({"tag_name": "v0.20.0"}),
        ) as mock_get:
            versioncheck.checkGithub()

        assert mock_get.call_args.kwargs.get("auth") is token
        assert mock_get.call_args.kwargs.get("timeout") == (10, 10)

    def test_timeout_error_is_unreachable(self, ctx):
        with patch.object(
            versioncheck.requests,
            "get",
            side_effect=versioncheck.requests.exceptions.Timeout("connect timed out"),
        ):
            result = versioncheck.checkGithub()

        assert result["status"] == "failure"
        assert system_service.get_version_info(ctx)["update_reason"] == "unreachable"


class TestDeadToastPathRetired:
    def test_check_github_emits_no_toast_event(self, ctx):
        """Version state is polled, never announced (#430 / #470 / #488)."""
        with patch.object(
            versioncheck.requests,
            "get",
            return_value=_github_response({"tag_name": "v0.21.0"}),
        ):
            result = versioncheck.checkGithub()

        assert "event" not in result
        assert result.get("event") != "check_update"

    def test_check_github_does_not_set_auto_update_signal(self, ctx):
        comicarr.SIGNAL = None
        with patch.object(
            versioncheck.requests,
            "get",
            return_value=_github_response({"tag_name": "v0.21.0"}),
        ):
            versioncheck.checkGithub()
        assert comicarr.SIGNAL is None


class TestVersionStateHelper:
    def test_writes_context_and_legacy_together(self, ctx):
        versioncheck._set_version_state(current_branch="python3-dev")

        assert ctx.current_branch == "python3-dev"
        assert comicarr.CURRENT_BRANCH == "python3-dev"

    def test_falls_back_to_the_module_before_the_runtime_exists(self):
        with patch("comicarr.app.core.runtime.get_runtime_if_initialized", return_value=None):
            versioncheck._set_version_state(current_version="preboot")

        assert comicarr.CURRENT_VERSION == "preboot"

    def test_falls_back_to_the_module_after_disposal(self, ctx):
        ctx.disposed = True

        versioncheck._set_version_state(latest_version="postdispose")

        assert comicarr.LATEST_VERSION == "postdispose"
        assert ctx.latest_version != "postdispose"

    def test_every_mapped_field_exists_on_the_context(self, ctx):
        for field in versioncheck._VERSION_FIELDS:
            assert hasattr(ctx, field), "AppContext is missing %s" % field

    def test_never_checked_is_the_precheck_default(self, ctx):
        info = system_service.get_version_info(ctx)
        assert info["update_state"] == "unknown"
        assert info["update_reason"] == "never_checked"
