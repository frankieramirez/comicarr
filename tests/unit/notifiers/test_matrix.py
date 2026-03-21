"""Tests for MATRIX notifier."""

import json
import re
import pytest
import responses


class TestMatrixInit:
    """Test MATRIX initialization."""

    def test_init_uses_config_values(self, notifiers_module, mock_notifier_config):
        """Init should use comicarr.CONFIG values by default."""
        matrix = notifiers_module.MATRIX()

        assert matrix.homeserver == "https://matrix.example.com"
        assert matrix.access_token == "test_matrix_token"
        assert matrix.room_id == "!test_room:example.com"
        assert matrix.test is False

    def test_init_test_params_override_config(
        self, notifiers_module, mock_notifier_config
    ):
        """Test parameters should override config values."""
        matrix = notifiers_module.MATRIX(
            test_homeserver="https://override.matrix.org",
            test_access_token="override_token",
            test_room_id="!override:example.com",
        )

        assert matrix.homeserver == "https://override.matrix.org"
        assert matrix.access_token == "override_token"
        assert matrix.room_id == "!override:example.com"
        assert matrix.test is True

    def test_init_all_test_params_required_for_test_mode(
        self, notifiers_module, mock_notifier_config
    ):
        """Partial test params should trigger test mode."""
        # If any test param is provided, test mode is True
        matrix = notifiers_module.MATRIX(test_homeserver="https://override.matrix.org")

        # With only partial params, test mode is True
        assert matrix.homeserver == "https://override.matrix.org"
        assert matrix.test is True


class TestMatrixNotify:
    """Test MATRIX notify method."""

    @responses.activate
    def test_notify_success_status_200(self, notifiers_module, mock_notifier_config):
        """Successful notification with status 200 returns True."""
        # Use regex to match any URL with the matrix endpoint pattern
        responses.add(
            responses.PUT,
            re.compile(r"https://matrix\.example\.com/_matrix/client/r0/rooms/.*/send/m\.room\.message/.*"),
            json={"event_id": "$test_event_id"},
            status=200,
        )

        matrix = notifiers_module.MATRIX()
        result = matrix.notify("Test Title", "Test message")

        assert result is True
        assert len(responses.calls) == 1

    @responses.activate
    def test_notify_success_status_201(self, notifiers_module, mock_notifier_config):
        """Successful notification with status 201 also returns True."""
        responses.add(
            responses.PUT,
            re.compile(r"https://matrix\.example\.com/_matrix/client/r0/rooms/.*/send/m\.room\.message/.*"),
            json={"event_id": "$test_event_id"},
            status=201,
        )

        matrix = notifiers_module.MATRIX()
        result = matrix.notify("Test Title", "Test message")

        assert result is True

    @responses.activate
    def test_notify_uses_put_method(self, notifiers_module, mock_notifier_config):
        """Matrix uses PUT method (not POST)."""
        responses.add(
            responses.PUT,
            re.compile(r"https://matrix\.example\.com/_matrix/client/r0/rooms/.*/send/m\.room\.message/.*"),
            json={"event_id": "$test_event_id"},
            status=200,
        )

        matrix = notifiers_module.MATRIX()
        result = matrix.notify("Test Title", "Test message")

        assert result is True
        # Verify it was a PUT request
        assert responses.calls[0].request.method == "PUT"

    @responses.activate
    def test_notify_transaction_id_from_timestamp(
        self, notifiers_module, mock_notifier_config, frozen_time
    ):
        """Transaction ID should be based on timestamp."""
        with frozen_time("2024-01-15 12:00:00"):
            expected_txn_id = str(int(1705320000.0 * 1000))  # milliseconds

            responses.add(
                responses.PUT,
                re.compile(r"https://matrix\.example\.com/_matrix/client/r0/rooms/.*/send/m\.room\.message/.*"),
                json={"event_id": "$test_event_id"},
                status=200,
            )

            matrix = notifiers_module.MATRIX()
            result = matrix.notify("Test Title", "Test message")

            # Verify transaction ID is in the URL
            assert expected_txn_id in responses.calls[0].request.url

    @responses.activate
    def test_notify_bearer_token_auth(self, notifiers_module, mock_notifier_config):
        """Request should include Bearer token in Authorization header."""
        responses.add(
            responses.PUT,
            re.compile(r"https://matrix\.example\.com/_matrix/client/r0/rooms/.*/send/m\.room\.message/.*"),
            json={"event_id": "$test_event_id"},
            status=200,
        )

        matrix = notifiers_module.MATRIX()
        result = matrix.notify("Test Title", "Test message")

        assert result is True
        auth_header = responses.calls[0].request.headers.get("Authorization", "")
        assert auth_header == "Bearer test_matrix_token"

    @responses.activate
    def test_notify_room_id_in_url(self, notifiers_module, mock_notifier_config):
        """Room ID should be in the URL path."""
        responses.add(
            responses.PUT,
            re.compile(r"https://matrix\.example\.com/_matrix/client/r0/rooms/.*/send/m\.room\.message/.*"),
            json={"event_id": "$test_event_id"},
            status=200,
        )

        matrix = notifiers_module.MATRIX()
        result = matrix.notify("Test Title", "Test message")

        assert result is True
        assert "!test_room:example.com" in responses.calls[0].request.url

    @responses.activate
    def test_notify_message_format(self, notifiers_module, mock_notifier_config):
        """Message payload should have correct format."""
        responses.add(
            responses.PUT,
            re.compile(r"https://matrix\.example\.com/_matrix/client/r0/rooms/.*/send/m\.room\.message/.*"),
            json={"event_id": "$test_event_id"},
            status=200,
        )

        matrix = notifiers_module.MATRIX()
        result = matrix.notify("Test Title", "Test message")

        assert result is True
        body = json.loads(responses.calls[0].request.body)
        assert body["msgtype"] == "m.text"
        assert body["body"] == "Test message"

    @responses.activate
    def test_notify_snatched_message_format(
        self, notifiers_module, mock_notifier_config
    ):
        """Snatched notification formats message correctly."""
        responses.add(
            responses.PUT,
            re.compile(r"https://matrix\.example\.com/_matrix/client/r0/rooms/.*/send/m\.room\.message/.*"),
            json={"event_id": "$test_event_id"},
            status=200,
        )

        matrix = notifiers_module.MATRIX()
        result = matrix.notify(
            text="Mylar Notification",
            attachment_text="Snatched",
            snatched_nzb="Spider-Man 001",
            prov="NZBGeek",
            sent_to="SABnzbd",
        )

        assert result is True
        body = json.loads(responses.calls[0].request.body)
        # Snatched message should include all info
        assert "Snatched" in body["body"]
        assert "Spider-Man 001" in body["body"]
        assert "NZBGeek" in body["body"]
        assert "SABnzbd" in body["body"]

    @responses.activate
    def test_notify_module_appended(self, notifiers_module, mock_notifier_config):
        """Module name should be appended for logging."""
        responses.add(
            responses.PUT,
            re.compile(r"https://matrix\.example\.com/_matrix/client/r0/rooms/.*/send/m\.room\.message/.*"),
            json={"event_id": "$test_event_id"},
            status=200,
        )

        matrix = notifiers_module.MATRIX()
        # Should not raise any errors
        result = matrix.notify("Test Title", "Test message", module="[TEST]")
        assert result is True


