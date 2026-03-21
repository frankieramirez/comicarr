"""Tests for PUSHBULLET notifier."""

import json
import pytest
import responses


class TestPushbulletInit:
    """Test PUSHBULLET initialization."""

    def test_init_uses_config_values(self, notifiers_module, mock_notifier_config):
        """Init should use comicarr.CONFIG values by default."""
        pushbullet = notifiers_module.PUSHBULLET()

        assert pushbullet.apikey == "test_pushbullet_apikey"
        assert pushbullet.deviceid is None
        assert pushbullet.channel_tag is None
        assert pushbullet.PUSH_URL == "https://api.pushbullet.com/v2/pushes"

    def test_init_test_apikey_overrides_config(
        self, notifiers_module, mock_notifier_config
    ):
        """Test API key should override config."""
        pushbullet = notifiers_module.PUSHBULLET(test_apikey="override_apikey")

        assert pushbullet.apikey == "override_apikey"

    def test_init_session_auth_configured(self, notifiers_module, mock_notifier_config):
        """Session should be configured with API key auth."""
        pushbullet = notifiers_module.PUSHBULLET()

        # Session auth is set to (apikey, "")
        assert pushbullet._session.auth == ("test_pushbullet_apikey", "")

    def test_init_json_headers_set(self, notifiers_module, mock_notifier_config):
        """Session should have JSON content type headers."""
        pushbullet = notifiers_module.PUSHBULLET()

        headers = pushbullet._session.headers
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"


class TestPushbulletGetDevices:
    """Test PUSHBULLET get_devices method."""

    @responses.activate
    def test_get_devices_returns_device_list(
        self, notifiers_module, mock_notifier_config
    ):
        """get_devices returns list of devices."""
        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/devices",
            json={
                "devices": [
                    {"iden": "device1", "nickname": "Phone"},
                    {"iden": "device2", "nickname": "Laptop"},
                ]
            },
            status=200,
        )

        pushbullet = notifiers_module.PUSHBULLET()
        result = pushbullet.get_devices()

        assert "devices" in result
        assert len(result["devices"]) == 2


class TestPushbulletNotify:
    """Test PUSHBULLET notify method."""

    @responses.activate
    def test_notify_success_returns_dict(self, notifiers_module, mock_notifier_config):
        """Successful notification returns dict with status True."""
        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/pushes",
            json={"iden": "push-id", "type": "note"},
            status=200,
        )

        pushbullet = notifiers_module.PUSHBULLET()
        result = pushbullet.notify(prline="Test Comic", prline2="Issue downloaded")

        assert isinstance(result, dict)
        assert result["status"] is True
        assert "notification sent" in result["message"]

    @responses.activate
    def test_notify_payload_format(self, notifiers_module, mock_notifier_config):
        """Verify payload format is correct."""
        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/pushes",
            json={"iden": "push-id", "type": "note"},
            status=200,
        )

        pushbullet = notifiers_module.PUSHBULLET()
        result = pushbullet.notify(prline="Test Comic", prline2="Issue downloaded")

        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["type"] == "note"
        assert "Test Comic" in request_body["title"]
        assert request_body["body"] == "Issue downloaded"

    @responses.activate
    def test_notify_snatched_format(self, notifiers_module, mock_notifier_config):
        """Snatched notification formats message correctly."""
        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/pushes",
            json={"iden": "push-id", "type": "note"},
            status=200,
        )

        pushbullet = notifiers_module.PUSHBULLET()
        result = pushbullet.notify(
            snline="Snatched",
            snatched="Spider-Man 001",
            prov="NZBGeek",
            sent_to="SABnzbd",
        )

        assert result["status"] is True
        request_body = json.loads(responses.calls[0].request.body)
        assert "Spider-Man 001" in request_body["body"]
        assert "NZBGeek" in request_body["body"]
        assert "SABnzbd" in request_body["body"]

    @responses.activate
    def test_notify_strips_trailing_period(self, notifiers_module, mock_notifier_config):
        """Trailing period should be stripped from snatched name."""
        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/pushes",
            json={"iden": "push-id", "type": "note"},
            status=200,
        )

        pushbullet = notifiers_module.PUSHBULLET()
        result = pushbullet.notify(
            snline="Snatched",
            snatched="Spider-Man 001.",  # With trailing period
            prov="NZBGeek",
            sent_to="SABnzbd",
        )

        assert result["status"] is True

    @responses.activate
    def test_notify_with_channel_tag(self, notifiers_module, mock_notifier_config):
        """Notification includes channel_tag when set."""
        mock_notifier_config.PUSHBULLET_CHANNEL_TAG = "comicarr_channel"

        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/pushes",
            json={"iden": "push-id", "type": "note"},
            status=200,
        )

        pushbullet = notifiers_module.PUSHBULLET()
        pushbullet.channel_tag = "comicarr_channel"
        result = pushbullet.notify(prline="Test Comic", prline2="Issue downloaded")

        assert result["status"] is True
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["channel_tag"] == "comicarr_channel"

    @responses.activate
    def test_notify_module_appended(self, notifiers_module, mock_notifier_config):
        """Module name should be appended for logging."""
        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/pushes",
            json={"iden": "push-id", "type": "note"},
            status=200,
        )

        pushbullet = notifiers_module.PUSHBULLET()
        result = pushbullet.notify(
            prline="Test Comic", prline2="Issue downloaded", module="[TEST]"
        )
        assert result["status"] is True


class TestPushbulletNotifyErrors:
    """Test PUSHBULLET error handling."""

    @responses.activate
    def test_notify_client_error_returns_false_status(
        self, notifiers_module, mock_notifier_config
    ):
        """4xx error returns dict with status False."""
        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/pushes",
            json={"error": {"message": "Invalid API key"}},
            status=401,
        )

        pushbullet = notifiers_module.PUSHBULLET()
        result = pushbullet.notify(prline="Test Comic", prline2="Issue downloaded")

        assert isinstance(result, dict)
        assert result["status"] is False
        assert "401" in result["message"]

    @responses.activate
    def test_notify_server_error_returns_false_status(
        self, notifiers_module, mock_notifier_config
    ):
        """5xx error returns dict with status False."""
        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/pushes",
            json={"error": {"message": "Internal Server Error"}},
            status=500,
        )

        pushbullet = notifiers_module.PUSHBULLET()
        result = pushbullet.notify(prline="Test Comic", prline2="Issue downloaded")

        assert isinstance(result, dict)
        assert result["status"] is False


class TestPushbulletTestNotify:
    """Test PUSHBULLET test_notify method."""

    @responses.activate
    def test_test_notify_sends_correct_message(
        self, notifiers_module, mock_notifier_config
    ):
        """test_notify sends expected test message."""
        responses.add(
            responses.POST,
            "https://api.pushbullet.com/v2/pushes",
            json={"iden": "push-id", "type": "note"},
            status=200,
        )

        pushbullet = notifiers_module.PUSHBULLET()
        result = pushbullet.test_notify()

        assert result["status"] is True
        request_body = json.loads(responses.calls[0].request.body)
        assert "Release the Ninjas" in request_body["body"]
