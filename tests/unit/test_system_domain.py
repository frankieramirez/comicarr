"""
Tests for comicarr.app.system domain — Phase 1.

Covers: auth login/logout, SSE streaming, config endpoints, JWT cookies.
"""

import configparser
import datetime
import json
import os
import stat
import threading
from unittest.mock import MagicMock, patch

import pytest

import comicarr

# Ensure LOG_LEVEL is set for tests (logger.info checks LOG_LEVEL > 0)
if comicarr.LOG_LEVEL is None:
    comicarr.LOG_LEVEL = 0

from comicarr.app.core.context import AppContext
from comicarr.app.core.security import (
    create_session_token,
    load_or_create_jwt_key,
    validate_jwt_token,
)
from comicarr.app.system import router as system_router
from comicarr.app.system import service as system_service


def _audit_lines(mock_logger):
    """Collect [AUTH-AUDIT] messages from a mocked logger across every level.

    Scanning all levels rather than just info() means moving an audit call to a
    different level can't silently satisfy a "no audit emitted" assertion.
    """
    lines = []
    for level in ("info", "warn", "warning", "error", "fdebug", "debug"):
        recorder = getattr(mock_logger, level, None)
        if recorder is None:
            continue
        for call in recorder.call_args_list:
            if call.args and "[AUTH-AUDIT]" in str(call.args[0]):
                lines.append(call.args[0])
    return lines


def _make_test_ctx(**overrides):
    """Create a test AppContext for system domain tests."""
    config = MagicMock()
    config.HTTP_USERNAME = "admin"
    config.HTTP_PASSWORD = "$2b$12$LJ3m4ys5Cq2n5o/xBp6Mj.abcdefghijklmnopqrstuv"  # bcrypt hash
    config.ENABLE_HTTPS = False
    config.API_KEY = "configured-api-key"
    config.COMICVINE_API = "configured-comicvine-key"
    config.AI_API_KEY = None
    config.METRON_PASSWORD = None
    config.MAL_CLIENT_ID = None
    config.PROWL_KEYS = "configured-prowl-keys"
    config.SLACK_WEBHOOK_URL = "configured-slack-webhook"
    config.MATTERMOST_WEBHOOK_URL = "configured-mattermost-webhook"
    config.DISCORD_WEBHOOK_URL = "configured-discord-webhook"
    config.SECURE_DIR = "/tmp/test_secure"
    config.OPDS_USERNAME = None
    config.OPDS_PASSWORD = None
    config.LOGIN_TIMEOUT = 43800
    config.COMIC_DIR = "/comics"
    config.DESTINATION_DIR = "/downloads"
    config.LOG_DIR = None

    def process_kwargs(values):
        for key, value in values.items():
            setattr(config, key.upper(), value)

    config.process_kwargs.side_effect = process_kwargs

    def apply_transaction(values, configure=True):
        previous = {key.upper(): getattr(config, key.upper(), None) for key in values}
        try:
            config.process_kwargs(values)
            if configure:
                config.configure(update=True, startup=False)
            return True
        except Exception:
            for key, value in previous.items():
                setattr(config, key, value)
            return False

    config.apply_transaction.side_effect = apply_transaction

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

    @patch("comicarr.encrypted")
    def test_password_migration_uses_shared_transaction_without_configure(self, mock_encrypted):
        """Login hash migration does not mutate the parser outside the transaction lock."""
        ctx = _make_test_ctx()
        mock_encrypted.hash_password.return_value = "$2b$12$migrated"

        system_service._migrate_password(ctx, "legacy-password")

        ctx.config.apply_transaction.assert_called_once_with({"http_password": "$2b$12$migrated"}, configure=False)
        ctx.config.writeconfig.assert_not_called()

    @patch("comicarr.encrypted")
    def test_password_migration_failure_is_logged_and_non_raising(self, mock_encrypted):
        """Failed bcrypt migration must not raise out of the migration helper."""
        ctx = _make_test_ctx()
        mock_encrypted.hash_password.return_value = "$2b$12$migrated"
        ctx.config.apply_transaction.side_effect = None
        ctx.config.apply_transaction.return_value = False

        system_service._migrate_password(ctx, "legacy-password")

        ctx.config.apply_transaction.assert_called_once_with({"http_password": "$2b$12$migrated"}, configure=False)

    @patch("comicarr.encrypted")
    def test_plaintext_login_succeeds_when_password_migration_fails(self, mock_encrypted):
        """Login still succeeds if hash migration cannot be persisted."""
        ctx = _make_test_ctx()
        ctx.config.HTTP_PASSWORD = "legacy-password"
        mock_encrypted.hash_password.return_value = "$2b$12$migrated"
        ctx.config.apply_transaction.side_effect = None
        ctx.config.apply_transaction.return_value = False

        result = system_service.verify_login(ctx, "admin", "legacy-password", "127.0.0.1")

        assert result["success"] is True
        assert result["username"] == "admin"
        assert ctx.config.HTTP_PASSWORD == "legacy-password"
        ctx.config.apply_transaction.assert_called_once_with({"http_password": "$2b$12$migrated"}, configure=False)


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

    def test_logout_rotates_key_and_revocation_survives_restart(self, tmp_path):
        """Logout revokes copied tokens in memory and from a fresh runtime key load."""
        secure_dir = tmp_path / "secure"
        secure_dir.mkdir()
        old_key = load_or_create_jwt_key(str(secure_dir))
        old_token = create_session_token("admin", old_key, generation=0)
        ctx = _make_test_ctx(
            jwt_secure_dir=str(secure_dir),
            jwt_secret_key=old_key,
        )

        response = system_router.logout(ctx=ctx, username="admin")

        assert response.status_code == 200
        assert any(
            name.lower() == b"set-cookie" and b"comicarr_session=" in value and b"Max-Age=0" in value
            for name, value in response.raw_headers
        )
        assert validate_jwt_token(old_token, ctx.jwt_secret_key, 0) is None
        new_token = create_session_token("admin", ctx.jwt_secret_key, generation=0)
        assert validate_jwt_token(new_token, ctx.jwt_secret_key, 0) == "admin"

        restarted_key = load_or_create_jwt_key(str(secure_dir))
        assert restarted_key == ctx.jwt_secret_key
        assert validate_jwt_token(old_token, restarted_key, 0) is None
        assert validate_jwt_token(new_token, restarted_key, 0) == "admin"

    def test_logout_persistence_failure_keeps_session_and_cookie(self, tmp_path):
        """A failed atomic replace must not claim logout or clear a valid cookie."""
        secure_dir = tmp_path / "secure"
        secure_dir.mkdir()
        old_key = load_or_create_jwt_key(str(secure_dir))
        old_token = create_session_token("admin", old_key, generation=0)
        ctx = _make_test_ctx(
            jwt_secure_dir=str(secure_dir),
            jwt_secret_key=old_key,
        )

        with patch("comicarr.app.core.security.os.replace", side_effect=OSError("/secret/path failed")):
            response = system_router.logout(ctx=ctx, username="admin")

        payload = json.loads(response.body)
        assert response.status_code == 500
        assert payload == {"success": False, "error": "Unable to revoke active sessions"}
        assert b"/secret/path" not in response.body
        assert all(name.lower() != b"set-cookie" for name, _value in response.raw_headers)
        assert ctx.jwt_secret_key == old_key
        assert (secure_dir / "jwt.key").read_bytes() == old_key
        assert validate_jwt_token(old_token, ctx.jwt_secret_key, 0) == "admin"

    def test_logout_without_persistent_key_authority_fails_closed(self):
        """An ephemeral runtime cannot claim durable session revocation."""
        ctx = _make_test_ctx(jwt_secure_dir=None)

        response = system_router.logout(ctx=ctx, username="admin")

        assert response.status_code == 500
        assert all(name.lower() != b"set-cookie" for name, _value in response.raw_headers)

    @pytest.mark.asyncio
    async def test_login_signs_token_while_holding_rotation_lock(self):
        """Login and logout share one key-authority serialization boundary."""

        class RecordingLock:
            def __init__(self):
                self.held = False

            def __enter__(self):
                self.held = True

            def __exit__(self, _exc_type, _exc_value, _traceback):
                self.held = False

        lock = RecordingLock()
        ctx = _make_test_ctx(runtime_lock=lock)

        def sign_while_locked(*_args, **_kwargs):
            assert lock.held is True
            return "signed-token"

        request = _JsonRequest({"username": "admin", "password": "password123"})
        request.client = None
        with (
            patch.object(
                system_router.system_service,
                "verify_login",
                return_value={"success": True, "username": "admin"},
            ),
            patch.object(system_router, "create_session_token", side_effect=sign_while_locked),
        ):
            response = await system_router.login(request, ctx)

        assert response.status_code == 200
        assert any(b"signed-token" in value for name, value in response.raw_headers if name.lower() == b"set-cookie")


# =============================================================================
# Initial Setup Tests
# =============================================================================