class TestMatrixNotifyErrors:
    """Test MATRIX error handling."""

    @responses.activate
    def test_notify_http_error_returns_false(
        self, notifiers_module, mock_notifier_config
    ):
        """HTTP error returns False."""
        responses.add(
            responses.PUT,
            re.compile(r"https://matrix\.example\.com/_matrix/client/r0/rooms/.*/send/m\.room\.message/.*"),
            json={"errcode": "M_FORBIDDEN", "error": "Forbidden"},
            status=403,
        )

        matrix = notifiers_module.MATRIX()
        result = matrix.notify("Test Title", "Test message")

        assert result is False

    @responses.activate
    def test_notify_unauthorized_returns_false(
        self, notifiers_module, mock_notifier_config
    ):
        """401 unauthorized returns False."""
        responses.add(
            responses.PUT,
            re.compile(r"https://matrix\.example\.com/_matrix/client/r0/rooms/.*/send/m\.room\.message/.*"),
            json={"errcode": "M_UNKNOWN_TOKEN", "error": "Unknown token"},
            status=401,
        )

        matrix = notifiers_module.MATRIX()
        result = matrix.notify("Test Title", "Test message")

        assert result is False

    @responses.activate
    def test_notify_room_not_found_returns_false(
        self, notifiers_module, mock_notifier_config
    ):
        """Room not found returns False."""
        responses.add(
            responses.PUT,
            re.compile(r"https://matrix\.example\.com/_matrix/client/r0/rooms/.*/send/m\.room\.message/.*"),
            json={"errcode": "M_NOT_FOUND", "error": "Room not found"},
            status=404,
        )

        matrix = notifiers_module.MATRIX()
        result = matrix.notify("Test Title", "Test message")

        assert result is False

    def test_notify_connection_error(
        self, notifiers_module, mock_notifier_config, mocker
    ):
        """Connection error returns False."""
        import requests

        mocker.patch(
            "requests.put",
            side_effect=requests.exceptions.ConnectionError("Network error"),
        )

        matrix = notifiers_module.MATRIX()
        result = matrix.notify("Test Title", "Test message")

        assert result is False

    def test_notify_timeout_error(self, notifiers_module, mock_notifier_config, mocker):
        """Timeout error returns False."""
        import requests

        mocker.patch(
            "requests.put",
            side_effect=requests.exceptions.Timeout("Request timed out"),
        )

        matrix = notifiers_module.MATRIX()
        result = matrix.notify("Test Title", "Test message")

        assert result is False


class TestMatrixTestNotify:
    """Test MATRIX test_notify method."""

    @responses.activate
    def test_test_notify_sends_correct_message(
        self, notifiers_module, mock_notifier_config
    ):
        """test_notify sends expected test message."""
        responses.add(
            responses.PUT,
            re.compile(r"https://matrix\.example\.com/_matrix/client/r0/rooms/.*/send/m\.room\.message/.*"),
            json={"event_id": "$test_event_id"},
            status=200,
        )

        matrix = notifiers_module.MATRIX()
        result = matrix.test_notify()

        assert result is True
        body = json.loads(responses.calls[0].request.body)
        assert "Release the Ninjas" in body["body"]
