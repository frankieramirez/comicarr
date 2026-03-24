#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Number/size utilities extracted from helpers.py.

Pure functions — no comicarr imports, no side effects.
"""

import re


def human_size(size_bytes):
    """Format bytes into human-readable file size (e.g., 4.3 MB)."""
    if size_bytes == 1:
        return "1 byte"

    suffixes_table = [("bytes", 0), ("KB", 0), ("MB", 1), ("GB", 2), ("TB", 2), ("PB", 2)]
    num = float(0 if size_bytes is None else size_bytes)
    for suffix, precision in suffixes_table:
        if num < 1024.0:
            break
        num /= 1024.0

    if precision == 0:
        formatted_size = "%d" % num
    else:
        formatted_size = str(round(num, ndigits=precision))

    return "%s %s" % (formatted_size, suffix)


def bytes_to_mb(bytes):
    """Convert bytes to MB string."""
    mb = int(bytes) / 1048576
    return "%.1f MB" % mb


def human2bytes(s):
    """Convert human-readable size string to bytes (e.g., '1G' -> 1073741824)."""
    symbols = ("B", "K", "M", "G", "T", "P", "E", "Z", "Y")
    letter = s[-1:].strip().upper()
    num = re.sub(",", "", s[:-1])
    if num != "0":
        assert float(num) and letter in symbols
        num = float(num)
        prefix = {symbols[0]: 1}
        for i, s in enumerate(symbols[1:]):
            prefix[s] = 1 << (i + 1) * 10
        return int(num * prefix[letter])
    return 0


def decimal_issue(iss):
    """Convert issue number string to integer representation for sorting."""
    iss_find = iss.find(".")
    dec_except = None
    if iss_find == -1:
        if "au" in iss.lower():
            dec_except = "AU"
            decex = iss.lower().find("au")
            deciss = int(iss[:decex]) * 1000
        else:
            deciss = int(iss) * 1000
    else:
        iss_b4dec = iss[:iss_find]
        iss_decval = iss[iss_find + 1:]
        if int(iss_decval) == 0:
            iss = iss_b4dec
            issdec = int(iss_decval)
        else:
            if len(iss_decval) == 1:
                iss = iss_b4dec + "." + iss_decval
                issdec = int(iss_decval) * 10
            else:
                iss = iss_b4dec + "." + iss_decval.rstrip("0")
                issdec = int(iss_decval.rstrip("0")) * 10
        deciss = (int(iss_b4dec) * 1000) + issdec
    return deciss, dec_except


def is_number(s):
    """Check if a value is numeric."""
    try:
        float(s)
    except (ValueError, TypeError):
        return False
    return True
