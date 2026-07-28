"""
Tests for comicarr.app.core modules — Phase 0 foundation.

Covers: AppContext, EventBus, security (JWT, CSRF), exceptions, middleware.
"""

import asyncio
import errno
import os
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
    load_or_create_jwt_key,
    rotate_jwt_key,
    rotate_runtime_jwt_key,
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

    def test_publish_ignores_closed_loop_during_shutdown(self):
        bus = EventBus()
        loop = MagicMock()
        loop.call_soon_threadsafe.side_effect = RuntimeError("Event loop is closed")
        bus.set_loop(loop)
        bus.subscribe()

        bus.publish_sync("shutdown", {"message": "stopping"})

        loop.call_soon_threadsafe.assert_called_once()

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

    @pytest.mark.asyncio
    async def test_publish_replaces_oldest_event_when_subscriber_queue_is_full(self):
        bus = EventBus()
        loop = asyncio.get_running_loop()
        bus.set_loop(loop)

        sub_id, q = bus.subscribe()
        seed_events = [AppEvent("seed", {"index": index}) for index in range(q.maxsize)]
        for event in seed_events:
            q.put_nowait(event)

        loop_errors = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
        try:
            bus.publish_sync("latest", {"index": q.maxsize})
            await asyncio.sleep(0)
        finally:
            loop.set_exception_handler(previous_handler)

        queued_events = [q.get_nowait() for _ in range(q.qsize())]
        assert loop_errors == []
        assert len(queued_events) == q.maxsize
        assert queued_events == seed_events[1:] + [AppEvent("latest", {"index": q.maxsize})]
        bus.unsubscribe(sub_id)

    @pytest.mark.asyncio
    async def test_publish_burst_retains_newest_window_when_queue_full(self):
        bus = EventBus()
        loop = asyncio.get_running_loop()
        bus.set_loop(loop)

        sub_id, q = bus.subscribe()
        seed_events = [AppEvent("seed", {"index": index}) for index in range(q.maxsize)]
        for event in seed_events:
            q.put_nowait(event)

        burst_count = 3
        newest_events = [AppEvent("burst", {"index": q.maxsize + offset}) for offset in range(burst_count)]

        loop_errors = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
        try:
            for event in newest_events:
                bus.publish_sync(event.event_type, event.payload)
            await asyncio.sleep(0)
        finally:
            loop.set_exception_handler(previous_handler)

        queued_events = [q.get_nowait() for _ in range(q.qsize())]
        assert loop_errors == []
        assert len(queued_events) == q.maxsize
        assert queued_events == seed_events[burst_count:] + newest_events
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

    def test_persisted_key_round_trip_preserves_binary_bytes_and_mode(self, tmp_path, monkeypatch):
        secure_dir = tmp_path / "secure"
        secure_dir.mkdir()
        binary_key = b" \t" + (b"k" * 28) + b"\r\n"
        monkeypatch.setattr(os, "urandom", lambda _size: binary_key)

        created = load_or_create_jwt_key(str(secure_dir))
        loaded = load_or_create_jwt_key(str(secure_dir))

        assert created == binary_key
        assert loaded == binary_key
        assert stat.S_IMODE((secure_dir / "jwt.key").stat().st_mode) == 0o600

    def test_rotation_invalidates_old_token_and_survives_restart(self, tmp_path):
        secure_dir = tmp_path / "secure"
        secure_dir.mkdir()
        old_key = load_or_create_jwt_key(str(secure_dir))
        old_token = create_session_token("admin", old_key, generation=0)

        new_key = rotate_jwt_key(str(secure_dir))

        assert new_key != old_key
        assert validate_jwt_token(old_token, new_key, 0) is None
        assert load_or_create_jwt_key(str(secure_dir)) == new_key
        assert stat.S_IMODE((secure_dir / "jwt.key").stat().st_mode) == 0o600

    def test_rotation_replace_failure_preserves_current_key(self, tmp_path, monkeypatch):
        secure_dir = tmp_path / "secure"
        secure_dir.mkdir()
        old_key = load_or_create_jwt_key(str(secure_dir))

        def fail_replace(_source, _destination):
            raise OSError("replace failed")

        monkeypatch.setattr(os, "replace", fail_replace)

        with pytest.raises(OSError, match="replace failed"):
            rotate_jwt_key(str(secure_dir))

        assert (secure_dir / "jwt.key").read_bytes() == old_key
        assert sorted(path.name for path in secure_dir.iterdir()) == ["jwt.key"]

    def test_rotation_write_failure_preserves_current_key(self, tmp_path, monkeypatch):
        secure_dir = tmp_path / "secure"
        secure_dir.mkdir()
        old_key = load_or_create_jwt_key(str(secure_dir))

        def fail_fsync(_file_descriptor):
            raise OSError("sync failed")

        monkeypatch.setattr(os, "fsync", fail_fsync)

        with pytest.raises(OSError, match="sync failed"):
            rotate_jwt_key(str(secure_dir))

        assert (secure_dir / "jwt.key").read_bytes() == old_key
        assert sorted(path.name for path in secure_dir.iterdir()) == ["jwt.key"]

    def test_concurrent_runtime_rotations_keep_memory_and_disk_consistent(self, tmp_path):
        secure_dir = tmp_path / "secure"
        secure_dir.mkdir()
        initial_key = load_or_create_jwt_key(str(secure_dir))
        ctx = create_test_context(
            jwt_secure_dir=str(secure_dir),
            jwt_secret_key=initial_key,
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            rotated_keys = list(executor.map(lambda _index: rotate_runtime_jwt_key(ctx), range(2)))

        persisted_key = (secure_dir / "jwt.key").read_bytes()
        assert len(set(rotated_keys)) == 2
        assert ctx.jwt_secret_key == persisted_key
        assert ctx.jwt_secret_key in rotated_keys
        assert ctx.jwt_secret_key != initial_key
        assert stat.S_IMODE((secure_dir / "jwt.key").stat().st_mode) == 0o600

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


def _placement_config(mode):
    """Config source for the placement stage: it reads the mode at call time."""
    return SimpleNamespace(FILE_OPTS=mode, ARC_FILEOPS=mode, ARC_FILEOPS_SOFTLINK_RELATIVE=False)


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

    def test_strict_rejects_root_itself_and_filesystem_root(self, tmp_path):
        import os

        from comicarr.app.common.filesystem import is_path_within_allowed_dirs

        child = tmp_path / "series"
        child.mkdir()
        assert is_path_within_allowed_dirs(str(child), [str(tmp_path)], strict=True)
        assert not is_path_within_allowed_dirs(str(tmp_path), [str(tmp_path)], strict=True)
        assert not is_path_within_allowed_dirs(str(child), [os.sep], strict=True)

    # These were unit tests of `file_ops`, which #334 deleted. They moved to the
    # placement stage with it, minus the `os_detect="Windows"` argument: #331
    # measured that parameter as accepted-but-never-read, so the "windows_"
    # prefixes were asserting the POSIX path. What they genuinely covered -- the
    # link direction each mode uses and each fallback -- is kept.

    def test_hardlink_uses_os_link_and_verifies_the_link_count(self):
        from comicarr.app.common.placement import OnExisting, Purpose, place

        src = "/downloads/book.cbz"
        dst = "/comics/book.cbz"
        stat_result = MagicMock()
        stat_result.st_nlink = 2

        with (
            patch("comicarr.app.common.placement.os.link") as mock_link,
            patch("comicarr.app.common.placement.os.lstat", return_value=stat_result) as mock_lstat,
        ):
            result = place(
                src, dst, Purpose.SERIES, on_existing=OnExisting.UNGUARDED, config=_placement_config("hardlink")
            )

        assert result.effective_mode == "hardlink"
        mock_link.assert_called_once_with(src, dst)
        mock_lstat.assert_called_once_with(dst)

    def test_hardlink_cross_device_falls_back_to_copy(self):
        from comicarr.app.common.placement import OnExisting, Purpose, place

        src = "/downloads/book.cbz"
        dst = "/other-volume/book.cbz"

        with (
            patch(
                "comicarr.app.common.placement.os.link",
                side_effect=OSError(errno.EXDEV, "Cross-device link"),
            ) as mock_link,
            patch("comicarr.app.common.placement.shutil.copy") as mock_copy,
        ):
            result = place(
                src, dst, Purpose.SERIES, on_existing=OnExisting.UNGUARDED, config=_placement_config("hardlink")
            )

        assert result.effective_mode == "copy", "the caller must be able to see the link never happened"
        mock_link.assert_called_once_with(src, dst)
        mock_copy.assert_called_once_with(src, dst)

    def test_non_arc_softlink_moves_then_links_the_source_back_at_the_destination(self):
        from comicarr.app.common.placement import OnExisting, Purpose, place

        src = "/downloads/book.cbz"
        dst = "/comics/book.cbz"

        with (
            patch("comicarr.app.common.placement.shutil.move") as mock_move,
            patch("comicarr.app.common.placement.os.path.lexists", return_value=False) as mock_lexists,
            patch("comicarr.app.common.placement.os.remove") as mock_remove,
            patch("comicarr.app.common.placement.os.symlink") as mock_symlink,
            patch("comicarr.app.common.placement.shutil.copy") as mock_copy,
        ):
            result = place(
                src, dst, Purpose.SERIES, on_existing=OnExisting.UNGUARDED, config=_placement_config("softlink")
            )

        assert result.source_is_symlink is True
        mock_move.assert_called_once_with(src, dst)
        mock_lexists.assert_called_once_with(src)
        mock_remove.assert_not_called()
        mock_symlink.assert_called_once_with(dst, src)
        mock_copy.assert_not_called()

    @pytest.mark.parametrize("copy_fails", [False, True])
    def test_non_arc_softlink_failure_copies_the_destination_back(self, copy_fails):
        from comicarr.app.common.placement import OnExisting, PlacementError, Purpose, place

        src = "/downloads/book.cbz"
        dst = "/comics/book.cbz"

        with (
            patch("comicarr.app.common.placement.shutil.move") as mock_move,
            patch("comicarr.app.common.placement.os.path.lexists", return_value=False),
            patch("comicarr.app.common.placement.os.remove") as mock_remove,
            patch(
                "comicarr.app.common.placement.os.symlink",
                side_effect=OSError("symlink denied"),
            ) as mock_symlink,
            patch(
                "comicarr.app.common.placement.shutil.copy",
                side_effect=Exception("copy failed") if copy_fails else None,
            ) as mock_copy,
        ):
            if copy_fails:
                with pytest.raises(PlacementError):
                    place(
                        src, dst, Purpose.SERIES, on_existing=OnExisting.UNGUARDED, config=_placement_config("softlink")
                    )
            else:
                result = place(
                    src, dst, Purpose.SERIES, on_existing=OnExisting.UNGUARDED, config=_placement_config("softlink")
                )
                assert result.effective_mode == "copy"

        mock_move.assert_called_once_with(src, dst)
        mock_remove.assert_not_called()
        mock_symlink.assert_called_once_with(dst, src)
        mock_copy.assert_called_once_with(dst, src)

    def test_arc_softlink_failure_copies_the_source_to_the_destination(self):
        from comicarr.app.common.placement import OnExisting, Purpose, place

        src = "/comics/book.cbz"
        dst = "/arcs/book.cbz"

        with (
            patch(
                "comicarr.app.common.placement.os.symlink",
                side_effect=OSError("symlink denied"),
            ) as mock_symlink,
            patch("comicarr.app.common.placement.shutil.copy") as mock_copy,
        ):
            result = place(
                src, dst, Purpose.ARC, on_existing=OnExisting.UNGUARDED, config=_placement_config("softlink")
            )

        assert result.effective_mode == "copy"
        mock_symlink.assert_called_once_with(src, dst)
        mock_copy.assert_called_once_with(src, dst)
        mock_copy.assert_called_once_with(src, dst)


# =============================================================================
# Setup Gate Middleware Tests
# =============================================================================


def _build_setup_gate_app(setup_token="test-setup-token"):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from comicarr.app.core.middleware import SetupGateMiddleware

    async def ok_endpoint(request):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[
            Route("/login", ok_endpoint, methods=["GET"]),
            Route("/api/auth/check-setup", ok_endpoint, methods=["GET"]),
            Route("/api/auth/setup", ok_endpoint, methods=["POST"]),
            Route("/api/auth/login", ok_endpoint, methods=["POST"]),
            Route("/api/health", ok_endpoint, methods=["GET"]),
            Route("/api/series", ok_endpoint, methods=["GET"]),
        ]
    )
    ctx = create_test_context(setup_token=setup_token)
    app.state.ctx = ctx
    app.add_middleware(SetupGateMiddleware)
    return TestClient(app)


class TestSetupGateMiddleware:
    def test_check_setup_allowed_during_setup(self):
        client = _build_setup_gate_app()
        response = client.get("/api/auth/check-setup")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_setup_post_allowed_during_setup(self):
        client = _build_setup_gate_app()
        response = client.post("/api/auth/setup")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_login_blocked_during_setup(self):
        client = _build_setup_gate_app()
        response = client.post("/api/auth/login")
        assert response.status_code == 503
        assert "Setup required" in response.json()["detail"]

    def test_login_page_allowed_during_setup(self):
        client = _build_setup_gate_app()
        response = client.get("/login")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_health_allowed_during_setup(self):
        client = _build_setup_gate_app()
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_series_blocked_during_setup(self):
        client = _build_setup_gate_app()
        response = client.get("/api/series")
        assert response.status_code == 503
        assert "Setup required" in response.json()["detail"]
