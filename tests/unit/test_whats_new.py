#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Post-upgrade What's New: LAST_SEEN_VERSION, modal pending range, About archive.

Seams (issue #474 / decisions #449 + #451):
- ``comicarr.app.system.whats_new.detect_pending`` — pure compare, no write
- ``resolve_pending_whats_new`` — seed-on-absent write + derived pending range
- ``dismiss_whats_new`` — write LAST_SEEN_VERSION = current only
- ``archive_sections`` — floor at pending, pad toward ~10 when quiet
- Registry: LAST_SEEN_VERSION install-wide, not Settings-exposed
"""

from unittest.mock import MagicMock, patch

import pytest

from comicarr.app.config.registry import REGISTRY
from comicarr.app.core import runtime
from comicarr.app.core.context import AppContext
from comicarr.app.system import service as system_service
from comicarr.app.system import whats_new


def test_last_seen_version_is_install_wide_and_not_settings():
    key = REGISTRY["LAST_SEEN_VERSION"]
    assert key.default is None
    assert key.readable is False
    assert key.writable is False
    assert key.section == "Git"
    assert key.type is str


class TestDetectPending:
    """Pure comparison — never writes."""

    def test_absent_last_seen_is_seed(self):
        result = whats_new.detect_pending(current="0.21.0", last_seen=None)
        assert result.kind == "seed"
        assert result.pending is None

    def test_empty_last_seen_is_seed(self):
        result = whats_new.detect_pending(current="0.21.0", last_seen="")
        assert result.kind == "seed"
        assert result.pending is None

    def test_upgrade_yields_pending_open_closed_range(self):
        result = whats_new.detect_pending(current="0.21.0", last_seen="0.20.4")
        assert result.kind == "pending"
        assert result.pending == {"from": "0.20.4", "to": "0.21.0"}

    def test_equal_is_quiet(self):
        result = whats_new.detect_pending(current="0.21.0", last_seen="0.21.0")
        assert result.kind == "quiet"
        assert result.pending is None

    def test_downgrade_is_quiet(self):
        result = whats_new.detect_pending(current="0.20.0", last_seen="0.21.0")
        assert result.kind == "quiet"
        assert result.pending is None

    def test_missing_current_is_quiet(self):
        result = whats_new.detect_pending(current=None, last_seen="0.20.0")
        assert result.kind == "quiet"
        assert result.pending is None

    def test_invalid_semver_is_quiet(self):
        result = whats_new.detect_pending(current="not-a-version", last_seen="0.20.0")
        assert result.kind == "quiet"


class TestResolveAndDismiss:
    @pytest.fixture
    def ctx(self, monkeypatch):
        config = MagicMock()
        config.LAST_SEEN_VERSION = None
        context = AppContext(
            prog_dir="/tmp/comicarr_test",
            data_dir="/tmp/comicarr_test/data",
            db_file=":memory:",
            config=config,
            scheduler=MagicMock(),
        )
        monkeypatch.setattr(runtime.current(), "config", config, raising=False)
        return context

    def test_seed_writes_current_and_returns_null(self, ctx):
        with patch.object(system_service, "get_release_version", return_value="0.21.0"):
            pending = whats_new.resolve_pending_whats_new(ctx)

        assert pending is None
        assert runtime.current().config.LAST_SEEN_VERSION == "0.21.0"
        runtime.current().config.writeconfig.assert_called_once_with(values={"last_seen_version": "0.21.0"})

    def test_pending_does_not_write(self, ctx):
        runtime.current().config.LAST_SEEN_VERSION = "0.20.0"
        with patch.object(system_service, "get_release_version", return_value="0.21.0"):
            pending = whats_new.resolve_pending_whats_new(ctx)

        assert pending == {"from": "0.20.0", "to": "0.21.0"}
        runtime.current().config.writeconfig.assert_not_called()

    def test_equal_quiet_does_not_write(self, ctx):
        runtime.current().config.LAST_SEEN_VERSION = "0.21.0"
        with patch.object(system_service, "get_release_version", return_value="0.21.0"):
            pending = whats_new.resolve_pending_whats_new(ctx)

        assert pending is None
        runtime.current().config.writeconfig.assert_not_called()

    def test_downgrade_quiet_does_not_write(self, ctx):
        runtime.current().config.LAST_SEEN_VERSION = "0.22.0"
        with patch.object(system_service, "get_release_version", return_value="0.21.0"):
            pending = whats_new.resolve_pending_whats_new(ctx)

        assert pending is None
        assert runtime.current().config.LAST_SEEN_VERSION == "0.22.0"
        runtime.current().config.writeconfig.assert_not_called()

    def test_dismiss_writes_current(self, ctx):
        runtime.current().config.LAST_SEEN_VERSION = "0.20.0"
        with patch.object(system_service, "get_release_version", return_value="0.21.0"):
            result = whats_new.dismiss_whats_new(ctx)

        assert result == {"success": True, "last_seen_version": "0.21.0"}
        assert runtime.current().config.LAST_SEEN_VERSION == "0.21.0"
        runtime.current().config.writeconfig.assert_called_once_with(values={"last_seen_version": "0.21.0"})


class TestVersionInfoIncludesPending:
    @pytest.fixture
    def ctx(self, monkeypatch):
        config = MagicMock()
        config.LAST_SEEN_VERSION = "0.20.0"
        context = AppContext(
            prog_dir="/tmp/comicarr_test",
            data_dir="/tmp/comicarr_test/data",
            db_file=":memory:",
            config=config,
            scheduler=MagicMock(),
            update_state="current",
            update_reason=None,
        )
        monkeypatch.setattr(runtime.current(), "config", config, raising=False)
        return context

    def test_get_version_info_exposes_pending_whats_new(self, ctx):
        with patch.object(system_service, "get_release_version", return_value="0.21.0"):
            info = system_service.get_version_info(ctx)
        assert info["pending_whats_new"] == {"from": "0.20.0", "to": "0.21.0"}
        runtime.current().config.writeconfig.assert_not_called()

    def test_get_version_info_null_when_caught_up(self, ctx):
        runtime.current().config.LAST_SEEN_VERSION = "0.21.0"
        with patch.object(system_service, "get_release_version", return_value="0.21.0"):
            info = system_service.get_version_info(ctx)
        assert info["pending_whats_new"] is None


class TestArchiveSections:
    SECTIONS = [
        {"version": "0.21.0", "bullets": ["a"]},
        {"version": "0.20.12", "bullets": ["b"]},
        {"version": "0.20.11", "bullets": ["c"]},
        {"version": "0.20.10", "bullets": ["d"]},
        {"version": "0.20.9", "bullets": ["e"]},
        {"version": "0.20.8", "bullets": ["f"]},
        {"version": "0.20.7", "bullets": ["g"]},
        {"version": "0.20.6", "bullets": ["h"]},
        {"version": "0.20.5", "bullets": ["i"]},
        {"version": "0.20.4", "bullets": ["j"]},
        {"version": "0.20.3", "bullets": ["k"]},
        {"version": "0.19.0", "bullets": ["l"]},
    ]

    def test_pads_to_floor_when_nothing_pending(self):
        rows = whats_new.archive_sections(
            self.SECTIONS,
            current="0.21.0",
            last_seen="0.21.0",
            floor=10,
        )
        assert len(rows) == 10
        assert rows[0]["version"] == "0.21.0"
        assert rows[-1]["version"] == "0.20.4"

    def test_floors_at_pending_when_unread_exceeds_floor(self):
        # last_seen 0.19.0 → 11 pending versions up through 0.21.0
        rows = whats_new.archive_sections(
            self.SECTIONS,
            current="0.21.0",
            last_seen="0.19.0",
            floor=10,
        )
        assert len(rows) == 11
        assert rows[0]["version"] == "0.21.0"
        assert rows[-1]["version"] == "0.20.3"

    def test_pads_when_pending_shorter_than_floor(self):
        rows = whats_new.archive_sections(
            self.SECTIONS,
            current="0.21.0",
            last_seen="0.20.11",
            floor=10,
        )
        # 2 pending (0.21.0, 0.20.12) but pad to 10
        assert len(rows) == 10
        assert {r["version"] for r in rows[:2]} == {"0.21.0", "0.20.12"}
