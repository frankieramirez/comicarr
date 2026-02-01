"""Tests for GOTIFY notifier."""

import json
import pytest
import responses


class TestGotifyInit:
    """Test GOTIFY initialization."""

    def test_init_uses_config_values(self, notifiers_module, mock_notifier_config):
        """Init should use mylar.CONFIG values by default."""
        gotify = notifiers_module.GOTIFY()

        expected_url = "https://gotify.example.com/message?token=test_gotify_token"
        assert gotify.webhook_url == expected_url

    def test_init_test_webhook_overrides_config(
        self, notifiers_module, mock_notifier_config
    ):
        """Test webhook URL should override config."""
        gotify = notifiers_module.GOTIFY(
            test_webhook_url="https://gotify.override.com/message?token=override"
        )

        assert gotify.webhook_url == "https://gotify.override.com/message?token=override"


class TestGotifyNotify:
    """Test GOTIFY notify method."""

    @responses.activate
    def test_notify_success(self, notifiers_module, mock_notifier_config):
        """Successful notification returns True."""
        responses.add(
            responses.POST,
            "https://gotify.example.com/message?token=test_gotify_token",
            json={"id": 1},
            status=200,
        )

        gotify = notifiers_module.GOTIFY()
        result = gotify.notify(text="Mylar", attachment_text="Test notification")

        assert result is True
        assert len(responses.calls) == 1

    @responses.activate
    def test_notify_payload_format(self, notifiers_module, mock_notifier_config):
        """Verify payload format is correct."""
        responses.add(
            responses.POST,
            "https://gotify.example.com/message?token=test_gotify_token",
            json={"id": 1},
            status=200,
        )

        gotify = notifiers_module.GOTIFY()
        result = gotify.notify(text="Test Title", attachment_text="Test message")

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["title"] == "Test Title"
        assert request_body["message"] == "Test message"

    @responses.activate
    def test_notify_snatched_format(self, notifiers_module, mock_notifier_config):
        """Snatched notification formats message correctly."""
        responses.add(
            responses.POST,
            "https://gotify.example.com/message?token=test_gotify_token",
            json={"id": 1},
            status=200,
        )

        gotify = notifiers_module.GOTIFY()
        result = gotify.notify(
            text="Mylar",
            attachment_text="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="NZBGeek",
            sent_to="SABnzbd",
        )

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        assert "Spider-Man 001" in request_body["message"]
        assert "NZBGeek" in request_body["message"]
        assert "SABnzbd" in request_body["message"]

    @responses.activate
    def test_notify_snatched_without_sent_to(
        self, notifiers_module, mock_notifier_config
    ):
        """Snatched notification without sent_to."""
        responses.add(
            responses.POST,
            "https://gotify.example.com/message?token=test_gotify_token",
            json={"id": 1},
            status=200,
        )

        gotify = notifiers_module.GOTIFY()
        result = gotify.notify(
            text="Mylar",
            attachment_text="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="NZBGeek",
            sent_to=None,
        )

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        assert "Spider-Man 001" in request_body["message"]
        assert "NZBGeek" in request_body["message"]

    @responses.activate
    def test_notify_with_image_uses_markdown(
        self, notifiers_module, mock_notifier_config, sample_image_base64, gotify_metadata
    ):
        """Notification with image uses markdown format."""
        responses.add(
            responses.POST,
            "https://gotify.example.com/message?token=test_gotify_token",
            json={"id": 1},
            status=200,
        )

        gotify = notifiers_module.GOTIFY()
        result = gotify.notify(
            text="Mylar",
            attachment_text="Test notification",
            imageFile=sample_image_base64,
            metadata=gotify_metadata,
        )

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        # Should have markdown image
        assert "data:image/jpeg;base64" in request_body["message"]
        # Should have extras for markdown display
        assert "extras" in request_body
        assert request_body["extras"]["client::display"]["contentType"] == "text/markdown"

    @responses.activate
    def test_notify_with_image_includes_comicvine_link(
        self, notifiers_module, mock_notifier_config, sample_image_base64, gotify_metadata
    ):
        """Image notification includes ComicVine issue link."""
        responses.add(
            responses.POST,
            "https://gotify.example.com/message?token=test_gotify_token",
            json={"id": 1},
            status=200,
        )

        gotify = notifiers_module.GOTIFY()
        result = gotify.notify(
            text="Mylar",
            attachment_text="Test notification",
            imageFile=sample_image_base64,
            metadata=gotify_metadata,
        )

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        # Should have click URL to ComicVine
        click_url = request_body["extras"]["client::notification"]["click"]["url"]
        assert "comicvine.gamespot.com" in click_url
        assert gotify_metadata["issueid"] in click_url

    @responses.activate
    def test_notify_module_appended(self, notifiers_module, mock_notifier_config):
        """Module name should be appended for logging."""
        responses.add(
            responses.POST,
            "https://gotify.example.com/message?token=test_gotify_token",
            json={"id": 1},
            status=200,
        )

        gotify = notifiers_module.GOTIFY()
        result = gotify.notify(
            text="Mylar", attachment_text="Test notification", module="[TEST]"
        )
        assert result is True


class TestGotifyNotifyErrors:
    """Test GOTIFY error handling."""

    @responses.activate
    def test_notify_http_error_returns_false(
        self, notifiers_module, mock_notifier_config
    ):
        """HTTP error returns False."""
        responses.add(
            responses.POST,
            "https://gotify.example.com/message?token=test_gotify_token",
            json={"error": "Unauthorized"},
            status=401,
        )

        gotify = notifiers_module.GOTIFY()
        result = gotify.notify(text="Mylar", attachment_text="Test notification")

        assert result is False

    @responses.activate
    def test_notify_server_error_returns_false(
        self, notifiers_module, mock_notifier_config
    ):
        """Server error returns False."""
        responses.add(
            responses.POST,
            "https://gotify.example.com/message?token=test_gotify_token",
            json={"error": "Internal error"},
            status=500,
        )

        gotify = notifiers_module.GOTIFY()
        result = gotify.notify(text="Mylar", attachment_text="Test notification")

        assert result is False


class TestGotifyTestNotify:
    """Test GOTIFY test_notify method."""

    @responses.activate
    def test_test_notify_sends_correct_message(
        self, notifiers_module, mock_notifier_config
    ):
        """test_notify sends expected test message."""
        responses.add(
            responses.POST,
            "https://gotify.example.com/message?token=test_gotify_token",
            json={"id": 1},
            status=200,
        )

        gotify = notifiers_module.GOTIFY()
        result = gotify.test_notify()

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        assert "Release the Ninjas" in request_body["message"]
