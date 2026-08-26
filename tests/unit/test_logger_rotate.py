#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Operator-initiated log rotation (#743): one verb, "start a new log".

Clearing and rotating are the same outcome from the viewer's perspective, so
`rotate_log_file` does both halves — rolls `comicarr.log` over (the old file
survives as `comicarr.log.1` under normal retention) and empties the Web UI
ring buffer. These tests drive the real ``initLogger`` for the same reason
``test_logger_levels`` does: the behaviour under test lives in handler state.
"""

import logging

import pytest

import comicarr
from comicarr import logger as comicarr_logger


@pytest.fixture
def isolated_logger(tmp_path, monkeypatch):
    """Reconfigure the real 'comicarr' logger, restoring handlers on teardown."""
    lg = logging.getLogger("comicarr")
    saved_handlers = lg.handlers[:]
    saved_level = lg.level
    saved_propagate = lg.propagate
    monkeypatch.setattr(comicarr, "LOG_LEVEL", 1, raising=False)
    monkeypatch.setattr(comicarr, "LOGLIST", [], raising=False)

    def configure(console=False, log_dir=str(tmp_path)):
        comicarr_logger.initLogger(console=console, log_dir=log_dir, loglevel=1)
        return lg

    try:
        yield configure
    finally:
        for handler in lg.handlers[:]:
            lg.removeHandler(handler)
            handler.close()
        for handler in saved_handlers:
            lg.addHandler(handler)
        lg.setLevel(saved_level)
        lg.propagate = saved_propagate


def test_rotate_starts_a_fresh_file_and_keeps_the_old_one(isolated_logger, tmp_path):
    lg = isolated_logger()
    lg.info("before rotation")

    rotated = comicarr_logger.rotate_log_file()

    assert rotated is True
    current = tmp_path / "comicarr.log"
    archive = tmp_path / "comicarr.log.1"
    assert archive.exists(), "previous log must survive as an archive"
    assert "before rotation" in archive.read_text()
    # The current file starts clean and keeps receiving new lines.
    lg.info("after rotation")
    for handler in lg.handlers:
        handler.flush()
    contents = current.read_text()
    assert "before rotation" not in contents
    assert "after rotation" in contents


def test_rotate_empties_the_web_ui_buffer(isolated_logger):
    lg = isolated_logger()
    lg.info("a line the viewer buffered")
    assert comicarr.LOGLIST, "sanity: the LogListHandler buffered the line"

    comicarr_logger.rotate_log_file()

    assert comicarr.LOGLIST == []


def test_rotate_without_a_file_handler_still_clears_the_buffer(isolated_logger):
    lg = isolated_logger(log_dir=False)
    lg.info("buffered but never written to disk")
    assert comicarr.LOGLIST

    rotated = comicarr_logger.rotate_log_file()

    assert rotated is False
    assert comicarr.LOGLIST == []


def test_rotate_preserves_loglist_identity(isolated_logger):
    """LogListHandler mutates comicarr.LOGLIST in place; rotation must too."""
    lg = isolated_logger()
    buffer_before = comicarr.LOGLIST
    lg.info("line")

    comicarr_logger.rotate_log_file()

    assert comicarr.LOGLIST is buffer_before
    lg.info("line after")
    assert comicarr.LOGLIST, "handler must keep feeding the same buffer"


class TestStartNewLogService:
    """The service wrapper turns rotation into an operator-facing result."""

    def test_success_reports_rotated(self, isolated_logger, monkeypatch):
        from comicarr.app.system import service as system_service

        isolated_logger()
        result = system_service.start_new_log(ctx=None)
        assert result == {"success": True, "rotated": True}

    def test_rotation_failure_is_reported_not_raised(self, isolated_logger, monkeypatch):
        from comicarr.app.system import service as system_service

        isolated_logger()

        def boom():
            raise OSError("disk says no")

        monkeypatch.setattr(comicarr_logger, "rotate_log_file", boom)
        result = system_service.start_new_log(ctx=None)
        assert result["success"] is False
        assert "disk says no" in result["error"]


def test_a_suppressed_rollover_failure_is_reported_not_swallowed(isolated_logger, monkeypatch):
    """The Windows ConcurrentRotatingFileHandler catches a failed rename and
    degrades instead of raising, leaving the current file untouched. Reporting
    that as a successful rotation would tell the operator a clean log exists
    when it does not, so the postcondition check must turn it into an error.
    """
    lg = isolated_logger()
    lg.info("line that stays because the rename silently failed")
    for handler in lg.handlers:
        if isinstance(handler, logging.handlers.BaseRotatingHandler):
            monkeypatch.setattr(handler, "doRollover", lambda: None)

    with pytest.raises(OSError, match="did not complete"):
        comicarr_logger.rotate_log_file()

    from comicarr.app.system import service as system_service

    result = system_service.start_new_log(ctx=None)
    assert result["success"] is False
    assert "did not complete" in result["error"]
