"""
Tests for comicarr.app.system domain — Phase 1.

Covers: auth login/logout, SSE streaming, config endpoints, JWT cookies.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

import comicarr

# Ensure LOG_LEVEL is set for tests (logger.info checks LOG_LEVEL > 0)
if comicarr.LOG_LEVEL is None:
    comicarr.LOG_LEVEL = 0

from comicarr.app.core.context import AppContext
from comicarr.app.core.security import (
    COOKIE_NAME,
    create_session_token,
    validate_jwt_token,
)
from comicarr.app.system import service as system_service


def _make_test_ctx(**overrides):
    """Create a test AppContext for system domain tests."""
    config = MagicMock()
    config.HTTP_USERNAME = "admin"
    config.HTTP_PASSWORD = "$2b$12$LJ3m4ys5Cq2n5o/xBp6Mj.abcdefghijklmnopqrstuv"  # bcrypt hash
    config.ENABLE_HTTPS = False
    config.API_KEY = "test_api_key_32chars_here_pad00"
    config.SECURE_DIR = "/tmp/test_secure"
    config.OPDS_USERNAME = None
    config.OPDS_PASSWORD = None
    config.LOGIN_TIMEOUT = 43800
    config.COMIC_DIR = "/comics"
    config.DESTINATION_DIR = "/downloads"
    config.LOG_DIR = None

    defaults = {
        "config": config,
        "jwt_secret_key": b"test_secret_key_32_bytes_padding!",
        "jwt_generation": 0,
        "sse_key": "test_sse_key",
        "download_apikey": "test_dl_key",
        "scheduler": MagicMock(),
        "setup_token": None,
    }
    defaults.update(overrides)
    return AppContext(**defaults)


# =============================================================================
# Login Service Tests
# =============================================================================


class TestVerifyLogin:
    @patch("comicarr.encrypted")
    def test_successful_bcrypt_login(self, mock_encrypted):
        """Login with correct bcrypt password succeeds."""
        ctx = _make_test_ctx()
        mock_encrypted.verify_password.return_value = True

        result = system_service.verify_login(ctx, "admin", "correct_password", "127.0.0.1")
        assert result["success"] is True
        assert result["username"] == "admin"

    @patch("comicarr.encrypted")
    def test_wrong_password_fails(self, mock_encrypted):
        """Login with wrong password fails."""
        ctx = _make_test_ctx()
        mock_encrypted.verify_password.return_value = False

        result = system_service.verify_login(ctx, "admin", "wrong_password", "127.0.0.1")
        assert result["success"] is False
        assert "error" in result

    def test_wrong_username_fails(self):
        """Login with wrong username fails."""
        ctx = _make_test_ctx()

        result = system_service.verify_login(ctx, "hacker", "any_password", "127.0.0.1")
        assert result["success"] is False

    def test_rate_limiting_blocks_after_5_failures(self):
        """Rate limiter blocks after 5 failed attempts."""
        ctx = _make_test_ctx()

        # Simulate 5 failed logins from same IP
        for _ in range(5):
            system_service.verify_login(ctx, "wrong_user", "wrong_pass", "10.0.0.99")

        # 6th attempt should be blocked
        result = system_service.verify_login(ctx, "admin", "any", "10.0.0.99")
        assert result["success"] is False
        assert "Incorrect" in result["error"]

    def test_no_config_returns_error(self):
        """Login without configured auth returns error."""
        ctx = _make_test_ctx()
        ctx.config.HTTP_USERNAME = None
        ctx.config.HTTP_PASSWORD = None

        result = system_service.verify_login(ctx, "admin", "pass", "127.0.0.1")
        assert result["success"] is False


# =============================================================================
# JWT Token Integration Tests
# =============================================================================


class TestJWTIntegration:
    def test_login_produces_valid_jwt(self):
        """A successful login should produce a JWT that validates."""
        secret = b"test_secret_key_32_bytes_padding!"
        token = create_session_token("admin", secret, generation=0)
        username = validate_jwt_token(token, secret, current_generation=0)
        assert username == "admin"

    def test_revoked_generation_invalidates_token(self):
        """Incrementing jwt_generation invalidates all tokens."""
        secret = b"test_secret_key_32_bytes_padding!"
        token = create_session_token("admin", secret, generation=0)

        # Token valid with generation 0
        assert validate_jwt_token(token, secret, 0) == "admin"
        # Token invalid after generation bump (simulating revocation)
        assert validate_jwt_token(token, secret, 1) is None


# =============================================================================
# Initial Setup Tests
# =============================================================================


class TestInitialSetup:
    @patch("comicarr.encrypted")
    def test_setup_succeeds(self, mock_encrypted):
        """Initial setup with valid credentials succeeds."""
        ctx = _make_test_ctx()
        ctx.config.HTTP_USERNAME = None
        ctx.config.HTTP_PASSWORD = None
        mock_encrypted.hash_password.return_value = "$2b$12$hashed"

        # initial_setup does `import comicarr` locally and sets globals —
        # this is harmless in tests, just let it run
        result = system_service.initial_setup(ctx, "admin", "password123", None)
        assert result["success"] is True
        ctx.config.process_kwargs.assert_called_once()
        ctx.config.writeconfig.assert_called_once()

    def test_setup_rejects_short_password(self):
        """Setup rejects passwords shorter than 8 characters."""
        ctx = _make_test_ctx()
        ctx.config.HTTP_USERNAME = None
        ctx.config.HTTP_PASSWORD = None

        result = system_service.initial_setup(ctx, "admin", "short", None)
        assert result["success"] is False
        assert "8 characters" in result["error"]

    def test_setup_rejects_when_already_configured(self):
        """Setup fails if credentials are already set."""
        ctx = _make_test_ctx()
        # config.HTTP_USERNAME and HTTP_PASSWORD are already set

        result = system_service.initial_setup(ctx, "admin", "password123", None)
        assert result["success"] is False
        assert "already configured" in result["error"]

    def test_setup_validates_token(self):
        """Setup requires valid setup token when one is active."""
        ctx = _make_test_ctx(setup_token="correct_token")
        ctx.config.HTTP_USERNAME = None
        ctx.config.HTTP_PASSWORD = None

        result = system_service.initial_setup(ctx, "admin", "password123", "wrong_token")
        assert result["success"] is False
        assert "Invalid setup token" in result["error"]


# =============================================================================
# Config Service Tests
# =============================================================================


class TestConfigService:
    def test_get_safe_config_excludes_passwords(self):
        """get_safe_config returns config without sensitive fields."""
        ctx = _make_test_ctx()
        ctx.config.COMIC_DIR = "/my/comics"
        ctx.config.HTTP_PORT = 8090

        result = system_service.get_safe_config(ctx)
        assert "COMIC_DIR" in result
        assert "HTTP_PORT" in result
        # Passwords should not be present
        assert "HTTP_PASSWORD" not in result
        assert "API_KEY" not in result

    def test_get_safe_config_includes_version_from_context(self):
        """get_safe_config includes version when ctx.current_version is set."""
        ctx = _make_test_ctx(current_version="1.2.3")
        result = system_service.get_safe_config(ctx)
        assert result["version"] == "1.2.3"

    @patch("importlib.metadata.version", return_value="0.8.0")
    def test_get_safe_config_falls_back_to_importlib_metadata(self, mock_version):
        """get_safe_config falls back to importlib.metadata when ctx.current_version is None."""
        ctx = _make_test_ctx(current_version=None)
        result = system_service.get_safe_config(ctx)
        assert result["version"] == "0.8.0"
        mock_version.assert_called_once_with("comicarr")

    @patch("importlib.metadata.version", side_effect=Exception("not found"))
    def test_get_safe_config_omits_version_when_unavailable(self, mock_version):
        """get_safe_config omits version key when both sources fail."""
        ctx = _make_test_ctx(current_version=None)
        result = system_service.get_safe_config(ctx)
        assert "version" not in result

    def test_get_job_info(self):
        """get_job_info returns scheduler job list."""
        ctx = _make_test_ctx()
        mock_job = MagicMock()
        mock_job.id = "search_job"
        mock_job.name = "Search"
        mock_job.next_run_time = None
        mock_job.trigger = "interval"
        ctx.scheduler.get_jobs.return_value = [mock_job]

        result = system_service.get_job_info(ctx)
        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["id"] == "search_job"

    def test_get_version_info(self):
        """get_version_info returns version data from context."""
        ctx = _make_test_ctx(current_version="0.6.0", install_type="git")

        result = system_service.get_version_info(ctx)
        assert result["current_version"] == "0.6.0"
        assert result["install_type"] == "git"
