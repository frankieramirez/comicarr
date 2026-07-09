#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Success-check and exception-path tests for webhook notifiers."""

from unittest.mock import MagicMock, patch

import pytest
import requests

WEBHOOK_URL = "https://example.test/webhook"


@pytest.fixture
def mock_webhook_config(monkeypatch):
    """Minimal comicarr.CONFIG for Slack/Mattermost/Discord/Gotify constructors."""
    import comicarr

    monkeypatch.setattr(comicarr, "LOG_LEVEL", 1)

    config = MagicMock()
    config.SLACK_WEBHOOK_URL = WEBHOOK_URL
    config.MATTERMOST_WEBHOOK_URL = WEBHOOK_URL
    config.DISCORD_WEBHOOK_URL = WEBHOOK_URL
    config.GOTIFY_SERVER_URL = "https://example.test/"
    config.GOTIFY_TOKEN = "fake-gotify-token"
    monkeypatch.setattr(comicarr, "CONFIG", config)
    return config


def _mock_response(status_code, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return response


class TestDiscordWebhookSuccess:
    def test_status_204_returns_true(self, mock_webhook_config):
        from comicarr.notifiers import DISCORD

        with patch("requests.post", return_value=_mock_response(204)):
            result = DISCORD(test_webhook_url=WEBHOOK_URL).notify("Test Message", "Release the Ninjas!")
        assert result is True

    def test_status_200_returns_true(self, mock_webhook_config):
        from comicarr.notifiers import DISCORD

        with patch("requests.post", return_value=_mock_response(200)):
            result = DISCORD(test_webhook_url=WEBHOOK_URL).notify("Test Message", "Release the Ninjas!")
        assert result is True

    def test_status_500_returns_false(self, mock_webhook_config):
        from comicarr.notifiers import DISCORD

        with patch("requests.post", return_value=_mock_response(500, "error")):
            result = DISCORD(test_webhook_url=WEBHOOK_URL).notify("Test Message", "Release the Ninjas!")
        assert result is False

    def test_request_exception_returns_false(self, mock_webhook_config):
        from comicarr.notifiers import DISCORD

        with patch(
            "requests.post",
            side_effect=requests.RequestException("network down"),
        ):
            result = DISCORD(test_webhook_url=WEBHOOK_URL).notify("Test Message", "Release the Ninjas!")
        assert result is False


class TestSlackWebhookSuccess:
    def test_status_200_returns_true(self, mock_webhook_config):
        from comicarr.notifiers import SLACK

        with patch("requests.post", return_value=_mock_response(200, "ok")):
            result = SLACK(test_webhook_url=WEBHOOK_URL).notify("Test Message", "Release the Ninjas!")
        assert result is True

    def test_status_500_returns_false(self, mock_webhook_config):
        from comicarr.notifiers import SLACK

        with patch("requests.post", return_value=_mock_response(500, "error")):
            result = SLACK(test_webhook_url=WEBHOOK_URL).notify("Test Message", "Release the Ninjas!")
        assert result is False

    def test_request_exception_returns_false(self, mock_webhook_config):
        from comicarr.notifiers import SLACK

        with patch(
            "requests.post",
            side_effect=requests.RequestException("network down"),
        ):
            result = SLACK(test_webhook_url=WEBHOOK_URL).notify("Test Message", "Release the Ninjas!")
        assert result is False


@pytest.mark.parametrize(
    "notifier_name",
    ["MATTERMOST", "GOTIFY"],
)
class TestSiblingWebhookSuccess:
    def test_status_200_returns_true(self, mock_webhook_config, notifier_name):
        from comicarr import notifiers

        cls = getattr(notifiers, notifier_name)
        with patch("requests.post", return_value=_mock_response(200, "ok")):
            result = cls(test_webhook_url=WEBHOOK_URL).notify("Test Message", "Release the Ninjas!")
        assert result is True

    def test_status_500_returns_false(self, mock_webhook_config, notifier_name):
        from comicarr import notifiers

        cls = getattr(notifiers, notifier_name)
        with patch("requests.post", return_value=_mock_response(500, "error")):
            result = cls(test_webhook_url=WEBHOOK_URL).notify("Test Message", "Release the Ninjas!")
        assert result is False

    def test_request_exception_returns_false(self, mock_webhook_config, notifier_name):
        from comicarr import notifiers

        cls = getattr(notifiers, notifier_name)
        with patch(
            "requests.post",
            side_effect=requests.RequestException("network down"),
        ):
            result = cls(test_webhook_url=WEBHOOK_URL).notify("Test Message", "Release the Ninjas!")
        assert result is False
