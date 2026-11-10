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


logger = logging.getLogger("comicarr")


class LogListHandler(logging.Handler):
    """
    Log handler for Web UI.
    """

    def emit(self, record):
        message = self.format(record)
        message = message.replace("\n", "<br />")
        comicarr.LOGLIST.insert(0, (helpers.now(), message, record.levelname, record.threadName))
        del comicarr.LOGLIST[MAX_LOGLIST_ENTRIES:]


def initLogger(console=True, log_dir=False, init=False, loglevel=1, max_logsize=None, max_logfiles=5):
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
        max_logsize = 1000000
    else:
        if max_logsize is None:
            max_logsize = 1000000

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
    for handler in logger.handlers[:]:
        if isinstance(handler, RFHandler):
            handler.close()
        elif isinstance(handler, logging.StreamHandler):
            handler.flush()

        logger.removeHandler(handler)

    logger.propagate = False

    threshold = logging.INFO if init is True else threshold_for_level(loglevel)
    logger.setLevel(threshold)

    loglist_handler = LogListHandler()
    loglist_handler.setLevel(threshold)
    logger.addHandler(loglist_handler)

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

    if console:
        console_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s :: %(name)s.%(funcName)s.%(lineno)s : %(threadName)s : %(message)s",
            "%d-%b-%Y %H:%M:%S",
        )
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(threshold)

        logger.addHandler(console_handler)

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
        try:
            message = "".join(traceback.format_exception(*exception_info))
            logger.error("Uncaught exception: %s", message)
        except Exception:
            pass

        if pass_original:
            sys.__excepthook__(*exception_info)

    if global_exceptions:
        sys.excepthook = excepthook

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

        threading.Thread.__init__ = new_init


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
            handler.acquire()
            try:
                handler.doRollover()
                filename = handler.baseFilename
                if os.path.exists(filename) and os.path.getsize(filename) > 0:
                    raise OSError("log rotation did not complete; the log file may be locked by another process")
            finally:
                handler.release()
            rotated = True
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
