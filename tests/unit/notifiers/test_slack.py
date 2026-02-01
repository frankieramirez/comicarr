"""Tests for SLACK notifier."""

import json
import pytest
import responses


class TestSlackInit:
    """Test SLACK initialization."""

    def test_init_uses_config_values(self, notifiers_module, mock_notifier_config):
        """Init should use mylar.CONFIG values by default."""
        slack = notifiers_module.SLACK()

        assert slack.webhook_url == "https://hooks.slack.com/services/test/webhook"

    def test_init_test_webhook_overrides_config(
        self, notifiers_module, mock_notifier_config
    ):
        """Test webhook URL should override config."""
        slack = notifiers_module.SLACK(
            test_webhook_url="https://hooks.slack.com/services/override"
        )

        assert slack.webhook_url == "https://hooks.slack.com/services/override"


class TestSlackNotify:
    """Test SLACK notify method."""

    @responses.activate
    def test_notify_success(self, notifiers_module, mock_notifier_config):
        """Successful notification returns True."""
        responses.add(
            responses.POST,
            "https://hooks.slack.com/services/test/webhook",
            body="ok",
            status=200,
        )

        slack = notifiers_module.SLACK()
        result = slack.notify(text="Mylar", attachment_text="Test notification")

        assert result is True
        assert len(responses.calls) == 1

    @responses.activate
    def test_notify_payload_format(self, notifiers_module, mock_notifier_config):
        """Verify payload format is correct."""
        responses.add(
            responses.POST,
            "https://hooks.slack.com/services/test/webhook",
            body="ok",
            status=200,
        )

        slack = notifiers_module.SLACK()
        result = slack.notify(text="Mylar", attachment_text="Test notification")

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        # Current implementation puts text directly in "text" field
        assert request_body["text"] == "Test notification"

    @responses.activate
    def test_notify_snatched_format(self, notifiers_module, mock_notifier_config):
        """Snatched notification formats message correctly."""
        responses.add(
            responses.POST,
            "https://hooks.slack.com/services/test/webhook",
            body="ok",
            status=200,
        )

        slack = notifiers_module.SLACK()
        result = slack.notify(
            text="Mylar",
            attachment_text="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="NZBGeek",
            sent_to="SABnzbd",
        )

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        assert "Spider-Man 001" in request_body["text"]
        assert "NZBGeek" in request_body["text"]
        assert "SABnzbd" in request_body["text"]

    @responses.activate
    def test_notify_snatched_without_sent_to(
        self, notifiers_module, mock_notifier_config
    ):
        """Snatched notification without sent_to."""
        responses.add(
            responses.POST,
            "https://hooks.slack.com/services/test/webhook",
            body="ok",
            status=200,
        )

        slack = notifiers_module.SLACK()
        result = slack.notify(
            text="Mylar",
            attachment_text="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="NZBGeek",
            sent_to=None,
        )

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        assert "Spider-Man 001" in request_body["text"]
        assert "NZBGeek" in request_body["text"]

    @responses.activate
    def test_notify_module_appended(self, notifiers_module, mock_notifier_config):
        """Module name should be appended for logging."""
        responses.add(
            responses.POST,
            "https://hooks.slack.com/services/test/webhook",
            body="ok",
            status=200,
        )

        slack = notifiers_module.SLACK()
        # Should not raise any errors
        result = slack.notify(
            text="Mylar", attachment_text="Test notification", module="[TEST]"
        )
        assert result is True


class TestSlackNotifyErrors:
    """Test SLACK error handling."""

    @responses.activate
    def test_notify_http_error_returns_false(
        self, notifiers_module, mock_notifier_config
    ):
        """HTTP error returns False."""
        responses.add(
            responses.POST,
            "https://hooks.slack.com/services/test/webhook",
            body="invalid_token",
            status=401,
        )

        slack = notifiers_module.SLACK()
        result = slack.notify(text="Mylar", attachment_text="Test notification")

        assert result is False

    @responses.activate
    def test_notify_not_found_returns_false(
        self, notifiers_module, mock_notifier_config
    ):
        """404 error returns False."""
        responses.add(
            responses.POST,
            "https://hooks.slack.com/services/test/webhook",
            body="channel_not_found",
            status=404,
        )

        slack = notifiers_module.SLACK()
        result = slack.notify(text="Mylar", attachment_text="Test notification")

        assert result is False


class TestSlackTestNotify:
    """Test SLACK test_notify method."""

    @responses.activate
    def test_test_notify_sends_correct_message(
        self, notifiers_module, mock_notifier_config
    ):
        """test_notify sends expected test message."""
        responses.add(
            responses.POST,
            "https://hooks.slack.com/services/test/webhook",
            body="ok",
            status=200,
        )

        slack = notifiers_module.SLACK()
        result = slack.test_notify()

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        assert "Release the Ninjas" in request_body["text"]
