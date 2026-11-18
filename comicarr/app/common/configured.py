#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Common helpers bound to the running configuration.

These wrap pure functions under ``comicarr/app/common/`` with the settings and
globals they need. They moved here from the ``comicarr/helpers.py`` re-export
shim (#1474); the globals they read move to ``AppContext`` in #1478.
"""

from comicarr.app.common.dates import now
from comicarr.app.common.dates import weekly_info as _weekly_info_impl
from comicarr.app.common.filesystem import checkFolder as _checkFolder_impl
from comicarr.app.common.numbers import ISSUE_EXCEPTIONS
from comicarr.app.common.numbers import issuedigits as _issuedigits_impl
from comicarr.app.common.utilities import crc as _crc_impl
from comicarr.app.common.utilities import log_that_exception as _log_that_exception_impl
from comicarr.app.core import db, logger, runtime


def issuedigits(issnum):
    return _issuedigits_impl(issnum, issue_exceptions=ISSUE_EXCEPTIONS, log=logger)


def checkFolder(folderpath=None):
    return _checkFolder_impl(folderpath=folderpath, check_folder=runtime.current().config.CHECK_FOLDER)


def weekly_info(week=None, year=None, current=None):
    return _weekly_info_impl(
        week=week,
        year=year,
        current=current,
        weekfolder_loc=runtime.current().config.WEEKFOLDER_LOC,
        destination_dir=runtime.current().config.DESTINATION_DIR,
        weekfolder_format=runtime.current().config.WEEKFOLDER_FORMAT,
        sched_weekly_last=runtime.current().sched_weekly_last,
    )


def crc(filename):
    return _crc_impl(filename, sys_encoding=runtime.current().sys_encoding)


def log_that_exception(except_info):
    from comicarr.app.system.service import tail_that_log

    return _log_that_exception_impl(
        except_info,
        db=db,
        now_func=now,
        log_dir=runtime.current().config.LOG_DIR,
        tail_func=tail_that_log,
    )
