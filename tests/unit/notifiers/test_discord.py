"""Tests for DISCORD notifier."""

import json
import re
import pytest
import responses


class TestDiscordInit:
    """Test DISCORD initialization."""

    def test_init_uses_config_values(self, notifiers_module, mock_notifier_config):
        """Init should use comicarr.CONFIG values by default."""
        discord = notifiers_module.DISCORD()

        assert discord.webhook_url == "https://discord.com/api/webhooks/test/webhook"
        assert discord.test is False

    def test_init_test_webhook_sets_test_mode(
        self, notifiers_module, mock_notifier_config
    ):
        """Test webhook URL sets test mode to True."""
        discord = notifiers_module.DISCORD(
            test_webhook_url="https://discord.com/api/webhooks/override"
        )

        assert discord.webhook_url == "https://discord.com/api/webhooks/override"
        assert discord.test is True


class TestDiscordNotify:
    """Test DISCORD notify method."""

    @responses.activate
    def test_notify_test_mode_simple_content(
        self, notifiers_module, mock_notifier_config
    ):
        """Test mode sends simple content without embeds."""
        responses.add(
            responses.POST,
            "https://discord.com/api/webhooks/override",
            status=204,
        )

        discord = notifiers_module.DISCORD(
            test_webhook_url="https://discord.com/api/webhooks/override"
        )
        result = discord.notify("Test", "Test message")

        # Note: Current implementation has a bug in status check (all([x==204, x==200]))
        # which is always False unless status is both 204 AND 200 simultaneously
        # This test documents the actual behavior
        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["content"] == "Test message"
        assert request_body["username"] == "Comicarr"

    @responses.activate
    def test_notify_snatched_with_embeds(self, notifiers_module, mock_notifier_config):
        """Snatched notification includes embeds with fields."""
        responses.add(
            responses.POST,
            "https://discord.com/api/webhooks/test/webhook",
            status=204,
        )

        discord = notifiers_module.DISCORD()
        result = discord.notify(
            text="Mylar Notification",
            attachment_text="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="NZBGeek",
            sent_to="sent to SABnzbd",
        )

        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)

        # Verify embeds structure
        assert "embeds" in request_body
        embeds = request_body["embeds"]
        assert len(embeds) == 1

        # Verify fields
        fields = embeds[0]["fields"]
        field_names = [f["name"] for f in fields]
        assert "Series" in field_names
        assert "Issue" in field_names
        assert "Indexer" in field_names
        assert "Sent to" in field_names

    @responses.activate
    def test_notify_snatched_ddl_detection(self, notifiers_module, mock_notifier_config):
        """DDL in sent_to is detected correctly."""
        responses.add(
            responses.POST,
            "https://discord.com/api/webhooks/test/webhook",
            status=204,
        )

        discord = notifiers_module.DISCORD()
        result = discord.notify(
            text="Mylar Notification",
            attachment_text="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="MediaFire",
            sent_to="sent to DDL folder",
        )

        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        embeds = request_body["embeds"]
        sent_to_field = next(f for f in embeds[0]["fields"] if f["name"] == "Sent to")
        assert sent_to_field["value"] == "DDL"

    @responses.activate
    def test_notify_snatched_torrent_client_detection(
        self, notifiers_module, mock_notifier_config
    ):
        """Torrent client in sent_to is detected correctly."""
        responses.add(
            responses.POST,
            "https://discord.com/api/webhooks/test/webhook",
            status=204,
        )

        discord = notifiers_module.DISCORD()
        result = discord.notify(
            text="Mylar Notification",
            attachment_text="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="TorrentLeech",
            sent_to="sent to qBittorrent client",
        )

        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        embeds = request_body["embeds"]
        sent_to_field = next(f for f in embeds[0]["fields"] if f["name"] == "Sent to")
        assert sent_to_field["value"] == "qBittorrent"

    @responses.activate
    def test_notify_snatched_nzb_client_detection(
        self, notifiers_module, mock_notifier_config
    ):
        """NZB client (no 'client' keyword) extracts last word."""
        responses.add(
            responses.POST,
            "https://discord.com/api/webhooks/test/webhook",
            status=204,
        )

        discord = notifiers_module.DISCORD()
        result = discord.notify(
            text="Mylar Notification",
            attachment_text="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="NZBGeek",
            sent_to="sent to SABnzbd",
        )

        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        embeds = request_body["embeds"]
        sent_to_field = next(f for f in embeds[0]["fields"] if f["name"] == "Sent to")
        assert sent_to_field["value"] == "SABnzbd"

    @responses.activate
    def test_notify_error_message_format(self, notifiers_module, mock_notifier_config):
        """Error notification has correct embed format."""
        responses.add(
            responses.POST,
            "https://discord.com/api/webhooks/test/webhook",
            status=204,
        )

        discord = notifiers_module.DISCORD()
        result = discord.notify(
            text="problematic_file.cbz",
            attachment_text="Error processing file",
        )

        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        embeds = request_body["embeds"]
        assert embeds[0]["author"]["name"] == "Mylar Error"
        # Error color should be different from success
        assert embeds[0]["color"] == 16705372

    @responses.activate
    def test_notify_download_format(self, notifiers_module, mock_notifier_config):
        """Download/post-process notification has correct format."""
        responses.add(
            responses.POST,
            "https://discord.com/api/webhooks/test/webhook",
            status=204,
        )

        discord = notifiers_module.DISCORD()
        # The format expects 41 characters prefix before series info
        # "Mylar has downloaded and post-processed: " is exactly 41 chars
        result = discord.notify(
            text="Mylar Notification",
            attachment_text="Mylar has downloaded and post-processed: Spider-Man 001",
        )

        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        embeds = request_body["embeds"]
        assert embeds[0]["author"]["name"] == "Downloaded by Mylar"
        assert embeds[0]["color"] == 32768  # Green

    @responses.activate
    def test_notify_with_image_multipart(
        self, notifiers_module, mock_notifier_config, sample_image_base64
    ):
        """Image notification uses multipart form data."""
        responses.add(
            responses.POST,
            "https://discord.com/api/webhooks/test/webhook",
            status=204,
        )

        discord = notifiers_module.DISCORD()
        result = discord.notify(
            text="Mylar Notification",
            attachment_text="Mylar has downloaded and post-processed: Spider-Man 001",
            imageFile=sample_image_base64,
        )

        assert len(responses.calls) == 1
        # Multipart form data
        assert "multipart/form-data" in responses.calls[0].request.headers.get(
            "Content-Type", ""
        )


