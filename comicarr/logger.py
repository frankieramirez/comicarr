#  Copyright (C) 2012–2024 Mylar3 contributors
#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Originally based on Mylar3 (https://github.com/mylar3/mylar3).
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

import logging
import logging.handlers
import os
import platform
import sys
import threading
import traceback
from logging import Formatter

import comicarr
from comicarr import helpers

# The Web UI log list is an in-memory ring buffer, so it needs a ceiling.
MAX_LOGLIST_ENTRIES = 2500


def current_log_level():
    """Return the numeric log level, treating startup/unconfigured state as quiet."""
    return comicarr.LOG_LEVEL or 0


def threshold_for_level(loglevel):
    """Map the operator-facing verbosity dial onto a stdlib logging threshold.

    The dial is the *only* verbosity control: whatever it resolves to is applied
    identically to the logger and to every sink it feeds (file, console, Web UI
    list). Level 0 is "warnings and errors", not "silence" — an operator who
    turns the dial down still needs to see that something broke.
    """
    if loglevel is None:
        loglevel = 1
    if loglevel <= 0:
        return logging.WARNING
    if loglevel == 1:
        return logging.INFO
    return logging.DEBUG


# Comicarr logger
logger = logging.getLogger("comicarr")


class LogListHandler(logging.Handler):
    """
    Log handler for Web UI.
    """

    def emit(self, record):
        message = self.format(record)
        message = message.replace("\n", "<br />")
        comicarr.LOGLIST.insert(0, (helpers.now(), message, record.levelname, record.threadName))
        # Bound the buffer. Without this the list grows for the life of the
        # process; a long-running install eventually pays for it in memory.
        del comicarr.LOGLIST[MAX_LOGLIST_ENTRIES:]


def initLogger(console=True, log_dir=False, init=False, loglevel=1, max_logsize=None, max_logfiles=5):
    # concurrentLogHandler/0.8.7 (to deal with windows locks)
    # since this only happens on windows boxes, if it's nix/mac use the default logger.
    if platform.system() == "Windows":
        try:
            from ConcurrentLogHandler.cloghandler import ConcurrentRotatingFileHandler as RFHandler

            comicarr.LOGTYPE = "clog"
        except ImportError:
            comicarr.LOGTYPE = "log"
            from logging.handlers import RotatingFileHandler as RFHandler
    else:
        comicarr.LOGTYPE = "log"
        from logging.handlers import RotatingFileHandler as RFHandler

    if all([init is True, max_logsize is None]):
        max_logsize = 1000000  # 1 MB
    else:
        if max_logsize is None:
            max_logsize = 1000000  # 1 MB

    """
    Setup logging for Comicarr. It uses the logger instance with the name
    'comicarr'. Three log handlers are added:

    * RotatingFileHandler: for the file comicarr.log
    * LogListHandler: for Web UI
    * StreamHandler: for console
    """

    logging.getLogger("apscheduler.scheduler").setLevel(logging.WARN)
    logging.getLogger("apscheduler.threadpool").setLevel(logging.WARN)
    logging.getLogger("apscheduler.scheduler").propagate = False
    logging.getLogger("apscheduler.threadpool").propagate = False
    # Close and remove old handlers. This is required to reinit the loggers
    # at runtime
    for handler in logger.handlers[:]:
        # Just make sure it is cleaned up.
        if isinstance(handler, RFHandler):
            handler.close()
        elif isinstance(handler, logging.StreamHandler):
            handler.flush()

        logger.removeHandler(handler)

    # Configure the logger to accept all messages
    logger.propagate = False

    # One threshold, derived once, applied to the logger and to every sink.
    # Setting it unconditionally matters: the old code left the level alone
    # at loglevel 0, so turning the dial *down* at runtime never took effect
    # and level 0 silently inherited root's WARNING by accident.
    threshold = logging.INFO if init is True else threshold_for_level(loglevel)
    logger.setLevel(threshold)

    # Add list logger
    loglist_handler = LogListHandler()
    loglist_handler.setLevel(threshold)
    logger.addHandler(loglist_handler)

    # Setup file logger
    if log_dir:
        filename = os.path.join(log_dir, "comicarr.log")
        file_formatter = Formatter(
            "%(asctime)s - %(levelname)-7s :: %(name)s.%(funcName)s.%(lineno)s : %(threadName)s : %(message)s",
            "%d-%b-%Y %H:%M:%S",
        )
        file_handler = RFHandler(filename, "a", maxBytes=max_logsize, backupCount=max_logfiles)
        file_handler.setLevel(threshold)
        file_handler.setFormatter(file_formatter)

        logger.addHandler(file_handler)

    # Setup console logger
    if console:
        console_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s :: %(name)s.%(funcName)s.%(lineno)s : %(threadName)s : %(message)s",
            "%d-%b-%Y %H:%M:%S",
        )
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(threshold)

        logger.addHandler(console_handler)

    # Install exception hooks
    initHooks()


