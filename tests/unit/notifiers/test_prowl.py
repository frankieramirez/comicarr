"""Tests for PROWL notifier."""

import pytest
from unittest.mock import MagicMock


class TestProwlInit:
    """Test PROWL initialization."""

    def test_init_uses_config_values(self, notifiers_module, mock_notifier_config):
        """Init should use mylar.CONFIG values by default."""
        prowl = notifiers_module.PROWL()

        assert prowl.enabled is True
        assert prowl.keys == "test_prowl_key"
        assert prowl.priority == 0


class TestProwlNotify:
    """Test PROWL notify method."""

    def test_notify_success(
        self, notifiers_module, mock_notifier_config, mock_https_connection
    ):
        """Successful notification returns True."""
        mock_https_connection["response"].status = 200

        prowl = notifiers_module.PROWL()
        result = prowl.notify("Test message", "Test Event")

        assert result is True
        mock_https_connection["connection"].request.assert_called_once()

    def test_notify_request_format(
        self, notifiers_module, mock_notifier_config, mock_https_connection
    ):
        """Verify request format is correct."""
        mock_https_connection["response"].status = 200

        prowl = notifiers_module.PROWL()
        result = prowl.notify("Test message", "Test Event")

        # Verify the request was made with correct parameters
        call_args = mock_https_connection["connection"].request.call_args
        method, path = call_args[0][:2]

        assert method == "POST"
        assert path == "/publicapi/add"

    def test_notify_includes_apikey_and_message(
        self, notifiers_module, mock_notifier_config, mock_https_connection
    ):
        """Request body should include API key and message."""
        mock_https_connection["response"].status = 200

        prowl = notifiers_module.PROWL()
        result = prowl.notify("Test message", "Test Event")

        # Get the request body
        call_args = mock_https_connection["connection"].request.call_args
        body = call_args[1]["body"]

        assert "test_prowl_key" in body
        assert "Test+message" in body or "Test%20message" in body
        assert "Mylar" in body  # Application name

    def test_notify_disabled_returns_none(
        self, notifiers_module, mock_notifier_config, mock_https_connection
    ):
        """Notification when disabled returns None."""
        mock_notifier_config.PROWL_ENABLED = False

        prowl = notifiers_module.PROWL()
        result = prowl.notify("Test message", "Test Event")

        assert result is None
        mock_https_connection["connection"].request.assert_not_called()

    def test_notify_module_appended(
        self, notifiers_module, mock_notifier_config, mock_https_connection
    ):
        """Module name should be appended for logging."""
        mock_https_connection["response"].status = 200

        prowl = notifiers_module.PROWL()
        # Should not raise any errors
        result = prowl.notify("Test message", "Test Event", module="[TEST]")
        assert result is True


class TestProwlNotifyErrors:
    """Test PROWL error handling."""

    def test_notify_auth_error_returns_false(
        self, notifiers_module, mock_notifier_config, mock_https_connection
    ):
        """401 auth error returns False."""
        mock_https_connection["response"].status = 401
        mock_https_connection["response"].reason = "Unauthorized"

        prowl = notifiers_module.PROWL()
        result = prowl.notify("Test message", "Test Event")

        assert result is False

    def test_notify_other_error_returns_false(
        self, notifiers_module, mock_notifier_config, mock_https_connection
    ):
        """Other HTTP errors return False."""
        mock_https_connection["response"].status = 500
        mock_https_connection["response"].reason = "Internal Server Error"

        prowl = notifiers_module.PROWL()
        result = prowl.notify("Test message", "Test Event")

        assert result is False


class TestProwlTestNotify:
    """Test PROWL test_notify method."""

    def test_test_notify_sends_test_message(
        self, notifiers_module, mock_notifier_config, mock_https_connection
    ):
        """test_notify sends the expected test message."""
        mock_https_connection["response"].status = 200

        prowl = notifiers_module.PROWL()
        prowl.test_notify()

        # Verify request was made
        call_args = mock_https_connection["connection"].request.call_args
        body = call_args[1]["body"]

        assert "ZOMG" in body or "Lazors" in body or "Pewpewpew" in body