class TestDiscordNotifyErrors:
    """Test DISCORD error handling."""

    @responses.activate
    def test_notify_http_error(self, notifiers_module, mock_notifier_config):
        """HTTP error handling - test with snatched format to avoid IndexError."""
        responses.add(
            responses.POST,
            "https://discord.com/api/webhooks/test/webhook",
            json={"message": "Invalid webhook"},
            status=401,
        )

        discord = notifiers_module.DISCORD()
        result = discord.notify(
            text="Mylar Notification",
            attachment_text="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="NZBGeek",
            sent_to="SABnzbd",
        )

        # The method returns False on non-200/204 status
        assert result is False

    @responses.activate
    def test_notify_rate_limit(self, notifiers_module, mock_notifier_config):
        """Rate limit returns False."""
        responses.add(
            responses.POST,
            "https://discord.com/api/webhooks/test/webhook",
            json={"message": "You are being rate limited"},
            status=429,
        )

        discord = notifiers_module.DISCORD()
        result = discord.notify(
            text="Mylar Notification",
            attachment_text="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="NZBGeek",
            sent_to="SABnzbd",
        )

        assert result is False

    def test_notify_connection_error_raises_unbound_local(
        self, notifiers_module, mock_notifier_config, mocker
    ):
        """Connection error causes UnboundLocalError due to missing exception handling.

        Note: This test documents a bug in the current implementation.
        The notify method should catch the exception and return False,
        but instead it tries to access `response` which was never assigned.
        """
        import requests

        mocker.patch(
            "requests.post",
            side_effect=requests.exceptions.ConnectionError("Network error"),
        )

        discord = notifiers_module.DISCORD()
        # Use snatched format to avoid IndexError in message parsing
        # The bug is that after the exception in requests.post,
        # the code continues to check response.status_code which is unbound
        with pytest.raises(UnboundLocalError):
            discord.notify(
                text="Mylar Notification",
                attachment_text="Snatched",
                snatched_nzb="Spider-Man 001",
                prov="NZBGeek",
                sent_to="SABnzbd",
            )


class TestDiscordTestNotify:
    """Test DISCORD test_notify method."""

    @responses.activate
    def test_test_notify_uses_test_mode(
        self, notifiers_module, mock_notifier_config
    ):
        """test_notify uses test webhook and test mode when provided."""
        responses.add(
            responses.POST,
            "https://discord.com/api/webhooks/override",
            status=204,
        )

        discord = notifiers_module.DISCORD(
            test_webhook_url="https://discord.com/api/webhooks/override"
        )
        result = discord.test_notify()

        # Test mode sends simple content
        assert len(responses.calls) == 1
        request_body = json.loads(responses.calls[0].request.body)
        assert "Release the Ninjas" in request_body["content"]
