"""Tests for BOXCAR notifier."""

import pytest
from unittest.mock import MagicMock
import urllib.error


class TestBoxcarInit:
    """Test BOXCAR initialization."""

    def test_init_sets_url(self, notifiers_module, mock_notifier_config):
        """Init should set the Boxcar2 API URL."""
        boxcar = notifiers_module.BOXCAR()

        assert boxcar.url == "https://new.boxcar.io/api/notifications"


class TestBoxcarNotify:
    """Test BOXCAR notify method."""

    def test_notify_success(
        self, notifiers_module, mock_notifier_config, mock_urllib
    ):
        """Successful notification returns True."""
        boxcar = notifiers_module.BOXCAR()
        result = boxcar.notify(prline="Test Event", prline2="Test message")

        assert result is True
        mock_urllib["urlopen"].assert_called_once()
        mock_urllib["handle"].close.assert_called_once()

    def test_notify_snatched_format(
        self, notifiers_module, mock_notifier_config, mock_urllib
    ):
        """Snatched notification formats message correctly."""
        boxcar = notifiers_module.BOXCAR()
        result = boxcar.notify(
            snline="Snatched",
            snatched_nzb="Spider-Man 001",
            sent_to="SABnzbd",
        )

        assert result is True

    def test_notify_disabled_returns_false(
        self, notifiers_module, mock_notifier_config, mock_urllib
    ):
        """Notification when disabled returns False."""
        mock_notifier_config.BOXCAR_ENABLED = False

        boxcar = notifiers_module.BOXCAR()
        result = boxcar.notify(prline="Test Event", prline2="Test message")

        assert result is False
        mock_urllib["urlopen"].assert_not_called()

    def test_notify_force_overrides_disabled(
        self, notifiers_module, mock_notifier_config, mock_urllib
    ):
        """Force parameter should override disabled state."""
        mock_notifier_config.BOXCAR_ENABLED = False

        boxcar = notifiers_module.BOXCAR()
        result = boxcar.notify(
            prline="Test Event", prline2="Test message", force=True
        )

        assert result is True
        mock_urllib["urlopen"].assert_called_once()

    def test_notify_module_appended(
        self, notifiers_module, mock_notifier_config, mock_urllib
    ):
        """Module name should be appended for logging."""
        boxcar = notifiers_module.BOXCAR()
        # Should not raise any errors
        result = boxcar.notify(
            prline="Test Event", prline2="Test message", module="[TEST]"
        )
        assert result is True


class TestBoxcarNotifyErrors:
    """Test BOXCAR error handling."""

    def test_notify_url_error_no_code(
        self, notifiers_module, mock_notifier_config, mock_urllib
    ):
        """URL error without code is handled."""
        error = urllib.error.URLError("Connection failed")
        mock_urllib["urlopen"].side_effect = error

        boxcar = notifiers_module.BOXCAR()
        result = boxcar.notify(prline="Test Event", prline2="Test message")

        # The _sendBoxcar method returns False on error
        assert result is True  # notify still returns True, internal method logged error

    def test_notify_url_error_400(
        self, notifiers_module, mock_notifier_config, mock_urllib
    ):
        """400 error (wrong data) is handled."""
        error = urllib.error.HTTPError(
            url="https://new.boxcar.io/api/notifications",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=None,
        )
        mock_urllib["urlopen"].side_effect = error

        boxcar = notifiers_module.BOXCAR()
        result = boxcar.notify(prline="Test Event", prline2="Test message")

        assert result is True  # notify returns True, error logged internally

    def test_notify_url_error_other_code(
        self, notifiers_module, mock_notifier_config, mock_urllib
    ):
        """Other HTTP error codes are handled."""
        error = urllib.error.HTTPError(
            url="https://new.boxcar.io/api/notifications",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=None,
        )
        mock_urllib["urlopen"].side_effect = error

        boxcar = notifiers_module.BOXCAR()
        result = boxcar.notify(prline="Test Event", prline2="Test message")

        assert result is True  # notify returns True, error logged internally


class TestBoxcarTestNotify:
    """Test BOXCAR test_notify method."""

    def test_test_notify_sends_test_message(
        self, notifiers_module, mock_notifier_config, mock_urllib
    ):
        """test_notify sends the expected test message."""
        boxcar = notifiers_module.BOXCAR()
        boxcar.test_notify()

        # Verify request was made
        mock_urllib["urlopen"].assert_called_once()