class TestAnnounceSetupToken:
    def test_quiet_mode_prints_token_and_logs(self, monkeypatch, capsys):
        """Quiet mode still prints the setup token to container stdout."""
        expected = [
            "[SETUP] *** First-run setup required ***",
            "[SETUP] Setup token: secret-token",
            "[SETUP] Provide this token when setting up credentials via the web interface.",
        ]
        monkeypatch.setattr(comicarr, "QUIET", True)
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 1)

        with patch.object(system_service.logger, "info") as mock_info:
            system_service.announce_setup_token("secret-token")

        captured = capsys.readouterr()
        assert captured.out.splitlines() == expected
        assert [call.args[0] for call in mock_info.call_args_list] == expected

    def test_normal_mode_logs_without_stdout_duplicate(self, monkeypatch, capsys):
        """Normal logging mode relies on the configured logger only."""
        expected = [
            "[SETUP] *** First-run setup required ***",
            "[SETUP] Setup token: secret-token",
            "[SETUP] Provide this token when setting up credentials via the web interface.",
        ]
        monkeypatch.setattr(comicarr, "QUIET", False)
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 1)

        with patch.object(system_service.logger, "info") as mock_info:
            system_service.announce_setup_token("secret-token")

        captured = capsys.readouterr()
        assert captured.out == ""
        assert [call.args[0] for call in mock_info.call_args_list] == expected

    def test_log_level_zero_prints_token_even_when_not_quiet(self, monkeypatch, capsys):
        """Console-suppressed log level still exposes the setup token."""
        expected = [
            "[SETUP] *** First-run setup required ***",
            "[SETUP] Setup token: secret-token",
            "[SETUP] Provide this token when setting up credentials via the web interface.",
        ]
        monkeypatch.setattr(comicarr, "QUIET", False)
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0)

        with patch.object(system_service.logger, "info") as mock_info:
            system_service.announce_setup_token("secret-token")

        captured = capsys.readouterr()
        assert captured.out.splitlines() == expected
        assert [call.args[0] for call in mock_info.call_args_list] == expected


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
        ctx.config.apply_transaction.assert_called_once_with(
            {
                "http_username": "admin",
                "http_password": "$2b$12$hashed",
                "authentication": 2,
            }
        )

    @patch("comicarr.encrypted")
    def test_setup_persistence_failure_preserves_setup_state(self, mock_encrypted, monkeypatch):
        """Failed setup writes must leave credentials, tokens, and signals unchanged."""
        ctx = _make_test_ctx(setup_token="setup-token")
        ctx.config.HTTP_USERNAME = None
        ctx.config.HTTP_PASSWORD = None
        ctx.config.apply_transaction.side_effect = None
        ctx.config.apply_transaction.return_value = False
        mock_encrypted.hash_password.return_value = "$2b$12$hashed"
        monkeypatch.setattr(comicarr, "SETUP_TOKEN", "setup-token")
        monkeypatch.setattr(comicarr, "SIGNAL", None)

        result = system_service.initial_setup(ctx, "admin", "password123", "setup-token")

        assert result == {"success": False, "error": "Failed to persist initial credentials"}
        assert ctx.config.HTTP_USERNAME is None
        assert ctx.config.HTTP_PASSWORD is None
        assert ctx.setup_token == "setup-token"
        assert comicarr.SETUP_TOKEN == "setup-token"
        assert ctx.signal is None
        assert comicarr.SIGNAL is None

    @patch("comicarr.encrypted")
    def test_setup_hash_failure_preserves_setup_state(self, mock_encrypted, monkeypatch):
        """Password hashing failures use the controlled setup persistence contract."""
        ctx = _make_test_ctx(setup_token="setup-token")
        ctx.config.HTTP_USERNAME = None
        ctx.config.HTTP_PASSWORD = None
        mock_encrypted.hash_password.side_effect = RuntimeError("hash failed")
        monkeypatch.setattr(comicarr, "SETUP_TOKEN", "setup-token")
        monkeypatch.setattr(comicarr, "SIGNAL", None)

        result = system_service.initial_setup(ctx, "admin", "password123", "setup-token")

        assert result == {"success": False, "error": "Failed to persist initial credentials"}
        ctx.config.apply_transaction.assert_not_called()
        assert ctx.setup_token == "setup-token"
        assert comicarr.SETUP_TOKEN == "setup-token"
        assert ctx.signal is None
        assert comicarr.SIGNAL is None

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
    def test_get_safe_config_returns_lowercase_keys(self):
        """get_safe_config returns all keys in lowercase."""
        ctx = _make_test_ctx()
        ctx.config.COMIC_DIR = "/my/comics"
        ctx.config.HTTP_PORT = 8090

        result = system_service.get_safe_config(ctx)
        assert "comic_dir" in result
        assert "http_port" in result
        # All keys should be lowercase
        for key in result:
            assert key == key.lower(), "Key %s should be lowercase" % key

    def test_get_safe_config_excludes_passwords(self):
        """get_safe_config returns config without sensitive fields."""
        ctx = _make_test_ctx()
        ctx.config.COMIC_DIR = "/my/comics"
        ctx.config.HTTP_PORT = 8090

        result = system_service.get_safe_config(ctx)
        assert "comic_dir" in result
        assert "http_port" in result
        # Passwords should not be present (check both cases)
        assert "http_password" not in result
        assert "HTTP_PASSWORD" not in result

    def test_get_safe_config_redacts_long_lived_secrets(self):
        """get_safe_config exposes secret indicators without secret values."""
        ctx = _make_test_ctx()
        result = system_service.get_safe_config(ctx)

        redacted_keys = [
            "api_key",
            "comicvine_api",
            "prowl_keys",
            "slack_webhook_url",
            "mattermost_webhook_url",
            "discord_webhook_url",
        ]
        for key in redacted_keys:
            assert key not in result

        assert result["api_key_set"] is True
        assert result["comicvine_api_set"] is True
        assert result["prowl_keys_set"] is True
        assert result["slack_webhook_url_set"] is True
        assert result["mattermost_webhook_url_set"] is True
        assert result["discord_webhook_url_set"] is True

    def test_get_safe_config_secret_indicators_false_when_empty(self):
        """Secret indicators are False when existing config values are empty."""
        ctx = _make_test_ctx()
        ctx.config.API_KEY = ""
        ctx.config.COMICVINE_API = "None"
        ctx.config.PROWL_KEYS = None
        ctx.config.SLACK_WEBHOOK_URL = ""
        ctx.config.MATTERMOST_WEBHOOK_URL = "None"
        ctx.config.DISCORD_WEBHOOK_URL = None

        result = system_service.get_safe_config(ctx)

        assert result["api_key_set"] is False
        assert result["comicvine_api_set"] is False
        assert result["prowl_keys_set"] is False
        assert result["slack_webhook_url_set"] is False
        assert result["mattermost_webhook_url_set"] is False
        assert result["discord_webhook_url_set"] is False

    def test_get_safe_config_includes_new_keys(self):
        """get_safe_config includes all frontend-needed keys."""
        ctx = _make_test_ctx()
        ctx.config.COMICVINE_ENABLED = True
        ctx.config.MANGADEX_ENABLED = False
        ctx.config.PREFERRED_QUALITY = "high"

        result = system_service.get_safe_config(ctx)
        assert "comicvine_enabled" in result
        assert "mangadex_enabled" in result
        assert "preferred_quality" in result

    def test_get_safe_config_includes_metron_password_set_indicator(self):
        """get_safe_config returns metron_password_set boolean, not the actual password."""
        ctx = _make_test_ctx()
        ctx.config.METRON_PASSWORD = "gAAAAAsecretencrypted"
        result = system_service.get_safe_config(ctx)
        assert result["metron_password_set"] is True
        assert "metron_password" not in result

    def test_get_safe_config_metron_password_set_false_when_empty(self):
        """metron_password_set is False when no password is configured."""
        ctx = _make_test_ctx()
        ctx.config.METRON_PASSWORD = None
        result = system_service.get_safe_config(ctx)
        assert result["metron_password_set"] is False

    def test_get_safe_config_includes_download_client_labels(self):
        """get_safe_config returns derived download client labels matching config.py enums."""
        ctx = _make_test_ctx()
        ctx.config.NZB_DOWNLOADER = 0
        ctx.config.TORRENT_DOWNLOADER = 1
        result = system_service.get_safe_config(ctx)
        assert result["nzb_downloader_label"] == "SABnzbd"
        assert result["torrent_downloader_label"] == "uTorrent"

    def test_get_safe_config_download_labels_all_values(self):
        """Verify all download client enum values map to correct labels."""
        ctx = _make_test_ctx()
        # NZB: 0=SABnzbd, 1=NZBGet, 2=Blackhole, 3=Disabled
        for val, label in [(0, "SABnzbd"), (1, "NZBGet"), (2, "Blackhole"), (3, "Disabled")]:
            ctx.config.NZB_DOWNLOADER = val
            result = system_service.get_safe_config(ctx)
            assert result["nzb_downloader_label"] == label, "NZB %d should be %s" % (val, label)
        # Torrent: 0=Watchfolder, 1=uTorrent, 2=rTorrent, 3=Transmission, 4=Deluge, 5=qBittorrent
        for val, label in [
            (0, "Watchfolder"),
            (1, "uTorrent"),
            (2, "rTorrent"),
            (3, "Transmission"),
            (4, "Deluge"),
            (5, "qBittorrent"),
        ]:
            ctx.config.TORRENT_DOWNLOADER = val
            result = system_service.get_safe_config(ctx)
            assert result["torrent_downloader_label"] == label, "Torrent %d should be %s" % (val, label)

    def test_get_safe_config_unknown_downloader_value(self):
        """Unknown downloader enum values fall back to 'None' string."""
        ctx = _make_test_ctx()
        ctx.config.NZB_DOWNLOADER = 99
        result = system_service.get_safe_config(ctx)
        assert result["nzb_downloader_label"] == "None"

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
    @patch("pathlib.Path.is_file", return_value=False)
    def test_get_safe_config_omits_version_when_unavailable(self, mock_isfile, mock_version):
        """get_safe_config omits version key when all sources fail."""
        ctx = _make_test_ctx(current_version=None)
        result = system_service.get_safe_config(ctx)
        assert "version" not in result

    def test_update_config_accepts_lowercase_keys(self):
        """update_config normalizes lowercase keys to uppercase."""
        ctx = _make_test_ctx()
        result = system_service.update_config(ctx, {"comic_dir": "/new/path"})
        assert result["success"] is True
        ctx.config.apply_transaction.assert_called_once()
        args = ctx.config.apply_transaction.call_args[0][0]
        assert "COMIC_DIR" in args

    def test_update_config_accepts_uppercase_keys(self):
        """update_config still accepts uppercase keys (backward compat)."""
        ctx = _make_test_ctx()
        result = system_service.update_config(ctx, {"COMIC_DIR": "/new/path"})
        assert result["success"] is True

    def test_update_config_rejects_sensitive_keys_regardless_of_case(self):
        """update_config rejects api_key, http_password in any casing."""
        ctx = _make_test_ctx()
        result = system_service.update_config(ctx, {"api_key": "hacked", "http_password": "hacked"})
        assert result["success"] is False
        assert "No valid config keys" in result["error"]

    def test_update_config_filters_sensitive_keys_from_mixed_payload(self):
        """update_config applies valid keys and silently filters sensitive ones."""
        ctx = _make_test_ctx()
        result = system_service.update_config(
            ctx,
            {
                "comic_dir": "/new/path",
                "api_key": "hacked",
            },
        )
        assert result["success"] is True
        args = ctx.config.apply_transaction.call_args[0][0]
        assert "COMIC_DIR" in args
        assert "API_KEY" not in args

    def test_update_config_reports_persistence_failure_without_side_effects(self, monkeypatch):
        """Failed durable writes must not reconfigure schedulers or replace the global config."""
        ctx = _make_test_ctx()
        previous_global = object()
        monkeypatch.setattr(comicarr, "CONFIG", previous_global)
        ctx.config.apply_transaction.side_effect = None
        ctx.config.apply_transaction.return_value = False

        with patch.object(system_service, "_reconfigure_schedulers") as reconfigure:
            result = system_service.update_config(ctx, {"search_interval": 720})

        assert result == {"success": False, "error": "Failed to persist configuration"}
        reconfigure.assert_not_called()
        assert comicarr.CONFIG is previous_global

    def test_update_config_reconfigures_scheduler_after_persistence(self):
        """Scheduler changes happen only after the transactional write succeeds."""
        ctx = _make_test_ctx()
        events = []

        def persist(values):
            events.append("persist")
            return True

        ctx.config.apply_transaction.side_effect = persist
        with patch.object(
            system_service, "_reconfigure_schedulers", side_effect=lambda _ctx: events.append("scheduler")
        ):
            result = system_service.update_config(ctx, {"search_interval": 720})

        assert result == {"success": True}
        assert events == ["persist", "scheduler"]

    @pytest.mark.parametrize(
        ("provider_type", "config_key"),
        (("newznab", "EXTRA_NEWZNABS"), ("torznab", "EXTRA_TORZNABS")),
    )
    def test_update_providers_uses_transactional_extra_provider_key(self, provider_type, config_key):
        providers = [["Indexer", "https://indexer.test", "1", "secret", "5030", "1", 101]]
        ctx = _make_test_ctx()

        result = system_service.update_providers(ctx, {"type": provider_type, "providers": providers})

        assert result == {"success": True}
        ctx.config.apply_transaction.assert_called_once_with({config_key: providers}, configure=False)
        ctx.config.configure.assert_not_called()
        ctx.config.writeconfig_values.assert_not_called()

    def test_update_providers_reports_transaction_failure_without_reconfigure(self):
        old_providers = [("Old", "https://old.test", "1", "old-key", "5030", "1", 100)]
        new_providers = [["New", "https://new.test", "1", "new-key", "5030", "1", 101]]
        ctx = _make_test_ctx()
        ctx.config.EXTRA_NEWZNABS = old_providers
        ctx.config.apply_transaction.side_effect = None
        ctx.config.apply_transaction.return_value = False

        result = system_service.update_providers(ctx, {"type": "newznab", "providers": new_providers})

        assert result == {"success": False, "error": "Failed to persist provider configuration"}
        assert ctx.config.EXTRA_NEWZNABS is old_providers
        ctx.config.apply_transaction.assert_called_once_with({"EXTRA_NEWZNABS": new_providers}, configure=False)
        ctx.config.configure.assert_not_called()
        ctx.config.writeconfig_values.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_providers_returns_bad_request_for_malformed_entry(self):
        """Malformed provider tuples remain validation errors rather than storage failures."""
        ctx = _make_test_ctx()
        ctx.config.validate_provider_extra_value.side_effect = ValueError("invalid provider entry")
        request = _JsonRequest({"type": "newznab", "providers": [["Too short", "https://short.test", "1"]]})

        response = await system_router.update_providers(request, ctx)

        assert response.status_code == 400
        assert json.loads(response.body) == {"success": False, "error": "Invalid provider configuration"}
        ctx.config.apply_transaction.assert_not_called()

    @pytest.mark.parametrize("payload", ({"type": "invalid", "providers": []}, [], None))
    def test_update_providers_rejects_invalid_payload_without_writing(self, payload):
        ctx = _make_test_ctx()

        result = system_service.update_providers(ctx, payload)

        assert result["success"] is False
        ctx.config.apply_transaction.assert_not_called()

    def test_recent_logs_redact_runtime_provider_and_header_credentials(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        provider_secret = "provider-secret-value"
        bearer_secret = "bearer-secret-value"
        basic_secret = "basic-secret-value"
        token_secret = "token-secret-value"
        query_secret = "query-secret-value"
        (log_dir / "comicarr.log").write_text(
            "provider_list: {'info': ('Indexer', 'https://indexer.test', '1', 'provider-secret-value')}\n"
            "Authorization: Bearer bearer-secret-value\n"
            "Authorization: Basic basic-secret-value\n"
            "{'Authorization': 'Token token-secret-value'}\n"
            "download failed https://indexer.test/api?apikey=query-secret-value\n"
        )
        ctx = _make_test_ctx(data_dir=str(tmp_path))
        ctx.config.LOG_DIR = str(log_dir)
        ctx.config.EXTRA_NEWZNABS = [("Indexer", "https://indexer.test", "1", provider_secret, "5030", "1", 100)]
        ctx.config.EXTRA_TORZNABS = []

        result = system_service.get_recent_logs(ctx)

        rendered = "".join(result["logs"])
        assert provider_secret not in rendered
        assert bearer_secret not in rendered
        assert basic_secret not in rendered
        assert token_secret not in rendered
        assert query_secret not in rendered
        assert "[redacted]" in rendered.lower()

    @patch("comicarr.app.system.service.secrets.token_hex", return_value="a" * 32)
    def test_regenerate_api_key_persists_new_key(self, mock_token_hex):
        """regenerate_api_key creates, persists, and returns a server-side key."""
        ctx = _make_test_ctx()
        result = system_service.regenerate_api_key(ctx, "admin", "10.0.0.5")

        assert result == {"success": True, "api_key": "a" * 32}
        assert ctx.config.API_KEY == "a" * 32
        mock_token_hex.assert_called_once_with(16)
        ctx.config.apply_transaction.assert_called_once_with({"api_key": "a" * 32})
        ctx.config.writeconfig.assert_not_called()
        ctx.config.configure.assert_called_once_with(update=True, startup=False)

    @patch("comicarr.app.system.service.logger")
    @patch("comicarr.app.system.service.secrets.token_hex", return_value="a" * 32)
    def test_regenerate_api_key_logs_audit_event(self, mock_token_hex, mock_logger):
        """Successful rotation is recorded as an attributed audit event."""
        ctx = _make_test_ctx()
        system_service.regenerate_api_key(ctx, "admin", "10.0.0.5")

        audit_lines = _audit_lines(mock_logger)
        assert len(audit_lines) == 1
        assert "admin" in audit_lines[0]
        assert "10.0.0.5" in audit_lines[0]
        # The key itself must never reach the log.
        assert "a" * 32 not in audit_lines[0]

    @patch("comicarr.app.system.service.logger")
    @patch("comicarr.app.system.service.secrets.token_hex", return_value="a" * 32)
    def test_regenerate_api_key_skips_audit_on_failure(self, mock_token_hex, mock_logger):
        """A failed rotation must not claim the key was rotated."""
        ctx = _make_test_ctx()
        ctx.config.apply_transaction.side_effect = None
        ctx.config.apply_transaction.return_value = False

        system_service.regenerate_api_key(ctx, "admin", "10.0.0.5")

        assert _audit_lines(mock_logger) == []

    def test_regenerate_api_key_rejects_missing_config(self):
        """regenerate_api_key fails when config is not loaded."""
        ctx = _make_test_ctx(config=None)
        result = system_service.regenerate_api_key(ctx, "admin", "10.0.0.5")
        assert result["success"] is False
        assert result["error"] == "Config not loaded"

    @patch("comicarr.app.system.service.secrets.token_hex", return_value="a" * 32)
    def test_regenerate_api_key_reports_persistence_failure(self, mock_token_hex):
        """regenerate_api_key reports persistence failures through the result contract."""
        ctx = _make_test_ctx()
        ctx.config.configure.side_effect = RuntimeError("cannot reload")

        result = system_service.regenerate_api_key(ctx, "admin", "10.0.0.5")

        assert result == {"success": False, "error": "Failed to persist new API key"}
        assert ctx.config.API_KEY == "configured-api-key"
        mock_token_hex.assert_called_once_with(16)
        ctx.config.apply_transaction.assert_called_once_with({"api_key": "a" * 32})
        ctx.config.writeconfig.assert_not_called()
        ctx.config.configure.assert_called_once_with(update=True, startup=False)

    @patch("comicarr.app.system.service.secrets.token_hex", return_value="a" * 32)
    def test_regenerate_api_key_reports_transaction_failure(self, mock_token_hex):
        """regenerate_api_key fails when the transactional write is unsuccessful."""
        ctx = _make_test_ctx()
        ctx.config.apply_transaction.side_effect = None
        ctx.config.apply_transaction.return_value = False

        result = system_service.regenerate_api_key(ctx, "admin", "10.0.0.5")

        assert result == {"success": False, "error": "Failed to persist new API key"}
        assert ctx.config.API_KEY == "configured-api-key"
        mock_token_hex.assert_called_once_with(16)
        ctx.config.apply_transaction.assert_called_once_with({"api_key": "a" * 32})
        ctx.config.writeconfig.assert_not_called()
        ctx.config.configure.assert_not_called()

    def test_update_config_accepts_new_writable_keys(self):
        """update_config accepts newly added writable keys."""
        ctx = _make_test_ctx()
        result = system_service.update_config(
            ctx,
            {
                "comicvine_enabled": True,
                "preferred_quality": "high",
                "use_minsize": True,
                "minsize": 50,
            },
        )
        assert result["success"] is True
        args = ctx.config.apply_transaction.call_args[0][0]
        assert "COMICVINE_ENABLED" in args
        assert "PREFERRED_QUALITY" in args

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

    def test_job_management_returns_empty_list_without_scheduler_jobs(self, monkeypatch):
        """A display-only scheduler read has a stable empty-list contract."""
        scheduler = MagicMock()
        scheduler.get_jobs.return_value = []
        monkeypatch.setattr(comicarr, "SCHED", scheduler)

        assert system_service.job_management(write=False) == []

    def test_operational_poll_can_skip_duplicate_acquisition_health(self):
        ctx = _make_test_ctx()
        ctx.scheduler.get_jobs.return_value = []

        with patch("comicarr.app.search.health.get_acquisition_health") as acquisition_health:
            jobs = system_service.get_job_info(ctx, include_acquisition=False)
            diagnostics = system_service.get_startup_diagnostics(ctx, include_acquisition=False)

        assert "acquisition" not in jobs
        assert "acquisition" not in diagnostics
        acquisition_health.assert_not_called()

    def test_get_job_info_includes_durable_weekly_outcomes(self):
        """The weekly scheduler reports its durable outcome fields for refresh polling."""
        ctx = _make_test_ctx()
        mock_job = MagicMock()
        mock_job.id = "weekly"
        mock_job.name = "Weekly Pullist"
        mock_job.next_run_time = "2026-07-12T00:00:00Z"
        mock_job.trigger = "interval"
        ctx.scheduler.get_jobs.return_value = [mock_job]

        with patch.object(
            system_service,
            "_get_weekly_job_history",
            return_value={
                "status": "Error",
                "last_success_timestamp": 100.0,
                "last_failure_timestamp": 200.0,
                "last_error": "upstream unavailable",
            },
        ):
            result = system_service.get_job_info(ctx)

        weekly = result["jobs"][0]
        assert weekly["state"] == "error"
        assert weekly["last_success_timestamp"] == 100.0
        assert weekly["last_failure_timestamp"] == 200.0
        assert weekly["last_error"] == "upstream unavailable"

    def test_weekly_refresh_queues_the_existing_scheduler_job(self, monkeypatch):
        """Manual refresh modifies the existing weekly job instead of creating work."""
        ctx = _make_test_ctx()
        job = MagicMock()
        job.next_run_time = datetime.datetime(2026, 7, 12, 0, 0, 0)
        ctx.scheduler.get_job.return_value = job
        ctx.weekly_status = "Waiting"
        monkeypatch.setattr(comicarr, "WEEKLY_STATUS", "Waiting")
        monkeypatch.setattr(comicarr, "WEEKLY_MANUAL_NEXT_RUN", None)

        with patch.object(system_service.db, "upsert") as upsert:
            result = system_service.request_weekly_refresh(ctx)

        assert result["accepted"] is True
        assert result["state"] == "queued"
        job.modify.assert_called_once()
        upsert.assert_called_once_with("jobhistory", {"status": "Queued"}, {"JobName": "Weekly Pullist"})
        assert ctx.weekly_manual_next_run == job.next_run_time
        assert ctx.weekly_status == "Queued"
        assert comicarr.WEEKLY_MANUAL_NEXT_RUN == job.next_run_time

    def test_weekly_refresh_coalesces_an_already_queued_request(self, monkeypatch):
        """Repeated clicks leave one scheduled run in place."""
        ctx = _make_test_ctx()
        job = MagicMock()
        job.next_run_time = "2026-07-12T00:00:00Z"
        ctx.scheduler.get_job.return_value = job
        ctx.weekly_status = "Queued"
        monkeypatch.setattr(comicarr, "WEEKLY_STATUS", "Queued")

        result = system_service.request_weekly_refresh(ctx)

        assert result == {
            "accepted": False,
            "state": "queued",
            "next_run_time": "2026-07-12T00:00:00Z",
        }
        job.modify.assert_not_called()

    def test_weekly_refresh_rejects_while_the_job_is_running(self, monkeypatch):
        """A running weekly pull cannot be scheduled a second time."""
        ctx = _make_test_ctx()
        job = MagicMock()
        job.next_run_time = "2026-07-12T00:00:00Z"
        ctx.scheduler.get_job.return_value = job
        ctx.weekly_status = "Running"
        monkeypatch.setattr(comicarr, "WEEKLY_STATUS", "Running")

        result = system_service.request_weekly_refresh(ctx)

        assert result["accepted"] is False
        assert result["state"] == "running"
        job.modify.assert_not_called()

    def test_weekly_completion_preserves_the_scheduler_next_run(self, monkeypatch):
        """A manual pull does not replace APScheduler's interval cadence."""
        next_run = datetime.datetime(2026, 7, 10, 16, 0, 0)

        class WeeklyJob:
            next_run_time = next_run

            def __init__(self):
                self.modify_calls = 0

            def __str__(self):
                return "Weekly Pullist (trigger: interval], next run at: 2026-07-10 16:00:00 UTC)"

            def modify(self, **_kwargs):
                self.modify_calls += 1

        job = WeeklyJob()
        scheduler = MagicMock()
        scheduler.get_jobs.return_value = [job]
        monkeypatch.setattr(comicarr, "SCHED", scheduler)
        monkeypatch.setattr(comicarr, "WEEKLY_STATUS", "Waiting")
        monkeypatch.setattr(comicarr, "SCHED_WEEKLY_LAST", None)
        monkeypatch.setattr(comicarr, "FORCE_STATUS", {})

        with patch.object(system_service.db, "upsert") as upsert:
            system_service.job_management(
                write=True,
                job="Weekly Pullist",
                last_run_completed=1_783_692_000.0,
                status="Waiting",
            )

        assert job.modify_calls == 0
        values = upsert.call_args.args[1]
        assert values["next_run_datetime"] == next_run.isoformat()
        assert values["next_run_timestamp"] == next_run.timestamp()

    def test_terminal_outcome_is_persisted_before_date_presentation(self, monkeypatch):
        """A display-only datetime failure cannot erase the durable job outcome."""
        next_run = datetime.datetime(2026, 7, 10, 16, tzinfo=datetime.timezone.utc)
        job = MagicMock()
        job.name = "Weekly Pullist"
        job.next_run_time = next_run
        job.__str__.return_value = "Weekly Pullist (trigger: interval], next run at: 2026-07-10 16:00:00 UTC)"
        scheduler = MagicMock()
        scheduler.get_jobs.return_value = [job]
        monkeypatch.setattr(comicarr, "SCHED", scheduler)
        monkeypatch.setattr(comicarr, "WEEKLY_STATUS", "Waiting")
        monkeypatch.setattr(comicarr, "SCHED_WEEKLY_LAST", None)
        monkeypatch.setattr(comicarr, "FORCE_STATUS", {})
        monkeypatch.setattr(
            comicarr.helpers,
            "utc_date_to_local",
            MagicMock(side_effect=RuntimeError("presentation failed")),
        )

        with patch.object(system_service.db, "upsert") as upsert, pytest.raises(RuntimeError, match="presentation"):
            system_service.job_management(
                write=True,
                job="Weekly Pullist",
                last_run_completed=1_783_692_000.0,
                status="Error",
                failure=True,
                failure_message="upstream failed",
            )

        first_values = upsert.call_args_list[0].args[1]
        assert first_values["status"] == "Error"
        assert first_values["last_failure_timestamp"] == 1_783_692_000.0
        assert first_values["last_error"] == "upstream failed"

    def test_startup_recovers_an_interrupted_weekly_refresh(self, monkeypatch):
        """A persisted Running state becomes safe-to-schedule after a restart."""
        monkeypatch.setattr(comicarr, "SCHED_WEEKLY_LAST", None)
        monkeypatch.setattr(comicarr, "WEEKLY_STATUS", "Waiting")
        monkeypatch.setattr(
            system_service.db,
            "select_all",
            lambda statement: [
                {
                    "JobName": "Weekly Pullist",
                    "status": "Running",
                    "prev_run_timestamp": 200.0,
                    "last_success_timestamp": 100.0,
                }
            ],
        )

        with patch.object(system_service.db, "upsert") as upsert:
            result = system_service.job_management(startup=True)

        assert result["weekly"] == {"last": 100.0, "status": "Waiting"}
        upsert.assert_called_once_with(
            "jobhistory",
            {
                "status": "Interrupted",
                "last_failure_timestamp": 200.0,
                "last_error": "Previous weekly refresh was interrupted by restart.",
            },
            {"JobName": "Weekly Pullist"},
        )

    def test_startup_normalizes_queued_weekly_refresh(self, monkeypatch):
        """A queued weekly state becomes waiting after a restart."""
        monkeypatch.setattr(comicarr, "SCHED_WEEKLY_LAST", None)
        monkeypatch.setattr(comicarr, "WEEKLY_STATUS", "Waiting")
        monkeypatch.setattr(
            system_service.db,
            "select_all",
            lambda statement: [
                {
                    "JobName": "Weekly Pullist",
                    "status": "Queued",
                    "prev_run_timestamp": 200.0,
                    "last_success_timestamp": 100.0,
                }
            ],
        )

        with patch.object(system_service.db, "upsert") as upsert:
            result = system_service.job_management(startup=True)

        assert result["weekly"] == {"last": 100.0, "status": "Waiting"}
        upsert.assert_called_once_with("jobhistory", {"status": "Waiting"}, {"JobName": "Weekly Pullist"})

    def test_startup_marks_every_running_acquisition_job_interrupted(self, monkeypatch):
        monkeypatch.setattr(comicarr, "SCHED_SEARCH_LAST", None)
        monkeypatch.setattr(comicarr, "SEARCH_STATUS", "Waiting")
        monkeypatch.setattr(
            system_service.db,
            "select_all",
            lambda statement: [
                {
                    "JobName": "Auto-Search",
                    "status": "Running",
                    "prev_run_timestamp": 300.0,
                    "last_success_timestamp": 100.0,
                }
            ],
        )

        with patch.object(system_service.db, "upsert") as upsert:
            result = system_service.job_management(startup=True)

        assert result["search"] == {"last": 300.0, "status": "Waiting"}
        values = upsert.call_args.args[1]
        assert values["status"] == "Interrupted"
        assert values["last_failure_timestamp"] == 300.0
        assert values["last_error"] == "Previous Auto-Search run was interrupted by restart."

    def test_sanitize_job_error_redacts_credentials(self):
        message = system_service.sanitize_job_error(
            "token=secret {'apikey': 'quoted-api-secret'} Authorization: Bearer bearer-secret "
            "https://user:pass@example.test failed"
        )

        assert "secret" not in message
        assert "quoted-api-secret" not in message
        assert "bearer-secret" not in message
        assert "user:pass" not in message
        assert "[redacted]" in message

    def test_get_version_info(self):
        """get_version_info returns version data from context."""
        ctx = _make_test_ctx(current_version="0.6.0", install_type="git")

        result = system_service.get_version_info(ctx)
        assert result["current_version"] == "0.6.0"
        assert result["install_type"] == "git"

    def test_get_version_info_includes_truthful_build_identity(self, monkeypatch):
        monkeypatch.setenv("COMICARR_BUILD_ID", "synology-20260710")
        monkeypatch.setenv("COMICARR_BUILD_COMMIT", "abc1234")
        ctx = _make_test_ctx(current_version="0.18.9", current_version_name="v0.18.9")

        result = system_service.get_version_info(ctx)

        assert result["build"] == {
            "id": "synology-20260710",
            "commit": "abc1234",
            "release": "v0.18.9",
            "version": "0.18.9",
            "source": "environment",
            "verified": True,
        }

    def test_runtime_fallback_build_identity_is_never_marked_verified(self, monkeypatch):
        monkeypatch.delenv("COMICARR_BUILD_ID", raising=False)
        monkeypatch.delenv("COMICARR_BUILD_COMMIT", raising=False)
        ctx = _make_test_ctx(
            current_version="a1b2c3d4e5f6",
            current_version_name="v0.18.9",
        )

        build = system_service.get_build_identity(ctx)

        assert build == {
            "id": "v0.18.9",
            "commit": "a1b2c3d4e5f6",
            "release": "v0.18.9",
            "version": "a1b2c3d4e5f6",
            "source": "runtime",
            "verified": False,
        }


class _JsonRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class TestConfigRouter:
    @pytest.mark.asyncio
    async def test_update_providers_maps_persistence_failure_to_server_error(self):
        failure = {"success": False, "error": "Failed to persist provider configuration"}
        request = _JsonRequest({"type": "newznab", "providers": []})

        with patch.object(system_router.system_service, "update_providers", return_value=failure):
            response = await system_router.update_providers(request, _make_test_ctx())

        assert response.status_code == 500
        assert json.loads(response.body) == failure

    @pytest.mark.asyncio
    async def test_update_providers_maps_validation_failure_to_bad_request(self):
        failure = {"success": False, "error": "Invalid provider type"}
        request = _JsonRequest({"type": "invalid", "providers": []})

        with patch.object(system_router.system_service, "update_providers", return_value=failure):
            response = await system_router.update_providers(request, _make_test_ctx())

        assert response.status_code == 400
        assert json.loads(response.body) == failure

    @pytest.mark.asyncio
    async def test_setup_returns_server_error_when_persistence_fails(self):
        """The setup endpoint distinguishes storage failure from invalid input."""
        ctx = _make_test_ctx(setup_token="setup-token")
        failure = {"success": False, "error": "Failed to persist initial credentials"}
        request = _JsonRequest(
            {
                "username": "admin",
                "password": "password123",
                "setup_token": "setup-token",
            }
        )

        with patch.object(system_router.system_service, "initial_setup", return_value=failure):
            response = await system_router.setup(request, ctx)

        assert response.status_code == 500
        assert json.loads(response.body) == failure

    @pytest.mark.asyncio
    async def test_setup_returns_bad_request_for_validation_failure(self):
        """Client-input failures remain HTTP 400, not 500."""
        ctx = _make_test_ctx(setup_token="setup-token")
        failure = {"success": False, "error": "Password must be at least 8 characters"}
        request = _JsonRequest(
            {
                "username": "admin",
                "password": "short",
                "setup_token": "setup-token",
            }
        )

        with patch.object(system_router.system_service, "initial_setup", return_value=failure):
            response = await system_router.setup(request, ctx)

        assert response.status_code == 400
        assert json.loads(response.body) == failure

    @pytest.mark.asyncio
    async def test_update_config_returns_server_error_when_persistence_fails(self):
        """The settings endpoint must not report HTTP success for a failed write."""
        ctx = _make_test_ctx()
        failure = {"success": False, "error": "Failed to persist configuration"}

        with patch.object(system_router.system_service, "update_config", return_value=failure):
            response = await system_router.update_config(_JsonRequest({"comic_dir": "/new/path"}), ctx)

        assert response.status_code == 500
        assert json.loads(response.body) == failure

    @pytest.mark.asyncio
    async def test_update_config_returns_bad_request_for_validation_failure(self):
        """Invalid settings payloads keep the 400 contract separate from storage errors."""
        ctx = _make_test_ctx()
        failure = {"success": False, "error": "No valid config keys provided"}

        with patch.object(system_router.system_service, "update_config", return_value=failure):
            response = await system_router.update_config(_JsonRequest({"api_key": "hacked"}), ctx)

        assert response.status_code == 400
        assert json.loads(response.body) == failure


def _make_real_config(tmp_path, monkeypatch):
    """Build a real Config with an isolated parser and no configure side effects."""
    from comicarr import config as config_module
    from comicarr import encrypted as encrypted_module

    config_path = tmp_path / "config.ini"
    config_path.write_text("")
    secure_dir = tmp_path / "secure"
    secure_dir.mkdir()

    monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
    monkeypatch.setattr(encrypted_module, "_fernet_instance", None)

    cfg = config_module.Config(str(config_path))
    cfg.config_vals()
    cfg.SECURE_DIR = str(secure_dir)
    config_module.config.set("General", "secure_dir", str(secure_dir))
    cfg.provider_sequence = MagicMock()
    cfg.write_out_provider_searches = MagicMock()
    monkeypatch.setattr(comicarr, "CONFIG", cfg)
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    return cfg, config_path, config_module


def _symlink_or_skip(link_path, target_path):
    try:
        link_path.symlink_to(target_path)
    except (OSError, NotImplementedError) as e:
        pytest.skip("symlinks unavailable: %s" % e)


class TestConfigTransactions:
    @pytest.mark.parametrize(
        ("config_version", "entry_width", "entry_count"),
        ((15, 6, 7), (10, 7, 6)),
    )
    def test_ambiguous_flat_provider_count_uses_structural_width(self, config_version, entry_width, entry_count):
        """A 42-field legacy payload never shifts API keys into another column."""
        from comicarr import config as config_module

        entries = []
        for index in range(entry_count):
            entry = [
                f"Provider {index}",
                f"https://provider-{index}.test",
                "1",
                f"secret-{index}",
                "5030",
                "1",
            ]
            if entry_width == 7:
                entry.append(100 + index)
            entries.append(entry)

        parsed = config_module.parse_provider_extras(
            ", ".join(str(field) for row in entries for field in row), config_version
        )

        assert len(parsed) == entry_count
        assert all(len(entry) == entry_width for entry in parsed)
        assert [entry[3] for entry in parsed] == [f"secret-{index}" for index in range(entry_count)]

    def test_config_read_encrypts_plaintext_provider_before_projection(self, tmp_path, monkeypatch):
        from comicarr import config as config_module
        from comicarr import encrypted as encrypted_module

        secure_dir = tmp_path / "secure"
        secure_dir.mkdir()
        config_path = tmp_path / "config.ini"
        parser = configparser.ConfigParser()
        parser["General"] = {
            "config_version": "15",
            "minimal_ini": "False",
            "secure_dir": str(secure_dir),
        }
        parser["Newznab"] = {"extra_newznabs": "Legacy, https://legacy.test, 1, startup-secret, 5030, 1"}
        parser["Torznab"] = {"extra_torznabs": ""}
        with open(config_path, "w") as config_file:
            parser.write(config_file)

        monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
        monkeypatch.setattr(encrypted_module, "_fernet_instance", None)
        monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
        cfg = config_module.Config(str(config_path))
        monkeypatch.setattr(comicarr, "CONFIG", cfg)
        projections = []

        def project_providers():
            projections.append((cfg.EXTRA_NEWZNABS[0][3], config_path.read_text()))

        cfg.provider_sequence = MagicMock(side_effect=project_providers)
        cfg.configure = MagicMock()

        assert cfg.read(startup=False) is cfg

        assert projections
        assert all(runtime_key == "startup-secret" for runtime_key, _file_text in projections)
        assert all("startup-secret" not in file_text for _runtime_key, file_text in projections)
        assert "gAAAAA" in config_path.read_text()

    def test_config_read_fails_closed_when_plaintext_provider_migration_cannot_replace(self, tmp_path, monkeypatch):
        """Startup never continues while a plaintext provider key remains on disk."""
        from comicarr import config as config_module
        from comicarr import encrypted as encrypted_module

        secure_dir = tmp_path / "secure"
        secure_dir.mkdir()
        config_path = tmp_path / "config.ini"
        config_path.write_text(
            "[General]\nconfig_version = 15\nminimal_ini = False\nsecure_dir = %s\n"
            "[Newznab]\nextra_newznabs = Legacy, https://legacy.test, 1, startup-secret, 5030, 1\n"
            "[Torznab]\nextra_torznabs =\n" % secure_dir
        )
        monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
        monkeypatch.setattr(encrypted_module, "_fernet_instance", None)
        monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
        cfg = config_module.Config(str(config_path))
        cfg.configure = MagicMock()
        cfg.provider_sequence = MagicMock()
        cfg._atomic_replace_file = MagicMock(side_effect=OSError("read-only config"))

        with pytest.raises(OSError, match="encrypted provider credentials"):
            cfg.read(startup=False)

        assert "startup-secret" in config_path.read_text()
        cfg.provider_sequence.assert_not_called()

    def test_preupgrade_backup_never_copies_plaintext_provider_key(self, tmp_path, monkeypatch):
        from comicarr import config as config_module
        from comicarr import encrypted as encrypted_module

        secure_dir = tmp_path / "secure"
        backup_dir = tmp_path / "backup"
        secure_dir.mkdir()
        backup_dir.mkdir()
        config_path = tmp_path / "config.ini"
        secret = "preupgrade-provider-secret"
        config_path.write_text(
            "[General]\nconfig_version = 14\nminimal_ini = False\nsecure_dir = %s\n"
            "[Backup]\nbackup_location = %s\nbackup_retention = 2\n"
            "[Newznab]\nextra_newznabs = Legacy, https://legacy.test, 1, %s, 5030, 1, 301\n"
            "[Torznab]\nextra_torznabs =\n" % (secure_dir, backup_dir, secret)
        )
        historical_backup = backup_dir / "config.ini-v13.backup"
        historical_backup.write_text(
            "[General]\nconfig_version = 13\n"
            "[Newznab]\nextra_newznabs = Old, https://old.test, 1, %s, 5030, 1, 300\n"
            "[Torznab]\nextra_torznabs =\n" % secret
        )
        monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
        monkeypatch.setattr(encrypted_module, "_fernet_instance", None)
        monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(comicarr, "CONFIG_FILE", str(config_path))
        cfg = config_module.Config(str(config_path))
        monkeypatch.setattr(comicarr, "CONFIG", cfg)
        cfg.provider_sequence = MagicMock()
        cfg.write_out_provider_searches = MagicMock()
        cfg.configure = MagicMock()

        assert cfg.read(startup=False) is cfg

        backup_files = list(backup_dir.glob("config.ini-v*.backup*"))
        assert backup_files
        assert secret not in config_path.read_text()
        assert all(secret not in backup.read_text() for backup in backup_files)
        assert all("gAAAAA" in backup.read_text() for backup in backup_files)

    def test_startup_rejects_malformed_legacy_provider_token_without_rewrite(self, tmp_path, monkeypatch):
        from comicarr import config as config_module
        from comicarr import encrypted as encrypted_module

        secure_dir = tmp_path / "secure"
        secure_dir.mkdir()
        config_path = tmp_path / "config.ini"
        malformed = "^~$z$!!!!"
        config_path.write_text(
            "[General]\nconfig_version = 15\nminimal_ini = False\nsecure_dir = %s\n"
            "[Newznab]\nextra_newznabs = Legacy, https://legacy.test, 1, %s, 5030, 1, 301\n"
            "[Torznab]\nextra_torznabs =\n" % (secure_dir, malformed)
        )
        monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
        monkeypatch.setattr(encrypted_module, "_fernet_instance", None)
        monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
        cfg = config_module.Config(str(config_path))
        cfg.provider_sequence = MagicMock()
        cfg.configure = MagicMock()

        with pytest.raises(ValueError, match="decrypt provider credential"):
            cfg.read(startup=False)

        assert malformed in config_path.read_text()
        cfg.provider_sequence.assert_not_called()

    def test_startup_missing_provider_key_does_not_create_replacement_authority(self, tmp_path, monkeypatch):
        from cryptography.fernet import Fernet

        from comicarr import config as config_module
        from comicarr import encrypted as encrypted_module

        secure_dir = tmp_path / "secure"
        backup_dir = tmp_path / "backup"
        secure_dir.mkdir()
        backup_dir.mkdir()
        token = Fernet(Fernet.generate_key()).encrypt(b"unrecoverable-secret").decode()
        historical_secret = "historical-plaintext-secret"
        config_path = tmp_path / "config.ini"
        config_path.write_text(
            "[General]\nconfig_version = 15\nminimal_ini = False\nsecure_dir = %s\n"
            "[Backup]\nbackup_location = %s\n"
            "[Newznab]\nextra_newznabs = Legacy, https://legacy.test, 1, %s, 5030, 1, 301\n"
            "[Torznab]\nextra_torznabs =\n" % (secure_dir, backup_dir, token)
        )
        historical_backup = backup_dir / "config.ini-v14.backup"
        historical_backup.write_text(
            "[General]\nconfig_version = 14\n"
            "[Newznab]\nextra_newznabs = Old, https://old.test, 1, %s, 5030, 1, 300\n"
            "[Torznab]\nextra_torznabs =\n" % historical_secret
        )
        monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
        monkeypatch.setattr(encrypted_module, "_fernet_instance", None)
        monkeypatch.setattr(encrypted_module, "_fernet_secure_dir", None)
        monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
        cfg = config_module.Config(str(config_path))
        cfg.provider_sequence = MagicMock()
        cfg.configure = MagicMock()

        with pytest.raises(ValueError, match="decrypt provider credential"):
            cfg.read(startup=False)

        assert not (secure_dir / "master.key").exists()
        assert historical_secret in historical_backup.read_text()
        cfg.provider_sequence.assert_not_called()

    def test_startup_missing_scalar_key_blocks_provider_and_backup_rewrites(self, tmp_path, monkeypatch):
        from cryptography.fernet import Fernet

        from comicarr import config as config_module
        from comicarr import encrypted as encrypted_module

        secure_dir = tmp_path / "secure"
        backup_dir = tmp_path / "backup"
        secure_dir.mkdir()
        backup_dir.mkdir()
        scalar_token = Fernet(Fernet.generate_key()).encrypt(b"unrecoverable-comicvine-secret").decode()
        config_path = tmp_path / "config.ini"
        config_path.write_text(
            "[General]\nconfig_version = 15\nminimal_ini = False\nsecure_dir = %s\n"
            "[Backup]\nbackup_location = %s\n"
            "[CV]\ncomicvine_api = %s\n"
            "[Newznab]\nextra_newznabs = Legacy, https://legacy.test, 1, live-plaintext-secret, 5030, 1, 301\n"
            "[Torznab]\nextra_torznabs =\n" % (secure_dir, backup_dir, scalar_token)
        )
        historical_backup = backup_dir / "config.ini-v14.backup"
        historical_backup.write_text(
            "[General]\nconfig_version = 14\n"
            "[Newznab]\nextra_newznabs = Old, https://old.test, 1, backup-plaintext-secret, 5030, 1, 300\n"
            "[Torznab]\nextra_torznabs =\n"
        )
        monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
        monkeypatch.setattr(encrypted_module, "_fernet_instance", None)
        monkeypatch.setattr(encrypted_module, "_fernet_secure_dir", None)
        monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
        cfg = config_module.Config(str(config_path))
        cfg.provider_sequence = MagicMock()
        cfg.configure = MagicMock()

        with pytest.raises(ValueError, match="encrypted configuration authority"):
            cfg.read(startup=False)

        assert not (secure_dir / "master.key").exists()
        assert "live-plaintext-secret" in config_path.read_text()
        assert "backup-plaintext-secret" in historical_backup.read_text()
        cfg.provider_sequence.assert_not_called()

    @pytest.mark.parametrize(
        ("torznab_name", "torznab_id", "error"),
        (("duplicate", 302, "Provider names must be unique"), ("Other", 301, "Provider IDs must be unique")),
    )
    def test_config_read_rejects_persisted_duplicate_provider_identity_before_projection(
        self, tmp_path, monkeypatch, torznab_name, torznab_id, error
    ):
        from comicarr import config as config_module
        from comicarr import encrypted as encrypted_module

        secure_dir = tmp_path / "secure"
        secure_dir.mkdir()
        config_path = tmp_path / "config.ini"
        config_path.write_text(
            "[General]\nconfig_version = 15\nminimal_ini = False\nsecure_dir = %s\n"
            "[Newznab]\nextra_newznabs = Duplicate, https://newz.test, 1, , 5030, 1, 301\n"
            "[Torznab]\nextra_torznabs = %s, https://torz.test, 1, , 5070, 1, %s\n"
            % (secure_dir, torznab_name, torznab_id)
        )
        monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
        monkeypatch.setattr(encrypted_module, "_fernet_instance", None)
        monkeypatch.setattr(encrypted_module, "_fernet_secure_dir", None)
        monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
        cfg = config_module.Config(str(config_path))
        cfg.provider_sequence = MagicMock()
        cfg.configure = MagicMock()

        with pytest.raises(ValueError, match=error):
            cfg.read(startup=False)

        cfg.provider_sequence.assert_not_called()
        cfg.configure.assert_not_called()

    def test_legacy_six_field_plaintext_provider_migrates_once(self, tmp_path, monkeypatch):
        cfg, config_path, config_module = _make_real_config(tmp_path, monkeypatch)
        cfg.CONFIG_VERSION = 10
        cfg.EXTRA_NEWZNABS = "Legacy, https://legacy.test, 1, legacy-secret, 5030, 1"
        cfg.EXTRA_TORZNABS = ""
        cfg.EXTRA_NEWZNABS, cfg.EXTRA_TORZNABS = cfg.get_extras()

        cfg._load_provider_extra_credentials()

        assert cfg.WRITE_THE_CONFIG is True
        assert cfg.EXTRA_NEWZNABS[0][3] == "legacy-secret"
        assert len(cfg.EXTRA_NEWZNABS[0]) == 7

        cfg.CONFIG_VERSION = 15
        config_module.config.set("General", "config_version", "15")
        cfg.provider_sequence = MagicMock()
        assert cfg.writeconfig(startup=True) is True
        first = configparser.ConfigParser()
        first.read(config_path)
        first_storage = first.get("Newznab", "extra_newznabs")
        first_entries = config_module.parse_provider_extras(first_storage, config_version=15)
        assert first_entries[0][3].startswith("gAAAAA")
        assert "legacy-secret" not in first_storage

        assert cfg.writeconfig(startup=True) is True
        second = configparser.ConfigParser()
        second.read(config_path)
        assert second.get("Newznab", "extra_newznabs") == first_storage
        assert cfg.EXTRA_NEWZNABS[0][3] == "legacy-secret"

    def test_provider_transaction_encrypts_at_rest_and_reloads_plaintext(self, tmp_path, monkeypatch):
        cfg, config_path, config_module = _make_real_config(tmp_path, monkeypatch)
        encrypted_module = config_module.encrypted
        monkeypatch.setattr(encrypted_module, "_fernet_instance", None)
        existing_token = encrypted_module.Encryptor(
            "existing-secret",
            secure_dir=cfg.SECURE_DIR,
        ).encrypt_it()["password"]
        cfg.configure = MagicMock()
        cfg.provider_sequence = MagicMock()
        newznabs = [
            ["Plain", "https://plain.test", "1", "plain-secret", "5030,5040", "1", 201],
            ["Encrypted", "https://encrypted.test", "1", existing_token, "5070", "1", 202],
            ["Empty", "https://empty.test", "1", "", "5000", "0", 203],
        ]
        torznabs = [["Legacy width", "https://tor.test", "1", "tor-secret", "5070", "1"]]

        assert (
            cfg.apply_transaction(
                {
                    "EXTRA_NEWZNABS": newznabs,
                    "EXTRA_TORZNABS": torznabs,
                }
            )
            is True
        )
        cfg.configure.assert_not_called()

        persisted = configparser.ConfigParser()
        persisted.read(config_path)
        persisted_newznabs = config_module.parse_provider_extras(
            persisted.get("Newznab", "extra_newznabs"),
            config_version=cfg.CONFIG_VERSION,
        )
        persisted_torznabs = config_module.parse_provider_extras(
            persisted.get("Torznab", "extra_torznabs"),
            config_version=cfg.CONFIG_VERSION,
        )
        assert persisted_newznabs[0][3].startswith("gAAAAA")
        assert persisted_newznabs[1][3] == existing_token
        assert persisted_newznabs[2][3] == ""
        assert persisted_newznabs[0][0:3] == ("Plain", "https://plain.test", "1")
        assert persisted_newznabs[0][4:] == ("5030#5040", "1", "201")
        assert persisted_torznabs[0][3].startswith("gAAAAA")
        assert len(persisted_torznabs[0]) == 7
        assert "plain-secret" not in config_path.read_text()
        assert "existing-secret" not in config_path.read_text()
        assert "tor-secret" not in config_path.read_text()

        first_newznab_storage = persisted.get("Newznab", "extra_newznabs")
        first_torznab_storage = persisted.get("Torznab", "extra_torznabs")
        monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
        monkeypatch.setattr(encrypted_module, "_fernet_instance", None)
        fresh = config_module.Config(str(config_path))
        fresh.config_vals()
        fresh.EXTRA_NEWZNABS, fresh.EXTRA_TORZNABS = fresh.get_extras()
        fresh._load_provider_extra_credentials()

        assert [entry[3] for entry in fresh.EXTRA_NEWZNABS] == ["plain-secret", "existing-secret", ""]
        assert fresh.EXTRA_TORZNABS[0][3] == "tor-secret"
        assert len(fresh.EXTRA_TORZNABS[0]) == 7
        assert fresh.WRITE_THE_CONFIG is False

        fresh.provider_sequence = MagicMock()
        assert fresh.writeconfig(startup=True) is True
        second = configparser.ConfigParser()
        second.read(config_path)
        assert second.get("Newznab", "extra_newznabs") == first_newznab_storage
        assert second.get("Torznab", "extra_torznabs") == first_torznab_storage

    def test_provider_transaction_persists_reconciled_order_in_same_write(self, tmp_path, monkeypatch):
        cfg, config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        cfg.configure = MagicMock()
        cfg.NEWZNAB = True
        cfg.PROVIDER_ORDER = None
        providers = [
            ["First", "https://first.test", "1", "first-secret", "5030", "1", 201],
            ["Second", "https://second.test", "1", "second-secret", "5030", "1", 202],
        ]

        assert cfg.apply_transaction({"EXTRA_NEWZNABS": providers}) is True

        persisted = configparser.ConfigParser()
        persisted.read(config_path)
        assert persisted.get("Providers", "provider_order") == "0, First, 1, Second"
        assert cfg.PROVIDER_ORDER == {"0": "First", "1": "Second"}

        cfg.PROVIDER_ORDER = {"0": "Second", "1": "First"}
        assert cfg.apply_transaction({"EXTRA_NEWZNABS": providers[1:]}) is True
        persisted.read(config_path)
        assert persisted.get("Providers", "provider_order") == "0, Second"
        assert cfg.PROVIDER_ORDER == {"0": "Second"}

    def test_failed_provider_write_never_publishes_candidate_to_concurrent_reader(self, tmp_path, monkeypatch):
        cfg, _config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        cfg.configure = MagicMock()
        old_providers = [("Old", "https://old.test", "1", "old-secret", "5030", "1", 100)]
        new_providers = [["New", "https://new.test", "1", "new-secret", "5030", "1", 101]]
        cfg.EXTRA_NEWZNABS = old_providers
        entered_write = threading.Event()
        release_write = threading.Event()
        result = []

        def fail_after_reader_observes(_target, _mode, _write_content, binary=False):
            assert binary is False
            entered_write.set()
            assert release_write.wait(timeout=2)
            raise OSError("replace failed")

        cfg._atomic_replace_file = fail_after_reader_observes
        worker = threading.Thread(
            target=lambda: result.append(cfg.apply_transaction({"EXTRA_NEWZNABS": new_providers}))
        )
        worker.start()
        assert entered_write.wait(timeout=2)
        assert cfg.EXTRA_NEWZNABS is old_providers
        release_write.set()
        worker.join(timeout=2)

        assert result == [False]
        assert cfg.EXTRA_NEWZNABS == old_providers

    def test_provider_projection_rolls_back_all_rows_when_later_upsert_fails(self, tmp_path, monkeypatch):
        from sqlalchemy import create_engine, select

        from comicarr import db as db_module
        from comicarr.tables import provider_searches

        engine = create_engine("sqlite:///:memory:")
        provider_searches.create(engine)
        monkeypatch.setattr(db_module, "_engine", engine)
        cfg, _config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        del cfg.write_out_provider_searches
        providers = [
            ("First", "https://first.test", "1", "secret-1", "5030", "1", 201),
            ("Second", "https://second.test", "1", "secret-2", "5030", "1", 202),
        ]
        real_upsert = db_module.upsert_conn
        calls = 0

        def fail_second_upsert(conn, table_name, values, controls):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("second projection failed")
            real_upsert(conn, table_name, values, controls)

        monkeypatch.setattr(db_module, "upsert_conn", fail_second_upsert)

        with pytest.raises(RuntimeError, match="second projection failed"):
            cfg.write_out_provider_searches(
                provider_order={"0": "First", "1": "Second"},
                extra_newznabs=providers,
                extra_torznabs=[],
            )

        with engine.connect() as conn:
            assert conn.execute(select(provider_searches)).all() == []
        engine.dispose()

    def test_provider_projection_tolerates_stale_rows_skips_32p_and_refreshes_identity(self, tmp_path, monkeypatch):
        from sqlalchemy import create_engine, select

        from comicarr import db as db_module
        from comicarr.tables import provider_searches

        engine = create_engine("sqlite:///:memory:")
        provider_searches.create(engine)
        with engine.begin() as conn:
            conn.execute(
                provider_searches.insert(),
                [
                    {
                        "id": 0,
                        "provider": "Removed",
                        "type": "newznab",
                        "lastrun": 1,
                        "active": False,
                        "hits": 2,
                    },
                    {
                        "id": 300,
                        "provider": "Reused",
                        "type": "newznab",
                        "lastrun": 3,
                        "active": True,
                        "hits": 4,
                    },
                    {
                        "id": 302,
                        "provider": "Stale",
                        "type": "newznab",
                        "lastrun": 5,
                        "active": True,
                        "hits": 6,
                    },
                ],
            )
        monkeypatch.setattr(db_module, "_engine", engine)
        cfg, _config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        del cfg.write_out_provider_searches
        torznabs = [("Reused", "https://reused.test", "1", "secret", "5070", "1", 301)]
        newznabs = [("New", "https://new.test", "1", "secret", "5030", "1", 302)]

        cfg.write_out_provider_searches(
            provider_order={"0": "32p", "1": "Reused", "2": "New"},
            extra_newznabs=newznabs,
            extra_torznabs=torznabs,
        )

        with engine.connect() as conn:
            rows = {row.provider: row for row in conn.execute(select(provider_searches))}
        assert rows["Removed"].id == 0
        assert rows["Reused"].id == 301
        assert rows["Reused"].type == "torznab"
        assert rows["Reused"].lastrun == 3
        assert rows["New"].id == 302
        assert rows["New"].lastrun == 0
        assert "Stale" not in rows
        assert "32p" not in rows
        engine.dispose()

    @pytest.mark.parametrize("collision", ("cross-list", "reserved", "duplicate-name"))
    def test_provider_transaction_rejects_global_id_collisions(self, tmp_path, monkeypatch, collision):
        cfg, config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        cfg.configure = MagicMock()
        newznabs = [["Newz", "https://newz.test", "1", "secret", "5030", "1", 301]]
        values = {"EXTRA_NEWZNABS": newznabs}
        if collision == "cross-list":
            values["EXTRA_TORZNABS"] = [["Torz", "https://torz.test", "1", "secret", "5070", "1", 301]]
        elif collision == "duplicate-name":
            values["EXTRA_TORZNABS"] = [["newz", "https://torz.test", "1", "secret", "5070", "1", 302]]
        else:
            cfg.EXPERIMENTAL = True
            newznabs[0][6] = 101
        original_file = config_path.read_bytes()
        original_runtime = cfg.EXTRA_NEWZNABS

        assert cfg.apply_transaction(values) is False

        assert config_path.read_bytes() == original_file
        assert cfg.EXTRA_NEWZNABS == original_runtime
        cfg.configure.assert_not_called()

    def test_provider_transaction_rolls_back_before_projection_on_write_failure(self, tmp_path, monkeypatch):
        cfg, config_path, config_module = _make_real_config(tmp_path, monkeypatch)
        provider_events = []
        cfg.configure = MagicMock()
        cfg.write_out_provider_searches = MagicMock(side_effect=lambda **_kwargs: provider_events.append("projected"))
        old_providers = [["Old", "https://old.test", "1", "old-secret", "5030", "1", 100]]
        new_providers = [["New", "https://new.test", "1", "new-secret", "5030", "1", 101]]
        assert cfg.apply_transaction({"EXTRA_NEWZNABS": old_providers}) is True
        original_file = config_path.read_bytes()
        original_runtime = cfg.EXTRA_NEWZNABS
        cfg.configure.reset_mock()
        cfg.write_out_provider_searches.reset_mock()
        provider_events.clear()
        real_replace = config_module.os.replace

        def fail_config_replace(source, destination):
            if config_module.Path(destination) == config_path:
                raise OSError("replace failed")
            return real_replace(source, destination)

        monkeypatch.setattr(config_module.os, "replace", fail_config_replace)

        assert cfg.apply_transaction({"EXTRA_NEWZNABS": new_providers}) is False

        assert cfg.EXTRA_NEWZNABS == original_runtime
        assert config_path.read_bytes() == original_file
        cfg.configure.assert_not_called()
        assert provider_events == []

    @pytest.mark.parametrize(
        "providers",
        (
            [["Too short", "https://short.test", "1"]],
            [["Bad token", "https://bad.test", "1", "gAAAAA-invalid", "5030", "1", 100]],
            [["Bad legacy token", "https://bad.test", "1", "^~$z$!!!!", "5030", "1", 100]],
            "not-a-provider-list",
        ),
    )
    def test_provider_transaction_rejects_malformed_entries_without_mutation(self, tmp_path, monkeypatch, providers):
        cfg, config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        cfg.configure = MagicMock()
        original_file = config_path.read_bytes()
        original_runtime = cfg.EXTRA_NEWZNABS

        assert cfg.apply_transaction({"EXTRA_NEWZNABS": providers}) is False

        assert cfg.EXTRA_NEWZNABS == original_runtime
        assert config_path.read_bytes() == original_file
        cfg.configure.assert_not_called()

    def test_legacy_cherrypy_logging_setting_is_ignored_but_preserved(self, tmp_path, monkeypatch):
        cfg, config_path, config_module = _make_real_config(tmp_path, monkeypatch)
        if not config_module.config.has_section("Interface"):
            config_module.config.add_section("Interface")
        config_module.config.set("Interface", "cherrypy_logging", "True")

        cfg.config_vals()

        assert not hasattr(cfg, "CHERRYPY_LOGGING")
        assert cfg.writeconfig() is True

        persisted = configparser.ConfigParser()
        persisted.read(config_path)
        assert persisted.getboolean("Interface", "cherrypy_logging") is True

    def test_locked_scalar_write_does_not_reproject_provider_database(self, tmp_path, monkeypatch):
        """Unrelated settings writes do not add provider database side effects."""
        cfg, _config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        events = []
        original_process = cfg.process_kwargs

        def tracked_process(values):
            events.append("process")
            original_process(values)

        def tracked_atomic_replace(_target, _mode, _write_content, binary=False):
            assert binary is False
            events.append("write")

        cfg.process_kwargs = tracked_process
        cfg.write_out_provider_searches = MagicMock(side_effect=lambda **_kwargs: events.append("provider_projection"))
        cfg._atomic_replace_file = tracked_atomic_replace

        assert cfg.writeconfig_values({"COMIC_DIR": "/ordered/library"}) is True

        assert cfg.COMIC_DIR == "/ordered/library"
        assert events == ["process", "write"]

    def test_writeconfig_values_restores_runtime_when_write_fails(self, tmp_path, monkeypatch):
        """Failed value writes must not leave process_kwargs mutations in memory."""
        cfg, _config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        original_dir = cfg.COMIC_DIR

        def fail_write(*_args, **_kwargs):
            raise OSError("simulated replace failure")

        cfg._atomic_replace_file = fail_write

        assert cfg.writeconfig_values({"COMIC_DIR": "/should-not-stick"}) is False
        assert cfg.COMIC_DIR == original_dir

    def test_incomplete_file_restore_halts_further_writes(self, tmp_path, monkeypatch):
        """After a durable write, failed file restore blocks subsequent config writes."""
        cfg, config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        original_dir = cfg.COMIC_DIR
        cfg.configure = MagicMock(side_effect=RuntimeError("configure boom"))

        real_restore_state = cfg._restore_transaction_state

        def restore_state_ok(*args, **kwargs):
            return real_restore_state(*args, **kwargs)

        def restore_file_fail(*_args, **_kwargs):
            raise OSError("simulated file restore failure")

        cfg._restore_transaction_state = restore_state_ok
        cfg._restore_config_file = restore_file_fail

        assert cfg.apply_transaction({"COMIC_DIR": "/new/library"}) is False
        assert getattr(cfg, "_config_write_halted", False) is True
        assert cfg.COMIC_DIR == original_dir
        assert cfg.apply_transaction({"COMIC_DIR": "/another/library"}) is False
        assert cfg.writeconfig() is False

    def test_transaction_encrypts_disk_secret_and_keeps_runtime_decrypted(self, tmp_path, monkeypatch):
        """A successful settings write persists ciphertext before configure runs."""
        cfg, config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        events = []
        original_write = cfg.writeconfig

        def tracked_write():
            events.append("write")
            return original_write()

        cfg.writeconfig = MagicMock(side_effect=tracked_write)
        cfg.configure = MagicMock(side_effect=lambda **_kwargs: events.append("configure"))
        secret = "transaction-test-secret"

        assert cfg.apply_transaction({"AI_API_KEY": secret}) is True

        persisted = configparser.ConfigParser()
        persisted.read(config_path)
        persisted_secret = persisted.get("AI", "ai_api_key")
        assert persisted_secret.startswith("gAAAAA")
        assert secret not in config_path.read_text()
        assert cfg.AI_API_KEY == secret
        assert cfg.ENCRYPT_PASSWORDS is True
        assert events == ["write", "configure"]
        cfg.writeconfig.assert_called_once_with()

    def test_transaction_preserves_existing_config_file_mode(self, tmp_path, monkeypatch):
        """Atomic replacement retains the permissions of an existing config file."""
        cfg, config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        os.chmod(config_path, 0o640)
        cfg.configure = MagicMock()

        assert cfg.apply_transaction({"COMIC_DIR": "/new/library"}) is True

        assert stat.S_IMODE(config_path.stat().st_mode) == 0o640

    def test_transaction_creates_new_config_file_with_private_mode(self, tmp_path, monkeypatch):
        """A first durable config write creates config.ini with mode 0600."""
        cfg, config_path, config_module = _make_real_config(tmp_path, monkeypatch)
        config_path.unlink()
        cfg.configure = MagicMock()
        replaced_modes = []
        real_replace = os.replace

        def checked_replace(source, destination):
            if config_module.Path(destination) == config_path:
                replaced_modes.append(stat.S_IMODE(os.stat(source).st_mode))
            real_replace(source, destination)

        monkeypatch.setattr(config_module.os, "replace", checked_replace)

        assert cfg.apply_transaction({"COMIC_DIR": "/new/library"}) is True

        assert replaced_modes == [0o600]
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    def test_normal_write_ignores_hostile_predictable_temp_symlink(self, tmp_path, monkeypatch):
        """A pre-created legacy .tmp symlink cannot redirect config output."""
        cfg, config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        victim = tmp_path / "victim.txt"
        victim.write_text("untouched")
        predictable_temp = tmp_path / "config.ini.tmp"
        _symlink_or_skip(predictable_temp, victim)
        cfg.configure = MagicMock()

        assert cfg.apply_transaction({"COMIC_DIR": "/new/library"}) is True

        assert victim.read_text() == "untouched"
        assert predictable_temp.is_symlink()
        assert config_path.is_file()

    def test_rollback_ignores_hostile_predictable_temp_symlink(self, tmp_path, monkeypatch):
        """A pre-created legacy .rollback symlink cannot redirect rollback output."""
        cfg, config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        cfg.process_kwargs({"COMIC_DIR": "/old/library"})
        assert cfg.writeconfig() is True
        victim = tmp_path / "victim.txt"
        victim.write_text("untouched")
        predictable_rollback = tmp_path / "config.ini.rollback"
        _symlink_or_skip(predictable_rollback, victim)
        cfg.configure = MagicMock(side_effect=RuntimeError("configure failed"))

        assert cfg.apply_transaction({"COMIC_DIR": "/new/library"}) is False

        assert victim.read_text() == "untouched"
        assert predictable_rollback.is_symlink()
        assert config_path.is_file()

    def test_transaction_preserves_config_symlink_identity(self, tmp_path, monkeypatch):
        """Atomic updates replace a symlink's target without replacing the link itself."""
        cfg, config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        cfg.process_kwargs({"COMIC_DIR": "/old/library"})
        assert cfg.writeconfig() is True
        target_path = tmp_path / "real-config.ini"
        config_path.replace(target_path)
        _symlink_or_skip(config_path, target_path)
        cfg.configure = MagicMock()

        assert cfg.apply_transaction({"COMIC_DIR": "/new/library"}) is True

        assert config_path.is_symlink()
        persisted = configparser.ConfigParser()
        persisted.read(target_path)
        assert persisted.get("Import", "comic_dir") == "/new/library"

    def test_unique_temp_is_cleaned_after_replace_failure(self, tmp_path, monkeypatch):
        """A failed replace removes only the exclusive temp created for that write."""
        cfg, config_path, config_module = _make_real_config(tmp_path, monkeypatch)
        replacement_sources = []
        real_replace = os.replace

        def failing_replace(source, destination):
            if config_module.Path(destination) == config_path:
                replacement_sources.append(config_module.Path(source))
                raise OSError("replace failed")
            real_replace(source, destination)

        monkeypatch.setattr(config_module.os, "replace", failing_replace)

        assert cfg.writeconfig(values={"COMIC_DIR": "/new/library"}) is False

        assert len(replacement_sources) == 1
        created_temp = replacement_sources[0]
        assert created_temp.name.startswith(".comicarr-config-")
        assert len(created_temp.name) <= 64
        assert not created_temp.exists()

    @pytest.mark.parametrize("fchmod_behavior", ["missing", "not-implemented"])
    def test_config_write_falls_back_when_fchmod_unavailable(self, tmp_path, monkeypatch, fchmod_behavior):
        """Platforms without fchmod still persist through a chmod fallback."""
        cfg, config_path, config_module = _make_real_config(tmp_path, monkeypatch)
        config_path.unlink()
        cfg.configure = MagicMock()
        if fchmod_behavior == "missing":
            monkeypatch.setattr(config_module.os, "fchmod", None)
        else:
            monkeypatch.setattr(
                config_module.os,
                "fchmod",
                MagicMock(side_effect=NotImplementedError),
            )

        assert cfg.apply_transaction({"COMIC_DIR": "/new/library"}) is True
        assert config_path.is_file()
        if os.name != "nt":
            assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    def test_transaction_restores_parser_runtime_and_file_after_write_failure(self, tmp_path, monkeypatch):
        """A failed atomic write rolls every staged config representation back."""
        cfg, config_path, config_module = _make_real_config(tmp_path, monkeypatch)
        cfg.process_kwargs({"COMIC_DIR": "/old/library"})
        original_file = config_path.read_bytes()
        writer = MagicMock(return_value=False)
        configure = MagicMock()
        cfg.writeconfig = writer
        cfg.configure = configure

        assert cfg.apply_transaction({"COMIC_DIR": "/new/library"}) is False

        assert cfg.COMIC_DIR == "/old/library"
        assert config_module.config.get("Import", "comic_dir") == "/old/library"
        assert config_path.read_bytes() == original_file
        writer.assert_called_once_with()
        configure.assert_not_called()

    def test_transaction_does_not_write_when_secret_encryption_fails(self, tmp_path, monkeypatch):
        """Plaintext secrets never reach the writer when encryption cannot complete."""
        cfg, config_path, config_module = _make_real_config(tmp_path, monkeypatch)
        writer = MagicMock(return_value=True)
        cfg.writeconfig = writer
        cfg.configure = MagicMock()
        cfg.encrypt_items = MagicMock()

        assert cfg.apply_transaction({"AI_API_KEY": "unpersisted-test-secret"}) is False

        assert cfg.AI_API_KEY is None
        assert config_module.config.get("AI", "ai_api_key") == "None"
        assert "unpersisted-test-secret" not in config_path.read_text()
        writer.assert_not_called()
        cfg.configure.assert_not_called()

    def test_unrelated_transaction_keeps_git_auth_tuple_flat(self, tmp_path, monkeypatch):
        """Repeated configure normalization keeps requests auth as a two-string tuple."""
        cfg, _config_path, _config_module = _make_real_config(tmp_path, monkeypatch)
        cfg.GIT_TOKEN = ("git-token", "x-oauth-basic")
        cfg.configure = MagicMock(side_effect=lambda **_kwargs: cfg._normalize_git_token_auth())

        assert cfg.apply_transaction({"COMIC_DIR": "/new/library"}) is True

        assert cfg.GIT_TOKEN == ("git-token", "x-oauth-basic")
        assert all(isinstance(part, str) for part in cfg.GIT_TOKEN)

    def test_transaction_restores_durable_file_when_configure_fails(self, tmp_path, monkeypatch):
        """A post-write configure failure restores the last durable configuration."""
        cfg, config_path, config_module = _make_real_config(tmp_path, monkeypatch)
        cfg.process_kwargs({"COMIC_DIR": "/old/library"})
        assert cfg.writeconfig() is True
        original_file = config_path.read_bytes()
        original_write = cfg.writeconfig
        writer = MagicMock(side_effect=original_write)
        cfg.writeconfig = writer
        cfg.configure = MagicMock(side_effect=RuntimeError("configure failed"))

        assert cfg.apply_transaction({"COMIC_DIR": "/new/library"}) is False

        assert cfg.COMIC_DIR == "/old/library"
        assert config_module.config.get("Import", "comic_dir") == "/old/library"
        assert config_path.read_bytes() == original_file
        writer.assert_called_once_with()

    def test_transaction_restores_state_when_configure_raises_system_exit(self, tmp_path, monkeypatch):
        """SystemExit from legacy configure rolls back, then propagates."""
        cfg, config_path, config_module = _make_real_config(tmp_path, monkeypatch)
        cfg.process_kwargs({"COMIC_DIR": "/old/library"})
        assert cfg.writeconfig() is True
        original_file = config_path.read_bytes()
        cfg.configure = MagicMock(side_effect=SystemExit(1))

        with pytest.raises(SystemExit):
            cfg.apply_transaction({"COMIC_DIR": "/new/library"})

        assert cfg.COMIC_DIR == "/old/library"
        assert config_module.config.get("Import", "comic_dir") == "/old/library"
        assert config_path.read_bytes() == original_file

    def test_direct_writer_waits_for_failed_transaction_rollback(self, tmp_path, monkeypatch):
        """A concurrent direct writer cannot be erased by another transaction's rollback."""
        cfg, config_path, config_module = _make_real_config(tmp_path, monkeypatch)
        cfg.process_kwargs({"COMIC_DIR": "/old/library", "DESTINATION_DIR": "/old/destination"})
        assert cfg.writeconfig() is True

        configure_entered = threading.Event()
        release_configure = threading.Event()
        direct_writer_started = threading.Event()
        direct_writer_done = threading.Event()
        results = {}

        def failing_configure(**_kwargs):
            configure_entered.set()
            assert release_configure.wait(timeout=2)
            raise RuntimeError("configure failed")

        def transactional_writer():
            results["transaction"] = cfg.apply_transaction({"COMIC_DIR": "/transaction/library"})

        def direct_writer():
            direct_writer_started.set()
            results["direct"] = cfg.writeconfig(values={"DESTINATION_DIR": "/direct/destination"})
            direct_writer_done.set()

        cfg.configure = failing_configure
        transaction_thread = threading.Thread(target=transactional_writer)
        direct_thread = threading.Thread(target=direct_writer)
        transaction_thread.start()
        assert configure_entered.wait(timeout=2)
        direct_thread.start()

        try:
            assert direct_writer_started.wait(timeout=2)
            direct_writer_was_blocked = not direct_writer_done.wait(timeout=0.1)
        finally:
            release_configure.set()
            transaction_thread.join(timeout=2)
            direct_thread.join(timeout=2)

        assert direct_writer_was_blocked
        assert not transaction_thread.is_alive()
        assert not direct_thread.is_alive()
        assert results == {"transaction": False, "direct": True}
        assert cfg.COMIC_DIR == "/old/library"
        assert cfg.DESTINATION_DIR == "/direct/destination"
        assert config_module.config.get("Import", "comic_dir") == "/old/library"
        assert config_module.config.get("General", "destination_dir") == "/direct/destination"

        persisted = configparser.ConfigParser()
        persisted.read(config_path)
        assert persisted.get("Import", "comic_dir") == "/old/library"
        assert persisted.get("General", "destination_dir") == "/direct/destination"
