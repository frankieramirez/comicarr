#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
General-purpose utilities extracted from helpers.py.

Pure functions — no comicarr imports, no side effects.
"""

import hashlib
import re
from operator import itemgetter


def multikeysort(items, columns):
    """Sort a list of dicts by multiple keys (prefix with '-' for descending)."""

    comparers = [
        ((itemgetter(col[1:].strip()), -1) if col.startswith("-") else (itemgetter(col.strip()), 1)) for col in columns
    ]

    def comparer(left, right):
        for fn, mult in comparers:
            result = cmp(fn(left), fn(right))
            if result:
                return mult * result
        else:
            return 0

    return sorted(items, cmp=comparer)


def checked(variable):
    """Return 'Checked' if variable is truthy, else empty string."""
    if variable:
        return "Checked"
    else:
        return ""


def radio(variable, pos):
    """Return 'Checked' if variable equals pos, else empty string."""
    if variable == pos:
        return "Checked"
    else:
        return ""


def extract_logline(s):
    """Parse a log line into (timestamp, level, thread, message) tuple."""
    # Default log format
    pattern = re.compile(
        r"(?P<timestamp>.*?)\s\-\s(?P<level>.*?)\s*\:\:\s(?P<thread>.*?)\s\:\s(?P<message>.*)", re.VERBOSE
    )
    match = pattern.match(s)
    if match:
        timestamp = match.group("timestamp")
        level = match.group("level")
        thread = match.group("thread")
        message = match.group("message")
        return (timestamp, level, thread, message)
    else:
        return None


def int_num(s):
    """Convert string to int, falling back to float if needed."""
    try:
        return int(s)
    except ValueError:
        return float(s)


def conversion(value):
    """Decode byte string to unicode using utf-8 or windows-1252."""
    if type(value) == str:
        try:
            value = value.decode("utf-8")
        except:
            value = value.decode("windows-1252")
    return value


def chunker(seq, size):
    """Split a sequence into chunks of given size."""
    # returns a list from a large group of tuples by size (ie. for group in chunker(seq, 3))
    return [seq[pos : pos + size] for pos in range(0, len(seq), size)]


def crc(filename, sys_encoding=None):
    """Return MD5 hex digest of a filename string (not file contents).

    sys_encoding: system encoding string (passed from comicarr.SYS_ENCODING)
    """
    if sys_encoding is None:
        sys_encoding = "utf-8"
    try:
        filename = filename.encode(sys_encoding)
    except UnicodeEncodeError:
        filename = "invalid"
        filename = filename.encode(sys_encoding)

    return hashlib.md5(filename).hexdigest()


def get_the_hash(filepath):
    """Return SHA-1 hash from a torrent file as uppercase hex string."""
    import logging

    import bencode

    log = logging.getLogger("comicarr")

    # Open torrent file
    torrent_file = open(filepath, "rb")
    metainfo = bencode.decode(torrent_file.read())
    info = metainfo["info"]
    thehash = hashlib.sha1(bencode.encode(info)).hexdigest().upper()
    log.info("Hash of file : " + thehash)
    return {"hash": thehash}


def log_that_exception(except_info, db=None, now_func=None, log_dir=None,
                       tail_func=None):
    """Format and store exception info to db and log file.

    Takes dependencies as parameters to stay free of global state.
    The wrapper in helpers.py passes in the comicarr globals.
    """
    import os

    # snip the log here and get the last 100 lines as quick leadup glance.
    leadup = tail_func()

    gather_info = {
        "comicname": except_info.get("comicname", None),
        "issuenumber": except_info.get("issuenumber", None),
        "seriesyear": except_info.get("seriesyear", None),
        "issueid": except_info.get("issueid", None),
        "comicid": except_info.get("comicid", None),
        "searchmode": except_info.get("mode", None),
        "booktype": except_info.get("booktype", None),
        "filename": except_info.get("filename", None),
        "line_num": except_info.get("line_num", None),
        "func_name": except_info.get("func_name", None),
        "error_text": except_info.get("err_text", None),
        "error": except_info.get("err", None),
        "traceback": except_info.get("traceback", None),
    }

    # write it to the exceptions table.
    logdate = now_func()
    db.upsert("exceptions_log", gather_info, {"date": logdate})

    # write the leadup log lines that were tailed above to the external file here...
    from sqlalchemy import select, text

    from comicarr.tables import exceptions_log

    fileline = db.select_one(
        select(text("rowid"), exceptions_log.c.date).select_from(exceptions_log).where(exceptions_log.c.date == logdate)
    )
    with open(os.path.join(log_dir, "specific_" + str(fileline["rowid"]) + ".log"), "w") as f:
        f.writelines(leadup)
        f.write(except_info.get("traceback", None))
