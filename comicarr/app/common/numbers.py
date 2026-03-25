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
        iss_decval = iss[iss_find + 1 :]
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


def issuedigits(issnum, issue_exceptions=None, log=None):
    """Convert issue number string to integer for sorting.

    Handles special issue types (AU, INH, NOW, BEY, MU, etc.),
    decimal issues, alpha-numeric issues, and unicode fractions.

    issue_exceptions: list of known alpha suffixes (passed from comicarr.ISSUE_EXCEPTIONS)
    log: logger instance (passed from comicarr logger)
    """
    if log is None:
        import logging

        log = logging.getLogger("comicarr")

    if issue_exceptions is None:
        issue_exceptions = []

    int_issnum = None

    try:
        issnum.isdigit()
    except Exception:
        try:
            isstest = str(issnum)
            isstest.isdigit()
        except Exception:
            return 9999999999
        else:
            issnum = str(issnum)

    if issnum.isdigit():
        int_issnum = int(issnum) * 1000
    else:
        try:
            if "au" in issnum.lower() and issnum[:1].isdigit():
                int_issnum = (int(issnum[:-2]) * 1000) + ord("a") + ord("u")
            elif "ai" in issnum.lower() and issnum[:1].isdigit():
                int_issnum = (int(issnum[:-2]) * 1000) + ord("a") + ord("i")
            elif "inh" in issnum.lower():
                remdec = issnum.find(".")  # find the decimal position.
                if remdec == -1:
                    int_issnum = (int(issnum[:-3]) * 1000) + ord("i") + ord("n") + ord("h")
                else:
                    int_issnum = (int(issnum[:-4]) * 1000) + ord("i") + ord("n") + ord("h")
            elif "now" in issnum.lower():
                if "!" in issnum:
                    issnum = re.sub(r"\!", "", issnum)
                remdec = issnum.find(".")  # find the decimal position.
                if remdec == -1:
                    int_issnum = (int(issnum[:-3]) * 1000) + ord("n") + ord("o") + ord("w")
                else:
                    int_issnum = (int(issnum[:-4]) * 1000) + ord("n") + ord("o") + ord("w")
            elif "bey" in issnum.lower():
                remdec = issnum.find(".")  # find the decimal position.
                if remdec == -1:
                    int_issnum = (int(issnum[:-3]) * 1000) + ord("b") + ord("e") + ord("y")
                else:
                    int_issnum = (int(issnum[:-4]) * 1000) + ord("b") + ord("e") + ord("y")
            elif "mu" in issnum.lower():
                remdec = issnum.find(".")
                if remdec == -1:
                    int_issnum = (int(issnum[:-2]) * 1000) + ord("m") + ord("u")
                else:
                    int_issnum = (int(issnum[:-3]) * 1000) + ord("m") + ord("u")
            elif "lr" in issnum.lower():
                remdec = issnum.find(".")
                if remdec == -1:
                    int_issnum = (int(issnum[:-2]) * 1000) + ord("l") + ord("r")
                else:
                    int_issnum = (int(issnum[:-3]) * 1000) + ord("l") + ord("r")
            elif "hu" in issnum.lower():
                remdec = issnum.find(".")  # find the decimal position.
                if remdec == -1:
                    int_issnum = (int(issnum[:-2]) * 1000) + ord("h") + ord("u")
                else:
                    int_issnum = (int(issnum[:-3]) * 1000) + ord("h") + ord("u")
            elif "black" in issnum.lower():
                remdec = issnum.find(".")  # find the decimal position.
                if remdec != -1:
                    issnum = "%s %s" % (issnum[:remdec], issnum[remdec + 1 :])
            elif "deaths" in issnum.lower():
                remdec = issnum.find(".")  # find the decimal position.
                if remdec == -1:
                    int_issnum = (
                        (int(issnum[:-6]) * 1000) + ord("d") + ord("e") + ord("a") + ord("t") + ord("h") + ord("s")
                    )
                else:
                    int_issnum = (
                        (int(issnum[:-7]) * 1000) + ord("d") + ord("e") + ord("a") + ord("t") + ord("h") + ord("s")
                    )

        except ValueError as e:
            log.error("[" + issnum + "] Unable to properly determine the issue number. Error: %s", e)
            return 9999999999

        if int_issnum is not None:
            return int_issnum

        if type(issnum) == str:
            vals = {"\xbd": 0.5, "\xbc": 0.25, "\xbe": 0.75, "\u221e": 9999999999, "\xe2": 9999999999}
        else:
            vals = {"\xbd": 0.5, "\xbc": 0.25, "\xbe": 0.75, "\\u221e": 9999999999, "\xe2": 9999999999}

        x = [vals[key] for key in vals if key in issnum]

        if x:
            chk = re.sub("[^0-9]", "", issnum).strip()
            if len(chk) == 0:
                int_issnum = x[0] * 1000
            else:
                int_issnum = (int(re.sub("[^0-9]", "", issnum).strip()) + x[0]) * 1000
        else:
            if any(["." in issnum, "," in issnum]):
                if "," in issnum:
                    issnum = re.sub(",", ".", issnum)
                issst = str(issnum).find(".")
                if issst == 0:
                    issb4dec = 0
                else:
                    issb4dec = str(issnum)[:issst]
                decis = str(issnum)[issst + 1 :]
                if len(decis) == 1:
                    decisval = int(decis) * 10
                    issaftdec = str(decisval)
                elif len(decis) == 2:
                    decisval = int(decis)
                    issaftdec = str(decisval)
                else:
                    decisval = decis
                    issaftdec = str(decisval)
                # if there's a trailing decimal (ie. 1.50.) and it's either intentional or not, blow it away.
                if issaftdec[-1:] == ".":
                    issaftdec = issaftdec[:-1]
                try:
                    int_issnum = (int(issb4dec) * 1000) + (int(issaftdec) * 10)
                except ValueError:
                    try:
                        ordtot = 0
                        if any(ext == issaftdec.upper() for ext in issue_exceptions):
                            inu = 0
                            while inu < len(issaftdec):
                                ordtot += ord(issaftdec[inu].lower())  # lower-case the letters for simplicty
                                inu += 1
                            int_issnum = (int(issb4dec) * 1000) + ordtot
                    except Exception as e:
                        log.warning("error: %s" % e)
                        ordtot = 0
                    if ordtot == 0:
                        int_issnum = 999999999999999
            elif all(["[" in issnum, "]" in issnum]):
                issnum_tmp = issnum.find("[")
                int_issnum = int(issnum[:issnum_tmp].strip()) * 1000
                issnum[issnum_tmp + 1 : issnum.find("]")]
            else:
                try:
                    x = float(issnum)
                    # validity check
                    if x < 0:
                        int_issnum = (int(x) * 1000) - 1
                    elif bool(x):
                        log.debug("Infinity issue found.")
                        int_issnum = 9999999999 * 1000
                    else:
                        raise ValueError
                except ValueError:
                    # this will account for any alpha in a issue#, so long as it doesn't have decimals.
                    x = 0
                    tstord = None
                    issno = None
                    invchk = "false"
                    if issnum.lower() != "preview":
                        while x < len(issnum):
                            if issnum[x].isalpha():
                                # take first occurance of alpha in string and carry it through
                                tstord = issnum[x:].rstrip()
                                tstord = re.sub(r"[\-\,\.\+]", "", tstord).rstrip()
                                issno = issnum[:x].rstrip()
                                issno = re.sub(r"[\-\,\.\+]", "", issno).rstrip()
                                try:
                                    float(issno)
                                except ValueError:
                                    if len(issnum) == 1 and issnum.isalpha():
                                        break
                                    issno = None
                                    tstord = None
                                    invchk = "true"
                                break
                            x += 1
                    if tstord is not None and issno is not None:
                        a = 0
                        ordtot = 0
                        if len(issnum) == 1 and issnum.isalpha():
                            int_issnum = ord(tstord.lower())
                        else:
                            while a < len(tstord):
                                ordtot += ord(tstord[a].lower())  # lower-case the letters for simplicty
                                a += 1
                            int_issnum = (int(issno) * 1000) + ordtot
                    elif invchk == "true":
                        if any(
                            [
                                issnum.lower() == "alpha",
                                issnum.lower() == "omega",
                                issnum.lower() == "fall",
                                issnum.lower() == "spring",
                                issnum.lower() == "summer",
                                issnum.lower() == "winter",
                            ]
                        ):
                            inu = 0
                            ordtot = 0
                            while inu < len(issnum):
                                ordtot += ord(issnum[inu].lower())  # lower-case the letters for simplicty
                                inu += 1
                            int_issnum = ordtot
                        else:
                            log.debug("this does not have an issue # that I can parse properly.")
                            return 999999999999999
                    else:
                        match = re.match(r"(?P<first>\d+)\s?[-&/\\]\s?(?P<last>\d+)", issnum)
                        if match:
                            first_num, last_num = map(int, match.groups())
                            if last_num > first_num:
                                int_issnum = (first_num * 1000) + int(((last_num - first_num) * 0.5) * 1000)
                            else:
                                int_issnum = (first_num * 1000) + (0.5 * 1000)
                        elif issnum == "9-5":
                            issnum = "9\xbd"
                            log.debug("issue: 9-5 is an invalid entry. Correcting to : " + issnum)
                            int_issnum = (9 * 1000) + (0.5 * 1000)
                        elif issnum == "2 & 3":
                            log.debug("issue: 2 & 3 is an invalid entry. Ensuring things match up")
                            int_issnum = (2 * 1000) + (0.5 * 1000)
                        elif issnum == "4 & 5":
                            log.debug("issue: 4 & 5 is an invalid entry. Ensuring things match up")
                            int_issnum = (4 * 1000) + (0.5 * 1000)
                        elif issnum == "112/113":
                            int_issnum = (112 * 1000) + (0.5 * 1000)
                        elif issnum == "14-16":
                            int_issnum = (15 * 1000) + (0.5 * 1000)
                        elif issnum == "380/381":
                            int_issnum = (380 * 1000) + (0.5 * 1000)
                        elif issnum.lower() == "preview":
                            inu = 0
                            ordtot = 0
                            while inu < len(issnum):
                                ordtot += ord(issnum[inu].lower())  # lower-case the letters for simplicty
                                inu += 1
                            int_issnum = ordtot
                        else:
                            log.error(issnum + " this has an alpha-numeric in the issue # which I cannot account for.")
                            return 999999999999999

    return int_issnum


def sizeof_fmt(num, suffix="B"):
    """Format byte size with binary suffix (e.g., KiB, MiB, GiB)."""
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, "Yi", suffix)
