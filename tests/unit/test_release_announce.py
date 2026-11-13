#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Outbound release announcements via enabled notifiers (#475 / #453).

Seams under test:
- ``versioncheck.should_announce_release`` — gate + dedup decision
- ``versioncheck.announce_release`` — fan-out to ENABLED notifiers and write
  ``LAST_ANNOUNCED_VERSION`` after the attempt
- ``versioncheck.checkGithub`` — hooks announce after behind state is computed
"""

from unittest.mock import MagicMock, patch

import pytest

import comicarr
from comicarr import versioncheck
from comicarr.app.config.registry import REGISTRY
from comicarr.app.core.context import AppContext
from comicarr.app.system import service as system_service


def test_announce_releases_defaults_off_and_is_settings_writable():
    assert REGISTRY["ANNOUNCE_RELEASES"].default is False
    assert REGISTRY["ANNOUNCE_RELEASES"].readable is True
    assert REGISTRY["ANNOUNCE_RELEASES"].writable is True
    assert REGISTRY["ANNOUNCE_RELEASES"].section == "Git"


def test_last_announced_version_is_install_wide_and_separate_from_settings():
    assert REGISTRY["LAST_ANNOUNCED_VERSION"].default is None
    assert REGISTRY["LAST_ANNOUNCED_VERSION"].readable is False
    assert REGISTRY["LAST_ANNOUNCED_VERSION"].writable is False
    assert REGISTRY["LAST_ANNOUNCED_VERSION"].section == "Git"
    # LAST_SEEN_VERSION is owned by What's New (#474), not announce dedup.


class TestShouldAnnounceRelease:
    def test_no_when_announce_off(self):
        assert (
            versioncheck.should_announce_release(
                announce_on=False,
                update_state="behind",
                latest_version="0.21.0",
                last_announced_version=None,
            )
            is False
        )

    def test_no_when_current(self):
        assert (
            versioncheck.should_announce_release(
                announce_on=True,
                update_state="current",
                latest_version="0.20.0",
                last_announced_version=None,
            )
            is False
        )

    def test_no_when_unknown(self):
        assert (
            versioncheck.should_announce_release(
                announce_on=True,
                update_state="unknown",
                latest_version="0.21.0",
                last_announced_version=None,
            )
            is False
        )

    def test_no_when_already_announced_same_latest(self):
        assert (
            versioncheck.should_announce_release(
                announce_on=True,
                update_state="behind",
                latest_version="0.21.0",
                last_announced_version="0.21.0",
            )
            is False
        )

    def test_yes_when_behind_announce_on_and_never_announced(self):
        assert (
            versioncheck.should_announce_release(
                announce_on=True,
                update_state="behind",
                latest_version="0.21.0",
                last_announced_version=None,
            )
            is True
        )

    def test_yes_when_latest_moved_past_last_announced(self):
        """Multi-release jump: only the newest latest is announced once."""
        assert (
            versioncheck.should_announce_release(
                announce_on=True,
                update_state="behind",
                latest_version="0.21.5",
                last_announced_version="0.20.0",
            )
            is True
        )

    def test_no_when_latest_missing(self):
        assert (
            versioncheck.should_announce_release(
                announce_on=True,
                update_state="behind",
                latest_version=None,
                last_announced_version=None,
            )
            is False
        )


class TestReleaseAnnounceMessage:
    def test_body_is_version_arrow_and_release_url_without_notes(self):
        event, body = versioncheck.release_announce_message("0.20.0", "0.21.0")
        assert event == "Update available"
        assert body == ("0.20.0 → 0.21.0\nhttps://github.com/frankieramirez/comicarr/releases/tag/v0.21.0")
        assert "changelog" not in body.lower()
        assert "##" not in body


@pytest.fixture
def announce_ctx(monkeypatch):
    config = MagicMock(
        GIT_USER="frankieramirez",
        GIT_BRANCH="main",
        GIT_TOKEN=None,
        CHECK_GITHUB=True,
        ANNOUNCE_RELEASES=True,
        LAST_ANNOUNCED_VERSION=None,
        PROWL_ENABLED=False,
        PUSHOVER_ENABLED=False,
        BOXCAR_ENABLED=False,
        PUSHBULLET_ENABLED=False,
        TELEGRAM_ENABLED=False,
        SLACK_ENABLED=False,
        MATTERMOST_ENABLED=False,
        DISCORD_ENABLED=False,
        EMAIL_ENABLED=False,
        GOTIFY_ENABLED=False,
        MATRIX_ENABLED=False,
    )
    config.writeconfig = MagicMock(return_value=True)
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
        patch.object(system_service, "get_release_version", return_value="0.20.0"),
    ):
        yield context, config


def _github_response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


class TestAnnounceReleaseFanout:
    def test_enabled_only_not_onsnatch_flags(self, announce_ctx):
        """Gate is ANNOUNCE_RELEASES × *_ENABLED; snatch/grab flags are ignored."""
        _ctx, config = announce_ctx
        config.PROWL_ENABLED = True
        config.PROWL_ONSNATCH = False  # must not matter
        config.EMAIL_ENABLED = True
        config.EMAIL_ONGRAB = False  # must not matter
        config.DISCORD_ENABLED = False
        config.DISCORD_ONSNATCH = True  # must not fire Discord

        with (
            patch("comicarr.app.notifications.service.PROWL") as prowl_cls,
            patch("comicarr.app.notifications.service.EMAIL") as email_cls,
            patch("comicarr.app.notifications.service.DISCORD") as discord_cls,
        ):
            prowl = prowl_cls.return_value
            email = email_cls.return_value
            versioncheck.announce_release(current_version="0.20.0", latest_version="0.21.0")

        prowl.notify.assert_called_once()
        email.notify.assert_called_once()
        discord_cls.assert_not_called()

        event, body = versioncheck.release_announce_message("0.20.0", "0.21.0")
        # Prowl: (message, event)
        assert prowl.notify.call_args.args[0] == body
        assert prowl.notify.call_args.args[1] == event
        # Email: (message, subject)
        assert email.notify.call_args.args[0] == body
        assert "Update available" in email.notify.call_args.args[1]

    def test_writes_last_announced_after_attempt_even_if_notifier_fails(self, announce_ctx):
        _ctx, config = announce_ctx
        config.TELEGRAM_ENABLED = True

        with patch("comicarr.app.notifications.service.TELEGRAM") as telegram_cls:
            telegram_cls.return_value.notify.side_effect = RuntimeError("flaky webhook")
            versioncheck.announce_release(current_version="0.20.0", latest_version="0.21.5")

        config.writeconfig.assert_called_once_with(values={"last_announced_version": "0.21.5"})
        assert config.LAST_ANNOUNCED_VERSION == "0.21.5"

    def test_all_eleven_notifiers_when_enabled(self, announce_ctx):
        _ctx, config = announce_ctx
        for name in (
            "PROWL",
            "PUSHOVER",
            "BOXCAR",
            "PUSHBULLET",
            "TELEGRAM",
            "SLACK",
            "MATTERMOST",
            "DISCORD",
            "EMAIL",
            "GOTIFY",
            "MATRIX",
        ):
            setattr(config, f"{name}_ENABLED", True)

        patches = {
            name: patch(f"comicarr.app.notifications.service.{name}")
            for name in (
                "PROWL",
                "PUSHOVER",
                "BOXCAR",
                "PUSHBULLET",
                "TELEGRAM",
                "SLACK",
                "MATTERMOST",
                "DISCORD",
                "EMAIL",
                "GOTIFY",
                "MATRIX",
            )
        }
        with (
            patches["PROWL"] as p_prowl,
            patches["PUSHOVER"] as p_push,
            patches["BOXCAR"] as p_box,
            patches["PUSHBULLET"] as p_pb,
            patches["TELEGRAM"] as p_tg,
            patches["SLACK"] as p_slack,
            patches["MATTERMOST"] as p_mm,
            patches["DISCORD"] as p_discord,
            patches["EMAIL"] as p_email,
            patches["GOTIFY"] as p_gotify,
            patches["MATRIX"] as p_matrix,
        ):
            versioncheck.announce_release(current_version="0.20.0", latest_version="0.22.0")

        for mock_cls in (
            p_prowl,
            p_push,
            p_box,
            p_pb,
            p_tg,
            p_slack,
            p_mm,
            p_discord,
            p_email,
            p_gotify,
            p_matrix,
        ):
            mock_cls.return_value.notify.assert_called_once()


class TestCheckGithubAnnounceHook:
    def test_announces_when_behind_and_opted_in(self, announce_ctx):
        _ctx, config = announce_ctx
        config.ANNOUNCE_RELEASES = True
        config.LAST_ANNOUNCED_VERSION = None

        with (
            patch.object(
                versioncheck.requests,
                "get",
                return_value=_github_response({"tag_name": "v0.21.0"}),
            ),
            patch.object(versioncheck, "announce_release") as announce,
        ):
            result = versioncheck.checkGithub()

        assert result["update_state"] == "behind"
        announce.assert_called_once_with(current_version="0.20.0", latest_version="0.21.0")

    def test_no_announce_when_current(self, announce_ctx):
        _ctx, config = announce_ctx
        config.ANNOUNCE_RELEASES = True

        with (
            patch.object(
                versioncheck.requests,
                "get",
                return_value=_github_response({"tag_name": "v0.20.0"}),
            ),
            patch.object(versioncheck, "announce_release") as announce,
        ):
            result = versioncheck.checkGithub()

        assert result["update_state"] == "current"
        announce.assert_not_called()

    def test_no_announce_when_opted_out(self, announce_ctx):
        _ctx, config = announce_ctx
        config.ANNOUNCE_RELEASES = False

        with (
            patch.object(
                versioncheck.requests,
                "get",
                return_value=_github_response({"tag_name": "v0.21.0"}),
            ),
            patch.object(versioncheck, "announce_release") as announce,
        ):
            result = versioncheck.checkGithub()

        assert result["update_state"] == "behind"
        announce.assert_not_called()

    def test_no_announce_when_already_announced(self, announce_ctx):
        _ctx, config = announce_ctx
        config.ANNOUNCE_RELEASES = True
        config.LAST_ANNOUNCED_VERSION = "0.21.0"

        with (
            patch.object(
                versioncheck.requests,
                "get",
                return_value=_github_response({"tag_name": "v0.21.0"}),
            ),
            patch.object(versioncheck, "announce_release") as announce,
        ):
            result = versioncheck.checkGithub()

        assert result["update_state"] == "behind"
        announce.assert_not_called()

    def test_single_announce_on_multi_release_jump(self, announce_ctx):
        """One check interval sees newest latest only — one fan-out for that latest."""
        _ctx, config = announce_ctx
        config.ANNOUNCE_RELEASES = True
        config.LAST_ANNOUNCED_VERSION = "0.20.0"

        with (
            patch.object(
                versioncheck.requests,
                "get",
                return_value=_github_response({"tag_name": "v0.21.5"}),
            ),
            patch.object(versioncheck, "announce_release") as announce,
        ):
            result = versioncheck.checkGithub()

        assert result["latest_version"] == "0.21.5"
        announce.assert_called_once_with(current_version="0.20.0", latest_version="0.21.5")

    def test_announces_for_docker_install_type(self, announce_ctx):
        _ctx, config = announce_ctx
        comicarr.INSTALL_TYPE = "docker"
        config.ANNOUNCE_RELEASES = True

        with (
            patch.object(
                versioncheck.requests,
                "get",
                return_value=_github_response({"tag_name": "v0.21.0"}),
            ),
            patch.object(versioncheck, "announce_release") as announce,
        ):
            versioncheck.checkGithub()

        announce.assert_called_once()
