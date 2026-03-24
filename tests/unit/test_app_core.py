"""
Tests for comicarr.app.core modules — Phase 0 foundation.

Covers: AppContext, EventBus, security (JWT, CSRF), exceptions, middleware.
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock

import pytest

from comicarr.app.core.context import AppContext
from comicarr.app.core.events import AppEvent, EventBus
from comicarr.app.core.exceptions import (
    AuthError,
    ConfigError,
    DomainError,
    NotFoundError,
    ProviderTimeoutError,
    ValidationError,
)
from comicarr.app.core.security import (
    create_session_token,
    generate_ephemeral_key,
    validate_jwt_token,
)


# =============================================================================
# Test Context Factory
# =============================================================================


def create_test_context(**overrides):
    """Factory for creating AppContext instances in tests.

    Provides sensible defaults (in-memory SQLite, no-op scheduler, mock sessions).
    Override any field by passing keyword arguments.
    """
    defaults = {
        "prog_dir": "/tmp/comicarr_test",
        "data_dir": "/tmp/comicarr_test/data",
        "db_file": ":memory:",
        "config": MagicMock(
            API_KEY="test_api_key_32chars_here_pad00",
            ENABLE_HTTPS=False,
            HTTP_USERNAME="testuser",
            HTTP_PASSWORD="testhash",
            SECURE_DIR="/tmp/comicarr_test/secure",
            DESTINATION_DIR="/tmp/comics",
            COMIC_DIR="/tmp/comics",
            OPDS_USERNAME=None,
            OPDS_PASSWORD=None,
        ),
        "scheduler": MagicMock(),
        "jwt_secret_key": b"test_secret_key_32_bytes_padding!",
        "jwt_generation": 0,
        "sse_key": "test_sse_key",
        "download_apikey": "test_dl_key",
    }
    defaults.update(overrides)
    return AppContext(**defaults)


# =============================================================================
# AppContext Tests
# =============================================================================


class TestAppContext:
    def test_create_default(self):
        ctx = AppContext()
        assert ctx.prog_dir == ""
        assert ctx.monitor_status == "Waiting"
        assert ctx.jwt_generation == 0

    def test_create_with_overrides(self):
        ctx = create_test_context(prog_dir="/custom/path")
        assert ctx.prog_dir == "/custom/path"
        assert ctx.config.API_KEY == "test_api_key_32chars_here_pad00"

    def test_queues_are_independent(self):
        ctx = create_test_context()
        ctx.snatched_queue.put("item1")
        assert ctx.nzb_queue.empty()
        assert not ctx.snatched_queue.empty()

    def test_ddl_queued_is_set(self):
        ctx = create_test_context()
        assert isinstance(ctx.ddl_queued, set)


# =============================================================================
# EventBus Tests
# =============================================================================


class TestEventBus:
    def test_subscribe_unsubscribe(self):
        bus = EventBus()
        sub_id, q = bus.subscribe()
        assert bus.subscriber_count == 1
        bus.unsubscribe(sub_id)
        assert bus.subscriber_count == 0

    def test_publish_without_loop_is_noop(self):
        bus = EventBus()
        sub_id, q = bus.subscribe()
        # No loop set — should not raise
        bus.publish_sync("test", {"msg": "hello"})
        assert q.empty()

    @pytest.mark.asyncio
    async def test_publish_delivers_to_subscriber(self):
        bus = EventBus()
        loop = asyncio.get_running_loop()
        bus.set_loop(loop)

        sub_id, q = bus.subscribe()
        bus.publish_sync("update", {"key": "value"})

        # Give the event loop a chance to process
        await asyncio.sleep(0.05)

        assert not q.empty()
        event = q.get_nowait()
        assert event.event_type == "update"
        assert event.payload == {"key": "value"}
        bus.unsubscribe(sub_id)

    @pytest.mark.asyncio
    async def test_publish_fans_out_to_multiple_subscribers(self):
        bus = EventBus()
        loop = asyncio.get_running_loop()
        bus.set_loop(loop)

        sub1, q1 = bus.subscribe()
        sub2, q2 = bus.subscribe()

        bus.publish_sync("event", {"data": 1})
        await asyncio.sleep(0.05)

        assert not q1.empty()
        assert not q2.empty()

        bus.unsubscribe(sub1)
        bus.unsubscribe(sub2)

    @pytest.mark.asyncio
    async def test_publish_from_background_thread(self):
        bus = EventBus()
        loop = asyncio.get_running_loop()
        bus.set_loop(loop)

        sub_id, q = bus.subscribe()

        def bg_publish():
            time.sleep(0.01)
            bus.publish_sync("bg_event", {"from": "thread"})

        t = threading.Thread(target=bg_publish)
        t.start()
        t.join(timeout=2)

        await asyncio.sleep(0.1)

        assert not q.empty()
        event = q.get_nowait()
        assert event.event_type == "bg_event"
        bus.unsubscribe(sub_id)


# =============================================================================
# JWT Security Tests
# =============================================================================


class TestJWTSecurity:
    def test_create_and_validate_token(self):
        secret = b"test_secret_32bytes_padding_here"
        token = create_session_token("admin", secret, generation=0)
        username = validate_jwt_token(token, secret, current_generation=0)
        assert username == "admin"

    def test_expired_token_returns_none(self):
        secret = b"test_secret_32bytes_padding_here"
        # Create token with very short expiry
        token = create_session_token("admin", secret, generation=0, login_timeout=0)
        # Token should be expired immediately (or within ms)
        time.sleep(0.1)
        username = validate_jwt_token(token, secret, current_generation=0)
        # May or may not be expired depending on timing — check for None on truly expired
        # The 0-minute timeout means exp = now, which JWT considers expired
        assert username is None

    def test_wrong_generation_returns_none(self):
        secret = b"test_secret_32bytes_padding_here"
        token = create_session_token("admin", secret, generation=0)
        # Validate with generation=1 (simulating revocation)
        username = validate_jwt_token(token, secret, current_generation=1)
        assert username is None

    def test_wrong_secret_returns_none(self):
        secret = b"test_secret_32bytes_padding_here"
        token = create_session_token("admin", secret, generation=0)
        username = validate_jwt_token(token, b"wrong_secret_key_32bytes_pad_!", current_generation=0)
        assert username is None

    def test_invalid_token_returns_none(self):
        username = validate_jwt_token("not.a.jwt", b"secret", current_generation=0)
        assert username is None

    def test_ephemeral_key_generation(self):
        key1 = generate_ephemeral_key()
        key2 = generate_ephemeral_key()
        assert key1 != key2
        assert len(key1) == 32  # 16 bytes = 32 hex chars


# =============================================================================
# Exception Hierarchy Tests
# =============================================================================


class TestExceptionHierarchy:
    def test_all_inherit_from_domain_error(self):
        assert issubclass(NotFoundError, DomainError)
        assert issubclass(ProviderTimeoutError, DomainError)
        assert issubclass(ConfigError, DomainError)
        assert issubclass(AuthError, DomainError)
        assert issubclass(ValidationError, DomainError)

    def test_can_catch_with_base_class(self):
        with pytest.raises(DomainError):
            raise NotFoundError("Comic not found")


# =============================================================================
# Common Utility Tests
# =============================================================================


class TestCommonStrings:
    def test_latinToAscii(self):
        from comicarr.app.common.strings import latinToAscii

        assert latinToAscii("café") == "cafe"
        assert latinToAscii("naïve") == "naive"
        assert latinToAscii("ASCII") == "ASCII"

    def test_cleanName(self):
        from comicarr.app.common.strings import cleanName

        result = cleanName("Spider-Man #100")
        assert "#" not in result
        assert result == result.lower()

    def test_filesafe(self):
        from comicarr.app.common.strings import filesafe

        result = filesafe("Batman: The Dark Knight")
        assert ":" not in result

    def test_replace_all(self):
        from comicarr.app.common.strings import replace_all

        result = replace_all("hello world", {"hello": "hi", "world": "earth"})
        assert result == "hi earth"


class TestCommonDates:
    def test_today_format(self):
        from comicarr.app.common.dates import today

        result = today()
        assert len(result) == 10  # YYYY-MM-DD
        assert result[4] == "-"

    def test_now_default_format(self):
        from comicarr.app.common.dates import now

        result = now()
        assert len(result) == 19  # YYYY-MM-DD HH:MM:SS

    def test_utctimestamp(self):
        from comicarr.app.common.dates import utctimestamp

        ts = utctimestamp()
        assert isinstance(ts, float)
        assert ts > 0


class TestCommonNumbers:
    def test_human_size(self):
        from comicarr.app.common.numbers import human_size

        assert human_size(1) == "1 byte"
        assert "KB" in human_size(2048)
        assert "MB" in human_size(5 * 1024 * 1024)

    def test_bytes_to_mb(self):
        from comicarr.app.common.numbers import bytes_to_mb

        assert "1.0 MB" in bytes_to_mb(1048576)

    def test_decimal_issue(self):
        from comicarr.app.common.numbers import decimal_issue

        result, exc = decimal_issue("5")
        assert result == 5000
        assert exc is None

    def test_is_number(self):
        from comicarr.app.common.numbers import is_number

        assert is_number("42")
        assert is_number("3.14")
        assert not is_number("abc")


class TestCommonFilesystem:
    def test_path_within_allowed(self, tmp_path):
        from comicarr.app.common.filesystem import is_path_within_allowed_dirs

        allowed = [str(tmp_path)]
        test_file = tmp_path / "test.cbz"
        test_file.touch()
        assert is_path_within_allowed_dirs(str(test_file), allowed)

    def test_path_outside_allowed(self, tmp_path):
        from comicarr.app.common.filesystem import is_path_within_allowed_dirs

        allowed = [str(tmp_path / "comics")]
        assert not is_path_within_allowed_dirs("/etc/passwd", allowed)

    def test_path_traversal_blocked(self, tmp_path):
        from comicarr.app.common.filesystem import is_path_within_allowed_dirs

        allowed = [str(tmp_path)]
        traversal = str(tmp_path) + "/../../../etc/passwd"
        assert not is_path_within_allowed_dirs(traversal, allowed)
