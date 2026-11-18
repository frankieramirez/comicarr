#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Saving the log level from Settings takes effect now, not at the next start.

``logger.configure_log_level`` has performed the live reconfigure all along;
its only caller was maintenance mode, so ``LOG_LEVEL`` was writable, invisible,
and inert until startup -- where a startup argument beat it anyway. The point
of raising verbosity is to catch a problem *while it is happening* (#610), so a
dial that needs a restart destroys the state the operator was trying to
capture.

Two fixtures, deliberately:

``stubbed_save`` stands in for the handler rebuild and covers what
``update_config`` itself decides -- parsing, refusal, ordering, persistence.
None of that depends on which logger path the process took, and the skip below
would otherwise silence all of it on any machine whose locale is not English.

``settings_save`` drives the real ``comicarr`` logger and asserts on what
actually gets *emitted*; a call-recording stub would pass against handlers that
never changed. Only those tests are skipped off the English path.
"""

import logging
import threading

import pytest

import comicarr
from comicarr.app.config.ini import config_transaction_lock
from comicarr.app.config.log_level import ACCEPTED_FORMS
from comicarr.app.core import logger as comicarr_logger
from comicarr.app.core import runtime
from comicarr.app.core.context import AppContext
from comicarr.app.system import service as system_service


class FakeConfig:
    """Enough config to persist a level and rebuild the handlers over it.

    Deliberately not a MagicMock: ``configure_log_level`` reads ``LOG_DIR``,
    ``MAX_LOGSIZE`` and ``MAX_LOGFILES`` straight off ``runtime.current().config`` and
    hands them to a real ``RotatingFileHandler``, which a Mock attribute would
    fail on rather than exercise.
    """

    def __init__(self, log_dir):
        self.LOG_DIR = log_dir
        self.MAX_LOGSIZE = 1000000
        self.MAX_LOGFILES = 5
        self.LOG_LEVEL = 1
        self.COMIC_DIR = "/comics"
        self.EXTRA_NEWZNABS = []
        self.EXTRA_TORZNABS = []
        self.persist = True
        self.transactions = []

    def apply_transaction(self, values, configure=True):
        self.transactions.append(dict(values))
        if not self.persist:
            return False
        for key, value in values.items():
            setattr(self, key.upper(), value)
        return True


def _make_save(tmp_path, monkeypatch):
    config = FakeConfig(str(tmp_path))
    ctx = AppContext(config=config, data_dir=str(tmp_path))
    monkeypatch.setattr(runtime.current(), "config", config, raising=False)
    monkeypatch.setattr(comicarr, "LOG_LEVEL", 1, raising=False)
    monkeypatch.setattr(comicarr, "LOGLIST", [], raising=False)

    def save(**key_values):
        return system_service.update_config(ctx, key_values)

    save.config = config
    save.ctx = ctx
    return save


@pytest.fixture
def stubbed_save(tmp_path, monkeypatch):
    """Save config through the real service, standing in for the handler rebuild.

    The stub still moves ``comicarr.LOG_LEVEL``, because that is what
    ``configure_log_level`` does and what everything else reads the dial from.
    """
    save = _make_save(tmp_path, monkeypatch)
    save.applied = []

    def record(level):
        comicarr.LOG_LEVEL = level
        save.applied.append(level)

    monkeypatch.setattr(comicarr_logger, "configure_log_level", record)
    return save


@pytest.fixture
def settings_save(tmp_path, monkeypatch):
    """Save config through the real service against the real logger.

    Restores the process logger on teardown -- these tests tear down and
    rebuild its handlers, which would otherwise leak into every later test.
    """
    lg = logging.getLogger("comicarr")
    saved_handlers = lg.handlers[:]
    saved_level = lg.level
    saved_propagate = lg.propagate

    save = _make_save(tmp_path, monkeypatch)
    save.logger = lg
    comicarr_logger.initLogger(console=True, log_dir=str(tmp_path), loglevel=1)

    try:
        yield save
    finally:
        for handler in lg.handlers[:]:
            lg.removeHandler(handler)
            handler.close()
        for handler in saved_handlers:
            lg.addHandler(handler)
        lg.setLevel(saved_level)
        lg.propagate = saved_propagate


def _emitted(message):
    """Whether a record reached the Web UI sink, rather than merely being sent."""
    return any(message in entry[1] for entry in comicarr.LOGLIST)


class TestASavedLevelChangesWhatIsEmitted:
    def test_raising_the_level_starts_emitting_debug(self, settings_save):
        comicarr_logger.debug("before-raise")
        assert not _emitted("before-raise")

        result = settings_save(log_level=2)

        assert result == {"success": True}
        comicarr_logger.debug("after-raise")
        assert _emitted("after-raise")

    def test_lowering_the_level_stops_emitting_info(self, settings_save):
        settings_save(log_level=0)

        comicarr_logger.info("after-lower")

        assert not _emitted("after-lower")
        assert settings_save.logger.isEnabledFor(logging.WARNING)

    def test_every_sink_follows_the_saved_level(self, settings_save):
        settings_save(log_level=2)

        sinks = {type(handler).__name__: handler.level for handler in settings_save.logger.handlers}

        assert settings_save.logger.level == logging.DEBUG
        assert sinks["RotatingFileHandler"] == logging.DEBUG
        assert sinks["LogListHandler"] == logging.DEBUG
        assert sinks["StreamHandler"] == logging.DEBUG

    def test_the_saved_level_becomes_the_level_in_force(self, settings_save):
        """Whoever asks the dial afterwards must get the level just saved."""
        settings_save(log_level=2)

        assert comicarr_logger.current_log_level() == 2
        assert settings_save.config.LOG_LEVEL == 2

    def test_a_clamp_notice_survives_the_level_it_clamps_to(self, settings_save):
        """The one level that hides the notice is the one a clamp lands on.

        A downward clamp resolves to 0, where INFO no longer emits -- so an
        operator whose value was quietly altered would have no record of it.
        WARNING passes at every level by contract, which is the whole reason
        the contract says level 0 is warnings-and-errors rather than silence.
        """
        settings_save(log_level=0)

        settings_save(log_level=-1)

        assert _emitted("out of range")


class TestTheValueIsReadByTheSameRulesAsEverySource:
    @pytest.mark.parametrize("raw, expected", [("2", 2), (0, 0), ("0", 0)])
    def test_a_numeric_string_is_a_level(self, stubbed_save, raw, expected):
        assert stubbed_save(log_level=raw) == {"success": True}
        assert stubbed_save.applied == [expected]
        assert comicarr_logger.current_log_level() == expected

    @pytest.mark.parametrize("raw, clamped", [(5, 2), (-1, 0)])
    def test_out_of_range_clamps_and_persists_the_clamped_value(self, stubbed_save, raw, clamped):
        """A compose file asking for 3 wants maximum verbosity; so does an operator.

        The clamped value is what gets written, so config.ini cannot claim a
        level the running process is not honouring.
        """
        assert stubbed_save(log_level=raw) == {"success": True}

        assert stubbed_save.config.LOG_LEVEL == clamped
        assert stubbed_save.applied == [clamped]

    @pytest.mark.parametrize("raw", ["verbose", "loud", True, 2.5])
    def test_a_non_level_is_refused_rather_than_persisted(self, stubbed_save, raw):
        """Persisting garbage would be ignored at the next start -- silently.

        Startup sources fall through to the next layer instead of refusing to
        boot. An HTTP request has somewhere to put the complaint. "verbose" is
        refused with the rest: it is a flag spelling, never a level name (#620).
        """
        result = stubbed_save(log_level=raw)

        assert result["success"] is False
        assert "LOG_LEVEL must be %s" % ACCEPTED_FORMS == result["error"]
        assert stubbed_save.config.transactions == []
        assert stubbed_save.applied == []

    @pytest.mark.parametrize("name, stored", [("warning", 0), ("info", 1), ("debug", 2), ("DEBUG", 2)])
    def test_a_name_is_accepted_and_persisted_as_its_integer(self, stubbed_save, name, stored):
        """The endpoint is no narrower than the CLI, and config.ini stays typed."""
        assert stubbed_save(log_level=name) == {"success": True}

        assert stubbed_save.config.LOG_LEVEL == stored
        assert stubbed_save.applied == [stored]


class TestTheRunningLevelOnlyFollowsADurableSave:
    def test_the_level_is_persisted_before_it_is_applied(self, stubbed_save, monkeypatch):
        """Live is not enough on its own -- the next start reads the file.

        A reconfigure that ran first would leave a process logging at a level
        no restart will bring back if the write then fails.
        """
        order = []

        def persist(values, configure=True):
            order.append(("persist", values["LOG_LEVEL"]))
            stubbed_save.config.LOG_LEVEL = values["LOG_LEVEL"]
            return True

        monkeypatch.setattr(stubbed_save.config, "apply_transaction", persist)
        monkeypatch.setattr(
            comicarr_logger,
            "configure_log_level",
            lambda level: order.append(("apply", level)),
        )

        stubbed_save(log_level=0)

        assert order == [("persist", 0), ("apply", 0)]

    def test_a_failed_save_leaves_the_running_level_alone(self, stubbed_save):
        stubbed_save.config.persist = False

        result = stubbed_save(log_level=2)

        assert result["success"] is False
        assert stubbed_save.applied == []
        assert comicarr_logger.current_log_level() == 1

    def test_a_save_that_persists_but_cannot_reconfigure_still_succeeds(self, stubbed_save, monkeypatch):
        """The level survives the restart; reporting a failed save would not.

        Rebuilding the handlers can fail on a log directory that has become
        unwritable. Losing the durable write over that is the worse outcome.
        """
        monkeypatch.setattr(
            comicarr_logger,
            "configure_log_level",
            lambda level: (_ for _ in ()).throw(FileNotFoundError("log dir vanished")),
        )

        result = stubbed_save(log_level=2)

        assert result == {"success": True}
        assert stubbed_save.config.LOG_LEVEL == 2

    def test_the_level_is_applied_under_the_config_write_lock(self, stubbed_save, monkeypatch):
        """Writing the level and applying it have to be one step.

        apply_transaction serializes the *writes* on its own, and nothing more:
        two saves racing could persist level 2 and then apply level 1 over it,
        leaving config.ini and the running logger disagreeing about the dial.
        Probed from another thread because the lock is reentrant -- the calling
        thread can always reacquire it, so asking there proves nothing.
        """
        observed = []

        def probe(level):
            taken = []

            def attempt():
                lock = config_transaction_lock()
                acquired = lock.acquire(blocking=False)
                if acquired:
                    lock.release()
                taken.append(acquired)

            other = threading.Thread(target=attempt)
            other.start()
            other.join()
            observed.append(taken[0])

        monkeypatch.setattr(comicarr_logger, "configure_log_level", probe)

        stubbed_save(log_level=2)

        assert observed == [False], "the level was applied outside the config write lock"

    def test_saving_an_unrelated_key_does_not_touch_the_logger(self, stubbed_save):
        assert stubbed_save(check_github=False) == {"success": True}

        assert stubbed_save.applied == []
