"""Tests for PUSHOVER notifier."""

import json
import urllib.parse
import pytest
import responses


class TestPushoverInit:
    """Test PUSHOVER initialization."""

    def test_init_uses_config_values(self, notifiers_module, mock_notifier_config):
        """Init should use comicarr.CONFIG values by default."""
        pushover = notifiers_module.PUSHOVER()

        assert pushover.apikey == "test_pushover_apikey"
        assert pushover.userkey == "test_pushover_userkey"
        assert pushover.device is None
        assert pushover.priority == 0
        assert pushover.test is False
        assert pushover.PUSHOVER_URL == "https://api.pushover.net/1/messages.json"

    def test_init_test_params_override_config(
        self, notifiers_module, mock_notifier_config
    ):
        """Test parameters should override config values."""
        pushover = notifiers_module.PUSHOVER(
            test_apikey="override_apikey",
            test_userkey="override_userkey",
            test_device="override_device",
        )

        assert pushover.apikey == "override_apikey"
        assert pushover.userkey == "override_userkey"
        assert pushover.device == "override_device"
        assert pushover.test is True
        # Test mode uses validate URL
        assert pushover.PUSHOVER_URL == "https://api.pushover.net/1/users/validate.json"


class TestPushoverNotify:
    """Test PUSHOVER notify method."""

    @responses.activate
    def test_notify_success(self, notifiers_module, mock_notifier_config):
        """Successful notification returns True."""
        responses.add(
            responses.POST,
            "https://api.pushover.net/1/messages.json",
            json={"status": 1, "request": "test-request-id"},
            status=200,
        )

        pushover = notifiers_module.PUSHOVER()
        result = pushover.notify(event="Test Event", message="Test message")

        assert result is True
        assert len(responses.calls) == 1

    @responses.activate
    def test_notify_with_snatched_info(self, notifiers_module, mock_notifier_config):
        """Snatched notification formats message correctly."""
        responses.add(
            responses.POST,
            "https://api.pushover.net/1/messages.json",
            json={"status": 1, "request": "test-request-id"},
            status=200,
        )

        pushover = notifiers_module.PUSHOVER()
        result = pushover.notify(
            event="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="NZBGeek",
            sent_to="SABnzbd",
        )

        assert result is True
        # Verify the message was formatted with snatched info (URL encoded)
        request_body = responses.calls[0].request.body
        # Decode URL encoding
        decoded_body = urllib.parse.unquote_plus(request_body)
        assert "Spider-Man 001" in decoded_body
        assert "NZBGeek" in decoded_body
        assert "SABnzbd" in decoded_body

    @responses.activate
    def test_notify_strips_trailing_period_from_nzb_name(
        self, notifiers_module, mock_notifier_config
    ):
        """Trailing period should be stripped from NZB name."""
        responses.add(
            responses.POST,
            "https://api.pushover.net/1/messages.json",
            json={"status": 1, "request": "test-request-id"},
            status=200,
        )

        pushover = notifiers_module.PUSHOVER()
        result = pushover.notify(
            event="Snatched",
            snatched_nzb="Spider-Man 001\\.",  # Escaped backslash-period
            prov="NZBGeek",
            sent_to="SABnzbd",
        )

        assert result is True

    @responses.activate
    def test_notify_with_device(self, notifiers_module, mock_notifier_config):
        """Notification includes device when specified."""
        mock_notifier_config.PUSHOVER_DEVICE = "my-device"

        responses.add(
            responses.POST,
            "https://api.pushover.net/1/messages.json",
            json={"status": 1, "request": "test-request-id"},
            status=200,
        )

        pushover = notifiers_module.PUSHOVER()
        pushover.device = "my-device"
        result = pushover.notify(event="Test Event", message="Test message")

        assert result is True
        request_body = responses.calls[0].request.body
        assert "my-device" in request_body

    @responses.activate
    def test_notify_with_image(
        self, notifiers_module, mock_notifier_config, sample_image_base64
    ):
        """Notification with image attachment."""
        responses.add(
            responses.POST,
            "https://api.pushover.net/1/messages.json",
            json={"status": 1, "request": "test-request-id"},
            status=200,
        )

        pushover = notifiers_module.PUSHOVER()
        result = pushover.notify(
            event="Test Event",
            message="Test message",
            imageFile=sample_image_base64,
        )

        assert result is True
        # Should be multipart with image
        assert "multipart/form-data" in responses.calls[0].request.headers.get(
            "Content-Type", ""
        )

    @responses.activate
    def test_notify_test_mode_validates_then_sends(
        self, notifiers_module, mock_notifier_config
    ):
        """Test mode validates credentials then sends actual notification."""
        # First call validates
        responses.add(
            responses.POST,
            "https://api.pushover.net/1/users/validate.json",
            json={"status": 1, "devices": ["device1", "device2"]},
            status=200,
        )
        # Second call sends message
        responses.add(
            responses.POST,
            "https://api.pushover.net/1/messages.json",
            json={"status": 1, "request": "test-request-id"},
            status=200,
        )

        pushover = notifiers_module.PUSHOVER(
            test_apikey="test_key",
            test_userkey="test_user",
            test_device=None,
        )
        result = pushover.notify(event="Test Event", message="Test message")

        assert result is True
        assert len(responses.calls) == 2

    def test_notify_returns_false_when_apikey_none(
        self, notifiers_module, mock_notifier_config
    ):
        """Notification returns False when apikey is None."""
        pushover = notifiers_module.PUSHOVER()
        pushover.apikey = None
        result = pushover.notify(event="Test Event", message="Test message")

        assert result is False


class TestPushoverNotifyErrors:
    """Test PUSHOVER error handling."""

    @responses.activate
    def test_notify_client_error_returns_false(
        self, notifiers_module, mock_notifier_config
    ):
        """4xx error returns False."""
        responses.add(
            responses.POST,
            "https://api.pushover.net/1/messages.json",
            json={"status": 0, "errors": ["invalid user key"]},
            status=400,
        )

        pushover = notifiers_module.PUSHOVER()
        result = pushover.notify(event="Test Event", message="Test message")

        assert result is False

    @responses.activate
    def test_notify_server_error_returns_false(
        self, notifiers_module, mock_notifier_config
    ):
        """5xx error returns False."""
        responses.add(
            responses.POST,
            "https://api.pushover.net/1/messages.json",
            json={"status": 0},
            status=500,
        )

        pushover = notifiers_module.PUSHOVER()
        result = pushover.notify(event="Test Event", message="Test message")

        assert result is False

    @responses.activate
    def test_notify_json_parse_error_returns_false(
        self, notifiers_module, mock_notifier_config
    ):
        """JSON parse error returns False."""
        responses.add(
            responses.POST,
            "https://api.pushover.net/1/messages.json",
            body="not valid json",
            status=200,
        )

        pushover = notifiers_module.PUSHOVER()
        result = pushover.notify(event="Test Event", message="Test message")

        assert result is False


class TestPushoverTestNotify:
    """Test PUSHOVER test_notify method."""

    @responses.activate
    def test_test_notify_sends_correct_message(
        self, notifiers_module, mock_notifier_config
    ):
        """test_notify sends expected test message."""
        responses.add(
            responses.POST,
            "https://api.pushover.net/1/messages.json",
            json={"status": 1, "request": "test-request-id"},
            status=200,
        )

        pushover = notifiers_module.PUSHOVER()
        result = pushover.test_notify()

        assert result is True
        request_body = responses.calls[0].request.body
        # URL decode to check content
        decoded_body = urllib.parse.unquote_plus(request_body)
        assert "Release the Ninjas" in decoded_body
