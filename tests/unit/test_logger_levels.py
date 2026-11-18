#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The log level contract: one dial, applied identically to every sink.

See docs/architecture/logging-levels.md. These tests drive the real
``initLogger`` rather than a stub, because the defects they guard against
(#610/#612) all lived in *handler* state that a call-recording stub cannot see.
"""

import logging

import pytest

from comicarr.app.core import logger as comicarr_logger
from comicarr.app.core import runtime

LEVEL_THRESHOLDS = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}


@pytest.fixture
def isolated_logger(tmp_path, monkeypatch):
    """Reconfigure the real 'comicarr' logger, restoring handlers on teardown."""
    lg = logging.getLogger("comicarr")
    saved_handlers = lg.handlers[:]
    saved_level = lg.level
    saved_propagate = lg.propagate
    monkeypatch.setattr(runtime.current(), "log_level", 1, raising=False)

    def configure(level, console=True):
        runtime.current().log_level = level
        comicarr_logger.initLogger(console=console, log_dir=str(tmp_path), loglevel=level)
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


def _sink_levels(lg):
    return {type(handler).__name__: handler.level for handler in lg.handlers}


@pytest.mark.parametrize("level, threshold", sorted(LEVEL_THRESHOLDS.items()))
def test_every_sink_follows_the_dial(isolated_logger, level, threshold):
    lg = isolated_logger(level)

    assert lg.level == threshold
    sinks = _sink_levels(lg)
    assert sinks["RotatingFileHandler"] == threshold
    assert sinks["StreamHandler"] == threshold
    assert sinks["LogListHandler"] == threshold


def test_level_zero_is_warnings_not_silence(isolated_logger):
    """Turning the dial down must not hide the fact that something broke."""
    lg = isolated_logger(0)

    assert lg.isEnabledFor(logging.WARNING)
    assert lg.isEnabledFor(logging.ERROR)
    assert not lg.isEnabledFor(logging.INFO)


def test_turning_the_dial_down_takes_effect(isolated_logger):
    """Regression: level 0 never called setLevel, so 2 -> 0 stayed at DEBUG.

    The old code only set a level for loglevel 1 and >= 2, so lowering
    verbosity at runtime silently kept the previous, more verbose threshold —
    and a fresh level-0 start inherited root's WARNING by accident rather than
    by intent.
    """
    isolated_logger(2)
    lg = isolated_logger(0)

    assert lg.level == logging.WARNING
    assert not lg.isEnabledFor(logging.DEBUG)


def test_raising_verbosity_keeps_the_console_attached(isolated_logger):
    """Regression for #610: raising verbosity used to remove the console sink."""
    for level in (0, 1, 2):
        lg = isolated_logger(level)
        assert "StreamHandler" in _sink_levels(lg), "console lost at level %s" % level


def test_console_can_still_be_detached_explicitly(isolated_logger):
    """Console attachment is a deployment concern, not a verbosity one."""
    lg = isolated_logger(2, console=False)

    assert "StreamHandler" not in _sink_levels(lg)
    assert lg.level == logging.DEBUG


def test_no_log_dir_degrades_to_screen_only(monkeypatch):
    """A screen-only recovery has to actually be screen-only.

    Both log-directory failure paths in config.py recover by setting
    ``LOG_DIR = None``. That recovery is only real if a falsy log_dir produces
    no file handler — otherwise the message lies and the next
    ``configure_log_level()`` raises FileNotFoundError building the handler
    over a directory that does not exist.
    """
    lg = logging.getLogger("comicarr")
    saved_handlers = lg.handlers[:]
    saved_level = lg.level
    monkeypatch.setattr(runtime.current(), "log_level", 1, raising=False)
    try:
        comicarr_logger.initLogger(console=True, log_dir=None, loglevel=1)
        sinks = _sink_levels(lg)

        assert "RotatingFileHandler" not in sinks
        assert "StreamHandler" in sinks
    finally:
        for handler in lg.handlers[:]:
            lg.removeHandler(handler)
            handler.close()
        for handler in saved_handlers:
            lg.addHandler(handler)
        lg.setLevel(saved_level)


@pytest.mark.parametrize(
    "level, threshold",
    [
        (None, logging.INFO),
        (-1, logging.WARNING),
        (0, logging.WARNING),
        (1, logging.INFO),
        (2, logging.DEBUG),
        (5, logging.DEBUG),
    ],
)
def test_threshold_for_level_maps_the_whole_dial(level, threshold):
    assert comicarr_logger.threshold_for_level(level) == threshold


@pytest.mark.parametrize("configured, expected", [(None, 0), (0, 0), (1, 1), (2, 2)])
def test_current_log_level_treats_unconfigured_as_quiet(monkeypatch, configured, expected):
    monkeypatch.setattr(runtime.current(), "log_level", configured, raising=False)

    assert comicarr_logger.current_log_level() == expected


@pytest.mark.parametrize("name", ["info", "debug", "fdebug", "warn", "warning", "error", "exception", "message"])
def test_every_logging_helper_the_codebase_calls_exists(name):
    """Regression for #619: the retired locale branch defined only five of these.

    ``logger.warning`` (21 call sites) and ``logger.exception`` (7, all inside
    ``except`` blocks) were missing on the non-English path — the path *every*
    Docker install took, because python:3.12-slim sets LANG=C.UTF-8. Calling
    them raised AttributeError instead of logging, so warnings were dropped and
    error handlers raised while handling the error.
    """
    assert callable(getattr(comicarr_logger, name))


def test_warnings_and_exceptions_reach_the_sinks(isolated_logger, monkeypatch):
    """The two helpers the retired branch omitted must actually emit."""
    monkeypatch.setattr(runtime.current(), "loglist", [], raising=False)
    isolated_logger(0)

    comicarr_logger.warning("[COMIC-SCAN] No COMIC_DIR configured")
    try:
        raise ValueError("boom")
    except ValueError:
        comicarr_logger.exception("handled")

    emitted = [entry[1] for entry in runtime.current().loglist]
    assert any("No COMIC_DIR configured" in line for line in emitted)
    assert any("handled" in line for line in emitted)


def test_the_web_ui_log_list_is_bounded(isolated_logger, monkeypatch):
    """The Web UI log list is an in-memory buffer for the life of the process, so it needs a cap.

    The retired locale branch trimmed at 2500; ``LogListHandler`` never did.
    Retiring that branch without carrying the cap across would have handed every
    Docker install an unbounded list.
    """
    monkeypatch.setattr(runtime.current(), "loglist", [], raising=False)
    monkeypatch.setattr(comicarr_logger, "MAX_LOGLIST_ENTRIES", 10)
    isolated_logger(2)

    for index in range(25):
        comicarr_logger.info("entry-%s" % index)

    assert len(runtime.current().loglist) == 10
    # Newest first, so the cap must drop the *oldest* entries.
    assert "entry-24" in runtime.current().loglist[0][1]
    assert not any("entry-0 " in entry[1] for entry in runtime.current().loglist)
