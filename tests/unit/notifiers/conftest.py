"""
Notifier-specific pytest fixtures.

Provides mocked configurations, HTTP clients, and test data for notifier tests.
"""

import base64
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Notifier Configuration Fixtures
# =============================================================================


@pytest.fixture
def mock_notifier_config(monkeypatch):
    """
    Mock comicarr.CONFIG with all notifier settings.

    Returns a mock CONFIG object that can be modified in individual tests.
    """
    import comicarr

    # Mock LOG_LEVEL to prevent TypeError in logger.py
    # The logger checks `comicarr.LOG_LEVEL > 0` which fails if LOG_LEVEL is None
    monkeypatch.setattr(comicarr, "LOG_LEVEL", 1)

    config = MagicMock()

    # PROWL settings
    config.PROWL_ENABLED = True
    config.PROWL_KEYS = "test_prowl_key"
    config.PROWL_PRIORITY = 0

    # PUSHOVER settings
    config.PUSHOVER_ENABLED = True
    config.PUSHOVER_APIKEY = "test_pushover_apikey"
    config.PUSHOVER_USERKEY = "test_pushover_userkey"
    config.PUSHOVER_DEVICE = None
    config.PUSHOVER_PRIORITY = 0

    # BOXCAR settings
    config.BOXCAR_ENABLED = True
    config.BOXCAR_TOKEN = "test_boxcar_token"

    # PUSHBULLET settings
    config.PUSHBULLET_ENABLED = True
    config.PUSHBULLET_APIKEY = "test_pushbullet_apikey"
    config.PUSHBULLET_DEVICEID = None
    config.PUSHBULLET_CHANNEL_TAG = None

    # TELEGRAM settings
    config.TELEGRAM_ENABLED = True
    config.TELEGRAM_USERID = "123456789"
    config.TELEGRAM_TOKEN = "test_telegram_token"

    # EMAIL settings
    config.EMAIL_ENABLED = True
    config.EMAIL_FROM = "comicarr@example.com"
    config.EMAIL_TO = "user@example.com"
    config.EMAIL_SERVER = "smtp.example.com"
    config.EMAIL_PORT = 587
    config.EMAIL_USER = "smtp_user"
    config.EMAIL_PASSWORD = "smtp_pass"
    config.EMAIL_ENC = 2  # TLS

    # SLACK settings
    config.SLACK_ENABLED = True
    config.SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/test/webhook"

    # MATTERMOST settings
    config.MATTERMOST_ENABLED = True
    config.MATTERMOST_WEBHOOK_URL = "https://mattermost.example.com/hooks/test"

    # DISCORD settings
    config.DISCORD_ENABLED = True
    config.DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/test/webhook"

    # GOTIFY settings
    config.GOTIFY_ENABLED = True
    config.GOTIFY_SERVER_URL = "https://gotify.example.com/"
    config.GOTIFY_TOKEN = "test_gotify_token"

    # MATRIX settings
    config.MATRIX_ENABLED = True
    config.MATRIX_HOMESERVER = "https://matrix.example.com"
    config.MATRIX_ACCESS_TOKEN = "test_matrix_token"
    config.MATRIX_ROOM_ID = "!test_room:example.com"

    monkeypatch.setattr(comicarr, "CONFIG", config)

    return config


# =============================================================================
# HTTP Mocking Fixtures
# =============================================================================


@pytest.fixture
def mock_https_connection(mocker):
    """
    Mock http.client.HTTPSConnection for PROWL notifier.

    Returns a mock that can be configured for different response scenarios.
    """
    mock_conn = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.reason = "OK"
    mock_conn.getresponse.return_value = mock_response

    mock_class = mocker.patch(
        "comicarr.notifiers.HTTPSConnection", return_value=mock_conn
    )

    return {"class": mock_class, "connection": mock_conn, "response": mock_response}


@pytest.fixture
def mock_urllib(mocker):
    """
    Mock urllib for BOXCAR notifier.

    Returns mocks for urllib.request functions.
    """
    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_handle = MagicMock()
    mock_urlopen.return_value = mock_handle

    return {"urlopen": mock_urlopen, "handle": mock_handle}


@pytest.fixture
def mock_smtp(mocker):
    """
    Mock smtplib.SMTP and SMTP_SSL for EMAIL notifier.

    Returns mocks for both SMTP classes.
    """
    mock_smtp_class = mocker.patch("comicarr.notifiers.smtplib.SMTP")
    mock_smtp_ssl_class = mocker.patch("comicarr.notifiers.smtplib.SMTP_SSL")

    mock_smtp_instance = MagicMock()
    mock_smtp_ssl_instance = MagicMock()

    mock_smtp_class.return_value = mock_smtp_instance
    mock_smtp_ssl_class.return_value = mock_smtp_ssl_instance

    return {
        "SMTP": mock_smtp_class,
        "SMTP_SSL": mock_smtp_ssl_class,
        "smtp_instance": mock_smtp_instance,
        "smtp_ssl_instance": mock_smtp_ssl_instance,
    }


# =============================================================================
# Test Data Fixtures
# =============================================================================


@pytest.fixture
def snatched_notification_data():
    """Standard data for snatched notification tests."""
    return {
        "snatched_nzb": "Spider-Man 001",
        "prov": "NZBGeek",
        "sent_to": "SABnzbd",
    }


@pytest.fixture
def download_notification_data():
    """Standard data for download completion notification tests."""
    return {
        "prline": "Spider-Man (2020)",
        "prline2": "Issue 001 downloaded successfully",
        "snline": "Comicarr Notification",
    }


@pytest.fixture
def mattermost_metadata():
    """Metadata for Mattermost notifications with rich formatting."""
    return {
        "series": "Spider-Man",
        "year": "2020",
        "issue": "001",
    }


@pytest.fixture
def gotify_metadata():
    """Metadata for Gotify notifications."""
    return {
        "series": "Spider-Man",
        "year": "2020",
        "issue": "001",
        "issueid": "12345",
    }


@pytest.fixture
def sample_image_base64():
    """
    Create a minimal valid JPEG as base64 for image attachment tests.

    This is the smallest valid JPEG that can be decoded.
    """
    try:
        from PIL import Image

        img_buffer = BytesIO()
        img = Image.new("RGB", (10, 10), color="red")
        img.save(img_buffer, format="JPEG", quality=50)
        img_data = img_buffer.getvalue()
        return base64.b64encode(img_data).decode("utf-8")
    except ImportError:
        # Fallback: minimal valid JPEG bytes
        # This is a 1x1 red pixel JPEG
        minimal_jpeg = bytes(
            [
                0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
                0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
                0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
                0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
                0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
                0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
                0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
                0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
                0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
                0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
                0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
                0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
                0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
                0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
                0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
                0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
                0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
                0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
                0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
                0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
                0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
                0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
                0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
                0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
                0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
                0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
                0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD5, 0xDB, 0x20, 0xA8, 0xA8, 0xA8, 0x00,
                0x00, 0x00, 0x00, 0x03, 0xFF, 0xD9,
            ]
        )
        return base64.b64encode(minimal_jpeg).decode("utf-8")


# =============================================================================
# Module Import Fixture
# =============================================================================


@pytest.fixture
def notifiers_module(mock_notifier_config):
    """
    Import and return the notifiers module with mocked config.

    This ensures comicarr.CONFIG is properly mocked before importing notifiers.
    """
    from comicarr import notifiers

    return notifiers
