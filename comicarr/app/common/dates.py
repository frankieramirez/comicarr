#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Date/time utilities extracted from helpers.py.

Pure functions — no comicarr imports, no side effects.
"""

import datetime
import time


def today():
    """Return today's date as ISO format string (YYYY-MM-DD)."""
    return datetime.date.isoformat(datetime.date.today())


def now(format_string=None):
    """Return current datetime as formatted string."""
    if format_string is None:
        format_string = "%Y-%m-%d %H:%M:%S"
    return datetime.datetime.now().strftime(format_string)


def utctimestamp():
    """Return current UTC timestamp as float."""
    return time.time()


def utc_date_to_local(run_time):
    """Convert a UTC datetime to local datetime."""
    pr = (run_time - datetime.datetime.utcfromtimestamp(0)).total_seconds()
    try:
        return datetime.datetime.fromtimestamp(int(pr))
    except Exception:
        return datetime.datetime.fromtimestamp(pr)


def convert_milliseconds(ms):
    """Convert milliseconds to HH:MM:SS or MM:SS string."""
    seconds = ms / 1000
    gmtime = time.gmtime(seconds)
    if seconds > 3600:
        return time.strftime("%H:%M:%S", gmtime)
    return time.strftime("%M:%S", gmtime)


def convert_seconds(s):
    """Convert seconds to HH:MM:SS or MM:SS string."""
    gmtime = time.gmtime(s)
    if s > 3600:
        return time.strftime("%H:%M:%S", gmtime)
    return time.strftime("%M:%S", gmtime)
