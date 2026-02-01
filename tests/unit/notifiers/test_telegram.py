"""Tests for TELEGRAM notifier."""

import pytest
import responses


class TestTelegramInit:
    """Test TELEGRAM initialization."""

    def test_init_uses_config_values(self, notifiers_module, mock_notifier_config):
        """Init should use mylar.CONFIG values by default."""
        telegram = notifiers_module.TELEGRAM()

        assert telegram.userid == "123456789"
        assert telegram.token == "test_telegram_token"

    def test_init_test_params_override_config(
        self, notifiers_module, mock_notifier_config
    ):
        """Test parameters should override config values."""
        telegram = notifiers_module.TELEGRAM(
            test_userid="override_user", test_token="override_token"
        )

        assert telegram.userid == "override_user"
        assert telegram.token == "override_token"

    def test_init_partial_test_params(self, notifiers_module, mock_notifier_config):
        """Test with partial test params - only userid overridden."""
        telegram = notifiers_module.TELEGRAM(test_userid="override_user")

        assert telegram.userid == "override_user"
        assert telegram.token == "test_telegram_token"


class TestTelegramNotify:
    """Test TELEGRAM notify method."""

    @responses.activate
    def test_notify_success(self, notifiers_module, mock_notifier_config):
        """Successful notification returns True."""
        responses.add(
            responses.POST,
            "https://api.telegram.org/bottest_telegram_token/sendMessage",
            json={"ok": True, "result": {}},
            status=200,
        )

        telegram = notifiers_module.TELEGRAM()
        result = telegram.notify("Test message")

        assert result is True
        assert len(responses.calls) == 1

        # Verify request payload
        import json

        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["chat_id"] == "123456789"
        assert request_body["text"] == "Test message"

    @responses.activate
    def test_notify_with_image(
        self, notifiers_module, mock_notifier_config, sample_image_base64
    ):
        """Notification with image uses sendPhoto endpoint."""
        responses.add(
            responses.POST,
            "https://api.telegram.org/bottest_telegram_token/sendPhoto",
            json={"ok": True, "result": {}},
            status=200,
        )

        telegram = notifiers_module.TELEGRAM()
        result = telegram.notify("Test message with image", imageFile=sample_image_base64)

        assert result is True
        assert len(responses.calls) == 1
        # Verify it's a multipart form request
        assert "multipart/form-data" in responses.calls[0].request.headers.get(
            "Content-Type", ""
        )

    @responses.activate
    def test_notify_image_decode_error_falls_back_to_text(
        self, notifiers_module, mock_notifier_config
    ):
        """Invalid image falls back to text message."""
        # First call for sendPhoto may fail, then falls back to sendMessage
        responses.add(
            responses.POST,
            "https://api.telegram.org/bottest_telegram_token/sendMessage",
            json={"ok": True, "result": {}},
            status=200,
        )

        telegram = notifiers_module.TELEGRAM()
        # Invalid base64 that will cause decode error
        result = telegram.notify("Test message", imageFile="not_valid_base64!!!")

        assert result is True


class TestTelegramNotifyErrors:
    """Test TELEGRAM error handling."""

    @responses.activate
    def test_notify_http_error(self, notifiers_module, mock_notifier_config):
        """HTTP error returns False."""
        responses.add(
            responses.POST,
            "https://api.telegram.org/bottest_telegram_token/sendMessage",
            json={"ok": False, "error_code": 401, "description": "Unauthorized"},
            status=401,
        )

        telegram = notifiers_module.TELEGRAM()
        result = telegram.notify("Test message")

        assert result is False

    @responses.activate
    def test_notify_server_error(self, notifiers_module, mock_notifier_config):
        """Server error returns False."""
        responses.add(
            responses.POST,
            "https://api.telegram.org/bottest_telegram_token/sendMessage",
            json={"ok": False, "description": "Internal Server Error"},
            status=500,
        )

        telegram = notifiers_module.TELEGRAM()
        result = telegram.notify("Test message")

        assert result is False

    def test_notify_connection_error(self, notifiers_module, mock_notifier_config, mocker):
        """Connection error returns False."""
        import requests

        mocker.patch(
            "requests.post", side_effect=requests.exceptions.ConnectionError("Network error")
        )

        telegram = notifiers_module.TELEGRAM()
        result = telegram.notify("Test message")

        assert result is False

    @responses.activate
    def test_notify_image_failure_falls_back_to_text(
        self, notifiers_module, mock_notifier_config, sample_image_base64
    ):
        """Image send failure falls back to text message."""
        # First sendPhoto fails
        responses.add(
            responses.POST,
            "https://api.telegram.org/bottest_telegram_token/sendPhoto",
            json={"ok": False, "description": "Bad Request"},
            status=400,
        )
        # Fallback to sendMessage succeeds
        responses.add(
            responses.POST,
            "https://api.telegram.org/bottest_telegram_token/sendMessage",
            json={"ok": True, "result": {}},
            status=200,
        )

        telegram = notifiers_module.TELEGRAM()
        result = telegram.notify("Test message", imageFile=sample_image_base64)

        # Should have made two calls - photo failed, then message succeeded
        assert len(responses.calls) == 2
        assert result is True


class TestTelegramTestNotify:
    """Test TELEGRAM test_notify method."""

    @responses.activate
    def test_test_notify_sends_correct_message(
        self, notifiers_module, mock_notifier_config
    ):
        """test_notify sends the expected test message."""
        responses.add(
            responses.POST,
            "https://api.telegram.org/bottest_telegram_token/sendMessage",
            json={"ok": True, "result": {}},
            status=200,
        )

        telegram = notifiers_module.TELEGRAM()
        result = telegram.test_notify()

        assert result is True
        import json

        request_body = json.loads(responses.calls[0].request.body)
        assert "Release the Ninjas" in request_body["text"]