def initHooks(global_exceptions=True, thread_exceptions=True, pass_original=True):
    """
    This method installs exception catching mechanisms. Any exception caught
    will pass through the exception hook, and will be logged to the logger as
    an error. Additionally, a traceback is provided.

    This is very useful for crashing threads and any other bugs, that may not
    be exposed when running as daemon.

    The default exception hook is still considered, if pass_original is True.
    """

    def excepthook(*exception_info):
        # We should always catch this to prevent loops!
        try:
            message = "".join(traceback.format_exception(*exception_info))
            logger.error("Uncaught exception: %s", message)
        except Exception:
            pass

        # Original excepthook
        if pass_original:
            sys.__excepthook__(*exception_info)

    # Global exception hook
    if global_exceptions:
        sys.excepthook = excepthook

    # Thread exception hook
    if thread_exceptions:
        old_init = threading.Thread.__init__

        def new_init(self, *args, **kwargs):
            old_init(self, *args, **kwargs)
            old_run = self.run

            def new_run(*args, **kwargs):
                try:
                    old_run(*args, **kwargs)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception:
                    excepthook(*sys.exc_info())

            self.run = new_run

        # Monkey patch the run() by monkey patching the __init__ method
        threading.Thread.__init__ = new_init


# Expose logger methods
info = logger.info
warn = logger.warn
error = logger.error
debug = logger.debug
warning = logger.warning
message = logger.info
exception = logger.exception
fdebug = logger.debug


def rotate_log_file():
    """Start a new log: roll `comicarr.log` over and empty the Web UI buffer.

    From the viewer's perspective clearing and rotating are the same outcome,
    so this is the only verb. The previous file survives as `comicarr.log.1`
    under the normal retention settings — nothing is deleted. Returns True if
    a file handler actually rotated; False means logging runs without a file
    sink (no log_dir), in which case only the buffer is cleared.

    `BaseRotatingHandler` covers both the stdlib `RotatingFileHandler` and the
    `ConcurrentRotatingFileHandler` used on Windows.
    """
    rotated = False
    for handler in logger.handlers:
        if isinstance(handler, logging.handlers.BaseRotatingHandler):
            # The handler lock keeps a concurrent emit() from writing into the
            # file mid-rename.
            handler.acquire()
            try:
                handler.doRollover()
                # The Windows ConcurrentRotatingFileHandler catches a failed
                # rename and "degrades" instead of raising, which would let
                # this report a rotation that never happened. We hold the
                # handler lock, so nothing can have written since the roll:
                # a non-empty current file means the rollover did not land.
                filename = handler.baseFilename
                if os.path.exists(filename) and os.path.getsize(filename) > 0:
                    raise OSError("log rotation did not complete; the log file may be locked by another process")
            finally:
                handler.release()
            rotated = True
    # In place, not rebound: LogListHandler holds no reference of its own, but
    # anything else that grabbed comicarr.LOGLIST must keep seeing new lines.
    del comicarr.LOGLIST[:]
    return rotated


def configure_log_level(level):
    """Reconfigure application logging without depending on a web controller."""
    if level is None:
        level = 1
    comicarr.LOG_LEVEL = level
    initLogger(
        console=True,
        log_dir=comicarr.CONFIG.LOG_DIR,
        max_logsize=comicarr.CONFIG.MAX_LOGSIZE,
        max_logfiles=comicarr.CONFIG.MAX_LOGFILES,
        loglevel=level,
    )
