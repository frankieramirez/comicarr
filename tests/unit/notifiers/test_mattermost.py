"""Tests for MATTERMOST notifier."""

import json
import pytest
import responses


class TestMattermostInit:
    """Test MATTERMOST initialization."""

    def test_init_uses_config_values(self, notifiers_module, mock_notifier_config):
        """Init should use mylar.CONFIG values by default."""
        mattermost = notifiers_module.MATTERMOST()

        assert mattermost.webhook_url == "https://mattermost.example.com/hooks/test"
        assert mattermost.test_hook is False

    def test_init_test_webhook_sets_test_mode(
        self, notifiers_module, mock_notifier_config
    ):
        """Test webhook URL sets test mode."""
        mattermost = notifiers_module.MATTERMOST(
            test_webhook_url="https://mattermost.example.com/hooks/override"
        )

        assert mattermost.webhook_url == "https://mattermost.example.com/hooks/override"
        assert mattermost.test_hook is True


class TestMattermostNotify:
    """Test MATTERMOST notify method."""

    @responses.activate
    def test_notify_success(self, notifiers_module, mock_notifier_config):
        """Successful notification returns True."""
        responses.add(
            responses.POST,
            "https://mattermost.example.com/hooks/test",
            body="ok",
            status=200,
        )

        mattermost = notifiers_module.MATTERMOST()
        result = mattermost.notify(
            text="Mylar",
            attachment_text="Test notification",
            metadata={"series": "Spider-Man", "year": "2020", "issue": "001"},
        )

        assert result is True
        assert len(responses.calls) == 1

    @responses.activate
    def test_notify_payload_includes_branding(
        self, notifiers_module, mock_notifier_config
    ):
        """Payload includes Mylar branding."""
        responses.add(
            responses.POST,
            "https://mattermost.example.com/hooks/test",
            body="ok",
            status=200,
        )

        mattermost = notifiers_module.MATTERMOST()
        result = mattermost.notify(
            text="Mylar",
            attachment_text="Test notification",
            metadata={"series": "Spider-Man", "year": "2020", "issue": "001"},
        )

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["username"] == "Mylar"
        assert "comicarrlogo" in request_body["icon_url"]
        assert "Powered by" in request_body["footer"]

    @responses.activate
    def test_notify_with_metadata_creates_attachments(
        self, notifiers_module, mock_notifier_config, mattermost_metadata
    ):
        """Notification with metadata creates attachment fields."""
        responses.add(
            responses.POST,
            "https://mattermost.example.com/hooks/test",
            body="ok",
            status=200,
        )

        mattermost = notifiers_module.MATTERMOST()
        result = mattermost.notify(
            text="Mylar",
            attachment_text="Test notification",
            metadata=mattermost_metadata,
        )

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        attachments = request_body["attachments"]
        assert len(attachments) == 1

        # Verify fields
        fields = attachments[0]["fields"]
        field_titles = [f["title"] for f in fields]
        assert "Series" in field_titles
        assert "Issue No." in field_titles
        assert "Year" in field_titles

    @responses.activate
    def test_notify_test_mode_no_attachments(
        self, notifiers_module, mock_notifier_config
    ):
        """Test mode notification has empty attachments."""
        responses.add(
            responses.POST,
            "https://mattermost.example.com/hooks/override",
            body="ok",
            status=200,
        )

        mattermost = notifiers_module.MATTERMOST(
            test_webhook_url="https://mattermost.example.com/hooks/override"
        )
        result = mattermost.notify(text="Mylar", attachment_text="Test notification")

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        # Test mode should have empty attachments
        assert request_body["attachments"] == []

    @responses.activate
    def test_notify_snatched_format(
        self, notifiers_module, mock_notifier_config, mattermost_metadata
    ):
        """Snatched notification formats message correctly."""
        responses.add(
            responses.POST,
            "https://mattermost.example.com/hooks/test",
            body="ok",
            status=200,
        )

        mattermost = notifiers_module.MATTERMOST()
        result = mattermost.notify(
            text="Mylar",
            attachment_text="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="NZBGeek",
            sent_to="SABnzbd",
            metadata=mattermost_metadata,
        )

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        assert "Spider-Man 001" in request_body["text"]
        assert "NZBGeek" in request_body["text"]
        assert "SABnzbd" in request_body["text"]

    @responses.activate
    def test_notify_snatched_without_sent_to(
        self, notifiers_module, mock_notifier_config, mattermost_metadata
    ):
        """Snatched notification without sent_to."""
        responses.add(
            responses.POST,
            "https://mattermost.example.com/hooks/test",
            body="ok",
            status=200,
        )

        mattermost = notifiers_module.MATTERMOST()
        result = mattermost.notify(
            text="Mylar",
            attachment_text="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="NZBGeek",
            sent_to=None,
            metadata=mattermost_metadata,
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
            "https://mattermost.example.com/hooks/test",
            body="ok",
            status=200,
        )

        mattermost = notifiers_module.MATTERMOST()
        result = mattermost.notify(
            text="Mylar",
            attachment_text="Test notification",
            module="[TEST]",
            metadata={"series": "Test", "year": "2024", "issue": "1"},
        )
        assert result is True


class TestMattermostNotifyErrors:
    """Test MATTERMOST error handling."""

    @responses.activate
    def test_notify_http_error_returns_false(
        self, notifiers_module, mock_notifier_config
    ):
        """HTTP error returns False."""
        responses.add(
            responses.POST,
            "https://mattermost.example.com/hooks/test",
            body="Invalid webhook",
            status=401,
        )

        mattermost = notifiers_module.MATTERMOST()
        result = mattermost.notify(
            text="Mylar",
            attachment_text="Test notification",
            metadata={"series": "Test", "year": "2024", "issue": "1"},
        )

        assert result is False

    @responses.activate
    def test_notify_not_found_returns_false(
        self, notifiers_module, mock_notifier_config
    ):
        """404 error returns False."""
        responses.add(
            responses.POST,
            "https://mattermost.example.com/hooks/test",
            body="Not found",
            status=404,
        )

        mattermost = notifiers_module.MATTERMOST()
        result = mattermost.notify(
            text="Mylar",
            attachment_text="Test notification",
            metadata={"series": "Test", "year": "2024", "issue": "1"},
        )

        assert result is False


class TestMattermostTestNotify:
    """Test MATTERMOST test_notify method."""

    @responses.activate
    def test_test_notify_sends_correct_message(
        self, notifiers_module, mock_notifier_config
    ):
        """test_notify sends expected test message in test mode."""
        responses.add(
            responses.POST,
            "https://mattermost.example.com/hooks/override",
            body="ok",
            status=200,
        )

        # Use test mode webhook to avoid metadata requirement
        mattermost = notifiers_module.MATTERMOST(
            test_webhook_url="https://mattermost.example.com/hooks/override"
        )
        result = mattermost.test_notify()

        assert result is True
        request_body = json.loads(responses.calls[0].request.body)
        assert "Release the Ninjas" in request_body["text"]
