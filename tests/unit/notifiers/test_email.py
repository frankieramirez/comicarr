"""Tests for EMAIL notifier."""

import pytest
from unittest.mock import MagicMock, patch, call


class TestEmailInit:
    """Test EMAIL initialization."""

    def test_init_uses_config_values(self, notifiers_module, mock_notifier_config):
        """Init should use comicarr.CONFIG values by default."""
        email = notifiers_module.EMAIL()

        assert email.emailfrom == "comicarr@example.com"
        assert email.emailto == "user@example.com"
        assert email.emailsvr == "smtp.example.com"
        assert email.emailport == 587
        assert email.emailuser == "smtp_user"
        assert email.emailpass == "smtp_pass"
        assert email.emailenc == 2  # TLS

    def test_init_test_params_override_config(
        self, notifiers_module, mock_notifier_config
    ):
        """Test parameters should override config values."""
        email = notifiers_module.EMAIL(
            test_emailfrom="override@example.com",
            test_emailto="dest@example.com",
            test_emailsvr="smtp.override.com",
            test_emailport=465,
            test_emailuser="override_user",
            test_emailpass="override_pass",
            test_emailenc=1,
        )

        assert email.emailfrom == "override@example.com"
        assert email.emailto == "dest@example.com"
        assert email.emailsvr == "smtp.override.com"
        assert email.emailport == 465
        assert email.emailuser == "override_user"
        assert email.emailpass == "override_pass"
        assert email.emailenc == 1

    def test_init_partial_test_params(self, notifiers_module, mock_notifier_config):
        """Test with partial test params."""
        email = notifiers_module.EMAIL(test_emailfrom="override@example.com")

        assert email.emailfrom == "override@example.com"
        assert email.emailto == "user@example.com"  # From config

    def test_init_encryption_converted_to_int(
        self, notifiers_module, mock_notifier_config
    ):
        """Encryption value should be converted to int."""
        email = notifiers_module.EMAIL(test_emailenc="1")
        assert email.emailenc == 1
        assert isinstance(email.emailenc, int)


class TestEmailNotify:
    """Test EMAIL notify method."""

    def test_notify_success_with_tls(self, notifiers_module, mock_notifier_config, mock_smtp):
        """Successful notification with TLS returns True."""
        mock_notifier_config.EMAIL_ENC = 2  # TLS

        email = notifiers_module.EMAIL()
        result = email.notify("Test message body", "Test Subject")

        assert result is True
        mock_smtp["SMTP"].assert_called_once_with("smtp.example.com", "587")
        mock_smtp["smtp_instance"].starttls.assert_called_once()
        mock_smtp["smtp_instance"].login.assert_called_once_with("smtp_user", "smtp_pass")
        mock_smtp["smtp_instance"].sendmail.assert_called_once()
        mock_smtp["smtp_instance"].quit.assert_called_once()

    def test_notify_success_with_ssl(self, notifiers_module, mock_notifier_config, mock_smtp):
        """Successful notification with SSL uses SMTP_SSL."""
        mock_notifier_config.EMAIL_ENC = 1  # SSL

        email = notifiers_module.EMAIL(test_emailenc=1)
        result = email.notify("Test message body", "Test Subject")

        assert result is True
        mock_smtp["SMTP_SSL"].assert_called_once_with("smtp.example.com", "587")
        mock_smtp["smtp_ssl_instance"].starttls.assert_not_called()
        mock_smtp["smtp_ssl_instance"].login.assert_called_once()
        mock_smtp["smtp_ssl_instance"].sendmail.assert_called_once()

    def test_notify_success_without_encryption(
        self, notifiers_module, mock_notifier_config, mock_smtp
    ):
        """Successful notification without encryption."""
        mock_notifier_config.EMAIL_ENC = 0  # No encryption

        email = notifiers_module.EMAIL(test_emailenc=0)
        result = email.notify("Test message body", "Test Subject")

        assert result is True
        mock_smtp["SMTP"].assert_called_once()
        mock_smtp["smtp_instance"].starttls.assert_not_called()

    def test_notify_without_credentials(
        self, notifiers_module, mock_notifier_config, mock_smtp
    ):
        """Notification without credentials skips login."""
        mock_notifier_config.EMAIL_USER = None
        mock_notifier_config.EMAIL_PASSWORD = None

        email = notifiers_module.EMAIL(test_emailuser=None, test_emailpass=None)
        result = email.notify("Test message body", "Test Subject")

        assert result is True
        mock_smtp["smtp_instance"].login.assert_not_called()

    def test_notify_message_format(self, notifiers_module, mock_notifier_config, mock_smtp):
        """Verify email message is properly formatted."""
        email = notifiers_module.EMAIL()
        result = email.notify("Test message body", "Test Subject")

        assert result is True
        # Get the message that was sent
        sendmail_call = mock_smtp["smtp_instance"].sendmail.call_args
        sent_from, sent_to, message = sendmail_call[0]

        assert sent_from == "comicarr@example.com"
        assert sent_to == "user@example.com"
        assert "Subject: Test Subject" in message
        assert "From: comicarr@example.com" in message
        assert "To: user@example.com" in message
        assert "Test message body" in message

    def test_notify_module_appended_to_logging(
        self, notifiers_module, mock_notifier_config, mock_smtp
    ):
        """Module name should be appended for logging."""
        email = notifiers_module.EMAIL()
        # The notify method should accept and use module parameter
        result = email.notify("Test message", "Test Subject", module="[TEST]")
        assert result is True


class TestEmailNotifyErrors:
    """Test EMAIL error handling."""

    def test_notify_smtp_connection_error(
        self, notifiers_module, mock_notifier_config, mock_smtp
    ):
        """SMTP connection error returns False."""
        import smtplib

        mock_smtp["SMTP"].side_effect = smtplib.SMTPConnectError(
            421, "Connection refused"
        )

        email = notifiers_module.EMAIL()
        result = email.notify("Test message", "Test Subject")

        assert result is False

    def test_notify_smtp_auth_error(
        self, notifiers_module, mock_notifier_config, mock_smtp
    ):
        """SMTP authentication error returns False."""
        import smtplib

        mock_smtp["smtp_instance"].login.side_effect = smtplib.SMTPAuthenticationError(
            535, "Authentication failed"
        )

        email = notifiers_module.EMAIL()
        result = email.notify("Test message", "Test Subject")

        assert result is False

    def test_notify_smtp_send_error(
        self, notifiers_module, mock_notifier_config, mock_smtp
    ):
        """SMTP send error returns False."""
        import smtplib

        mock_smtp["smtp_instance"].sendmail.side_effect = smtplib.SMTPDataError(
            554, "Message rejected"
        )

        email = notifiers_module.EMAIL()
        result = email.notify("Test message", "Test Subject")

        assert result is False

    def test_notify_general_exception(
        self, notifiers_module, mock_notifier_config, mock_smtp
    ):
        """General exception returns False."""
        mock_smtp["SMTP"].side_effect = Exception("Unexpected error")

        email = notifiers_module.EMAIL()
        result = email.notify("Test message", "Test Subject")

        assert result is False


class TestEmailTestNotify:
    """Test EMAIL test_notify method."""

    def test_test_notify_sends_correct_message(
        self, notifiers_module, mock_notifier_config, mock_smtp
    ):
        """test_notify sends the expected test message."""
        email = notifiers_module.EMAIL()
        result = email.test_notify()

        assert result is True
        sendmail_call = mock_smtp["smtp_instance"].sendmail.call_args
        _, _, message = sendmail_call[0]

        assert "Subject: Comicarr notification - Test" in message
        assert "great power comes great responsibility" in message
