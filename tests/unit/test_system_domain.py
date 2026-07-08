"""
Tests for comicarr.app.system domain — Phase 1.

Covers: auth login/logout, SSE streaming, config endpoints, JWT cookies.
"""

from unittest.mock import MagicMock, call, patch

import comicarr

# Ensure LOG_LEVEL is set for tests (logger.info checks LOG_LEVEL > 0)
if comicarr.LOG_LEVEL is None:
    comicarr.LOG_LEVEL = 0

from comicarr.app.core.context import AppContext
from comicarr.app.core.security import (
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
        ctx.config.process_kwargs.assert_called_once()
        args = ctx.config.process_kwargs.call_args[0][0]
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
        args = ctx.config.process_kwargs.call_args[0][0]
        assert "COMIC_DIR" in args
        assert "API_KEY" not in args

    @patch("comicarr.app.system.service.secrets.token_hex", return_value="a" * 32)
    def test_regenerate_api_key_persists_new_key(self, mock_token_hex):
        """regenerate_api_key creates, persists, and returns a server-side key."""
        ctx = _make_test_ctx()
        result = system_service.regenerate_api_key(ctx)

        assert result == {"success": True, "api_key": "a" * 32}
        assert ctx.config.API_KEY == "a" * 32
        mock_token_hex.assert_called_once_with(16)
        ctx.config.process_kwargs.assert_called_once_with({"api_key": "a" * 32})
        ctx.config.writeconfig.assert_called_once_with()
        ctx.config.configure.assert_called_once_with(update=True, startup=False)

    def test_regenerate_api_key_rejects_missing_config(self):
        """regenerate_api_key fails when config is not loaded."""
        ctx = _make_test_ctx(config=None)
        result = system_service.regenerate_api_key(ctx)
        assert result["success"] is False
        assert result["error"] == "Config not loaded"

    @patch("comicarr.app.system.service.secrets.token_hex", return_value="a" * 32)
    def test_regenerate_api_key_reports_persistence_failure(self, mock_token_hex):
        """regenerate_api_key reports persistence failures through the result contract."""
        ctx = _make_test_ctx()
        ctx.config.configure.side_effect = RuntimeError("cannot reload")

        result = system_service.regenerate_api_key(ctx)

        assert result == {"success": False, "error": "Failed to persist new API key"}
        assert ctx.config.API_KEY == "configured-api-key"
        mock_token_hex.assert_called_once_with(16)
        assert ctx.config.process_kwargs.call_args_list == [
            call({"api_key": "a" * 32}),
            call({"api_key": "configured-api-key"}),
        ]
        assert ctx.config.writeconfig.call_count == 2
        assert ctx.config.configure.call_args_list == [
            call(update=True, startup=False),
            call(update=True, startup=False),
        ]

    @patch("comicarr.app.system.service.secrets.token_hex", return_value="a" * 32)
    def test_regenerate_api_key_reports_silent_write_failure(self, mock_token_hex):
        """regenerate_api_key fails when writeconfig reports an unsuccessful write."""
        ctx = _make_test_ctx()
        ctx.config.writeconfig.return_value = False

        result = system_service.regenerate_api_key(ctx)

        assert result == {"success": False, "error": "Failed to persist new API key"}
        assert ctx.config.API_KEY == "configured-api-key"
        mock_token_hex.assert_called_once_with(16)
        assert ctx.config.process_kwargs.call_args_list == [
            call({"api_key": "a" * 32}),
            call({"api_key": "configured-api-key"}),
        ]
        ctx.config.writeconfig.assert_called_once_with()
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
        args = ctx.config.process_kwargs.call_args[0][0]
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

    def test_get_version_info(self):
        """get_version_info returns version data from context."""
        ctx = _make_test_ctx(current_version="0.6.0", install_type="git")

        result = system_service.get_version_info(ctx)
        assert result["current_version"] == "0.6.0"
        assert result["install_type"] == "git"
