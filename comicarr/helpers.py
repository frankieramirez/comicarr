#  Copyright (C) 2012–2024 Mylar3 contributors
#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Originally based on Mylar3 (https://github.com/mylar3/mylar3).
# -*- coding: utf-8 -*-
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

import calendar
import ctypes
import datetime
import errno
import hashlib
import json
import os
import platform
import queue
import re
import shlex
import shutil
import subprocess
import sys
import time
import zipfile
from collections import namedtuple
from datetime import date, timedelta
from operator import itemgetter
from pathlib import Path
from urllib.parse import urljoin

import rarfile
import requests
import sqlalchemy
from PIL import Image
from sqlalchemy import Integer, case, cast, delete, func, select, text, update

import comicarr
from comicarr import db, getcomics, getimage, nzbget, process, sabnzbd
from comicarr.downloaders import mediafire, mega, pixeldrain
from comicarr.tables import (
    annuals,
    comics,
    ddl_info,
    exceptions_log,
    issues,
    jobhistory,
    oneoffhistory,
    ref32p,
    snatched,
    storyarcs,
    weekly,
)

from . import logger


def is_path_within_allowed_dirs(path):
    """Check if a path is within the configured comic directories.
    Uses os.path.realpath + os.path.commonpath to prevent path traversal."""
    import comicarr

    real_path = os.path.realpath(path)
    for root in [comicarr.CONFIG.DESTINATION_DIR, comicarr.CONFIG.COMIC_DIR]:
        if not root:
            continue
        real_root = os.path.realpath(root)
        try:
            if os.path.commonpath([real_root, real_path]) == real_root:
                return True
        except ValueError:
            continue
    return False


def multikeysort(items, columns):

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
    if variable:
        return "Checked"
    else:
        return ""


def radio(variable, pos):

    if variable == pos:
        return "Checked"
    else:
        return ""


def latinToAscii(unicrap):
    """
    From couch potato
    """
    xlate = {
        0xC0: "A",
        0xC1: "A",
        0xC2: "A",
        0xC3: "A",
        0xC4: "A",
        0xC5: "A",
        0xC6: "Ae",
        0xC7: "C",
        0xC8: "E",
        0xC9: "E",
        0xCA: "E",
        0xCB: "E",
        0x86: "e",
        0xCC: "I",
        0xCD: "I",
        0xCE: "I",
        0xCF: "I",
        0xD0: "Th",
        0xD1: "N",
        0xD2: "O",
        0xD3: "O",
        0xD4: "O",
        0xD5: "O",
        0xD6: "O",
        0xD8: "O",
        0xD9: "U",
        0xDA: "U",
        0xDB: "U",
        0xDC: "U",
        0xDD: "Y",
        0xDE: "th",
        0xDF: "ss",
        0xE0: "a",
        0xE1: "a",
        0xE2: "a",
        0xE3: "a",
        0xE4: "a",
        0xE5: "a",
        0xE6: "ae",
        0xE7: "c",
        0xE8: "e",
        0xE9: "e",
        0xEA: "e",
        0xEB: "e",
        0x0259: "e",
        0xEC: "i",
        0xED: "i",
        0xEE: "i",
        0xEF: "i",
        0xF0: "th",
        0xF1: "n",
        0xF2: "o",
        0xF3: "o",
        0xF4: "o",
        0xF5: "o",
        0xF6: "o",
        0xF8: "o",
        0xF9: "u",
        0xFA: "u",
        0xFB: "u",
        0xFC: "u",
        0xFD: "y",
        0xFE: "th",
        0xFF: "y",
        0xA1: "!",
        0xA2: "{cent}",
        0xA3: "{pound}",
        0xA4: "{currency}",
        0xA5: "{yen}",
        0xA6: "|",
        0xA7: "{section}",
        0xA8: "{umlaut}",
        0xA9: "{C}",
        0xAA: "{^a}",
        0xAB: "<<",
        0xAC: "{not}",
        0xAD: "-",
        0xAE: "{R}",
        0xAF: "_",
        0xB0: "{degrees}",
        0xB1: "{+/-}",
        0xB2: "{^2}",
        0xB3: "{^3}",
        0xB4: "'",
        0xB5: "{micro}",
        0xB6: "{paragraph}",
        0xB7: "*",
        0xB8: "{cedilla}",
        0xB9: "{^1}",
        0xBA: "{^o}",
        0xBB: ">>",
        0xBC: "{1/4}",
        0xBD: "{1/2}",
        0xBE: "{3/4}",
        0xBF: "?",
        0xD7: "*",
        0xF7: "/",
    }

    r = ""
    for i in unicrap:
        if ord(i) in xlate:
            r += xlate[ord(i)]
        elif ord(i) >= 0x80:
            pass
        else:
            r += str(i)
    return r


def convert_milliseconds(ms):

    seconds = ms / 1000
    gmtime = time.gmtime(seconds)
    if seconds > 3600:
        minutes = time.strftime("%H:%M:%S", gmtime)
    else:
        minutes = time.strftime("%M:%S", gmtime)

    return minutes


def convert_seconds(s):

    gmtime = time.gmtime(s)
    if s > 3600:
        minutes = time.strftime("%H:%M:%S", gmtime)
    else:
        minutes = time.strftime("%M:%S", gmtime)

    return minutes


def today():
    today = datetime.date.today()
    yyyymmdd = datetime.date.isoformat(today)
    return yyyymmdd


def now(format_string=None):
    now = datetime.datetime.now()
    if format_string is None:
        format_string = "%Y-%m-%d %H:%M:%S"
    return now.strftime(format_string)


def utctimestamp():
    return time.time()


def bytes_to_mb(bytes):

    mb = int(bytes) / 1048576
    size = "%.1f MB" % mb
    return size


def utc_date_to_local(run_time):
    pr = (run_time - datetime.datetime.utcfromtimestamp(0)).total_seconds()
    try:
        run_it = datetime.datetime.fromtimestamp(int(pr))
    except Exception:
        run_it = datetime.datetime.fromtimestamp(pr)
    return run_it


def human_size(size_bytes):
    """
    format a size in bytes into a 'human' file size, e.g. bytes, KB, MB, GB, TB, PB
    Note that bytes/KB will be reported in whole numbers but MB and above will have greater precision
    e.g. 1 byte, 43 bytes, 443 KB, 4.3 MB, 4.43 GB, etc
    """
    if size_bytes == 1:
        # because I really hate unnecessary plurals
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


def human2bytes(s):
    """
    >>> human2bytes('1M')
    1048576
    >>> human2bytes('1G')
    1073741824
    """
    symbols = ("B", "K", "M", "G", "T", "P", "E", "Z", "Y")
    letter = s[-1:].strip().upper()
    num = re.sub(",", "", s[:-1])
    # assert num.isdigit() and letter in symbols
    # use below assert statement to handle sizes with decimal places
    if num != "0":
        assert float(num) and letter in symbols
        num = float(num)
        prefix = {symbols[0]: 1}
        for i, s in enumerate(symbols[1:]):
            prefix[s] = 1 << (i + 1) * 10
        return int(num * prefix[letter])
    else:
        return 0


def replace_all(text, dic):
    for i, j in dic.items():
        if all([j != "None", j is not None]):
            text = text.replace(i, j)
    return text.rstrip()


def cleanName(string):

    pass1 = latinToAscii(string).lower()
    out_string = re.sub('[\\/\\@\\#\\$\\%\\^\\*\\+"\\[\\]\\{\\}\\<\\>\\=\\_]', " ", pass1)  # .encode('utf-8')

    return out_string


def cleanTitle(title):

    title = re.sub(r"[\.\-\/\_]", " ", title).lower()

    # Strip out extra whitespace
    title = " ".join(title.split())

    title = title.title()

    return title


def extract_logline(s):
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


def is_number(s):
    try:
        float(s)
    except (ValueError, TypeError):
        return False
    else:
        return True


def decimal_issue(iss):
    iss_find = iss.find(".")
    dec_except = None
    if iss_find == -1:
        # no matches for a decimal, assume we're converting from decimal to int.
        # match for special issues with alphanumeric numbering...
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


def rename_param(comicid, comicname, issue, ofilename, comicyear=None, issueid=None, annualize=None, arc=False):
    comicid = str(comicid)  # it's coming in unicoded...

    logger.fdebug(type(comicid))
    logger.fdebug(type(issueid))
    logger.fdebug("comicid: %s" % comicid)
    logger.fdebug("issue# as per cv: %s" % issue)

    if issueid is None:
        logger.fdebug("annualize is " + str(annualize))
        if arc:
            chkissue = db.select_one(
                select(storyarcs).where(storyarcs.c.ComicID == comicid, storyarcs.c.IssueNumber == issue)
            )
        else:
            chkissue = db.select_one(select(issues).where(issues.c.ComicID == comicid, issues.c.Issue_Number == issue))
            if all([chkissue is None, annualize is None, not comicarr.CONFIG.ANNUALS_ON]):
                chkissue = db.select_one(
                    select(annuals).where(
                        annuals.c.ComicID == comicid, annuals.c.Issue_Number == issue, annuals.c.Deleted != 1
                    )
                )

        if chkissue is None:
            if arc:
                chkissue = db.select_one(
                    select(storyarcs).where(
                        storyarcs.c.ComicID == comicid, storyarcs.c.Int_IssueNumber == issuedigits(issue)
                    )
                )
            else:
                chkissue = db.select_one(
                    select(issues).where(issues.c.ComicID == comicid, issues.c.Int_IssueNumber == issuedigits(issue))
                )
                if all([chkissue is None, annualize == "yes", comicarr.CONFIG.ANNUALS_ON]):
                    chkissue = db.select_one(
                        select(annuals).where(
                            annuals.c.ComicID == comicid,
                            annuals.c.Int_IssueNumber == issuedigits(issue),
                            annuals.c.Deleted != 1,
                        )
                    )

            if chkissue is None:
                logger.error("Invalid Issue_Number - please validate.")
                return
            else:
                logger.info("Int Issue_number compare found. continuing...")
                issueid = chkissue["IssueID"]
        else:
            issueid = chkissue["IssueID"]

    # use issueid to get publisher, series, year, issue number
    logger.fdebug("issueid is now : " + str(issueid))
    if arc:
        issuenzb = db.select_one(
            select(storyarcs).where(
                storyarcs.c.ComicID == comicid, storyarcs.c.IssueID == issueid, storyarcs.c.StoryArc == arc
            )
        )
    else:
        issuenzb = db.select_one(select(issues).where(issues.c.ComicID == comicid, issues.c.IssueID == issueid))
        if issuenzb is None:
            logger.fdebug("not an issue, checking against annuals")
            issuenzb = db.select_one(
                select(annuals).where(
                    annuals.c.ComicID == comicid, annuals.c.IssueID == issueid, annuals.c.Deleted != 1
                )
            )
            if issuenzb is None:
                logger.fdebug("Unable to rename - cannot locate issue id within db")
                return
            else:
                annualize = True

    if issuenzb is None:
        logger.fdebug("Unable to rename - cannot locate issue id within db")
        return

    # remap the variables to a common factor.
    if arc:
        issuenum = issuenzb["IssueNumber"]
        issuedate = issuenzb["IssueDate"]
        publisher = issuenzb["IssuePublisher"]
        series = issuenzb["ComicName"]
        seriesfilename = series  # Alternate FileNaming is not available with story arcs.
        seriesyear = issuenzb["SeriesYear"]
        arcdir = filesafe(issuenzb["StoryArc"])
        if comicarr.CONFIG.REPLACE_SPACES:
            arcdir = arcdir.replace(" ", comicarr.CONFIG.REPLACE_CHAR)
        if comicarr.CONFIG.STORYARCDIR:
            if comicarr.CONFIG.STORYARC_LOCATION is None:
                storyarcd = os.path.join(comicarr.CONFIG.DESTINATION_DIR, "StoryArcs", arcdir)
            else:
                storyarcd = os.path.join(comicarr.CONFIG.STORYARC_LOCATION, arcdir)
            logger.fdebug("Story Arc Directory set to : " + storyarcd)
        else:
            logger.fdebug("Story Arc Directory set to : " + comicarr.CONFIG.GRABBAG_DIR)
            storyarcd = os.path.join(comicarr.CONFIG.DESTINATION_DIR, comicarr.CONFIG.GRABBAG_DIR)

        comlocation = storyarcd
        comversion = None  # need to populate this.

    else:
        issuenum = issuenzb["Issue_Number"]
        issuedate = issuenzb["IssueDate"]
        comicnzb = db.select_one(select(comics).where(comics.c.ComicID == comicid))
        publisher = comicnzb["ComicPublisher"]
        series = comicnzb["ComicName"]
        if any([comicnzb["AlternateFileName"] is None, comicnzb["AlternateFileName"] == "None"]) or all(
            [comicnzb["AlternateFileName"] is not None, comicnzb["AlternateFileName"].strip() == ""]
        ):
            seriesfilename = series
        else:
            seriesfilename = comicnzb["AlternateFileName"]
            logger.fdebug(
                "Alternate File Naming has been enabled for this series. Will rename series title to : "
                + seriesfilename
            )
        seriesyear = comicnzb["ComicYear"]
        comlocation = comicnzb["ComicLocation"]
        comversion = comicnzb["ComicVersion"]

    unicodeissue = issuenum

    if type(issuenum) == str:
        vals = {"\xbd": ".5", "\xbc": ".25", "\xbe": ".75", "\u221e": "9999999999", "\xe2": "9999999999"}
    else:
        vals = {"\xbd": ".5", "\xbc": ".25", "\xbe": ".75", "\\u221e": "9999999999", "\xe2": "9999999999"}
    x = [vals[key] for key in vals if key in issuenum]
    if x:
        issuenum = x[0]
        logger.fdebug("issue number formatted: %s" % issuenum)

    # comicid = issuenzb['ComicID']
    # issueno = str(issuenum).split('.')[0]
    issue_except = "None"
    valid_spaces = (".", "-")
    for issexcept in comicarr.ISSUE_EXCEPTIONS:
        if issexcept.lower() in issuenum.lower():
            logger.fdebug("ALPHANUMERIC EXCEPTION : [" + issexcept + "]")
            v_chk = [v for v in valid_spaces if v in issuenum]
            if v_chk:
                iss_space = v_chk[0]
                logger.fdebug("character space denoted as : " + iss_space)
            else:
                logger.fdebug("character space not denoted.")
                iss_space = ""
            #                    if issexcept == 'INH':
            #                       issue_except = '.INH'
            if issexcept == "NOW":
                if "!" in issuenum:
                    issuenum = re.sub(r"\!", "", issuenum)
            #                       issue_except = '.NOW'

            issue_except = iss_space + issexcept
            logger.fdebug("issue_except denoted as : %s" % issue_except)
            if issuenum.lower() != issue_except.lower():
                issuenum = re.sub("[^0-9]", "", issuenum)
                if any([issuenum == "", issuenum is None]):
                    issuenum = issue_except
            break

    #            if 'au' in issuenum.lower() and issuenum[:1].isdigit():
    #                issue_except = ' AU'
    #            elif 'ai' in issuenum.lower() and issuenum[:1].isdigit():
    #                issuenum = re.sub("[^0-9]", "", issuenum)
    #                issue_except = ' AI'
    #            elif 'inh' in issuenum.lower() and issuenum[:1].isdigit():
    #                issuenum = re.sub("[^0-9]", "", issuenum)
    #                issue_except = '.INH'
    #            elif 'now' in issuenum.lower() and issuenum[:1].isdigit():
    #                if '!' in issuenum: issuenum = re.sub('\!', '', issuenum)
    #                issuenum = re.sub("[^0-9]", "", issuenum)
    #                issue_except = '.NOW'
    if "." in issuenum:
        iss_find = issuenum.find(".")
        iss_b4dec = issuenum[:iss_find]
        if iss_find == 0:
            iss_b4dec = "0"
        iss_decval = issuenum[iss_find + 1 :]
        if iss_decval.endswith("."):
            iss_decval = iss_decval[:-1]
        if int(iss_decval) == 0:
            iss = iss_b4dec
            int(iss_decval)
            issueno = iss
        else:
            if len(iss_decval) == 1:
                iss = iss_b4dec + "." + iss_decval
                int(iss_decval) * 10
            else:
                iss = iss_b4dec + "." + iss_decval.rstrip("0")
                int(iss_decval.rstrip("0")) * 10
            issueno = iss_b4dec
    else:
        iss = issuenum
        issueno = iss
    # issue zero-suppression here
    if comicarr.CONFIG.ZERO_LEVEL is False:
        zeroadd = ""
    else:
        if any([comicarr.CONFIG.ZERO_LEVEL_N == "none", comicarr.CONFIG.ZERO_LEVEL_N is None]):
            zeroadd = ""
        elif comicarr.CONFIG.ZERO_LEVEL_N == "0x":
            zeroadd = "0"
        elif comicarr.CONFIG.ZERO_LEVEL_N == "00x":
            zeroadd = "00"

    logger.fdebug("Zero Suppression set to : " + str(comicarr.CONFIG.ZERO_LEVEL_N))
    prettycomiss = None

    if issueno.isalpha():
        logger.fdebug("issue detected as an alpha.")
        prettycomiss = str(issueno)
    else:
        try:
            x = float(issuenum)
            # validity check
            if x < 0:
                logger.info("I've encountered a negative issue #: %s. Trying to accomodate." % issueno)
                prettycomiss = "-" + str(zeroadd) + str(issueno[1:])
            elif x == 9999999999:
                logger.fdebug("Infinity issue found.")
                issuenum = "infinity"
            elif x >= 0:
                pass
            else:
                raise ValueError
        except ValueError:
            logger.warn(
                "Unable to properly determine issue number [ %s] - you should probably log this on github for help."
                % issueno
            )
            return

    if all([prettycomiss is None, len(str(issueno)) > 0]):
        # if int(issueno) < 0:
        #    self._log("issue detected is a negative")
        #    prettycomiss = '-' + str(zeroadd) + str(abs(issueno))
        if int(issueno) < 10:
            logger.fdebug("issue detected less than 10")
            if "." in iss:
                if int(iss_decval) > 0:
                    issueno = str(iss)
                    prettycomiss = str(zeroadd) + str(iss)
                else:
                    prettycomiss = str(zeroadd) + str(int(issueno))
            else:
                prettycomiss = str(zeroadd) + str(iss)
            if issue_except != "None":
                prettycomiss = str(prettycomiss) + issue_except
            logger.fdebug(
                "Zero level supplement set to "
                + str(comicarr.CONFIG.ZERO_LEVEL_N)
                + ". Issue will be set as : "
                + str(prettycomiss)
            )
        elif int(issueno) >= 10 and int(issueno) < 100:
            logger.fdebug("issue detected greater than 10, but less than 100")
            if any(
                [
                    comicarr.CONFIG.ZERO_LEVEL_N == "none",
                    comicarr.CONFIG.ZERO_LEVEL_N is None,
                    comicarr.CONFIG.ZERO_LEVEL is False,
                ]
            ):
                zeroadd = ""
            else:
                zeroadd = "0"
            if "." in iss:
                if int(iss_decval) > 0:
                    issueno = str(iss)
                    prettycomiss = str(zeroadd) + str(iss)
                else:
                    prettycomiss = str(zeroadd) + str(int(issueno))
            else:
                prettycomiss = str(zeroadd) + str(iss)
            if issue_except != "None":
                prettycomiss = str(prettycomiss) + issue_except
            logger.fdebug(
                "Zero level supplement set to "
                + str(comicarr.CONFIG.ZERO_LEVEL_N)
                + ".Issue will be set as : "
                + str(prettycomiss)
            )
        else:
            logger.fdebug("issue detected greater than 100")
            if issuenum == "infinity":
                prettycomiss = "infinity"
            else:
                if "." in iss:
                    if int(iss_decval) > 0:
                        issueno = str(iss)
                prettycomiss = str(issueno)
            if issue_except != "None":
                prettycomiss = str(prettycomiss) + issue_except
            logger.fdebug(
                "Zero level supplement set to "
                + str(comicarr.CONFIG.ZERO_LEVEL_N)
                + ". Issue will be set as : "
                + str(prettycomiss)
            )
    elif len(str(issueno)) == 0:
        prettycomiss = str(issueno)
        logger.fdebug("issue length error - cannot determine length. Defaulting to None:  " + str(prettycomiss))

    logger.fdebug("Pretty Comic Issue is : " + str(prettycomiss))
    if comicarr.CONFIG.UNICODE_ISSUENUMBER:
        logger.fdebug("Setting this to Unicode format as requested: %s" % prettycomiss)
        prettycomiss = unicodeissue

    issueyear = issuedate[:4]
    month = issuedate[5:7].replace("-", "").strip()
    month_name = fullmonth(month)
    if month_name is None:
        month_name = "None"
    logger.fdebug("Issue Year : " + str(issueyear))
    logger.fdebug("Publisher: " + publisher)
    logger.fdebug("Series: " + series)
    logger.fdebug("Year: " + str(seriesyear))
    logger.fdebug("Comic Location: " + comlocation)
    if comversion is None:
        comversion = "None"
    # if comversion is None, remove it so it doesn't populate with 'None'
    if comversion == "None":
        chunk_f_f = re.sub(r"\$VolumeN", "", comicarr.CONFIG.FILE_FORMAT)
        chunk_f = re.compile(r"\s+")
        chunk_file_format = chunk_f.sub(" ", chunk_f_f)
        logger.fdebug("No version # found for series, removing from filename")
        logger.fdebug("new format: " + str(chunk_file_format))
    else:
        chunk_file_format = comicarr.CONFIG.FILE_FORMAT

    if annualize is None:
        chunk_f_f = re.sub(r"\$Annual", "", chunk_file_format)
        chunk_f = re.compile(r"\s+")
        chunk_file_format = chunk_f.sub(" ", chunk_f_f)
        logger.fdebug("not an annual - removing from filename paramaters")
        logger.fdebug("new format: " + str(chunk_file_format))

    else:
        logger.fdebug("chunk_file_format is: " + str(chunk_file_format))
        if comicarr.CONFIG.ANNUALS_ON:
            if "annual" in series.lower():
                if "$Annual" not in chunk_file_format:  # and 'annual' not in ofilename.lower():
                    # if it's an annual, but $annual isn't specified in file_format, we need to
                    # force it in there, by default in the format of $Annual $Issue
                    # prettycomiss = "Annual " + str(prettycomiss)
                    logger.fdebug(
                        "[%s][ANNUALS-ON][ANNUAL IN SERIES][NO ANNUAL FORMAT] prettycomiss: %s" % (series, prettycomiss)
                    )
                else:
                    # because it exists within title, strip it then use formatting tag for placement of wording.
                    chunk_f_f = re.sub(r"\$Annual", "", chunk_file_format)
                    chunk_f = re.compile(r"\s+")
                    chunk_file_format = chunk_f.sub(" ", chunk_f_f)
                    logger.fdebug(
                        "[%s][ANNUALS-ON][ANNUAL IN SERIES][ANNUAL FORMAT] prettycomiss: %s" % (series, prettycomiss)
                    )
            else:
                if "$Annual" not in chunk_file_format:  # and 'annual' not in ofilename.lower():
                    # if it's an annual, but $annual isn't specified in file_format, we need to
                    # force it in there, by default in the format of $Annual $Issue
                    prettycomiss = "Annual %s" % prettycomiss
                    logger.fdebug(
                        "[%s][ANNUALS-ON][ANNUAL NOT IN SERIES][NO ANNUAL FORMAT] prettycomiss: %s"
                        % (series, prettycomiss)
                    )
                else:
                    logger.fdebug(
                        "[%s][ANNUALS-ON][ANNUAL NOT IN SERIES][ANNUAL FORMAT] prettycomiss: %s"
                        % (series, prettycomiss)
                    )

        else:
            # if annuals aren't enabled, then annuals are being tracked as independent series.
            # annualize will be true since it's an annual in the seriesname.
            if "annual" in series.lower():
                if "$Annual" not in chunk_file_format:  # and 'annual' not in ofilename.lower():
                    # if it's an annual, but $annual isn't specified in file_format, we need to
                    # force it in there, by default in the format of $Annual $Issue
                    # prettycomiss = "Annual " + str(prettycomiss)
                    logger.fdebug(
                        "[%s][ANNUALS-OFF][ANNUAL IN SERIES][NO ANNUAL FORMAT] prettycomiss: %s"
                        % (series, prettycomiss)
                    )
                else:
                    # because it exists within title, strip it then use formatting tag for placement of wording.
                    chunk_f_f = re.sub(r"\$Annual", "", chunk_file_format)
                    chunk_f = re.compile(r"\s+")
                    chunk_file_format = chunk_f.sub(" ", chunk_f_f)
                    logger.fdebug(
                        "[%s][ANNUALS-OFF][ANNUAL IN SERIES][ANNUAL FORMAT] prettycomiss: %s" % (series, prettycomiss)
                    )
            else:
                if "$Annual" not in chunk_file_format:  # and 'annual' not in ofilename.lower():
                    # if it's an annual, but $annual isn't specified in file_format, we need to
                    # force it in there, by default in the format of $Annual $Issue
                    prettycomiss = "Annual %s" % prettycomiss
                    logger.fdebug(
                        "[%s][ANNUALS-OFF][ANNUAL NOT IN SERIES][NO ANNUAL FORMAT] prettycomiss: %s"
                        % (series, prettycomiss)
                    )
                else:
                    logger.fdebug(
                        "[%s][ANNUALS-OFF][ANNUAL NOT IN SERIES][ANNUAL FORMAT] prettycomiss: %s"
                        % (series, prettycomiss)
                    )

            logger.fdebug("Annual detected within series title of " + series + ". Not auto-correcting issue #")

    seriesfilename = seriesfilename  # .encode('ascii', 'ignore').strip()
    filebad = [
        ":",
        ",",
        "/",
        "?",
        "!",
        "'",
        '"',
        r"\*",
    ]  # in u_comicname or '/' in u_comicname or ',' in u_comicname or '?' in u_comicname:
    for dbd in filebad:
        if dbd in seriesfilename:
            if any([dbd == "/", dbd == "*"]):
                repthechar = "-"
            else:
                repthechar = ""
            seriesfilename = seriesfilename.replace(dbd, repthechar)
            logger.fdebug("Altering series name due to filenaming restrictions: " + seriesfilename)

    publisher = re.sub("!", "", publisher)

    file_values = {
        "$Series": seriesfilename,
        "$Issue": prettycomiss,
        "$Year": issueyear,
        "$series": series.lower(),
        "$Publisher": publisher,
        "$publisher": publisher.lower(),
        "$VolumeY": "V" + str(seriesyear),
        "$VolumeN": comversion,
        "$monthname": month_name,
        "$month": month,
        "$Annual": "Annual",
    }

    extensions = (".cbr", ".cbz", ".cb7")

    if ofilename.lower().endswith(extensions):
        path, ext = os.path.splitext(ofilename)

    if comicarr.CONFIG.FILE_FORMAT == "":
        logger.fdebug("Rename Files is not enabled - keeping original filename.")
        # check if extension is in nzb_name - will screw up otherwise
        if ofilename.lower().endswith(extensions):
            nfilename = ofilename[:-4]
        else:
            nfilename = ofilename
    else:
        nfilename = replace_all(chunk_file_format, file_values)
        if comicarr.CONFIG.REPLACE_SPACES:
            # comicarr.CONFIG.REPLACE_CHAR ...determines what to replace spaces with underscore or dot
            nfilename = nfilename.replace(" ", comicarr.CONFIG.REPLACE_CHAR)

    nfilename = re.sub(r"[\,\:]", "", nfilename) + ext.lower()
    logger.fdebug("New Filename: " + nfilename)

    if comicarr.CONFIG.LOWERCASE_FILENAMES:
        nfilename = nfilename.lower()
        dst = os.path.join(comlocation, nfilename)
    else:
        dst = os.path.join(comlocation, nfilename)

    logger.fdebug("Source: " + ofilename)
    logger.fdebug("Destination: " + dst)

    rename_this = {"destination_dir": dst, "nfilename": nfilename, "issueid": issueid, "comicid": comicid}

    return rename_this


def apiremove(apistring, apitype):
    if apitype == "nzb":
        value_regex = re.compile("(?<=apikey=)(?P<value>.*?)(?=$)")
        # match = value_regex.search(apistring)
        apiremoved = value_regex.sub("xUDONTNEEDTOKNOWTHISx", apistring)
    else:
        # type = $ to denote end of string
        # type = & to denote up until next api variable
        value_regex1 = re.compile("(?<=%26i=1%26r=)(?P<value>.*?)(?=" + str(apitype) + ")")
        # match = value_regex.search(apistring)
        apiremoved1 = value_regex1.sub("xUDONTNEEDTOKNOWTHISx", apistring)
        value_regex = re.compile("(?<=apikey=)(?P<value>.*?)(?=" + str(apitype) + ")")
        apiremoved = value_regex.sub("xUDONTNEEDTOKNOWTHISx", apiremoved1)

    # need to remove the urlencoded-portions as well in future
    return apiremoved


def remove_apikey(payd, key):
    # payload = some dictionary with payload values
    # key = the key to replace with REDACTED (normally apikey)
    for _k, _v in list(payd.items()):
        payd[key] = "REDACTED"

    return payd


def ComicSort(comicorder=None, sequence=None, imported=None):
    if sequence:
        # if it's on startup, load the sql into a tuple for use to avoid record-locking
        i = 0
        comicsort = db.select_all(select(comics).order_by(comics.c.ComicSortName))
        comicorderlist = []
        comicorder = {}
        comicidlist = []
        if sequence == "update":
            comicarr.COMICSORT["SortOrder"] = None
            comicarr.COMICSORT["LastOrderNo"] = None
            comicarr.COMICSORT["LastOrderID"] = None
        for csort in comicsort:
            if csort["ComicID"] is None:
                pass
            if csort["ComicID"] not in comicidlist:
                if sequence == "startup":
                    comicorderlist.append({"ComicID": csort["ComicID"], "ComicOrder": i})
                elif sequence == "update":
                    comicorderlist.append(
                        {
                            #                    comicarr.COMICSORT['SortOrder'].append({
                            "ComicID": csort["ComicID"],
                            "ComicOrder": i,
                        }
                    )

                comicidlist.append(csort["ComicID"])
                i += 1
        if sequence == "startup":
            if i == 0:
                comicorder["SortOrder"] = {"ComicID": "99999", "ComicOrder": 1}
                comicorder["LastOrderNo"] = 1
                comicorder["LastOrderID"] = 99999
            else:
                comicorder["SortOrder"] = comicorderlist
                comicorder["LastOrderNo"] = i - 1
                comicorder["LastOrderID"] = comicorder["SortOrder"][i - 1]["ComicID"]
            if i < 0:
                i == 0
            logger.info("Sucessfully ordered " + str(i - 1) + " series in your watchlist.")
            return comicorder
        elif sequence == "update":
            comicarr.COMICSORT["SortOrder"] = comicorderlist
            # logger.fdebug('i: %s' % i)
            if i == 0:
                placemnt = 1
            else:
                placemnt = int(i - 1)
            try:
                comicarr.COMICSORT["LastOrderNo"] = placemnt
                comicarr.COMICSORT["LastOrderID"] = comicarr.COMICSORT["SortOrder"][placemnt]["ComicID"]
            except Exception:
                comicorder["SortOrder"] = {"ComicID": "99999", "ComicOrder": 1}
                comicarr.COMICSORT["LastOrderNo"] = 1
                comicarr.COMICSORT["LastOrderID"] = 99999
            return
    else:
        # for new series adds, we already know the comicid, so we set the sortorder to an abnormally high #
        # we DO NOT write to the db to avoid record-locking.
        # if we get 2 999's we're in trouble though.
        sortedapp = []
        if comicorder["LastOrderNo"] == "999":
            lastorderval = int(comicorder["LastOrderNo"]) + 1
        else:
            lastorderval = 999
        sortedapp.append({"ComicID": imported, "ComicOrder": lastorderval})
        comicarr.COMICSORT["SortOrder"] = sortedapp
        comicarr.COMICSORT["LastOrderNo"] = lastorderval
        comicarr.COMICSORT["LastOrderID"] = imported
        return


def fullmonth(monthno):
    # simple numerical to worded month conversion....
    basmonths = {
        "1": "January",
        "2": "February",
        "3": "March",
        "4": "April",
        "5": "May",
        "6": "June",
        "7": "July",
        "8": "August",
        "9": "September",
        "10": "October",
        "11": "November",
        "12": "December",
    }

    monthconv = None

    for numbs in basmonths:
        if int(numbs) == int(monthno):
            monthconv = basmonths[numbs]

    return monthconv


def updateComicLocation():
    # in order for this to work, the ComicLocation MUST be left at the original location.
    # in the config.ini - set LOCMOVE = 1  (to enable this to run on the NEXT startup)
    #                  - set NEWCOMDIR = new ComicLocation
    # after running, set ComicLocation to new location in Configuration GUI

    if comicarr.CONFIG.NEWCOM_DIR is not None:
        logger.info("Performing a one-time mass update to Comic Location")
        # create the root dir if it doesn't exist
        checkdirectory = comicarr.filechecker.validateAndCreateDirectory(comicarr.CONFIG.NEWCOM_DIR, create=True)
        if not checkdirectory:
            logger.warn("Error trying to validate/create directory. Aborting this process at this time.")
            return
        dirlist = db.select_all(select(comics))
        comloc = []

        if dirlist is not None:
            for dl in dirlist:
                u_comicnm = dl["ComicName"]
                # let's remove the non-standard characters here that will break filenaming / searching.
                comicname_folder = filesafe(u_comicnm)

                publisher = re.sub("!", "", dl["ComicPublisher"])  # thanks Boom!
                year = dl["ComicYear"]

                if dl["Corrected_Type"] is not None:
                    booktype = dl["Corrected_Type"]
                else:
                    booktype = dl["Type"]
                if booktype == "Print" or all([booktype != "Print", comicarr.CONFIG.FORMAT_BOOKTYPE is False]):
                    chunk_fb = re.sub(r"\$Type", "", comicarr.CONFIG.FOLDER_FORMAT)
                    chunk_b = re.compile(r"\s+")
                    chunk_folder_format = chunk_b.sub(" ", chunk_fb)
                else:
                    chunk_folder_format = comicarr.CONFIG.FOLDER_FORMAT

                comversion = dl["ComicVersion"]
                if comversion is None:
                    comversion = "None"
                # if comversion is None, remove it so it doesn't populate with 'None'
                if comversion == "None":
                    chunk_f_f = re.sub(r"\$VolumeN", "", chunk_folder_format)
                    chunk_f = re.compile(r"\s+")
                    chunk_folder = chunk_f.sub(" ", chunk_f_f)
                else:
                    chunk_folder = chunk_folder_format

                imprint = dl["PublisherImprint"]
                if any([imprint is None, imprint == "None"]):
                    chunk_f_f = re.sub(r"\$Imprint", "", chunk_folder)
                    chunk_f = re.compile(r"\s+")
                    folderformat = chunk_f.sub(" ", chunk_f_f)
                else:
                    folderformat = chunk_folder

                # do work to generate folder path

                values = {
                    "$Series": comicname_folder,
                    "$Publisher": publisher,
                    "$Imprint": imprint,
                    "$Year": year,
                    "$series": comicname_folder.lower(),
                    "$publisher": publisher.lower(),
                    "$VolumeY": "V" + str(year),
                    "$VolumeN": comversion,
                    "$Type": booktype,
                }

                # set the paths here with the seperator removed allowing for cross-platform altering.
                ccdir = re.sub(r"[\\|/]", "%&", comicarr.CONFIG.NEWCOM_DIR)
                ddir = re.sub(r"[\\|/]", "%&", comicarr.CONFIG.DESTINATION_DIR)
                dlc = re.sub(r"[\\|/]", "%&", dl["ComicLocation"])

                if comicarr.CONFIG.FFTONEWCOM_DIR:
                    # if this is enabled (1) it will apply the Folder_Format to all the new dirs
                    if comicarr.CONFIG.FOLDER_FORMAT == "":
                        comlocation = re.sub(ddir, ccdir, dlc).strip()
                    else:
                        first = replace_all(folderformat, values)
                        if comicarr.CONFIG.REPLACE_SPACES:
                            # comicarr.CONFIG.REPLACE_CHAR ...determines what to replace spaces with underscore or dot
                            first = first.replace(" ", comicarr.CONFIG.REPLACE_CHAR)
                        comlocation = os.path.join(comicarr.CONFIG.NEWCOM_DIR, first).strip()

                else:
                    # DESTINATION_DIR = /mnt/mediavg/Comics
                    # NEWCOM_DIR = /mnt/mediavg/Comics/Comics-1
                    # dl['ComicLocation'] = /mnt/mediavg/Comics/Batman-(2011)
                    comlocation = re.sub(ddir, ccdir, dlc).strip()

                # regenerate the new path location so that it's os.dependent now.
                try:
                    com_done = re.sub("%&", os.sep.encode().decode("unicode-escape"), comlocation).strip()
                except Exception as e:
                    logger.warn("[%s] error during conversion: %s" % (comlocation, e))
                    com_done = comlocation.replace("%&", os.sep).strip()

                comloc.append({"comlocation": com_done, "origlocation": dl["ComicLocation"], "comicid": dl["ComicID"]})

            if len(comloc) > 0:
                # give the information about what we're doing.
                if comicarr.CONFIG.FFTONEWCOM_DIR:
                    logger.info(
                        "FFTONEWCOM_DIR is enabled. Applying the existing folder format to ALL directories regardless of existing location paths"
                    )
                else:
                    logger.info(
                        "FFTONEWCOM_DIR is not enabled. I will keep existing subdirectory paths, and will only change the actual Comic Location in the path."
                    )
                    logger.fdebug(" (ie. /mnt/Comics/Marvel/Hush-(2012) to /mnt/mynewLocation/Marvel/Hush-(2012) ")

                # do the deed.
                for cl in comloc:
                    ctrlVal = {"ComicID": cl["comicid"]}
                    newVal = {"ComicLocation": cl["comlocation"]}
                    db.upsert("Comics", newVal, ctrlVal)
                    logger.fdebug("Updated : " + cl["origlocation"] + " .: TO :. " + cl["comlocation"])
                logger.info(
                    "Updated " + str(len(comloc)) + " series to a new Comic Location as specified in the config.ini"
                )
            else:
                logger.fdebug(
                    "Failed in updating the Comic Locations. Check Folder Format string and/or log the issue."
                )
        else:
            logger.info(
                "There are no series in your watchlist to Update the locations. Not updating anything at this time."
            )
        # set the value to 0 here so we don't keep on doing this...
        comicarr.CONFIG.LOCMOVE = False
        comicarr.CONFIG.writeconfig(values={"locmove": False})
    else:
        logger.info("No new ComicLocation path specified - not updating. Set NEWCOMD_DIR in config.ini")
        # raise cherrypy.HTTPRedirect("config")
    return


def cleanhtml(raw_html):
    # cleanr = re.compile('<.*?>')
    # cleantext = re.sub(cleanr, '', raw_html)
    # return cleantext
    from bs4 import BeautifulSoup

    VALID_TAGS = ["div", "p"]

    soup = BeautifulSoup(raw_html, "html.parser")

    for tag in soup.findAll("p"):
        if tag.name not in VALID_TAGS:
            tag.replaceWith(tag.renderContents())
    flipflop = soup.renderContents()
    print(flipflop)
    return flipflop


def issuedigits(issnum):
    # import db

    int_issnum = None

    try:
        issnum.isdigit()
    except:
        try:
            isstest = str(issnum)
            isstest.isdigit()
        except:
            return 9999999999
        else:
            issnum = str(issnum)

    if issnum.isdigit():
        int_issnum = int(issnum) * 1000
    else:
        # count = 0
        # for char in issnum:
        #    if char.isalpha():
        #        count += 1
        # if count > 5:
        #    logger.error('This is not an issue number - not enough numerics to parse')
        #    int_issnum = 999999999999999
        #    return int_issnum
        try:
            if "au" in issnum.lower() and issnum[:1].isdigit():
                int_issnum = (int(issnum[:-2]) * 1000) + ord("a") + ord("u")
            elif "ai" in issnum.lower() and issnum[:1].isdigit():
                int_issnum = (int(issnum[:-2]) * 1000) + ord("a") + ord("i")
            elif "inh" in issnum.lower():
                remdec = issnum.find(".")  # find the decimal position.
                if remdec == -1:
                    # if no decimal, it's all one string
                    # remove the last 3 characters from the issue # (INH)
                    int_issnum = (int(issnum[:-3]) * 1000) + ord("i") + ord("n") + ord("h")
                else:
                    int_issnum = (int(issnum[:-4]) * 1000) + ord("i") + ord("n") + ord("h")
            elif "now" in issnum.lower():
                if "!" in issnum:
                    issnum = re.sub(r"\!", "", issnum)
                remdec = issnum.find(".")  # find the decimal position.
                if remdec == -1:
                    # if no decimal, it's all one string
                    # remove the last 3 characters from the issue # (NOW)
                    int_issnum = (int(issnum[:-3]) * 1000) + ord("n") + ord("o") + ord("w")
                else:
                    int_issnum = (int(issnum[:-4]) * 1000) + ord("n") + ord("o") + ord("w")
            elif "bey" in issnum.lower():
                remdec = issnum.find(".")  # find the decimal position.
                if remdec == -1:
                    # if no decimal, it's all one string
                    # remove the last 3 characters from the issue # (BEY)
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
                    # int_issnum = (int(issnum[:-2]) * 1000) + ord('b') + ord('l')
                # else:
                #    int_issnum = (int(issnum[:-3]) * 1000) + ord('h') + ord('u')
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
            logger.error("[" + issnum + "] Unable to properly determine the issue number. Error: %s", e)
            return 9999999999

        if int_issnum is not None:
            return int_issnum

        # try:
        #    issnum.decode('ascii')
        #    logger.fdebug('ascii character.')
        # except:
        #    logger.fdebug('Unicode character detected: ' + issnum)
        # else: issnum.decode(comicarr.SYS_ENCODING).decode('utf-8')
        # if type(issnum) == str:
        #    try:
        #        issnum = issnum.decode('utf-8')
        #    except:
        #        issnum = issnum.decode('windows-1252')

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
            # logger.fdebug('int_issnum: ' + str(int_issnum))
        else:
            if any(["." in issnum, "," in issnum]):
                # logger.fdebug('decimal detected.')
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
                        if any(ext == issaftdec.upper() for ext in comicarr.ISSUE_EXCEPTIONS):
                            inu = 0
                            while inu < len(issaftdec):
                                ordtot += ord(issaftdec[inu].lower())  # lower-case the letters for simplicty
                                inu += 1
                            int_issnum = (int(issb4dec) * 1000) + ordtot
                    except Exception as e:
                        logger.warn("error: %s" % e)
                        ordtot = 0
                    if ordtot == 0:
                        # logger.error('This has no issue # for me to get - Either a Graphic Novel or one-shot.')
                        int_issnum = 999999999999999
            elif all(["[" in issnum, "]" in issnum]):
                issnum_tmp = issnum.find("[")
                int_issnum = int(issnum[:issnum_tmp].strip()) * 1000
                issnum[issnum_tmp + 1 : issnum.find("]")]
            else:
                try:
                    x = float(issnum)
                    # logger.info(x)
                    # validity check
                    if x < 0:
                        # logger.info("I've encountered a negative issue #: " + str(issnum) + ". Trying to accomodate.")
                        int_issnum = (int(x) * 1000) - 1
                    elif bool(x):
                        logger.fdebug("Infinity issue found.")
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
                                    # logger.fdebug('[' + issno + '] Invalid numeric for issue - cannot be found. Ignoring.')
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
                            logger.fdebug("this does not have an issue # that I can parse properly.")
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
                            logger.fdebug("issue: 9-5 is an invalid entry. Correcting to : " + issnum)
                            int_issnum = (9 * 1000) + (0.5 * 1000)
                        elif issnum == "2 & 3":
                            logger.fdebug("issue: 2 & 3 is an invalid entry. Ensuring things match up")
                            int_issnum = (2 * 1000) + (0.5 * 1000)
                        elif issnum == "4 & 5":
                            logger.fdebug("issue: 4 & 5 is an invalid entry. Ensuring things match up")
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
                            logger.error(
                                issnum + " this has an alpha-numeric in the issue # which I cannot account for."
                            )
                            return 999999999999999

    return int_issnum


def checkthepub(ComicID):
    publishers = ["marvel", "dc", "darkhorse"]
    pubchk = db.select_one(select(comics).where(comics.c.ComicID == ComicID))
    if pubchk is None:
        logger.fdebug(
            "No publisher information found to aid in determining series..defaulting to base check of 55 days."
        )
        return comicarr.CONFIG.BIGGIE_PUB
    else:
        for publish in publishers:
            if publish in pubchk["ComicPublisher"].lower():
                # logger.fdebug('Biggie publisher detected - ' + pubchk['ComicPublisher'])
                return comicarr.CONFIG.BIGGIE_PUB

        # logger.fdebug('Indie publisher detected - ' + pubchk['ComicPublisher'])
        return comicarr.CONFIG.INDIE_PUB


def annual_update():
    annuallist = db.select_all(select(annuals).where(annuals.c.Deleted != 1))
    if annuallist is None:
        logger.info("no annuals to update.")
        return

    cnames = []
    # populate the ComicName field with the corresponding series name from the comics table.
    for ann in annuallist:
        coms = db.select_one(select(comics).where(comics.c.ComicID == ann["ComicID"]))
        cnames.append({"ComicID": ann["ComicID"], "ComicName": coms["ComicName"]})

    # write in a seperate loop to avoid db locks
    i = 0
    for cns in cnames:
        ctrlVal = {"ComicID": cns["ComicID"]}
        newVal = {"ComicName": cns["ComicName"]}
        db.upsert("annuals", newVal, ctrlVal)
        i += 1

    logger.info(str(i) + " series have been updated in the annuals table.")
    return


def replacetheslash(data):
    # this is necessary for the cache directory to display properly in IE/FF.
    # os.path.join will pipe in the '\' in windows, which won't resolve
    # when viewing through cherrypy - so convert it and viola.
    if platform.system() == "Windows":
        slashreplaced = data.replace("\\", "/")
    else:
        slashreplaced = data
    return slashreplaced


def urlretrieve(urlfile, fpath):
    chunk = 4096
    f = open(fpath, "w")
    while 1:
        data = urlfile.read(chunk)
        if not data:
            print("done.")
            break
        f.write(data)
        print("Read %s bytes" % len(data))


def renamefile_readingorder(readorder):
    logger.fdebug("readingorder#: " + str(readorder))
    if int(readorder) < 10:
        readord = "00" + str(readorder)
    elif int(readorder) >= 10 and int(readorder) <= 99:
        readord = "0" + str(readorder)
    else:
        readord = str(readorder)

    return readord


def latestdate_fix():
    datefix = []
    cnupdate = []
    comiclist = db.select_all(select(comics))
    if comiclist is None:
        logger.fdebug("No Series in watchlist to correct latest date")
        return
    for cl in comiclist:
        if cl["ComicName_Filesafe"] is None:
            cnupdate.append({"comicid": cl["ComicID"], "comicname_filesafe": filesafe(cl["ComicName"])})
        latestdate = cl["LatestDate"]
        # logger.fdebug("latestdate:  " + str(latestdate))
        try:
            if latestdate[8:] == "":
                # logger.fdebug("invalid date " + str(latestdate) + " appending 01 for day to avoid errors")
                if len(latestdate) <= 7:
                    finddash = latestdate.find("-")
                    # logger.info('dash found at position ' + str(finddash))
                    if finddash != 4:  # format of mm-yyyy
                        lat_month = latestdate[:finddash]
                        lat_year = latestdate[finddash + 1 :]
                    else:  # format of yyyy-mm
                        lat_month = latestdate[finddash + 1 :]
                        lat_year = latestdate[:finddash]

                    latestdate = (lat_year) + "-" + str(lat_month) + "-01"
                    datefix.append({"comicid": cl["ComicID"], "latestdate": latestdate})
                    # logger.info('latest date: ' + str(latestdate))
        except:
            datefix.append({"comicid": cl["ComicID"], "latestdate": "0000-00-00"})

    # now we fix.
    if len(datefix) > 0:
        logger.info(
            "Preparing to correct/fix "
            + str(len(datefix))
            + " series that have incorrect values given for the Latest Date field."
        )
        for df in datefix:
            newCtrl = {"ComicID": df["comicid"]}
            newVal = {"LatestDate": df["latestdate"]}
            db.upsert("comics", newVal, newCtrl)
    if len(cnupdate) > 0:
        logger.info(
            "Preparing to update " + str(len(cnupdate)) + " series on your watchlist for use with non-ascii characters"
        )
        for cn in cnupdate:
            newCtrl = {"ComicID": cn["comicid"]}
            newVal = {"ComicName_Filesafe": cn["comicname_filesafe"]}
            db.upsert("comics", newVal, newCtrl)

    return


def upgrade_dynamic():
    dynamic_comiclist = []
    # update the comicdb to include the Dynamic Names (and any futher changes as required)
    clist = db.select_all(select(comics))
    for cl in clist:
        cl_d = comicarr.filechecker.FileChecker(watchcomic=cl["ComicName"])
        cl_dyninfo = cl_d.dynamic_replace(cl["ComicName"])
        dynamic_comiclist.append(
            {
                "DynamicComicName": re.sub(r"[\|\s]", "", cl_dyninfo["mod_seriesname"].lower()).strip(),
                "ComicID": cl["ComicID"],
            }
        )

    if len(dynamic_comiclist) > 0:
        for dl in dynamic_comiclist:
            CtrlVal = {"ComicID": dl["ComicID"]}
            newVal = {"DynamicComicName": dl["DynamicComicName"]}
            db.upsert("Comics", newVal, CtrlVal)

    # update the storyarcsdb to include the Dynamic Names (and any futher changes as required)
    dynamic_storylist = []
    rlist = db.select_all(select(storyarcs).where(storyarcs.c.StoryArcID.isnot(None)))
    for rl in rlist:
        comicarr.filechecker.FileChecker(watchcomic=rl["ComicName"])
        rl_dyninfo = cl_d.dynamic_replace(rl["ComicName"])
        dynamic_storylist.append(
            {
                "DynamicComicName": re.sub(r"[\|\s]", "", rl_dyninfo["mod_seriesname"].lower()).strip(),
                "IssueArcID": rl["IssueArcID"],
            }
        )

    if len(dynamic_storylist) > 0:
        for ds in dynamic_storylist:
            CtrlVal = {"IssueArcID": ds["IssueArcID"]}
            newVal = {"DynamicComicName": ds["DynamicComicName"]}
            db.upsert("storyarcs", newVal, CtrlVal)

    logger.info(
        "Finished updating "
        + str(len(dynamic_comiclist))
        + " / "
        + str(len(dynamic_storylist))
        + " entries within the db."
    )
    comicarr.CONFIG.DYNAMIC_UPDATE = 4
    comicarr.CONFIG.writeconfig()
    return


def checkFolder(folderpath=None):
    from comicarr import postprocessor

    queue = queue.Queue()
    # monitor a selected folder for 'snatched' files that haven't been processed
    if folderpath is None:
        logger.info("Checking folder " + comicarr.CONFIG.CHECK_FOLDER + " for newly snatched downloads")
        path = comicarr.CONFIG.CHECK_FOLDER
    else:
        logger.info("Submitted folder " + folderpath + " for direct folder post-processing")
        path = folderpath

    PostProcess = postprocessor.PostProcessor("Manual Run", path, queue=queue)
    PostProcess.Process()
    return


def LoadAlternateSearchNames(seriesname_alt, comicid):
    # seriesname_alt = db.comics['AlternateSearch']
    AS_Alt = []
    Alternate_Names = {}
    alt_count = 0

    # logger.fdebug('seriesname_alt:' + str(seriesname_alt))
    if seriesname_alt is None or seriesname_alt == "None":
        return "no results"
    else:
        chkthealt = seriesname_alt.split("##")
        if chkthealt == 0:
            AS_Alt.append(seriesname_alt)
        for calt in chkthealt:
            AS_Alter = re.sub("##", "", calt)
            u_altsearchcomic = AS_Alter  # .encode('ascii', 'ignore').strip()
            AS_formatrem_seriesname = re.sub(r"\s+", " ", u_altsearchcomic)
            if AS_formatrem_seriesname[:1] == " ":
                AS_formatrem_seriesname = AS_formatrem_seriesname[1:]

            AS_Alt.append({"AlternateName": AS_formatrem_seriesname})
            alt_count += 1

        Alternate_Names["AlternateName"] = AS_Alt
        Alternate_Names["ComicID"] = comicid
        Alternate_Names["Count"] = alt_count
        logger.info("AlternateNames returned:" + str(Alternate_Names))

        return Alternate_Names


def havetotals(refreshit=None):
    # import db

    comics_list = []

    if refreshit is None:
        if comicarr.CONFIG.ANNUALS_ON:
            stmt = (
                select(comics, func.count(annuals.c.IssueID).label("TotalAnnuals"))
                .outerjoin(annuals, annuals.c.ComicID == comics.c.ComicID)
                .group_by(comics.c.ComicID)
                .order_by(comics.c.ComicSortName)
            )
            comiclist = db.select_all(stmt)
        else:
            stmt = select(comics).group_by(comics.c.ComicID).order_by(comics.c.ComicSortName)
            comiclist = db.select_all(stmt)
    else:
        comiclist = []
        stmt = (
            select(
                comics.c.ComicID,
                comics.c.Have,
                comics.c.Total,
                func.count(annuals.c.IssueID).label("TotalAnnuals"),
            )
            .outerjoin(annuals, annuals.c.ComicID == comics.c.ComicID)
            .where(comics.c.ComicID == refreshit)
            .group_by(comics.c.ComicID)
        )
        comicref = db.select_one(stmt)
        # refreshit is the ComicID passed from the Refresh Series to force/check numerical have totals
        comiclist.append(
            {
                "ComicID": comicref["ComicID"],
                "Have": comicref["Have"],
                "Total": comicref["Total"],
                "TotalAnnuals": comicref["TotalAnnuals"],
            }
        )

    for comic in comiclist:
        # --not sure about this part
        # if comic['Total'] is None:
        #    if refreshit is not None:
        #        logger.fdebug(str(comic['ComicID']) + ' has no issuedata available. Forcing complete Refresh/Rescan')
        #        return True
        #    else:
        #        continue
        try:
            totalissues = comic["Total"]
            #                if comicarr.CONFIG.ANNUALS_ON:
            #                    totalissues += comic['TotalAnnuals']
            haveissues = comic["Have"]
        except TypeError:
            logger.warn(
                "[Warning] ComicID: "
                + str(comic["ComicID"])
                + " is incomplete - Removing from DB. You should try to re-add the series."
            )
            with db.get_engine().begin() as conn:
                conn.execute(
                    delete(comics).where(comics.c.ComicID == comic["ComicID"], comics.c.ComicName.like("Comic ID%"))
                )
                conn.execute(
                    delete(issues).where(issues.c.ComicID == comic["ComicID"], issues.c.ComicName.like("Comic ID%"))
                )
            continue

        if not haveissues:
            haveissues = 0

        if refreshit is not None:
            if haveissues > totalissues:
                return True  # if it's 5/4, send back to updater and don't restore previous status'
            else:
                return False  # if it's 5/5 or 4/5, send back to updater and restore previous status'

        if any([haveissues == "None", haveissues is None]):
            haveissues = 0
        if any([totalissues == "None", totalissues is None]):
            totalissues = 0

        try:
            percent = (haveissues * 100.0) / totalissues
            if percent > 100:
                percent = 101
        except (ZeroDivisionError, TypeError):
            percent = 0
            totalissues = "?"

        if comic["LatestDate"] is None:
            logger.warn(
                comic["ComicName"]
                + " has not finished loading. Nulling some values so things display properly until they can populate."
            )
            recentstatus = "Loading"
        elif comic["ComicPublished"] is None or comic["ComicPublished"] == "" or comic["LatestDate"] is None:
            recentstatus = "Unknown"
        elif comic["ForceContinuing"] == 1:
            recentstatus = "Continuing"
        elif "present" in comic["ComicPublished"].lower() or (today()[:4] in comic["LatestDate"]):
            if "Err" in comic["LatestDate"]:
                recentstatus = "Loading"
            else:
                latestdate = comic["LatestDate"]
                # pull-list f'd up the date by putting '15' instead of '2015' causing 500 server errors
                if "-" in latestdate[:3]:
                    st_date = latestdate.find("-")
                    st_remainder = latestdate[st_date + 1 :]
                    st_year = latestdate[:st_date]
                    year = "20" + st_year
                    latestdate = str(year) + "-" + str(st_remainder)
                    # logger.fdebug('year set to: ' + latestdate)
                c_date = datetime.date(int(latestdate[:4]), int(latestdate[5:7]), 1)
                n_date = datetime.date.today()
                recentchk = (n_date - c_date).days
                if comic["NewPublish"] is True:
                    recentstatus = "Continuing"
                else:
                    # do this just incase and as an extra measure of accuracy hopefully.
                    if recentchk < 55:
                        recentstatus = "Continuing"
                    else:
                        recentstatus = "Ended"
        else:
            recentstatus = "Ended"

        if recentstatus == "Loading":
            cpub = comic["ComicPublished"]
        else:
            try:
                cpub = re.sub("(N)", "", comic["ComicPublished"]).strip()
            except Exception as e:
                if comic["cv_removed"] == 0:
                    logger.warn(
                        "[Error: %s] No Publisher found for %s - you probably want to Refresh the series when you get a chance."
                        % (e, comic["ComicName"])
                    )
                cpub = None

        comictype = comic["Type"]
        try:
            if (
                any([comictype == "None", comictype is None, comictype == "Print"])
                and all(
                    [comic["Corrected_Type"] != "TPB", comic["Corrected_Type"] != "GN", comic["Corrected_Type"] != "HC"]
                )
            ) or all([comic["Corrected_Type"] is not None, comic["Corrected_Type"] == "Print"]):
                comictype = None
            else:
                if comic["Corrected_Type"] is not None:
                    comictype = comic["Corrected_Type"]
                else:
                    comictype = comictype
        except:
            comictype = None

        if any([comic["ComicVersion"] is None, comic["ComicVersion"] == "None", comic["ComicVersion"] == ""]):
            cversion = None
        else:
            cversion = comic["ComicVersion"]

        if comic["ComicImage"] is None:
            comicImage = "cache/%s.jpg" % comic["ComicID"]
        else:
            comicImage = comic["ComicImage"]

        # cv_removed: 0 = series is present on CV
        #            1 = series has been removed from CV
        #            2 = series has been removed from CV but retaining what comicarr has in it's db

        comics_list.append(
            {
                "ComicID": comic["ComicID"],
                "ComicName": comic["ComicName"],
                "ComicSortName": comic["ComicSortName"],
                "ComicPublisher": comic["ComicPublisher"],
                "ComicYear": comic["ComicYear"],
                "ComicImage": comicImage,
                "LatestIssue": comic["LatestIssue"],
                "IntLatestIssue": comic["IntLatestIssue"],
                "LatestDate": comic["LatestDate"],
                "ComicVolume": cversion,
                "ComicPublished": cpub,
                "PublisherImprint": comic["PublisherImprint"],
                "Status": comic["Status"],
                "recentstatus": recentstatus,
                "percent": percent,
                "totalissues": totalissues,
                "haveissues": haveissues,
                "DateAdded": comic["LastUpdated"],
                "Type": comic["Type"],
                "Corrected_Type": comic["Corrected_Type"],
                "displaytype": comictype,
                "cv_removed": comic["cv_removed"],
            }
        )
    return comics_list


def filesafe(comic):
    import unicodedata

    if "\u2014" in comic:
        comic = re.sub("\u2014", " - ", comic)
    try:
        u_comic = unicodedata.normalize("NFKD", comic).encode("ASCII", "ignore").strip()
    except TypeError:
        u_comic = comic.encode("ASCII", "ignore").strip()

    # logger.info('comic-type: %s' % type(u_comic))

    if type(u_comic) != bytes:
        comicname_filesafe = re.sub("[\\:'\"\\,\\?\\!\\\\]", "", u_comic)
        comicname_filesafe = re.sub(r"[\/\*]", "-", comicname_filesafe)
    else:
        comicname_filesafe = re.sub("[\\:'\"\\,\\?\\!\\\\]", "", u_comic.decode("utf-8"))
        comicname_filesafe = re.sub(r"[\/\*]", "-", comicname_filesafe)

    return comicname_filesafe


def IssueDetails(filelocation, IssueID=None, justinfo=False, comicname=None):
    import zipfile
    from xml.dom.minidom import parseString

    issuetag = None
    if any([filelocation == "None", filelocation is None]):
        issue_data = comicarr.cv.getComic(None, "single_issue", IssueID)
        IssueImage = getimage.retrieve_image(issue_data["image"])
        metadata_info = {"metadata_source": "ComicVine", "metadata_type": None}
        return {
            "metadata": issue_data,
            "datamode": "single_issue",
            "IssueImage": IssueImage,
            "metadata_source": metadata_info,
        }
    # else:
    #    filelocation = urllib.parse.unquote_plus(filelocation)
    if justinfo is False:
        file_info = getimage.extract_image(filelocation, single=True, imquality="issue", comicname=comicname)
        IssueImage = file_info["ComicImage"]
        data = file_info["metadata"]
        if data:
            issuetag = "xml"
    else:
        IssueImage = "None"
        try:
            with zipfile.ZipFile(filelocation, "r") as inzipfile:
                for infile in sorted(inzipfile.namelist()):
                    if infile == "ComicInfo.xml":
                        logger.fdebug("Found ComicInfo.xml - now retrieving information.")
                        data = inzipfile.read(infile)
                        issuetag = "xml"
                        break
        except:
            metadata_info = {"metadata_source": None, "metadata_type": None}
            logger.info(
                "ERROR. Unable to properly retrieve the cover for displaying. It's probably best to re-tag this file."
            )
            return {"IssueImage": IssueImage, "datamode": "file", "metadata": None, "metadata_source": metadata_info}

    if issuetag is None:
        data = None
        try:
            dz = zipfile.ZipFile(filelocation, "r")
            data = dz.comment
        except:
            metadata_info = {"metadata_source": "ComicVine", "metadata_type": None}
            logger.warn("Unable to extract any metadata from within file.")
            return {"IssueImage": IssueImage, "datamode": "file", "metadata": None, "metadata_source": metadata_info}
        else:
            if data:
                issuetag = "comment"
                metadata_info = {"metadata_source": "ComicVine", "metadata_type": "comicbooklover"}

            else:
                metadata_info = {"metadata_source": None, "metadata_type": None}
                logger.warn("No metadata available in zipfile comment field.")
                return {
                    "IssueImage": IssueImage,
                    "datamode": "file",
                    "metadata": None,
                    "metadata_source": metadata_info,
                }

    logger.info("Tag returned as being: " + str(issuetag))

    if issuetag == "xml":
        # import easy to use xml parser called minidom:
        dom = parseString(data)

        results = dom.getElementsByTagName("ComicInfo")
        metadata_info = {"metadata_source": None, "metadata_type": "comicinfo.xml"}

        for result in results:
            try:
                issue_title = result.getElementsByTagName("Title")[0].firstChild.wholeText
            except:
                issue_title = "None"
            try:
                series_title = result.getElementsByTagName("Series")[0].firstChild.wholeText
            except:
                series_title = "None"
            try:
                series_volume = result.getElementsByTagName("Volume")[0].firstChild.wholeText
            except:
                series_volume = "None"
            try:
                issue_number = result.getElementsByTagName("Number")[0].firstChild.wholeText
            except:
                issue_number = "None"
            try:
                summary = result.getElementsByTagName("Summary")[0].firstChild.wholeText
            except:
                summary = "None"

            if "*List" in summary:
                summary_cut = summary.find("*List")
                summary = summary[:summary_cut]
                # check here to see if Covers exist as they will probably be misnamed when trying to determine the actual cover
                # (ie. 00a.jpg / 00d.jpg  - when there's a Cover A or a Cover D listed)
            try:
                notes = result.getElementsByTagName("Notes")[0].firstChild.wholeText  # IssueID is in here
            except:
                notes = "None"
            else:
                if "CMXID" in notes:
                    mtype = "Comixology"
                elif any(["cvdb" in notes.lower(), "issue id" in notes.lower(), "comic vine" in notes.lower()]):
                    mtype = "ComicVine"
                else:
                    mtype = None
                metadata_info = {"metadata_source": mtype, "metadata_type": "comicinfo.xml"}
            try:
                year = result.getElementsByTagName("Year")[0].firstChild.wholeText
            except:
                year = "None"
            try:
                month = result.getElementsByTagName("Month")[0].firstChild.wholeText
            except:
                month = "None"
            try:
                day = result.getElementsByTagName("Day")[0].firstChild.wholeText
            except:
                day = "None"
            try:
                writer = result.getElementsByTagName("Writer")[0].firstChild.wholeText
            except:
                writer = None
            try:
                penciller = result.getElementsByTagName("Penciller")[0].firstChild.wholeText
            except:
                penciller = None
            try:
                inker = result.getElementsByTagName("Inker")[0].firstChild.wholeText
            except:
                inker = None
            try:
                colorist = result.getElementsByTagName("Colorist")[0].firstChild.wholeText
            except:
                colorist = None
            try:
                letterer = result.getElementsByTagName("Letterer")[0].firstChild.wholeText
            except:
                letterer = None
            try:
                cover_artist = result.getElementsByTagName("CoverArtist")[0].firstChild.wholeText
            except:
                cover_artist = None
            try:
                editor = result.getElementsByTagName("Editor")[0].firstChild.wholeText
            except:
                editor = None
            try:
                publisher = result.getElementsByTagName("Publisher")[0].firstChild.wholeText
            except:
                publisher = "None"
            try:
                webpage = result.getElementsByTagName("Web")[0].firstChild.wholeText
            except:
                webpage = "None"
            try:
                pagecount = result.getElementsByTagName("PageCount")[0].firstChild.wholeText
            except:
                pagecount = 0

            # not used atm.
            # to validate a front cover if it's tagged as one within the zip (some do this)
            # i = 0
            # try:
            #    pageinfo = result.getElementsByTagName('Page')[0].attributes
            #    if pageinfo: pageinfo_test == True
            # except:
            #    pageinfo_test = False

            # if pageinfo_test:
            #    while (i < int(pagecount)):
            #        pageinfo = result.getElementsByTagName('Page')[i].attributes
            #        attrib = pageinfo.getNamedItem('Image')
            #        #logger.fdebug('Frontcover validated as being image #: ' + str(attrib.value))
            #        att = pageinfo.getNamedItem('Type')
            #        #logger.fdebug('pageinfo: ' + str(pageinfo))
            #        if att.value == 'FrontCover':
            #            #logger.fdebug('FrontCover detected. Extracting.')
            #            break
            #        i+=1

    elif issuetag == "comment":
        logger.info("CBL Tagging.")
        stripline = "Archive:  " + filelocation
        data = re.sub(stripline, "", data.decode("utf-8"))  # .strip() #.encode("utf-8")).strip()
        if data is None or data == "":
            return {"IssueImage": IssueImage}
        import ast

        ast_data = ast.literal_eval(str(data))
        ast_data["lastModified"]

        dt = ast_data["ComicBookInfo/1.0"]
        try:
            publisher = dt["publisher"]
        except:
            publisher = None
        try:
            year = dt["publicationYear"]
        except:
            year = None
        try:
            month = dt["publicationMonth"]
        except:
            month = None
        try:
            day = dt["publicationDay"]
        except:
            day = None
        try:
            issue_title = dt["title"]
        except:
            issue_title = None
        try:
            series_title = dt["series"]
        except:
            series_title = None
        try:
            issue_number = dt["issue"]
        except:
            issue_number = None
        try:
            summary = dt["comments"]
        except:
            summary = "None"

        editor = None
        colorist = None
        artist = None
        writer = None
        letterer = None
        cover_artist = None
        penciller = None
        inker = None

        try:
            series_volume = dt["volume"]
        except:
            series_volume = None

        try:
            dt["credits"]
        except:
            pass
        else:
            for cl in dt["credits"]:
                if cl["role"] == "Editor":
                    if editor == "None":
                        editor = cl["person"]
                    else:
                        editor += ", " + cl["person"]
                elif cl["role"] == "Colorist":
                    if colorist == "None":
                        colorist = cl["person"]
                    else:
                        colorist += ", " + cl["person"]
                elif cl["role"] == "Artist":
                    if artist == "None":
                        artist = cl["person"]
                    else:
                        artist += ", " + cl["person"]
                elif cl["role"] == "Writer":
                    if writer == "None":
                        writer = cl["person"]
                    else:
                        writer += ", " + cl["person"]
                elif cl["role"] == "Letterer":
                    if letterer == "None":
                        letterer = cl["person"]
                    else:
                        letterer += ", " + cl["person"]
                elif cl["role"] == "Cover":
                    if cover_artist == "None":
                        cover_artist = cl["person"]
                    else:
                        cover_artist += ", " + cl["person"]
                elif cl["role"] == "Penciller":
                    if penciller == "None":
                        penciller = cl["person"]
                    else:
                        penciller += ", " + cl["person"]
                elif cl["role"] == "Inker":
                    if inker == "None":
                        inker = cl["person"]
                    else:
                        inker += ", " + cl["person"]

        try:
            notes = dt["notes"]
        except:
            notes = "None"
        try:
            webpage = dt["web"]
        except:
            webpage = "None"
        try:
            pagecount = dt["pagecount"]
        except:
            pagecount = "None"

    else:
        logger.warn("Unable to locate any metadata within cbz file. Tag this file and try again if necessary.")
        return

    return {
        "metadata": {
            "title": issue_title,
            "series": series_title,
            "volume": series_volume,
            "issue_number": issue_number,
            "summary": summary,
            "notes": notes,
            "year": year,
            "month": month,
            "day": day,
            "writer": writer,
            "penciller": penciller,
            "inker": inker,
            "colorist": colorist,
            "letterer": letterer,
            "cover_artist": cover_artist,
            "editor": editor,
            "publisher": publisher,
            "webpage": webpage,
            "pagecount": pagecount,
        },
        "IssueImage": IssueImage,
        "datamode": "file",
        "metadata_source": metadata_info,
    }


def get_issue_title(IssueID=None, ComicID=None, IssueNumber=None, IssueArcID=None):
    if IssueID:
        issue = db.select_one(select(issues).where(issues.c.IssueID == IssueID))
        if issue is None:
            issue = db.select_one(select(annuals).where(annuals.c.IssueID == IssueID))
            if issue is None:
                logger.fdebug("Unable to locate given IssueID within the db. Assuming Issue Title is None.")
                return None
    else:
        issue = db.select_one(
            select(issues).where(issues.c.ComicID == ComicID, issues.c.Int_IssueNumber == issuedigits(IssueNumber))
        )
        if issue is None:
            issue = db.select_one(select(annuals).where(annuals.c.IssueID == IssueID))
            if issue is None:
                if IssueArcID:
                    issue = db.select_one(select(storyarcs).where(storyarcs.c.IssueArcID == IssueArcID))
                    if issue is None:
                        logger.fdebug("Unable to locate given IssueID within the db. Assuming Issue Title is None.")
                        return None
                else:
                    logger.fdebug("Unable to locate given IssueID within the db. Assuming Issue Title is None.")
                    return None

    return issue["IssueName"]


def int_num(s):
    try:
        return int(s)
    except ValueError:
        return float(s)


def listPull(weeknumber, year):
    library = {}
    # Get individual comics
    rows = db.select_all(select(weekly.c.ComicID).where(weekly.c.weeknumber == weeknumber, weekly.c.year == year))
    for row in rows:
        library[row["ComicID"]] = row["ComicID"]
    return library


def listLibrary(comicid=None):
    library = {}
    if comicid is None:
        if comicarr.CONFIG.ANNUALS_ON is True:
            stmt = (
                select(
                    comics.c.ComicID,
                    annuals.c.ReleaseComicID,
                    comics.c.Status,
                    comics.c.ComicName,
                    comics.c.ComicYear,
                )
                .outerjoin(annuals, comics.c.ComicID == annuals.c.ComicID)
                .group_by(comics.c.ComicID)
            )
        else:
            stmt = select(comics.c.ComicID, comics.c.Status, comics.c.ComicName, comics.c.ComicYear).group_by(
                comics.c.ComicID
            )
    else:
        cleaned_id = re.sub("4050-", "", comicid).strip()
        if comicarr.CONFIG.ANNUALS_ON is True:
            stmt = (
                select(
                    comics.c.ComicID,
                    annuals.c.ReleaseComicID,
                    comics.c.Status,
                    comics.c.ComicName,
                    comics.c.ComicYear,
                )
                .outerjoin(annuals, comics.c.ComicID == annuals.c.ComicID)
                .where(comics.c.ComicID == cleaned_id)
                .group_by(comics.c.ComicID)
            )
        else:
            stmt = (
                select(comics.c.ComicID, comics.c.Status, comics.c.ComicName, comics.c.ComicYear)
                .where(comics.c.ComicID == cleaned_id)
                .group_by(comics.c.ComicID)
            )

    rows = db.select_all(stmt)
    for row in rows:
        library[row["ComicID"]] = {"comicid": row["ComicID"], "status": row["Status"]}
        try:
            if row["ReleaseComicID"] is not None:
                library[row["ReleaseComicID"]] = {"comicid": row["ComicID"], "status": row["Status"]}
        except:
            pass
        # Also index by normalized (name, year) for cross-provider matching
        try:
            name = row["ComicName"]
            year = row["ComicYear"]
            if name and year:
                # Normalize name: lowercase and strip whitespace
                name_key = "name:" + name.lower().strip() + ":" + str(year).strip()
                library[name_key] = {"comicid": row["ComicID"], "status": row["Status"]}
        except:
            pass

    return library


def listStoryArcs():
    library = {}
    # Get Distinct CV Arc IDs
    stmt = select(storyarcs.c.CV_ArcID).distinct()
    rows = db.select_all(stmt)
    for row in rows:
        library[row["CV_ArcID"]] = {"comicid": row["CV_ArcID"]}
    return library


def listoneoffs(weeknumber, year):
    library = []
    # Get Distinct one-off issues from the pullist that have already been downloaded / snatched
    stmt = (
        select(
            oneoffhistory.c.IssueID,
            oneoffhistory.c.Status,
            oneoffhistory.c.ComicID,
            oneoffhistory.c.ComicName,
            oneoffhistory.c.IssueNumber,
        )
        .distinct()
        .where(
            oneoffhistory.c.weeknumber == weeknumber,
            oneoffhistory.c.year == year,
            oneoffhistory.c.Status.in_(["Downloaded", "Snatched"]),
        )
    )
    rows = db.select_all(stmt)
    for row in rows:
        library.append(
            {
                "IssueID": row["IssueID"],
                "ComicID": row["ComicID"],
                "ComicName": row["ComicName"],
                "IssueNumber": row["IssueNumber"],
                "Status": row["Status"],
                "weeknumber": weeknumber,
                "year": year,
            }
        )
    return library


def manualArc(issueid, reading_order, storyarcid):
    # import db
    if issueid.startswith("4000-"):
        issueid = issueid[5:]

    arc_chk = db.select_all(
        select(storyarcs).where(storyarcs.c.StoryArcID == storyarcid, storyarcs.c.Manual != "deleted")
    )
    storyarcname = arc_chk[0]["StoryArc"]
    storyarcissues = arc_chk[0]["TotalIssues"]

    iss_arcids = []
    for issarc in arc_chk:
        iss_arcids.append(
            {
                "IssueArcID": issarc["IssueArcID"],
                "IssueID": issarc["IssueID"],
                "Manual": issarc["Manual"],
                "ReadingOrder": issarc["ReadingOrder"],
            }
        )

    arc_results = comicarr.cv.getComic(
        comicid=None, rtype="issue", issueid=None, arcid=storyarcid, arclist="M" + str(issueid)
    )
    arcval = arc_results["issuechoice"][0]
    comicname = arcval["ComicName"]
    st_d = comicarr.filechecker.FileChecker(watchcomic=comicname)
    st_dyninfo = st_d.dynamic_replace(comicname)
    dynamic_name = re.sub(r"[\|\s]", "", st_dyninfo["mod_seriesname"].lower()).strip()
    issname = arcval["Issue_Name"]
    issid = str(arcval["IssueID"])
    comicid = str(arcval["ComicID"])
    cidlist = str(comicid)
    st_issueid = None
    manual_mod = "added"
    new_readorder = []
    for aid in iss_arcids:
        if aid["IssueID"] == issid:
            logger.info(
                "Issue already exists for storyarc [IssueArcID:" + aid["IssueArcID"] + "][Manual:" + aid["Manual"]
            )
            st_issueid = aid["IssueArcID"]
            manual_mod = aid["Manual"]

        if reading_order is None:
            # if no reading order is given, drop in the last spot.
            reading_order = len(iss_arcids) + 1
        if int(aid["ReadingOrder"]) >= int(reading_order):
            reading_seq = int(aid["ReadingOrder"]) + 1
        else:
            reading_seq = int(aid["ReadingOrder"])

        new_readorder.append({"IssueArcID": aid["IssueArcID"], "IssueID": aid["IssueID"], "ReadingOrder": reading_seq})

    import random

    if st_issueid is None:
        st_issueid = str(storyarcid) + "_" + str(random.randint(1000, 9999))
    issnum = arcval["Issue_Number"]
    issdate = str(arcval["Issue_Date"])
    storedate = str(arcval["Store_Date"])
    int_issnum = issuedigits(issnum)

    comicid_results = comicarr.cv.getComic(comicid=None, rtype="comicyears", comicidlist=cidlist)
    seriesYear = "None"
    issuePublisher = "None"
    seriesVolume = "None"

    if issname is None:
        IssueName = "None"
    else:
        IssueName = issname[:70]

    for cid in comicid_results:
        if cid["ComicID"] == comicid:
            seriesYear = cid["SeriesYear"]
            issuePublisher = cid["Publisher"]
            seriesVolume = cid["Volume"]
            # assume that the arc is the same
            storyarcpublisher = issuePublisher
            break

    newCtrl = {"IssueID": issid, "StoryArcID": storyarcid}
    newVals = {
        "ComicID": comicid,
        "IssueArcID": st_issueid,
        "StoryArc": storyarcname,
        "ComicName": comicname,
        "Volume": seriesVolume,
        "DynamicComicName": dynamic_name,
        "IssueName": IssueName,
        "IssueNumber": issnum,
        "Publisher": storyarcpublisher,
        "TotalIssues": str(int(storyarcissues) + 1),
        "ReadingOrder": int(
            reading_order
        ),  # arbitrarily set it to the last reading order sequence # just to see if it works.
        "IssueDate": issdate,
        "ReleaseDate": storedate,
        "SeriesYear": seriesYear,
        "IssuePublisher": issuePublisher,
        "CV_ArcID": storyarcid,
        "Int_IssueNumber": int_issnum,
        "Manual": manual_mod,
    }

    db.upsert("storyarcs", newVals, newCtrl)

    # now we resequence the reading-order to accomdate the change.
    logger.info(
        "Adding the new issue into the reading order & resequencing the order to make sure there are no sequence drops..."
    )
    new_readorder.append({"IssueArcID": st_issueid, "IssueID": issid, "ReadingOrder": int(reading_order)})

    newrl = 0
    for rl in sorted(new_readorder, key=itemgetter("ReadingOrder"), reverse=False):
        if rl["ReadingOrder"] - 1 != newrl:
            rorder = newrl + 1
            logger.fdebug(rl["IssueID"] + " - changing reading order seq to : " + str(rorder))
        else:
            rorder = rl["ReadingOrder"]
            logger.fdebug(rl["IssueID"] + " - setting reading order seq to : " + str(rorder))

        rl_ctrl = {"IssueID": rl["IssueID"], "IssueArcID": rl["IssueArcID"], "StoryArcID": storyarcid}
        r1_new = {"ReadingOrder": rorder}
        newrl = rorder

        db.upsert("storyarcs", r1_new, rl_ctrl)

    # check to see if the issue exists already so we can set the status right away.
    iss_chk = db.select_one(select(issues).where(issues.c.IssueID == issueid))
    if iss_chk is None:
        logger.info("Issue is not currently in your watchlist. Setting status to Skipped")
        status_change = "Skipped"
    else:
        status_change = iss_chk["Status"]
        logger.info("Issue currently exists in your watchlist. Setting status to " + status_change)
        db.upsert("storyarcs", {"Status": status_change}, newCtrl)

    return


def listIssues(weeknumber, year):
    library = []
    # Get individual issues
    stmt = (
        select(
            issues.c.Status,
            issues.c.ComicID,
            issues.c.IssueID,
            issues.c.ComicName,
            issues.c.IssueDate,
            issues.c.ReleaseDate,
            weekly.c.PUBLISHER.label("publisher"),
            issues.c.Issue_Number,
        )
        .select_from(weekly.join(issues, weekly.c.IssueID == issues.c.IssueID))
        .where(weekly.c.weeknumber == str(int(weeknumber)), weekly.c.year == str(year))
    )
    rows = db.select_all(stmt)
    for row in rows:
        if row["ReleaseDate"] is None:
            tmpdate = row["IssueDate"]
        else:
            tmpdate = row["ReleaseDate"]
        library.append(
            {
                "ComicID": row["ComicID"],
                "Status": row["Status"],
                "IssueID": row["IssueID"],
                "ComicName": row["ComicName"],
                "Publisher": row["publisher"],
                "Issue_Number": row["Issue_Number"],
                "IssueYear": tmpdate,
            }
        )

    # Add the annuals
    if comicarr.CONFIG.ANNUALS_ON:
        stmt_ann = (
            select(
                annuals.c.Status,
                annuals.c.ComicID,
                annuals.c.ReleaseComicID,
                annuals.c.IssueID,
                annuals.c.ComicName,
                annuals.c.ReleaseDate,
                annuals.c.IssueDate,
                weekly.c.PUBLISHER.label("publisher"),
                annuals.c.Issue_Number,
            )
            .select_from(weekly.join(annuals, weekly.c.IssueID == annuals.c.IssueID))
            .where(weekly.c.weeknumber == str(int(weeknumber)), weekly.c.year == str(year))
        )
        ann_rows = db.select_all(stmt_ann)
        for row in ann_rows:
            if row["ReleaseDate"] is None:
                tmpdate = row["IssueDate"]
            else:
                tmpdate = row["ReleaseDate"]
            library.append(
                {
                    "ComicID": row["ComicID"],
                    "Status": row["Status"],
                    "IssueID": row["IssueID"],
                    "ComicName": row["ComicName"],
                    "Publisher": row["publisher"],
                    "Issue_Number": row["Issue_Number"],
                    "IssueYear": tmpdate,
                }
            )

    # tmplist = library
    # librarylist = []
    # for liblist in tmplist:
    #    lb = myDB.select('SELECT ComicVersion, Type, ComicYear, ComicID from comics WHERE ComicID=?', [liblist['ComicID']])
    #    librarylist.append(liblist)
    #    librarylist.update({'Comic_Volume': lb['ComicVersion'],
    #                        'ComicYear': lb['ComicYear'],
    #                        'ComicType': lb['Type']})
    return library


def incr_snatched(ComicID):
    incr_count = db.select_one(select(comics.c.Have).where(comics.c.ComicID == ComicID))
    logger.fdebug("Incrementing HAVE count total to : " + str(incr_count["Have"] + 1))
    newCtrl = {"ComicID": ComicID}
    newVal = {"Have": incr_count["Have"] + 1}
    db.upsert("comics", newVal, newCtrl)
    return


def duplicate_filecheck(filename, ComicID=None, IssueID=None, StoryArcID=None, rtnval=None):
    # filename = the filename in question that's being checked against
    # comicid = the comicid of the series that's being checked for duplication
    # issueid = the issueid of the issue that's being checked for duplication
    # storyarcid = the storyarcid of the issue that's being checked for duplication.
    # rtnval = the return value of a previous duplicate_filecheck that's re-running against new values
    #
    logger.info("[DUPECHECK] Duplicate check for " + filename)
    try:
        filesz = os.path.getsize(filename)
    except OSError:
        logger.warn(
            "[DUPECHECK] File cannot be located in location specified. Something has moved or altered the name."
        )
        logger.warn(
            "[DUPECHECK] Make sure if you are using ComicRN, you do not have Completed Download Handling enabled (or vice-versa). Aborting"
        )
        return {"action": None}

    if IssueID:
        dupchk = db.select_one(select(issues).where(issues.c.IssueID == IssueID))
    if dupchk is None:
        dupchk = db.select_one(select(annuals).where(annuals.c.IssueID == IssueID, annuals.c.Deleted != 1))
        if dupchk is None:
            logger.info(
                "[DUPECHECK] Unable to find corresponding Issue within the DB. Do you still have the series on your watchlist?"
            )
            return {"action": None}

    series = db.select_one(select(comics).where(comics.c.ComicID == dupchk["ComicID"]))

    # if it's a retry and the file was already snatched, the status is Snatched and won't hit the dupecheck.
    # rtnval will be one of 3:
    #'write' - write new file
    #'dupe_file' - do not write new file as existing file is better quality
    #'dupe_src' - write new file, as existing file is a lesser quality (dupe)

    if dupchk["Status"] == "Downloaded" or dupchk["Status"] == "Archived":
        try:
            dupsize = dupchk["ComicSize"]
        except:
            logger.info(
                "[DUPECHECK] Duplication detection returned no hits as this is a new Snatch. This is not a duplicate."
            )
            rtnval = {"action": "write"}

        logger.info("[DUPECHECK] Existing Status already set to " + dupchk["Status"])
        cid = []
        if dupsize is None:
            logger.info(
                "[DUPECHECK] Existing filesize is 0 bytes as I cannot locate the orginal entry - it is probably archived."
            )
            logger.fdebug("[DUPECHECK] Checking series for unrefreshed series syndrome (USS).")
            havechk = db.select_one(select(comics).where(comics.c.ComicID == ComicID))
            if havechk:
                if havechk["Have"] > havechk["Total"]:
                    logger.info(
                        "[DUPECHECK] Series has invalid issue totals ["
                        + str(havechk["Have"])
                        + "/"
                        + str(havechk["Total"])
                        + "] Attempting to Refresh & continue post-processing this issue."
                    )
                    cid.append(ComicID)
                    logger.fdebug("[DUPECHECK] ComicID: " + str(ComicID))
                    comicarr.updater.dbUpdate(ComicIDList=cid, calledfrom="dupechk")
                    return duplicate_filecheck(filename, ComicID, IssueID, StoryArcID)
                else:
                    if rtnval is not None:
                        if rtnval["action"] == "dont_dupe":
                            logger.fdebug(
                                "[DUPECHECK] File is Archived but no file can be located within the db at the specified location. Assuming this was a manual archival and will not post-process this issue."
                            )
                        return rtnval
                    else:
                        rtnval = {"action": "dont_dupe"}
                        # file is Archived, but no entry exists in the db for the location. Assume Archived, and don't post-process.
                        # quick rescan of files in dir, then rerun the dup check again...
                        comicarr.updater.forceRescan(ComicID)
                        chk1 = duplicate_filecheck(filename, ComicID, IssueID, StoryArcID, rtnval)
                        rtnval = chk1
            else:
                rtnval = {"action": "dupe_file", "to_dupe": os.path.join(series["ComicLocation"], dupchk["Location"])}
        else:
            logger.info(
                "[DUPECHECK] Existing file within db :"
                + dupchk["Location"]
                + " has a filesize of : "
                + str(dupsize)
                + " bytes."
            )

            # keywords to force keep / delete
            # this will be eventually user-controlled via the GUI once the options are enabled.
            fixed = False
            fixed_file = re.findall(r"[(]f\d{1}[)]", filename.lower())
            fixed_db_file = re.findall(r"[(]f\d{1}[)]", dupchk["Location"].lower())
            if all([fixed_file, not fixed_db_file]):
                logger.info(
                    '[DUPECHECK] %s is a "Fixed" version that should be retained over existing version. Bypassing filesize/filetype check.'
                    % filename
                )
                fixed = True
                rtnval = {"action": "dupe_src", "to_dupe": os.path.join(series["ComicLocation"], dupchk["Location"])}
            elif all([fixed_db_file, not fixed_file]):
                logger.info(
                    '[DUPECHECK] %s is a "Fixed" version that should be retained over newly aquired version. Bypassing filesize/filetype check.'
                    % filename
                )
                fixed = True
                rtnval = {"action": "dupe_file", "to_dupe": filename}
            elif all([fixed_file, fixed_db_file]):
                ff_int = int(re.sub("[^0-9]", "", fixed_file).strip())
                fdf_int = int(re.sub("[^0-9]", "", fixed_db_file).strip())
                if ff_int > fdf_int:
                    logger.info(
                        '[DUPECHECK] %s is a higher "Fixed" version (%s) that should be retained over existing version(%s). Bypassing filesize/filetype check.'
                        % (fixed_file, fixed_db_file, filename)
                    )
                    fixed = True
                    rtnval = {
                        "action": "dupe_src",
                        "to_dupe": os.path.join(series["ComicLocation"], dupchk["Location"]),
                    }
                else:
                    logger.info(
                        '[DUPECHECK] %s is a higher "Fixed" version (%s) that should be retained over existing version(%s). Bypassing filesize/filetype check.'
                        % (fixed_db_file, fixed_file, os.path.join(series["ComicLocation"], dupehk["Location"]))
                    )
                    fixed = True
                    rtnval = {"action": "dupe_file", "to_dupe": filename}

            elif int(dupsize) == 0:
                logger.info("[DUPECHECK] Existing filesize is 0 as I cannot locate the original entry.")
                if dupchk["Status"] == "Archived":
                    logger.info("[DUPECHECK] Assuming issue is Archived.")
                    rtnval = {"action": "dupe_file", "to_dupe": filename}
                    return rtnval
                else:
                    logger.info("[DUPECHECK] Assuming 0-byte file - this one is gonna get hammered.")

            logger.fdebug(
                "[DUPECHECK] Based on duplication preferences I will retain based on : "
                + comicarr.CONFIG.DUPECONSTRAINT
            )

            tmp_dupeconstraint = comicarr.CONFIG.DUPECONSTRAINT

            if any(["cbr" in comicarr.CONFIG.DUPECONSTRAINT, "cbz" in comicarr.CONFIG.DUPECONSTRAINT]) and not fixed:
                if "cbr" in comicarr.CONFIG.DUPECONSTRAINT:
                    if filename.endswith(".cbr"):
                        # this has to be configured in config - either retain cbr or cbz.
                        if dupchk["Location"].endswith(".cbr"):
                            logger.info(
                                "[DUPECHECK-CBR PRIORITY] [#"
                                + dupchk["Issue_Number"]
                                + "] BOTH files are in cbr format. Retaining the larger filesize of the two."
                            )
                            tmp_dupeconstraint = "filesize"
                        else:
                            # keep filename
                            logger.info(
                                "[DUPECHECK-CBR PRIORITY] [#"
                                + dupchk["Issue_Number"]
                                + "] Retaining newly scanned in file : "
                                + filename
                            )
                            rtnval = {
                                "action": "dupe_src",
                                "to_dupe": os.path.join(series["ComicLocation"], dupchk["Location"]),
                            }
                    else:
                        if dupchk["Location"].endswith(".cbz"):
                            logger.info(
                                "[DUPECHECK-CBR PRIORITY] [#"
                                + dupchk["Issue_Number"]
                                + "] BOTH files are in cbz format. Retaining the larger filesize of the two."
                            )
                            tmp_dupeconstraint = "filesize"
                        else:
                            # keep filename
                            logger.info(
                                "[DUPECHECK-CBR PRIORITY] [#"
                                + dupchk["Issue_Number"]
                                + "] Retaining newly scanned in file : "
                                + dupchk["Location"]
                            )
                            rtnval = {"action": "dupe_file", "to_dupe": filename}

                elif "cbz" in comicarr.CONFIG.DUPECONSTRAINT:
                    if filename.endswith(".cbr"):
                        if dupchk["Location"].endswith(".cbr"):
                            logger.info(
                                "[DUPECHECK-CBZ PRIORITY] [#"
                                + dupchk["Issue_Number"]
                                + "] BOTH files are in cbr format. Retaining the larger filesize of the two."
                            )
                            tmp_dupeconstraint = "filesize"
                        else:
                            # keep filename
                            logger.info(
                                "[DUPECHECK-CBZ PRIORITY] [#"
                                + dupchk["Issue_Number"]
                                + "] Retaining currently scanned in filename : "
                                + dupchk["Location"]
                            )
                            rtnval = {"action": "dupe_file", "to_dupe": filename}
                    else:
                        if dupchk["Location"].endswith(".cbz"):
                            logger.info(
                                "[DUPECHECK-CBZ PRIORITY] [#"
                                + dupchk["Issue_Number"]
                                + "] BOTH files are in cbz format. Retaining the larger filesize of the two."
                            )
                            tmp_dupeconstraint = "filesize"
                        else:
                            # keep filename
                            logger.info(
                                "[DUPECHECK-CBZ PRIORITY] [#"
                                + dupchk["Issue_Number"]
                                + "] Retaining newly scanned in filename : "
                                + filename
                            )
                            rtnval = {
                                "action": "dupe_src",
                                "to_dupe": os.path.join(series["ComicLocation"], dupchk["Location"]),
                            }

            if not fixed and (comicarr.CONFIG.DUPECONSTRAINT == "filesize" or tmp_dupeconstraint == "filesize"):
                if filesz <= int(dupsize) and int(dupsize) != 0:
                    logger.info(
                        "[DUPECHECK-FILESIZE PRIORITY] [#"
                        + dupchk["Issue_Number"]
                        + "] Retaining currently scanned in filename : "
                        + dupchk["Location"]
                    )
                    rtnval = {"action": "dupe_file", "to_dupe": filename}
                else:
                    logger.info(
                        "[DUPECHECK-FILESIZE PRIORITY] [#"
                        + dupchk["Issue_Number"]
                        + "] Retaining newly scanned in filename : "
                        + filename
                    )
                    rtnval = {
                        "action": "dupe_src",
                        "to_dupe": os.path.join(series["ComicLocation"], dupchk["Location"]),
                    }

    else:
        logger.info(
            "[DUPECHECK] Duplication detection returned no hits. This is not a duplicate of anything that I have scanned in as of yet."
        )
        rtnval = {"action": "write"}
    return rtnval


def create_https_certificates(ssl_cert, ssl_key):
    """
    Create a pair of self-signed HTTPS certificares and store in them in
    'ssl_cert' and 'ssl_key'. Method assumes pyOpenSSL is installed.

    This code is stolen from SickBeard (http://github.com/midgetspy/Sick-Beard).
    """

    from certgen import TYPE_RSA, createCertificate, createCertRequest, createKeyPair, serial
    from OpenSSL import crypto

    # Create the CA Certificate
    cakey = createKeyPair(TYPE_RSA, 2048)
    careq = createCertRequest(cakey, CN="Certificate Authority")
    cacert = createCertificate(careq, (careq, cakey), serial, (0, 60 * 60 * 24 * 365 * 10))  # ten years

    pkey = createKeyPair(TYPE_RSA, 2048)
    req = createCertRequest(pkey, CN="Comicarr")
    cert = createCertificate(req, (cacert, cakey), serial, (0, 60 * 60 * 24 * 365 * 10))  # ten years

    # Save the key and certificate to disk
    try:
        with open(ssl_key, "w") as fp:
            fp.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, pkey))
        os.chmod(ssl_key, 0o600)
        with open(ssl_cert, "w") as fp:
            fp.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
    except IOError as e:
        logger.error("Error creating SSL key and certificate: %s", e)
        return False

    return True


def torrent_create(site, linkid, alt=None):
    if any([site == "32P", site == "TOR"]):
        pass
    # elif site == 'TPSE':
    #    if alt is None:
    #        url = comicarr.TPSEURL + 'torrent/' + str(linkid) + '.torrent'
    #    else:
    #        url = comicarr.TPSEURL + 'torrent/' + str(linkid) + '.torrent'
    elif site == "DEM":
        url = comicarr.DEMURL + "files/download/" + str(linkid) + "/"
    elif site == "WWT":
        url = comicarr.WWTURL + "download.php"

    return url


def parse_32pfeed(rssfeedline):
    KEYS_32P = {}
    if comicarr.CONFIG.ENABLE_32P and len(rssfeedline) > 1:
        userid_st = rssfeedline.find("&user")
        userid_en = rssfeedline.find("&", userid_st + 1)
        if userid_en == -1:
            USERID_32P = rssfeedline[userid_st + 6 :]
        else:
            USERID_32P = rssfeedline[userid_st + 6 : userid_en]

        auth_st = rssfeedline.find("&auth")
        auth_en = rssfeedline.find("&", auth_st + 1)
        if auth_en == -1:
            AUTH_32P = rssfeedline[auth_st + 6 :]
        else:
            AUTH_32P = rssfeedline[auth_st + 6 : auth_en]

        authkey_st = rssfeedline.find("&authkey")
        authkey_en = rssfeedline.find("&", authkey_st + 1)
        if authkey_en == -1:
            AUTHKEY_32P = rssfeedline[authkey_st + 9 :]
        else:
            AUTHKEY_32P = rssfeedline[authkey_st + 9 : authkey_en]

        KEYS_32P = {
            "user": USERID_32P,
            "auth": AUTH_32P,
            "authkey": AUTHKEY_32P,
            "passkey": comicarr.CONFIG.PASSKEY_32P,
        }

    return KEYS_32P


def humanize_time(amount, units="seconds"):

    def process_time(amount, units):

        INTERVALS = [
            1,
            60,
            60 * 60,
            60 * 60 * 24,
            60 * 60 * 24 * 7,
            60 * 60 * 24 * 7 * 4,
            60 * 60 * 24 * 7 * 4 * 12,
            60 * 60 * 24 * 7 * 4 * 12 * 100,
            60 * 60 * 24 * 7 * 4 * 12 * 100 * 10,
        ]
        NAMES = [
            ("second", "seconds"),
            ("minute", "minutes"),
            ("hour", "hours"),
            ("day", "days"),
            ("week", "weeks"),
            ("month", "months"),
            ("year", "years"),
            ("century", "centuries"),
            ("millennium", "millennia"),
        ]

        result = []

        unit = [a[1] for a in NAMES].index(units)
        # Convert to seconds
        amount = amount * INTERVALS[unit]

        for i in range(len(NAMES) - 1, -1, -1):
            a = amount // INTERVALS[i]
            if a > 0:
                result.append((a, NAMES[i][1 % a]))
                amount -= a * INTERVALS[i]

        return result

    rd = process_time(int(amount), units)
    cont = 0
    for u in rd:
        if u[0] > 0:
            cont += 1

    buf = ""
    i = 0
    for u in rd:
        if u[0] > 0:
            buf += "%d %s" % (u[0], u[1])
            cont -= 1

        if i < (len(rd) - 1):
            if cont > 1:
                buf += ", "
            else:
                buf += " and "

        i += 1

    return buf


def issue_status(IssueID):
    IssueID = str(IssueID)

    isschk = db.select_one(select(issues).where(issues.c.IssueID == IssueID))
    if isschk is None:
        isschk = db.select_one(select(annuals).where(annuals.c.IssueID == IssueID, annuals.c.Deleted != 1))
        if isschk is None:
            isschk = db.select_one(select(storyarcs).where(storyarcs.c.IssueArcID == IssueID))
            if isschk is None:
                logger.warn("Unable to retrieve IssueID from db. This is a problem. Aborting.")
                return False

    if any([isschk["Status"] == "Downloaded", isschk["Status"] == "Snatched"]):
        return True
    else:
        return False


def crc(filename):
    # memory in lieu of speed (line by line)
    # prev = 0
    # for eachLine in open(filename,"rb"):
    #    prev = zlib.crc32(eachLine, prev)
    # return "%X"%(prev & 0xFFFFFFFF)

    # speed in lieu of memory (file into memory entirely)
    # return "%X" % (zlib.crc32(open(filename, "rb").read()) & 0xFFFFFFFF)
    try:
        filename = filename.encode(comicarr.SYS_ENCODING)
    except UnicodeEncodeError:
        filename = "invalid"
        filename = filename.encode(comicarr.SYS_ENCODING)

    return hashlib.md5(filename).hexdigest()


def issue_find_ids(ComicName, ComicID, pack, IssueNumber, pack_id):

    # logger.fdebug('pack: %s' % pack)
    issuelist = db.select_all(select(issues).where(issues.c.ComicID == ComicID))

    if "Annual" not in pack:
        if "," not in pack:
            packlist = pack.split(" ")
            pack = re.sub("#", "", pack).strip()
        else:
            packlist = [x.strip() for x in pack.split(",")]
        plist = []
        pack_issues = []
        logger.fdebug("packlist: %s" % packlist)
        for pl in packlist:
            pl = re.sub("#", "", pl).strip()
            if "-" in pl:
                le_range = list(range(int(pack[: pack.find("-")]), int(pack[pack.find("-") + 1 :]) + 1))
                for x in le_range:
                    if not [y for y in plist if y == x]:
                        plist.append(int(x))
                # logger.fdebug('plist: %s' % plist)
            else:
                # logger.fdebug('starting single: %s' % pl)
                if not [x for x in plist if x == int(pl)]:
                    # logger.fdebug('single not present')
                    plist.append(int(pl))
            # logger.fdebug('plist:%s' % plist)

        for pi in plist:
            if type(pi) == list:
                for x in pi:
                    pack_issues.append(x)
            else:
                pack_issues.append(pi)

        pack_issues.sort()
    else:
        # remove the annuals wording
        tmp_annuals = pack[pack.find("Annual") :]
        re.sub("[annual/annuals/+]", "", tmp_annuals.lower()).strip()
        tmp_pack = re.sub("[annual/annuals/+]", "", pack.lower()).strip()
        pack_issues_numbers = re.findall(r"\d+", tmp_pack)
        pack_issues = list(range(int(pack_issues_numbers[0]), int(pack_issues_numbers[1]) + 1))

    issues = {}
    issueinfo = []
    write_valids = []  # to keep track of snatched packs already downloading so we don't re-queue/download again

    Int_IssueNumber = issuedigits(IssueNumber)
    valid = False

    ignores = []
    for iss in pack_issues:
        int_iss = issuedigits(str(iss))
        for xb in issuelist:
            if xb["Status"] != "Downloaded":
                if xb["Int_IssueNumber"] == int_iss:
                    if Int_IssueNumber == xb["Int_IssueNumber"]:
                        valid = True
                    issueinfo.append({"issueid": xb["IssueID"], "int_iss": int_iss, "issuenumber": xb["Issue_Number"]})

                    write_valids.append({"issueid": xb["IssueID"], "pack_id": pack_id})
                    break
            else:
                ignores.append(iss)

    if ignores:
        logger.info(
            "[%s] These issues already exist in the pack and is already in a Downloaded state. Mark the issue as anything"
            "other than Wanted if you want the pack to be downloaded." % ignores
        )

    if valid:
        for wv in write_valids:
            comicarr.PACK_ISSUEIDS_DONT_QUEUE[wv["issueid"]] = wv["pack_id"]

    issues["issues"] = issueinfo
    logger.fdebug("pack_issueids_dont_queue: %s" % comicarr.PACK_ISSUEIDS_DONT_QUEUE)

    if len(issues["issues"]) == len(pack_issues):
        logger.fdebug(
            "Complete issue count of %s issues are available within this pack for %s" % (len(pack_issues), ComicName)
        )
    else:
        logger.fdebug("Issue counts are not complete (not a COMPLETE pack) for %s" % ComicName)

    issues["issue_range"] = pack_issues
    issues["valid"] = valid
    return issues


def reverse_the_pack_snatch(pack_id, comicid):
    logger.info(
        "[REVERSE UNO] Reversal of issues marked as Snatched via pack download reversing due to invalid link retrieval.."
    )
    # logger.fdebug(comicarr.PACK_ISSUEIDS_DONT_QUEUE)
    reverselist = [issueid for issueid, packid in comicarr.PACK_ISSUEIDS_DONT_QUEUE.items() if pack_id == packid]
    for x in reverselist:
        db.upsert("issues", {"Status": "Skipped"}, {"IssueID": x})
    if reverselist:
        logger.info("[REVERSE UNO] Reversal completed for %s issues" % len(reverselist))
        comicarr.GLOBAL_MESSAGES = {
            "status": "success",
            "comicid": comicid,
            "tables": "both",
            "message": "Successfully changed status of %s issues to %s" % (len(reverselist), "Skipped"),
        }


def conversion(value):
    if type(value) == str:
        try:
            value = value.decode("utf-8")
        except:
            value = value.decode("windows-1252")
    return value


def clean_url(url):
    leading = len(url) - len(url.lstrip(" "))
    ending = len(url) - len(url.rstrip(" "))
    if leading >= 1:
        url = url[leading:]
    if ending >= 1:
        url = url[:-ending]
    return url


def chunker(seq, size):
    # returns a list from a large group of tuples by size (ie. for group in chunker(seq, 3))
    return [seq[pos : pos + size] for pos in range(0, len(seq), size)]


def cleanHost(host, protocol=True, ssl=False, username=None, password=None):
    """Return a cleaned up host with given url options set
            taken verbatim from CouchPotato
    Changes protocol to https if ssl is set to True and http if ssl is set to false.
    >>> cleanHost("localhost:80", ssl=True)
    'https://localhost:80/'
    >>> cleanHost("localhost:80", ssl=False)
    'http://localhost:80/'

    Username and password is managed with the username and password variables
    >>> cleanHost("localhost:80", username="user", password="passwd")
    'http://user:passwd@localhost:80/'

    Output without scheme (protocol) can be forced with protocol=False
    >>> cleanHost("localhost:80", protocol=False)
    'localhost:80'
    """

    if "://" not in host and protocol:
        host = ("https://" if ssl else "http://") + host

    if not protocol:
        host = host.split("://", 1)[-1]

    if protocol and username and password:
        try:
            auth = re.findall("^(?:.+?//)(.+?):(.+?)@(?:.+)$", host)
            if auth:
                log.error("Cleanhost error: auth already defined in url: %s, please remove BasicAuth from url.", host)
            else:
                host = host.replace("://", "://%s:%s@" % (username, password), 1)
        except:
            pass

    host = host.rstrip("/ ")
    if protocol:
        host += "/"

    return host


def checkthe_id(comicid=None, up_vals=None):
    if not up_vals:
        chk = db.select_one(select(ref32p).where(ref32p.c.ComicID == comicid))
        if chk is None:
            return None
        else:
            # if updated time hasn't been set or it's > 24 hrs, blank the entry so we can make sure we pull an updated groupid from 32p
            if chk["Updated"] is None:
                logger.fdebug(
                    "Reference found for 32p - but the id has never been verified after populating. Verifying it is still the right id before proceeding."
                )
                return None
            else:
                c_obj_date = datetime.datetime.strptime(chk["Updated"], "%Y-%m-%d %H:%M:%S")
                n_date = datetime.datetime.now()
                absdiff = abs(n_date - c_obj_date)
                hours = (absdiff.days * 24 * 60 * 60 + absdiff.seconds) / 3600.0
                if hours >= 24:
                    logger.fdebug(
                        "Reference found for 32p - but older than 24hours since last checked. Verifying it is still the right id before proceeding."
                    )
                    return None
                else:
                    return {"id": chk["ID"], "series": chk["Series"]}

    else:
        ctrlVal = {"ComicID": comicid}
        newVal = {"Series": up_vals[0]["series"], "ID": up_vals[0]["id"], "Updated": now()}
        db.upsert("ref32p", newVal, ctrlVal)


def updatearc_locs(storyarcid, arc_issues):
    issueid_list = []
    for x in arc_issues:
        issueid_list.append(x["IssueID"])
    stmt = (
        select(
            comics.c.ComicID,
            comics.c.ComicLocation,
            issues.c.ComicID.label("issue_ComicID"),
            issues.c.Status,
            issues.c.IssueID,
            issues.c.Location,
        )
        .select_from(comics.join(issues, comics.c.ComicID == issues.c.ComicID))
        .where(issues.c.IssueID.in_(issueid_list))
    )
    chkthis = db.select_all(stmt)
    update_iss = []
    if chkthis is None:
        return
    else:
        for chk in chkthis:
            if chk["Status"] == "Downloaded":
                pathsrc = os.path.join(chk["ComicLocation"], chk["Location"])
                if not os.path.exists(pathsrc):
                    try:
                        if all(
                            [
                                comicarr.CONFIG.MULTIPLE_DEST_DIRS is not None,
                                comicarr.CONFIG.MULTIPLE_DEST_DIRS != "None",
                            ]
                        ):
                            if os.path.exists(
                                os.path.join(comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(chk["ComicLocation"]))
                            ):
                                secondary_folders = os.path.join(
                                    comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(chk["ComicLocation"])
                                )
                            else:
                                ff = comicarr.filers.FileHandlers(ComicID=chk["ComicID"])
                                secondary_folders = ff.secondary_folders(chk["ComicLocation"])

                            pathsrc = os.path.join(secondary_folders, chk["Location"])
                        else:
                            logger.fdebug(
                                module
                                + " file does not exist in location: "
                                + pathsrc
                                + ". Cannot validate location - some options will not be available for this item."
                            )
                            continue
                    except:
                        continue

                #                update_iss.append({'IssueID':    chk['IssueID'],
                #                                   'Location':   pathdir})
                arcinfo = None
                for la in arc_issues:
                    if la["IssueID"] == chk["IssueID"]:
                        arcinfo = la
                        break

                if arcinfo is None:
                    continue

                if arcinfo["Publisher"] is None:
                    arcpub = arcinfo["IssuePublisher"]
                else:
                    arcpub = arcinfo["Publisher"]

                grdst = arcformat(arcinfo["StoryArc"], spantheyears(arcinfo["StoryArcID"]), arcpub)
                if grdst is not None:
                    logger.info("grdst:" + grdst)
                    # send to renamer here if valid.
                    dfilename = chk["Location"]
                    if comicarr.CONFIG.RENAME_FILES:
                        renamed_file = rename_param(
                            arcinfo["ComicID"],
                            arcinfo["ComicName"],
                            arcinfo["IssueNumber"],
                            chk["Location"],
                            issueid=arcinfo["IssueID"],
                            arc=arcinfo["StoryArc"],
                        )
                        if renamed_file:
                            dfilename = renamed_file["nfilename"]

                    if comicarr.CONFIG.READ2FILENAME:
                        # logger.fdebug('readingorder#: ' + str(arcinfo['ReadingOrder']))
                        # if int(arcinfo['ReadingOrder']) < 10: readord = "00" + str(arcinfo['ReadingOrder'])
                        # elif int(arcinfo['ReadingOrder']) >= 10 and int(arcinfo['ReadingOrder']) <= 99: readord = "0" + str(arcinfo['ReadingOrder'])
                        # else: readord = str(arcinfo['ReadingOrder'])
                        readord = renamefile_readingorder(arcinfo["ReadingOrder"])
                        dfilename = str(readord) + "-" + dfilename

                    pathdst = os.path.join(grdst, dfilename)

                    logger.fdebug("Destination Path : " + pathdst)
                    logger.fdebug("Source Path : " + pathsrc)
                    if not os.path.isdir(grdst):
                        logger.fdebug("[ARC-DIRECTORY] Arc directory doesn't exist. Creating: %s" % grdst)
                        comicarr.filechecker.validateAndCreateDirectory(grdst, create=True)

                    if not os.path.isfile(pathdst):
                        logger.info(
                            "[" + comicarr.CONFIG.ARC_FILEOPS.upper() + "] " + pathsrc + " into directory : " + pathdst
                        )

                        try:
                            # need to ensure that src is pointing to the series in order to do a soft/hard-link properly
                            fileoperation = file_ops(pathsrc, pathdst, arc=True)
                            if not fileoperation:
                                raise OSError
                        except (OSError, IOError):
                            logger.fdebug(
                                "["
                                + comicarr.CONFIG.ARC_FILEOPS.upper()
                                + "] Failure "
                                + pathsrc
                                + " - check directories and manually re-run."
                            )
                            continue
                    updateloc = pathdst
                else:
                    updateloc = pathsrc

                update_iss.append({"IssueID": chk["IssueID"], "Location": updateloc})

    for ui in update_iss:
        logger.info(ui["IssueID"] + " to update location to: " + ui["Location"])
        db.upsert("storyarcs", {"Location": ui["Location"]}, {"IssueID": ui["IssueID"], "StoryArcID": storyarcid})


def spantheyears(storyarcid):
    year_expr = case(
        (
            (storyarcs.c.IssueDate.isnot(None)) & (storyarcs.c.IssueDate != "0000-00-00"),
            cast(func.substr(storyarcs.c.IssueDate, 1, 4), Integer),
        ),
    )
    stmt = (
        select(
            func.min(year_expr).label("min_year"),
            func.max(year_expr).label("max_year"),
            func.min(storyarcs.c.SeriesYear).label("fallback_year"),
        )
        .where(storyarcs.c.StoryArcID == storyarcid)
        .where(storyarcs.c.Manual != "deleted")
    )
    row = db.select_one(stmt)
    if row is None:
        return None

    min_year = row["min_year"]
    max_year = row["max_year"]

    if min_year is None or max_year is None:
        return row["fallback_year"]
    elif min_year == max_year:
        return str(max_year)
    else:
        return "%s - %s" % (min_year, max_year)


def arcformat(arc, spanyears, publisher):
    arcdir = filesafe(arc)
    if publisher is None:
        publisher = "None"

    values = {"$arc": arcdir, "$spanyears": spanyears, "$publisher": publisher}

    tmp_folderformat = comicarr.CONFIG.ARC_FOLDERFORMAT

    if tmp_folderformat is not None:
        if publisher == "None":
            chunk_f_f = re.sub(r"\$publisher", "", tmp_folderformat)
            chunk_f = re.compile(r"\s+")
            tmp_folderformat = chunk_f.sub(" ", chunk_f_f)

    if any([tmp_folderformat == "", tmp_folderformat is None]):
        arcpath = replace_all("$arc ($spanyears)", values)
    else:
        arcpath = replace_all(tmp_folderformat, values)

    if comicarr.CONFIG.REPLACE_SPACES:
        arcpath = arcpath.replace(" ", comicarr.CONFIG.REPLACE_CHAR)

    if arcpath.startswith("/"):
        arcpath = arcpath[1:]
    elif arcpath.startswith("//"):
        arcpath = arcpath[2:]

    if comicarr.CONFIG.STORYARCDIR is True:
        if comicarr.CONFIG.STORYARC_LOCATION is None:
            dstloc = os.path.join(comicarr.CONFIG.DESTINATION_DIR, "StoryArcs", arcpath)
        else:
            dstloc = os.path.join(comicarr.CONFIG.STORYARC_LOCATION, arcpath)
    elif comicarr.CONFIG.COPY2ARCDIR is True:
        logger.warn(
            "Story arc directory is not configured. Defaulting to grabbag directory: " + comicarr.CONFIG.GRABBAG_DIR
        )
        dstloc = os.path.join(comicarr.CONFIG.GRABBAG_DIR, arcpath)
    else:
        dstloc = None

    return dstloc


def torrentinfo(issueid=None, torrent_hash=None, download=False, monitor=False):
    # import db
    from base64 import b16encode, b32decode

    # check the status of the issueid to make sure it's in Snatched status and was grabbed via torrent.
    if issueid:
        stmt = (
            select(
                issues.c.Issue_Number,
                issues.c.ComicName,
                issues.c.Status,
                snatched.c.Hash,
            )
            .select_from(issues.join(snatched, issues.c.IssueID == snatched.c.IssueID))
            .where(issues.c.IssueID == issueid)
        )
        cinfo = db.select_one(stmt)
        if cinfo is None:
            logger.warn("Unable to locate IssueID of : " + issueid)
            snatch_status = "MONITOR ERROR"

        if cinfo["Status"] != "Snatched" or cinfo["Hash"] is None:
            logger.warn(
                cinfo["ComicName"] + " #" + cinfo["Issue_Number"] + " is currently in a " + cinfo["Status"] + " Status."
            )
            snatch_status = "MONITOR ERROR"

        torrent_hash = cinfo["Hash"]

    logger.fdebug("Working on torrent: " + torrent_hash)
    if len(torrent_hash) == 32:
        torrent_hash = b16encode(b32decode(torrent_hash))

    if not len(torrent_hash) == 40:
        logger.error("Torrent hash is missing, or an invalid hash value has been passed")
        snatch_status = "MONITOR ERROR"
    else:
        if comicarr.USE_RTORRENT:
            from . import rtorrent_test_client

            rp = rtorrent_test_client.RTorrent()
            torrent_info = rp.main(torrent_hash, check=True)
        elif comicarr.USE_DELUGE:
            # need to set the connect here as well....
            from comicarr.torrent.clients import deluge as delu

            dp = delu.TorrentClient()
            if not dp.connect(
                comicarr.CONFIG.DELUGE_HOST, comicarr.CONFIG.DELUGE_USERNAME, comicarr.CONFIG.DELUGE_PASSWORD
            ):
                logger.warn("Not connected to Deluge!")

            torrent_info = dp.get_torrent(torrent_hash)
        else:
            snatch_status = "MONITOR ERROR"
            return

    logger.info("torrent_info: %s" % torrent_info)

    if torrent_info is False or len(torrent_info) == 0:
        logger.warn("torrent returned no information. Check logs - aborting auto-snatch at this time.")
        snatch_status = "MONITOR ERROR"
    else:
        if comicarr.USE_DELUGE:
            torrent_status = torrent_info["is_finished"]
            torrent_files = torrent_info["num_files"]
            torrent_folder = torrent_info["save_path"]
            torrent_info["total_filesize"] = torrent_info["total_size"]
            torrent_info["upload_total"] = torrent_info["total_uploaded"]
            torrent_info["download_total"] = torrent_info["total_payload_download"]
            torrent_info["time_started"] = torrent_info["time_added"]

        elif comicarr.USE_RTORRENT:
            torrent_status = torrent_info["completed"]
            torrent_files = len(torrent_info["files"])
            torrent_folder = torrent_info["folder"]

        if all([torrent_status is True, download is True]):
            if not issueid:
                torrent_info["snatch_status"] = "MONITOR STARTING"
                # yield torrent_info

            import shlex
            import subprocess

            logger.info("Torrent is completed and status is currently Snatched. Attempting to auto-retrieve.")
            with open(comicarr.CONFIG.AUTO_SNATCH_SCRIPT, "r") as f:
                first_line = f.readline()

            if comicarr.CONFIG.AUTO_SNATCH_SCRIPT.endswith(".sh"):
                shell_cmd = re.sub("#!", "", first_line)
                if shell_cmd == "" or shell_cmd is None:
                    shell_cmd = "/bin/bash"
            else:
                shell_cmd = sys.executable

            curScriptName = shell_cmd + " " + str(comicarr.CONFIG.AUTO_SNATCH_SCRIPT)  # .decode("string_escape")
            if torrent_files > 1:
                downlocation = torrent_folder
            else:
                if comicarr.USE_DELUGE:
                    downlocation = os.path.join(torrent_folder, torrent_info["files"][0]["path"])
                else:
                    downlocation = torrent_info["files"][0]

            autosnatch_env = os.environ.copy()
            autosnatch_env["downlocation"] = downlocation.replace("'", "\\'")

            # these are pulled from the config and are the ssh values to use to retrieve the data
            autosnatch_env["host"] = comicarr.CONFIG.PP_SSHHOST
            autosnatch_env["port"] = comicarr.CONFIG.PP_SSHPORT
            autosnatch_env["user"] = comicarr.CONFIG.PP_SSHUSER
            autosnatch_env["localcd"] = comicarr.CONFIG.PP_SSHLOCALCD
            # bash won't accept None, so send check and send empty strings for the 2 possible None values if needed
            if comicarr.CONFIG.PP_SSHKEYFILE is not None:
                autosnatch_env["keyfile"] = comicarr.CONFIG.PP_SSHKEYFILE
            else:
                autosnatch_env["keyfile"] = ""
            if comicarr.CONFIG.PP_SSHPASSWD is not None:
                autosnatch_env["passwd"] = comicarr.CONFIG.PP_SSHPASSWD
            else:
                autosnatch_env["passwd"] = ""

            # downlocation = re.sub("\'", "\\'", downlocation)
            # downlocation = re.sub("&", "\&", downlocation)

            script_cmd = shlex.split(curScriptName, posix=False)  # + [downlocation]
            logger.fdebug("Executing command %s" % script_cmd)
            try:
                p = subprocess.Popen(
                    script_cmd,
                    env=dict(autosnatch_env),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=comicarr.PROG_DIR,
                )
                out, err = p.communicate()
                logger.fdebug("Script result: %s" % out)
            except OSError as e:
                logger.warn("Unable to run extra_script: %s" % e)
                snatch_status = "MONITOR ERROR"
            else:
                if "Access failed: No such file" in str(out):
                    logger.fdebug(
                        "Not located in location it is supposed to be in - probably has been moved by some script and I got the wrong location due to timing. Trying again..."
                    )
                    snatch_status = "IN PROGRESS"
                else:
                    snatch_status = "MONITOR COMPLETE"  # COMPLETED
                torrent_info["completed"] = torrent_status
                torrent_info["files"] = torrent_files
                torrent_info["folder"] = torrent_folder
                torrent_info["copied_filepath"] = os.path.join(comicarr.CONFIG.PP_SSHLOCALCD, torrent_info["name"])
                torrent_info["snatch_status"] = snatch_status
        else:
            if download is True:
                snatch_status = "IN PROGRESS"
            elif monitor is True:
                # pause the torrent, copy it to the cache folder, unpause the torrent and return the complete path to the cache location
                if comicarr.USE_DELUGE:
                    pauseit = dp.stop_torrent(torrent_hash)
                    if pauseit is False:
                        logger.warn("Unable to pause torrent - cannot run post-process on item at this time.")
                        snatch_status = "MONITOR FAIL"
                    else:
                        try:
                            new_filepath = os.path.join(torrent_path, ".copy")
                            logger.fdebug("New_Filepath: %s" % new_filepath)
                            shutil.copy(torrent_path, new_filepath)
                            torrent_info["copied_filepath"] = new_filepath
                        except:
                            logger.warn("Unexpected Error: %s" % sys.exc_info()[0])
                            logger.warn(
                                "Unable to create temporary directory to perform meta-tagging. Processing cannot continue with given item at this time."
                            )
                            torrent_info["copied_filepath"] = torrent_path
                        else:
                            dp.start_torrent(torrent_hash)
            else:
                snatch_status = "NOT SNATCHED"

    # torrent_info['snatch_status'] = snatch_status
    return torrent_info


def weekly_info(week=None, year=None, current=None):
    # find the current week and save it as a reference point.
    todaydate = datetime.datetime.today()
    if todaydate.year == 2025:
        current_weeknumber = todaydate.isocalendar()[1]
    else:
        current_weeknumber = int(todaydate.strftime("%U"))
    if current is not None:
        c_weeknumber = int(current[: current.find("-")])
        c_weekyear = int(current[current.find("-") + 1 :])
    else:
        c_weeknumber = week
        c_weekyear = year

    if week:
        weeknumber = int(week)
        year = int(year)
    else:
        # find the given week number for the current day
        weeknumber = current_weeknumber
        year = int(todaydate.strftime("%Y"))

    # monkey patch for 2018/2019 - week 52/week 0
    if all([weeknumber == 52, c_weeknumber == 51, c_weekyear == 2018]):
        weeknumber = 0
        year = 2019
    elif all([weeknumber == 52, c_weeknumber == 0, c_weekyear == 2019]):
        weeknumber = 51
        year = 2018

    # monkey patch for 2019/2020 - week 52/week 0
    if all([weeknumber == 52, c_weeknumber == 51, c_weekyear == 2019]) or all([weeknumber == "52", year == "2019"]):
        weeknumber = 0
        year = 2020
    elif all([weeknumber == 52, c_weeknumber == 0, c_weekyear == 2020]):
        weeknumber = 51
        year = 2019

    # monkey patch for 2020/2021 - week 52/week 0
    if all([int(weeknumber) == 0, int(year) == 2021]) or all([int(weeknumber) == 52, int(year) == 2020]):
        weeknumber = 52
        year = 2020

    # monkey patch for 2021/2022 - week 52/week 0
    if all([int(weeknumber) == 0, int(year) == 2022]) or all([int(weeknumber) == 52, int(year) == 2021]):
        weeknumber = 52
        year = 2021

    # monkey patch for 2024/2025 - week 52/week 0
    if all([weeknumber == 52, c_weeknumber == 51, c_weekyear == 2024]) or all([weeknumber == "52", year == "2024"]):
        weeknumber = 1
        year = 2025
    elif any([weeknumber == 52, weeknumber == 0]) and all([c_weeknumber == 1, c_weekyear == 2025]):
        weeknumber = 51
        year = 2024

    startofyear = date(year, 1, 1)
    week0 = startofyear - timedelta(days=startofyear.isoweekday())
    stweek = datetime.datetime.strptime(week0.strftime("%Y-%m-%d"), "%Y-%m-%d")
    if year == 2025:
        startweek = stweek + timedelta(weeks=weeknumber - 1)
    else:
        startweek = stweek + timedelta(weeks=weeknumber)

    midweek = startweek + timedelta(days=3)
    endweek = startweek + timedelta(days=6)

    if all([weeknumber == 1, year == 2021]):
        # make sure the arrow going back will hit the correct week in the previous year.
        prev_week = 52
        prev_year = 2020
    elif all([weeknumber == 0, year == 2022]):
        # make sure the arrow going back will hit the correct week in the previous year.
        prev_week = 52
        prev_year = 2021
    elif all([weeknumber == 0, year == 2025]):
        # make sure the arrow going back will hit the correct week in the previous year.
        prev_week = 51
        prev_year = 2024
    else:
        prev_week = int(weeknumber) - 1
        prev_year = year
        if prev_week < 0:
            prev_week = 52
            prev_year = int(year) - 1

    next_week = int(weeknumber) + 1
    next_year = year
    if next_week > 52:
        next_year = int(year) + 1
        if all([weeknumber == 52, year == 2020]):
            # make sure the next arrow will hit the correct week in the following year.
            next_week = "1"
        elif all([weeknumber == 52, year == 2021]):
            # make sure the next arrow will hit the correct week in the following year.
            next_week = "1"
        elif all([weeknumber == 51, year == 2024]):
            # make sure the next arrow will hit the correct week in the following year.
            next_week = "1"
        else:
            next_week = datetime.date(int(next_year), 1, 1).strftime("%U")

    date_fmt = "%B %d, %Y"
    try:
        con_startweek = "" + startweek.strftime(date_fmt)
        con_endweek = "" + endweek.strftime(date_fmt)
    except:
        con_startweek = "" + startweek.strftime(date_fmt)
        con_endweek = "" + endweek.strftime(date_fmt)

    if comicarr.CONFIG.WEEKFOLDER_LOC is not None:
        weekdst = comicarr.CONFIG.WEEKFOLDER_LOC
    else:
        weekdst = comicarr.CONFIG.DESTINATION_DIR

    if comicarr.SCHED_WEEKLY_LAST is not None:
        weekly_stamp = datetime.datetime.fromtimestamp(comicarr.SCHED_WEEKLY_LAST)
        weekly_last = weekly_stamp.replace(microsecond=0)
    else:
        weekly_last = "None"

    weekinfo = {
        "weeknumber": weeknumber,
        "startweek": con_startweek,
        "midweek": midweek.strftime("%Y-%m-%d"),
        "endweek": con_endweek,
        "year": year,
        "prev_weeknumber": prev_week,
        "prev_year": prev_year,
        "next_weeknumber": next_week,
        "next_year": next_year,
        "current_weeknumber": current_weeknumber,
        "last_update": weekly_last,
    }

    if weekdst is not None:
        if comicarr.CONFIG.WEEKFOLDER_FORMAT == 0:
            weekn = weeknumber
            if len(str(weekn)) == 1:
                weekn = "%s%s" % ("0", str(weekn))
            weekfold = os.path.join(weekdst, "%s-%s" % (weekinfo["year"], weekn))
        else:
            weekfold = os.path.join(weekdst, str(str(weekinfo["midweek"])))
    else:
        weekfold = None

    weekinfo["week_folder"] = weekfold

    return weekinfo


def latestdate_update():
    stmt = (
        select(
            comics.c.ComicID,
            issues.c.IssueID,
            comics.c.LatestDate,
            issues.c.ReleaseDate,
            issues.c.Issue_Number,
        )
        .select_from(comics.outerjoin(issues, comics.c.ComicID == issues.c.ComicID))
        .where(
            sqlalchemy.or_(
                comics.c.LatestDate < issues.c.ReleaseDate,
                comics.c.LatestDate.like("%Unknown%"),
            )
        )
        .group_by(comics.c.ComicID)
    )
    ccheck = db.select_all(stmt)
    if ccheck is None or len(ccheck) == 0:
        return
    logger.info(
        "Now preparing to update " + str(len(ccheck)) + " series that have out-of-date latest date information."
    )
    ablist = []
    for cc in ccheck:
        ablist.append({"ComicID": cc["ComicID"], "LatestDate": cc["ReleaseDate"], "LatestIssue": cc["Issue_Number"]})

    # forcibly set the latest date and issue number to the most recent.
    for a in ablist:
        logger.info(a)
        newVal = {"LatestDate": a["LatestDate"], "LatestIssue": a["LatestIssue"]}
        ctrlVal = {"ComicID": a["ComicID"]}
        logger.info("updating latest date for : " + a["ComicID"] + " to " + a["LatestDate"] + " #" + a["LatestIssue"])
        db.upsert("comics", newVal, ctrlVal)


def latestissue_update():
    cck = db.select_all(select(comics.c.ComicID, comics.c.LatestIssue).where(comics.c.intLatestIssue.is_(None)))

    if cck:
        c_list = []
        for ck in cck:
            c_list.append({"ComicID": ck["ComicID"], "intLatestIssue": issuedigits(ck["LatestIssue"])})

        logger.info("[LATEST_ISSUE_TO_INT] Updating the latestIssue field for %s series" % (len(c_list)))

        for ct in c_list:
            try:
                newVal = {"intLatestIssue": ct["intLatestIssue"]}
                ctrlVal = {"ComicID": ct["ComicID"]}
                db.upsert("comics", newVal, ctrlVal)
            except Exception as e:
                logger.fdebug("exception encountered: %s" % e)
                continue


def ddl_downloader(queue):
    link_type_failure = {}
    while True:
        if comicarr.DDL_LOCK.locked():
            time.sleep(5)

        elif not comicarr.DDL_LOCK.locked() and queue.qsize() >= 1:
            item = queue.get(True)

            if item == "exit":
                logger.info("Cleaning up workers for shutdown")
                break

            if item["id"] not in comicarr.DDL_QUEUED:
                comicarr.DDL_QUEUED.append(item["id"])

            try:
                link_type_failure[item["id"]].append(item["link_type_failure"])
            except Exception:
                pass

            # logger.info('[%s] link_type_failure: %s' % (item['id'], link_type_failure))

            logger.info("Now loading request from DDL queue: %s" % item["series"])

            # write this to the table so we have a record of what's going on.
            ctrlval = {"id": item["id"]}
            val = {"status": "Downloading", "updated_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
            db.upsert("ddl_info", val, ctrlval)

            if item["site"] == "DDL(GetComics)":
                try:
                    remote_filesize = item["remote_filesize"]
                except Exception:
                    try:
                        remote_filesize = helpers.human2bytes(re.sub("/s", "", item["size"][:-1]).strip())
                    except Exception:
                        remote_filesize = 0

                if any([item["link_type"] == "GC-Main", item["link_type"] == "GC_Mirror"]):
                    ddz = getcomics.GC()
                    ddzstat = ddz.downloadit(
                        item["id"], item["link"], item["mainlink"], item["resume"], item["issueid"], remote_filesize
                    )
                elif item["link_type"] == "GC-Mega":
                    meganz = mega.MegaNZ()
                    ddzstat = meganz.ddl_download(
                        item["link"], None, item["id"], item["issueid"], item["link_type"]
                    )  # item['filename'], item['id'])
                elif item["link_type"] == "GC-Media":
                    mediaf = mediafire.MediaFire()
                    ddzstat = mediaf.ddl_download(
                        item["link"], item["id"], item["issueid"]
                    )  # item['filename'], item['id'])
                elif item["link_type"] == "GC-Pixel":
                    pdrain = pixeldrain.PixelDrain()
                    ddzstat = pdrain.ddl_download(
                        item["link"], item["id"], item["issueid"]
                    )  # item['filename'], item['id'])

            elif item["site"] == "DDL(External)":
                meganz = mega.MegaNZ()
                ddzstat = meganz.ddl_download(
                    item["link"], item["filename"], item["id"], item["issueid"], item["link_type"]
                )

            # Check for file validity post download and mark as failure if file is not a zip, rar, or pdf
            # Can only check single downloads.  Packs will have to be managed by post-processing if enabled
            if ddzstat["success"] and ddzstat["filename"] is not None:
                filecondition = check_file_condition(ddzstat["path"])
                if not filecondition["status"]:
                    logger.warn(
                        f"CRC Check: File {ddzstat['path']} failed condition check ({filecondition['quality']}).  Marking as failed."
                    )
                    ddzstat["success"] = False
                    ddzstat["link_type_failure"] = item["link_type"]

            if ddzstat["success"] is True:
                tdnow = datetime.datetime.now()
                nval = {"status": "Completed", "updated_date": tdnow.strftime("%Y-%m-%d %H:%M")}
                db.upsert("ddl_info", nval, ctrlval)

            if all([ddzstat["success"] is True, comicarr.CONFIG.POST_PROCESSING is True]):
                try:
                    if ddzstat["filename"] is None:
                        logger.info(
                            "%s successfully downloaded - now initiating post-processing for %s."
                            % (os.path.basename(ddzstat["path"]), ddzstat["path"])
                        )
                        comicarr.PP_QUEUE.put(
                            {
                                "nzb_name": os.path.basename(ddzstat["path"]),
                                "nzb_folder": ddzstat["path"],
                                "failed": False,
                                "issueid": None,
                                "comicid": item["comicid"],
                                "apicall": True,
                                "ddl": True,
                                "download_info": {"provider": "DDL", "id": item["id"]},
                            }
                        )
                    else:
                        logger.info(
                            "%s successfully downloaded - now initiating post-processing for %s"
                            % (ddzstat["filename"], ddzstat["path"])
                        )
                        comicarr.PP_QUEUE.put(
                            {
                                "nzb_name": ddzstat["filename"],
                                "nzb_folder": ddzstat["path"],
                                "failed": False,
                                "issueid": item["issueid"],
                                "comicid": item["comicid"],
                                "apicall": True,
                                "ddl": True,
                                "download_info": {"provider": "DDL", "id": item["id"]},
                            }
                        )
                except Exception as e:
                    logger.error("process error: %s [%s]" % (e, ddzstat))

                # logger.fdebug('comicarr.ddl_queued: %s' % comicarr.DDL_QUEUED)
                comicarr.DDL_QUEUED.remove(item["id"])
                comicarr.DDL_STUCK_NOTIFIED.discard(item["id"])
                try:
                    link_type_failure.pop(item["id"])
                except KeyError:
                    pass

                try:
                    pck_cnt = 0
                    if item["comicinfo"][0]["pack"] is True:
                        logger.fdebug("[PACK DETECTION] Attempting to remove issueids from the pack dont-queue list")
                        for x, y in dict(comicarr.PACK_ISSUEIDS_DONT_QUEUE).items():
                            if y == item["id"]:
                                pck_cnt += 1
                                del comicarr.PACK_ISSUEIDS_DONT_QUEUE[x]
                        logger.fdebug(
                            "Successfully removed %s issueids from pack queue list as download is completed." % pck_cnt
                        )
                except Exception:
                    pass

                # remove html file from cache if it's successful
                ddl_cleanup(item["id"])

            elif all([ddzstat["success"] is True, comicarr.CONFIG.POST_PROCESSING is False]):
                path = ddzstat["path"]
                if ddzstat["filename"] is not None:
                    path = os.path.join(path, ddzstat["filename"])
                logger.info(
                    "File successfully downloaded. Post Processing is not enabled - item retained here: %s" % (path,)
                )
                ddl_cleanup(item["id"])
            else:
                if item["site"] == "DDL(GetComics)":
                    try:
                        ddzstat["links_exhausted"]
                    except KeyError:
                        logger.info(
                            "[Status: %s] Failed to download item from %s : %s "
                            % (ddzstat["success"], item["link_type"], ddzstat)
                        )
                        try:
                            link_type_failure[item["id"]].append(item["link_type"])
                        except KeyError:
                            link_type_failure[item["id"]] = [item["link_type"]]
                        logger.fdebug("[%s] link_type_failure: %s" % (item["id"], link_type_failure))
                        ggc = getcomics.GC(comicid=item["comicid"], issueid=item["issueid"], oneoff=item["oneoff"])
                        ggc.parse_downloadresults(
                            item["id"],
                            item["mainlink"],
                            item["comicinfo"],
                            item["packinfo"],
                            link_type_failure[item["id"]],
                        )
                    else:
                        logger.info(
                            "[REDO] Exhausted all available links [%s] for issueid %s and was not able to download anything"
                            % (link_type_failure[item["id"]], item["issueid"])
                        )
                        nval = {"status": "Failed", "updated_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
                        db.upsert("ddl_info", nval, ctrlval)
                        # undo all snatched items, to previous status via item['id'] - this will be set to Skipped currently regardless of previous status
                        reverse_the_pack_snatch(item["id"], item["comicid"])
                        link_type_failure.pop(item["id"])
                        comicarr.DDL_STUCK_NOTIFIED.discard(item["id"])
                        ddl_cleanup(item["id"])
                else:
                    logger.info(
                        "[Status: %s] Failed to download item from %s : %s "
                        % (ddzstat["success"], item["site"], ddzstat)
                    )
                    with db.get_engine().begin() as conn:
                        conn.execute(delete(ddl_info).where(ddl_info.c.ID == item["id"]))
                    comicarr.DDL_STUCK_NOTIFIED.discard(item["id"])
                    comicarr.search.FailedMark(
                        item["issueid"], item["comicid"], item["id"], ddzstat["filename"], item["site"]
                    )
        else:
            time.sleep(5)


def ddl_cleanup(id):
    # remove html file from cache if it's successful
    tlnk = "getcomics-%s.html" % id
    try:
        os.remove(os.path.join(comicarr.CONFIG.CACHE_DIR, "html_cache", tlnk))
    except Exception:
        logger.fdebug(
            "[HTML-cleanup] Unable to remove html used for item from html_cache folder."
            " Manual removal required or set `cleanup_cache=True` in the config.ini to"
            " clean cache items on every startup. If this was a Retry - ignore this."
        )


def ddl_health_check():
    """
    Check for stuck DDL downloads and send notifications.
    A download is considered stuck if it has been in 'Downloading' status
    for longer than DDL_STUCK_THRESHOLD minutes without progress.
    """
    if not comicarr.CONFIG.DDL_STUCK_NOTIFY:
        return

    if not comicarr.CONFIG.ENABLE_DDL:
        return

    stuck_items = db.select_all(select(ddl_info).where(ddl_info.c.status == "Downloading"))

    if not stuck_items:
        return

    threshold_minutes = comicarr.CONFIG.DDL_STUCK_THRESHOLD
    now = datetime.datetime.now()

    for item in stuck_items:
        if item["updated_date"] is None:
            continue

        try:
            updated = datetime.datetime.strptime(item["updated_date"], "%Y-%m-%d %H:%M")
        except ValueError:
            continue

        age_minutes = (now - updated).total_seconds() / 60

        if age_minutes > threshold_minutes:
            if item["id"] in comicarr.DDL_STUCK_NOTIFIED:
                continue

            logger.warn(
                "[DDL-HEALTH] Download stuck for %d minutes: %s (%s)" % (int(age_minutes), item["series"], item["id"])
            )

            notify_ddl_stuck(item, int(age_minutes))

            comicarr.DDL_STUCK_NOTIFIED.add(item["id"])


def notify_ddl_stuck(item, age_minutes):
    """
    Send notifications for a stuck DDL download.
    Follows the same notifier pattern as notify_snatch() in search.py.
    """
    from comicarr import notifiers

    stuck_name = "%s (%s)" % (item["series"], item["year"])
    if item["issues"]:
        stuck_name += " #%s" % item["issues"]

    subject = "DDL Queue Stuck!"
    message = "%s has been downloading for %d minutes without progress." % (stuck_name, age_minutes)

    if comicarr.CONFIG.PROWL_ENABLED and comicarr.CONFIG.PROWL_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Prowl notification")
        prowl = notifiers.PROWL()
        prowl.notify(message, subject)

    if comicarr.CONFIG.PUSHOVER_ENABLED and comicarr.CONFIG.PUSHOVER_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Pushover notification")
        pushover = notifiers.PUSHOVER()
        pushover.notify(subject, message, None, "DDL", "Comicarr")

    if comicarr.CONFIG.BOXCAR_ENABLED and comicarr.CONFIG.BOXCAR_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Boxcar notification")
        boxcar = notifiers.BOXCAR()
        boxcar.notify(snatched_nzb=stuck_name, sent_to="DDL", snline=subject)

    if comicarr.CONFIG.PUSHBULLET_ENABLED and comicarr.CONFIG.PUSHBULLET_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Pushbullet notification")
        pushbullet = notifiers.PUSHBULLET()
        pushbullet.notify(snline=subject, snatched=stuck_name, sent_to="DDL", prov="DDL", method="POST")

    if comicarr.CONFIG.TELEGRAM_ENABLED and comicarr.CONFIG.TELEGRAM_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Telegram notification")
        telegram = notifiers.TELEGRAM()
        telegram.notify("%s - %s" % (subject, message))

    if comicarr.CONFIG.SLACK_ENABLED and comicarr.CONFIG.SLACK_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Slack notification")
        slack = notifiers.SLACK()
        slack.notify("DDL Stuck", subject, snatched_nzb=stuck_name, sent_to="DDL", prov="DDL")

    if comicarr.CONFIG.DISCORD_ENABLED and comicarr.CONFIG.DISCORD_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Discord notification")
        discord = notifiers.DISCORD()
        discord.notify("DDL Stuck", subject, snatched_nzb=stuck_name, sent_to="DDL", prov="DDL")

    if comicarr.CONFIG.EMAIL_ENABLED and comicarr.CONFIG.EMAIL_ONGRAB:
        logger.info("[DDL-HEALTH] Sending email notification")
        email = notifiers.EMAIL()
        email.notify(message, "Comicarr - DDL Queue Stuck", module="[DDL-HEALTH]")

    if comicarr.CONFIG.GOTIFY_ENABLED and comicarr.CONFIG.GOTIFY_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Gotify notification")
        gotify = notifiers.GOTIFY()
        gotify.notify("DDL Stuck", subject, snatched_nzb=stuck_name, sent_to="DDL", prov="DDL")

    if comicarr.CONFIG.MATRIX_ENABLED and comicarr.CONFIG.MATRIX_ONSNATCH:
        logger.info("[DDL-HEALTH] Sending Matrix notification")
        matrix = notifiers.MATRIX()
        matrix.notify("DDL Stuck", subject, snatched_nzb=stuck_name, sent_to="DDL", prov="DDL")


def postprocess_main(queue):
    import queue as queue_module

    while True:
        try:
            item = queue.get(timeout=5)
        except queue_module.Empty:
            continue

        if item == "exit":
            logger.info("Cleaning up workers for shutdown")
            break

        if comicarr.APILOCK.locked():
            queue.put(item)  # re-enqueue
            time.sleep(1)
            continue

        pp = None
        logger.info("Now loading from post-processing queue: %s" % item)

        try:
            pprocess = process.Process(
                item["nzb_name"],
                item["nzb_folder"],
                item["failed"],
                item["issueid"],
                item["comicid"],
                item["apicall"],
                item["ddl"],
                item["download_info"],
            )
        except Exception:
            pprocess = process.Process(
                item["nzb_name"],
                item["nzb_folder"],
                item["failed"],
                item["issueid"],
                item["comicid"],
                item["apicall"],
            )
        pp = pprocess.post_process()

        if pp is not None:
            if pp["mode"] == "stop":
                # reset the lock so any subsequent items can pp and not keep the queue locked up.
                comicarr.APILOCK.release()

        if comicarr.APILOCK.locked():
            logger.info("Another item is post-processing still...")
            time.sleep(15)


def search_queue(queue):
    import queue as queue_module

    while True:
        try:
            item = queue.get(timeout=5)
        except queue_module.Empty:
            continue

        if item == "exit":
            logger.info("[SEARCH-QUEUE] Cleaning up workers for shutdown")
            break

        if comicarr.SEARCHLOCK.locked():
            queue.put(item)  # re-enqueue
            time.sleep(1)
            continue

            gumbo_line = True
            # logger.fdebug('pack_issueids_dont_queue: %s' % comicarr.PACK_ISSUEIDS_DONT_QUEUE)
            # logger.fdebug('ddl_queued: %s' % comicarr.DDL_QUEUED)
            if item["issueid"] in comicarr.PACK_ISSUEIDS_DONT_QUEUE:
                if comicarr.PACK_ISSUEIDS_DONT_QUEUE[item["issueid"]] in comicarr.DDL_QUEUED:
                    logger.fdebug(
                        "[SEARCH-QUEUE-PACK-DETECTION] %s already queued to download via pack...Ignoring"
                        % item["issueid"]
                    )
                    gumbo_line = False

            if gumbo_line:
                logger.fdebug("[SEARCH-QUEUE] Now loading item from search queue: %s" % item)
                if not comicarr.SEARCHLOCK.locked():
                    arcid = None
                    comicid = item["comicid"]
                    issueid = item["issueid"]
                    if issueid is not None:
                        if "_" in issueid:
                            arcid = issueid
                            comicid = None  # required for storyarcs to work
                            issueid = None  # required for storyarcs to work
                    mofo = comicarr.filers.FileHandlers(ComicID=comicid, IssueID=issueid, arcID=arcid)
                    local_check = mofo.walk_the_walk()

                    if local_check["status"]:
                        fullpath = Path(local_check["filepath"]) / local_check["filename"]
                        filecondition = check_file_condition(fullpath)
                        if not filecondition["status"]:
                            logger.warn(
                                f"CRC Check: File {fullpath} failed condition check ({filecondition['quality']}).  Ignoring."
                            )
                            local_check["status"] = False

                    if local_check["status"] is True:
                        comicarr.PP_QUEUE.put(
                            {
                                "nzb_name": local_check["filename"],
                                "nzb_folder": local_check["filepath"],
                                "failed": False,
                                "issueid": item["issueid"],
                                "comicid": item["comicid"],
                                "apicall": True,
                                "ddl": False,
                                "download_info": None,
                            }
                        )
                    else:
                        try:
                            manual = item["manual"]
                        except Exception:
                            manual = False
                        comicarr.search.searchforissue(item["issueid"], manual=manual)
                    time.sleep(5)  # arbitrary sleep to let the process attempt to finish pp'ing

            if comicarr.SEARCHLOCK.locked():
                logger.fdebug("[SEARCH-QUEUE] Another item is currently being searched....")
                time.sleep(15)


def worker_main(queue):
    import queue as queue_module

    while True:
        try:
            item = queue.get(timeout=15)
        except queue_module.Empty:
            continue

        logger.info("Now loading from queue: %s" % item)
        if item == "exit":
            logger.info("Cleaning up workers for shutdown")
            break
        snstat = torrentinfo(torrent_hash=item["hash"], download=True)
        if snstat["snatch_status"] == "IN PROGRESS":
            logger.info("Still downloading in client....let us try again momentarily.")
            time.sleep(30)
            comicarr.SNATCHED_QUEUE.put(item)
        elif any([snstat["snatch_status"] == "MONITOR FAIL", snstat["snatch_status"] == "MONITOR COMPLETE"]):
            logger.info("File copied for post-processing - submitting as a direct pp.")
            comicarr.PP_QUEUE.put(
                {
                    "nzb_name": os.path.basename(snstat["copied_filepath"]),
                    "nzb_folder": snstat[
                        "copied_filepath"
                    ],  # os.path.abspath(os.path.join(snstat['copied_filepath'], os.pardir)),
                    "failed": False,
                    "issueid": item["issueid"],
                    "comicid": item["comicid"],
                    "apicall": True,
                    "ddl": False,
                    "download_info": None,
                }
            )


def nzb_monitor(queue):
    while True:
        if comicarr.RETURN_THE_NZBQUEUE.qsize() >= 1:
            if comicarr.USE_SABNZBD is True:
                # this checks the sabnzbd queue to see if it's paused / unpaused.
                sab_params = {
                    "apikey": comicarr.CONFIG.SAB_APIKEY,
                    "mode": "queue",
                    "start": 0,
                    "limit": 5,
                    "search": None,
                    "output": "json",
                }
                s = sabnzbd.SABnzbd(params=sab_params)
                sabresponse = s.sender(chkstatus=True)
                # response will be: Paused = True, UnPaused = False
                if sabresponse["status"] is False:
                    while True:
                        if comicarr.RETURN_THE_NZBQUEUE.qsize() >= 1:
                            qu_retrieve = comicarr.RETURN_THE_NZBQUEUE.get(True)
                            try:
                                nzstat = s.historycheck(qu_retrieve)
                                cdh_monitor(queue, qu_retrieve, nzstat, readd=True)
                            except Exception as e:
                                logger.error("Exception occured trying to re-add %s to queue: %s" % (qu_retrieve, e))
                            time.sleep(5)
                        else:
                            break

        if queue.qsize() >= 1:
            item = queue.get(True)
            if item == "exit":
                logger.info("Cleaning up workers for shutdown")
                break
            try:
                tmp_apikey = item["queue"].pop("apikey")
                logger.info("Now loading from queue: %s" % item)
            except Exception:
                # nzbget doesn't pass the queue field. So just let it fly.
                logger.info("Now loading from queue: %s" % item)
            else:
                item["queue"]["apikey"] = tmp_apikey
            if all([comicarr.USE_SABNZBD is True, comicarr.CONFIG.SAB_CLIENT_POST_PROCESSING is True]):
                nz = sabnzbd.SABnzbd(item)
                nzstat = nz.processor()
            elif all([comicarr.USE_NZBGET is True, comicarr.CONFIG.NZBGET_CLIENT_POST_PROCESSING is True]):
                nz = nzbget.NZBGet()
                nzstat = nz.processor(item)
            else:
                logger.warn(
                    "There are no NZB Completed Download handlers enabled. Not sending item to completed download handling..."
                )
                break
            cdh_monitor(queue, item, nzstat)
        else:
            time.sleep(5)


def cdh_monitor(queue, item, nzstat, readd=False):
    known_nzb_id = item["nzo_id"] if (comicarr.USE_SABNZBD is True) else item["NZBID"]
    if any([nzstat["status"] == "file not found", nzstat["status"] == "double-pp"]):
        logger.warn(
            "Unable to complete post-processing call due to not finding file in the location provided. [%s]" % item
        )
    elif nzstat["status"] == "nzb removed" or "unhandled status" in str(nzstat["status"]).lower():
        if readd is True:
            # if the queue isn't empty, retry it like 5 times or until queue is empty
            # if queue is empty, this could be a timing issue, so we'd have to recheck it one more time at least
            # need to implement some kind of counter here for all of this ^^^
            logger.warn(
                "NZB seems to have been in a staging process within SABnzbd during attempt. Will requeue: %s."
                % known_nzb_id
            )
            comicarr.RETURN_THE_NZBQUEUE.put(item)
        else:
            logger.warn("NZB seems to have been removed from queue: %s" % known_nzb_id)
    elif nzstat["status"] == "failed_in_sab":
        logger.warn(
            "Failure returned from SAB for %s for some reason. You should probably check your SABnzbd logs"
            % known_nzb_id
        )
    elif nzstat["status"] == "queue_paused":
        # queue pause check for sabnzbd only atm.
        if comicarr.USE_SABNZBD is True:
            logger.info(
                "[PAUSED_SAB_QUEUE] adding %s to a temporary queue that will fire off when SABnzbd is unpaused" % item
            )
            comicarr.RETURN_THE_NZBQUEUE.put(item)
    elif nzstat["status"] is False:
        logger.info("Download %s failed. Requeue NZB to check later..." % known_nzb_id)
        time.sleep(5)
        if item not in queue.queue:
            comicarr.NZB_QUEUE.put(item)
    elif nzstat["status"] is True:
        if nzstat["failed"] is False:
            fullpath = Path(nzstat["location"]) / nzstat["name"]
            filecondition = check_file_condition(fullpath)
            if not filecondition["status"]:
                logger.warn(
                    f"CRC Check: File {fullpath} failed condition check ({filecondition['quality']}).  Marking as failed."
                )
                nzstat["failed"] = True

        if nzstat["failed"] is False:
            logger.info("File successfully downloaded - now initiating completed downloading handling.")
        else:
            logger.info(
                "File failed either due to being corrupt or incomplete - now initiating completed failed downloading handling."
            )
        try:
            comicarr.PP_QUEUE.put(
                {
                    "nzb_name": nzstat["name"],
                    "nzb_folder": nzstat["location"],
                    "failed": nzstat["failed"],
                    "issueid": nzstat["issueid"],
                    "comicid": nzstat["comicid"],
                    "apicall": nzstat["apicall"],
                    "ddl": False,
                    "download_info": nzstat["download_info"],
                }
            )
        except Exception as e:
            logger.error("process error: %s" % e)
    return


QueueInfo = namedtuple("QueueInfo", ("name", "is_alive", "size"))


def queue_info():
    yield from (
        QueueInfo(queue_name, thread_obj.is_alive() if thread_obj is not None else None, queue.qsize())
        for (queue_name, thread_obj, queue) in [
            ("AUTO-COMPLETE-NZB", comicarr.NZBPOOL, comicarr.NZB_QUEUE),
            ("AUTO-SNATCHER", comicarr.SNPOOL, comicarr.SNATCHED_QUEUE),
            ("DDL-QUEUE", comicarr.DDLPOOL, comicarr.DDL_QUEUE),
            ("POST-PROCESS-QUEUE", comicarr.PPPOOL, comicarr.PP_QUEUE),
            ("SEARCH-QUEUE", comicarr.SEARCHPOOL, comicarr.SEARCH_QUEUE),
        ]
    )


def script_env(mode, vars):
    # mode = on-snatch, pre-postprocess, post-postprocess
    # var = dictionary containing variables to pass
    comicarr_env = os.environ.copy()
    shell_cmd = sys.executable
    if mode == "on-snatch":
        runscript = comicarr.CONFIG.SNATCH_SCRIPT
        if comicarr.CONFIG.SNATCH_SHELL_LOCATION is not None:
            shell_cmd = comicarr.CONFIG.SNATCH_SHELL_LOCATION
        if "torrentinfo" in vars:
            if "hash" in vars["torrentinfo"]:
                comicarr_env["comicarr_release_hash"] = vars["torrentinfo"]["hash"]
            if "torrent_filename" in vars["torrentinfo"]:
                comicarr_env["comicarr_torrent_filename"] = vars["torrentinfo"]["torrent_filename"]
            if "name" in vars["torrentinfo"]:
                comicarr_env["comicarr_release_name"] = vars["torrentinfo"]["name"]
            if "folder" in vars["torrentinfo"]:
                comicarr_env["comicarr_release_folder"] = vars["torrentinfo"]["folder"]
            if "label" in vars["torrentinfo"]:
                comicarr_env["comicarr_release_label"] = vars["torrentinfo"]["label"]
            if "total_filesize" in vars["torrentinfo"]:
                comicarr_env["comicarr_release_filesize"] = str(vars["torrentinfo"]["total_filesize"])
            if "time_started" in vars["torrentinfo"]:
                comicarr_env["comicarr_release_start"] = str(vars["torrentinfo"]["time_started"])
            if "filepath" in vars["torrentinfo"]:
                comicarr_env["comicarr_torrent_file"] = str(vars["torrentinfo"]["filepath"])
            else:
                try:
                    comicarr_env["comicarr_release_files"] = "|".join(vars["torrentinfo"]["files"])
                except TypeError:
                    comicarr_env["comicarr_release_files"] = "|".join(json.dumps(vars["torrentinfo"]["files"]))
        elif "nzbinfo" in vars:
            comicarr_env["comicarr_release_id"] = vars["nzbinfo"]["id"]
            if "client_id" in vars["nzbinfo"]:
                comicarr_env["comicarr_client_id"] = vars["nzbinfo"]["client_id"]
            comicarr_env["comicarr_release_nzbname"] = vars["nzbinfo"]["nzbname"]
            comicarr_env["comicarr_release_link"] = vars["nzbinfo"]["link"]
            comicarr_env["comicarr_release_nzbpath"] = vars["nzbinfo"]["nzbpath"]
            if "blackhole" in vars["nzbinfo"]:
                comicarr_env["comicarr_release_blackhole"] = vars["nzbinfo"]["blackhole"]
        comicarr_env["comicarr_release_provider"] = vars["provider"]
        if "comicinfo" in vars:
            try:
                if vars["comicinfo"]["comicid"] is not None:
                    comicarr_env["comicarr_comicid"] = vars["comicinfo"][
                        "comicid"
                    ]  # comicid/issueid are unknown for one-offs (should be fixable tho)
                else:
                    comicarr_env["comicarr_comicid"] = "None"
            except:
                pass
            try:
                if vars["comicinfo"]["issueid"] is not None:
                    comicarr_env["comicarr_issueid"] = vars["comicinfo"]["issueid"]
                else:
                    comicarr_env["comicarr_issueid"] = "None"
            except:
                pass
            try:
                if vars["comicinfo"]["issuearcid"] is not None:
                    comicarr_env["comicarr_issuearcid"] = vars["comicinfo"]["issuearcid"]
                else:
                    comicarr_env["comicarr_issuearcid"] = "None"
            except:
                pass
            comicarr_env["comicarr_comicname"] = vars["comicinfo"]["comicname"]
            comicarr_env["comicarr_issuenumber"] = str(vars["comicinfo"]["issuenumber"])
            try:
                comicarr_env["comicarr_comicvolume"] = str(vars["comicinfo"]["volume"])
            except:
                pass
            try:
                comicarr_env["comicarr_seriesyear"] = str(vars["comicinfo"]["seriesyear"])
            except:
                pass
            try:
                comicarr_env["comicarr_issuedate"] = str(vars["comicinfo"]["issuedate"])
            except:
                pass

        comicarr_env["comicarr_release_pack"] = str(vars["pack"])
        if vars["pack"] is True:
            if vars["pack_numbers"] is not None:
                comicarr_env["comicarr_release_pack_numbers"] = vars["pack_numbers"]
            if vars["pack_issuelist"] is not None:
                comicarr_env["comicarr_release_pack_issuelist"] = vars["pack_issuelist"]
        comicarr_env["comicarr_method"] = vars["method"]
        comicarr_env["comicarr_client"] = vars["clientmode"]

    elif mode == "post-process":
        # to-do
        runscript = comicarr.CONFIG.EXTRA_SCRIPTS
        if comicarr.CONFIG.ES_SHELL_LOCATION is not None:
            shell_cmd = comicarr.CONFIG.ES_SHELL_LOCATION

    elif mode == "pre-process":
        # to-do
        runscript = comicarr.CONFIG.PRE_SCRIPTS
        if comicarr.CONFIG.PRE_SHELL_LOCATION is not None:
            shell_cmd = comicarr.CONFIG.PRE_SHELL_LOCATION

    logger.fdebug("Initiating " + mode + " script detection.")
    with open(runscript, "r") as f:
        first_line = f.readline()

    if runscript.endswith(".sh"):
        shell_cmd = re.sub("#!", "", first_line)
        if shell_cmd == "" or shell_cmd is None:
            shell_cmd = "/bin/bash"

    curScriptName = shell_cmd + " " + runscript  # .decode("string_escape")
    logger.fdebug("snatch script detected...enabling: " + str(curScriptName))

    script_cmd = shlex.split(curScriptName)
    logger.fdebug("Executing command " + str(script_cmd))
    try:
        subprocess.call(script_cmd, env=dict(comicarr_env))
    except OSError:
        logger.warn("Unable to run extra_script: " + str(script_cmd))
        return False
    except TypeError as e:
        bad_environment = False
        for key, value in comicarr_env.items():
            if not isinstance(key, str) or not isinstance(value, str):
                bad_environment = True
                if key in os.environ:
                    logger.error("Invalid global environment variable: {k!r} = {v!r}".format(k=key, v=value))
                else:
                    logger.error("Invalid Comicarr environment variable: {k!r} = {v!r}".format(k=key, v=value))
        if not bad_environment:
            raise e
    else:
        return True


def get_the_hash(filepath):
    import bencode

    # Open torrent file
    torrent_file = open(filepath, "rb")
    metainfo = bencode.decode(torrent_file.read())
    info = metainfo["info"]
    thehash = hashlib.sha1(bencode.encode(info)).hexdigest().upper()
    logger.info("Hash of file : " + thehash)
    return {"hash": thehash}


def block_provider_check(site, simple=True, force=False):
    timenow = int(time.time())
    for prov in comicarr.PROVIDER_BLOCKLIST:
        if prov["site"] == site:
            if force is True:
                comicarr.PROVIDER_BLOCKLIST.remove(prov)
                if simple is True:
                    return False
                else:
                    return {"blocked": False, "remain": (int(prov["resume"]) - timenow) / 60}
            else:
                if timenow < int(prov["resume"]):
                    if simple is True:
                        return True
                    else:
                        return {"blocked": True, "remain": (int(prov["resume"]) - timenow) / 60}
                else:
                    comicarr.PROVIDER_BLOCKLIST.remove(prov)
    if simple is True:
        return False
    else:
        return {"blocked": False, "remain": 0}


def disable_provider(site, reason=None, delay=0):
    if not delay:
        if comicarr.CONFIG.BLOCKLIST_TIMER > 0:
            delay = int(comicarr.CONFIG.BLOCKLIST_TIMER)
        else:
            delay = 3600
    mins = int(delay / 60) + (delay % 60 > 0)
    logger.info("Temporarily blocking provider %s for %s minutes..." % (site, mins))
    for entry in comicarr.PROVIDER_BLOCKLIST:
        if entry["site"] == site:
            comicarr.PROVIDER_BLOCKLIST.remove(entry)
    newentry = {"site": site, "resume": int(time.time()) + delay, "reason": reason}
    comicarr.PROVIDER_BLOCKLIST.append(newentry)
    logger.info("provider_blocklist: %s" % comicarr.PROVIDER_BLOCKLIST)


def date_conversion(originaldate):
    c_obj_date = datetime.datetime.strptime(originaldate, "%Y-%m-%d %H:%M:%S")
    n_date = datetime.datetime.now()
    absdiff = abs(n_date - c_obj_date)
    hours = (absdiff.days * 24 * 60 * 60 + absdiff.seconds) / 3600.0
    return hours


def job_management(
    write=False, job=None, last_run_completed=None, current_run=None, status=None, failure=False, startup=False
):
    jobresults = []

    if startup is True:
        # on startup - db status will over-ride any settings to ensure persistent state
        job_info = db.select_all(
            select(jobhistory.c.JobName, jobhistory.c.status, jobhistory.c.prev_run_timestamp).distinct()
        )
        for ji in job_info:
            jstatus = ji["status"]
            if any([jstatus is None, jstatus == "Running"]):
                jstatus = "Waiting"
            if "update" in ji["JobName"].lower():
                if comicarr.SCHED_DBUPDATE_LAST is None:
                    comicarr.SCHED_DBUPDATE_LAST = ji["prev_run_timestamp"]
                if jstatus is None:
                    jstatus = "Waiting"
                comicarr.UPDATER_STATUS = jstatus
            elif "search" in ji["JobName"].lower():
                if comicarr.SCHED_SEARCH_LAST is None:
                    comicarr.SCHED_SEARCH_LAST = ji["prev_run_timestamp"]
                if jstatus is None:
                    jstatus = "Waiting"
                comicarr.SEARCH_STATUS = jstatus
            elif "rss" in ji["JobName"].lower():
                # db value isn't used in startup as config option controls status
                if comicarr.SCHED_RSS_LAST is None:
                    comicarr.SCHED_RSS_LAST = ji["prev_run_timestamp"]
                if jstatus is None:
                    if comicarr.CONFIG.ENABLE_RSS:
                        jstatus = "Waiting"
                if any([jstatus == "Waiting", jstatus == "Running"]) and comicarr.CONFIG.ENABLE_RSS is False:
                    jstatus = "Paused"
                comicarr.RSS_STATUS = jstatus
            elif "weekly" in ji["JobName"].lower():
                if comicarr.SCHED_WEEKLY_LAST is None:
                    comicarr.SCHED_WEEKLY_LAST = ji["prev_run_timestamp"]
                if jstatus is None:
                    jstatus = "Waiting"
                comicarr.WEEKLY_STATUS = jstatus
            elif "version" in ji["JobName"].lower():
                # db value isn't used in startup as config option controls status
                if comicarr.SCHED_VERSION_LAST is None:
                    comicarr.SCHED_VERSION_LAST = ji["prev_run_timestamp"]
                if jstatus is None:
                    if comicarr.CONFIG.CHECK_GITHUB:
                        jstatus = "Waiting"
                if any([jstatus == "Waiting", jstatus == "Running"]) and comicarr.CONFIG.CHECK_GITHUB is False:
                    jstatus = "Paused"
                comicarr.VERSION_STATUS = jstatus
            elif "monitor" in ji["JobName"].lower():
                # db value isn't used in startup as config option controls status
                if comicarr.SCHED_MONITOR_LAST is None:
                    comicarr.SCHED_MONITOR_LAST = ji["prev_run_timestamp"]
                if jstatus is None:
                    if comicarr.CONFIG.CHECK_FOLDER:
                        jstatus = "Waiting"
                if any([jstatus == "Waiting", jstatus == "Running"]) and comicarr.CONFIG.CHECK_FOLDER is False:
                    jstatus = "Paused"
                comicarr.MONITOR_STATUS = jstatus

        return {
            "weekly": {"last": comicarr.SCHED_WEEKLY_LAST, "status": comicarr.WEEKLY_STATUS},
            "monitor": {"last": comicarr.SCHED_MONITOR_LAST, "status": comicarr.MONITOR_STATUS},
            "search": {"last": comicarr.SCHED_SEARCH_LAST, "status": comicarr.SEARCH_STATUS},
            "updater": {"last": comicarr.SCHED_DBUPDATE_LAST, "status": comicarr.UPDATER_STATUS},
            "version": {"last": comicarr.SCHED_VERSION_LAST, "status": comicarr.VERSION_STATUS},
            "rss": {"last": comicarr.SCHED_RSS_LAST, "status": comicarr.RSS_STATUS},
        }

    for jb in comicarr.SCHED.get_jobs():
        jobinfo = str(jb)
        jobname = jobinfo[: jobinfo.find("(") - 1].strip()
        jobstatus = jobinfo[jobinfo.find("],") + 2 : len(jobinfo) - 1].strip()
        next_the_run = False

        # logger.info('[%s] ==> %s' % (jobname, jobstatus))

        # jobstatus will be either paused / next run - running jobs have to be
        # identified farther below
        if jobname == "DB Updater":
            prev_run_timestamp = comicarr.SCHED_DBUPDATE_LAST
            if "next run" in jobstatus:
                comicarr.UPDATER_STATUS = "Waiting"
                if any(ky == "updater" for ky, vl in comicarr.FORCE_STATUS.items()):
                    comicarr.UPDATER_STATUS = comicarr.FORCE_STATUS["updater"]
                    next_the_run = True
            else:
                comicarr.UPDATER_STATUS = "Paused"
            sched_status = comicarr.UPDATER_STATUS
        elif jobname == "Auto-Search":
            prev_run_timestamp = comicarr.SCHED_SEARCH_LAST
            if "next run" in jobstatus:
                comicarr.SEARCH_STATUS = "Waiting"
                if any(ky == "search" for ky, vl in comicarr.FORCE_STATUS.items()):
                    comicarr.SEARCH_STATUS = comicarr.FORCE_STATUS["search"]
                    next_the_run = True
            else:
                comicarr.SEARCH_STATUS = "Paused"
            sched_status = comicarr.SEARCH_STATUS
        elif jobname == "RSS Feeds":
            prev_run_timestamp = comicarr.SCHED_RSS_LAST
            if "next run" in jobstatus:
                comicarr.RSS_STATUS = "Waiting"
                if any(ky == "rss" for ky, vl in comicarr.FORCE_STATUS.items()):
                    comicarr.RSS_STATUS = comicarr.FORCE_STATUS["rss"]
                    next_the_run = True
            else:
                comicarr.RSS_STATUS = "Paused"
            sched_status = comicarr.RSS_STATUS
        elif jobname == "Weekly Pullist":
            prev_run_timestamp = comicarr.SCHED_WEEKLY_LAST
            if "next run" in jobstatus:
                comicarr.WEEKLY_STATUS = "Waiting"
                if any(ky == "weekly" for ky, vl in comicarr.FORCE_STATUS.items()):
                    comicarr.WEEKLY_STATUS = comicarr.FORCE_STATUS["weekly"]
                    next_the_run = True
            else:
                comicarr.WEEKLY_STATUS = "Paused"
            sched_status = comicarr.WEEKLY_STATUS
        elif jobname == "Check Version":
            prev_run_timestamp = comicarr.SCHED_VERSION_LAST
            if "next run" in jobstatus:
                comicarr.VERSION_STATUS = "Waiting"
                if any(ky == "version" for ky, vl in comicarr.FORCE_STATUS.items()):
                    comicarr.VERSION_STATUS = comicarr.FORCE_STATUS["version"]
                    next_the_run = True
            else:
                comicarr.VERSION_STATUS = "Paused"
            sched_status = comicarr.VERSION_STATUS
        elif jobname == "Folder Monitor":
            prev_run_timestamp = comicarr.SCHED_MONITOR_LAST
            if "next run" in jobstatus:
                comicarr.MONITOR_STATUS = "Waiting"
                if any(ky == "monitor" for ky, vl in comicarr.FORCE_STATUS.items()):
                    comicarr.MONITOR_STATUS = comicarr.FORCE_STATUS["monitor"]
                    next_the_run = True
            else:
                comicarr.MONITOR_STATUS = "Paused"
            sched_status = comicarr.MONITOR_STATUS

        # jobname = jobinfo[:jobinfo.find('(')-1].strip()
        # logger.fdebug('jobinfo: %s' % jobinfo)
        try:
            jobtimetmp = jobinfo.split("at: ")[1].split(".")[0].strip()
        except:
            jobtime = None
        else:
            if next_the_run is False:
                jtime = float(
                    calendar.timegm(datetime.datetime.strptime(jobtimetmp[:-1], "%Y-%m-%d %H:%M:%S %Z").timetuple())
                )
                jobtime = datetime.datetime.utcfromtimestamp(jtime)
            else:
                jobtime = None

        if prev_run_timestamp is not None:
            prev_run_time_utc = datetime.datetime.utcfromtimestamp(float(prev_run_timestamp))
            prev_run_time_utc = prev_run_time_utc.replace(microsecond=0)
        else:
            prev_run_time_utc = None

        jobresults.append(
            {
                "jobname": jobname,
                "next_run_datetime": jobtime,
                "prev_run_datetime": prev_run_time_utc,
                "next_run_timestamp": jobtime,
                "prev_run_timestamp": prev_run_timestamp,
                "status": sched_status,
            }
        )

    if not write:
        if len(jobresults) == 0:
            return monitors
        else:
            return jobresults
    else:
        if job is None:
            for x in jobresults:
                updateCtrl = {"JobName": x["jobname"]}
                updateVals = {
                    "next_run_timestamp": x["next_run_timestamp"],
                    "prev_run_timestamp": x["prev_run_timestamp"],
                    "next_run_datetime": x["next_run_datetime"],
                    "prev_run_datetime": x["prev_run_datetime"],
                    "status": x["status"],
                }

                db.upsert("jobhistory", updateVals, updateCtrl)
        else:
            # logger.fdebug('Updating info - job: %s' % job)
            # logger.fdebug('Updating info - last run: %s' % last_run_completed)
            # logger.fdebug('Updating info - status: %s' % status)
            updateCtrl = {"JobName": job}
            if current_run is not None:
                pr_datetime = datetime.datetime.utcfromtimestamp(current_run)
                pr_datetime = pr_datetime.replace(microsecond=0)
                updateVals = {"prev_run_timestamp": current_run, "prev_run_datetime": pr_datetime, "status": status}
                # logger.info('updateVals: %s' % updateVals)
            elif last_run_completed is not None:
                if any(
                    [
                        job == "DB Updater",
                        job == "Auto-Search",
                        job == "RSS Feeds",
                        job == "Weekly Pullist",
                        job == "Check Version",
                        job == "Folder Monitor",
                    ]
                ):
                    jobstore = None
                    nextrun_stamp = None
                    nextrun_date = None
                    for jbst in comicarr.SCHED.get_jobs():
                        jb = str(jbst)
                        if "Status Updater" in jb.lower():
                            continue
                        elif job == "DB Updater" and "update" in jb.lower():
                            if any(ky == "updater" for ky, vl in comicarr.FORCE_STATUS.items()):
                                comicarr.UPDATER_STATUS = comicarr.FORCE_STATUS["updater"]
                                comicarr.FORCE_STATUS.pop("updater")

                            if comicarr.UPDATER_STATUS != "Paused":
                                if comicarr.DB_BACKFILL is True:
                                    # if backfilling, set it for every 15 mins
                                    nextrun_stamp = utctimestamp() + (comicarr.CONFIG.BACKFILL_TIMESPAN * 60)
                                    logger.fdebug(
                                        "[BACKFILL-UPDATER] Will fire off every %s"
                                        " minutes until backlog is decimated." % (comicarr.CONFIG.BACKFILL_TIMESPAN)
                                    )
                                else:
                                    nextrun_stamp = utctimestamp() + (int(comicarr.DBUPDATE_INTERVAL) * 60)
                            else:
                                comicarr.SCHED.pause_job("dbupdater")
                            jobstore = jbst
                            break
                        elif job == "Auto-Search" and "search" in jb.lower():
                            if any(ky == "search" for ky, vl in comicarr.FORCE_STATUS.items()):
                                comicarr.SEARCH_STATUS = comicarr.FORCE_STATUS["search"]
                                comicarr.FORCE_STATUS.pop("search")

                            if comicarr.SEARCH_STATUS != "Paused":
                                if failure is True:
                                    logger.info(
                                        "Previous job could not run due to other jobs. Scheduling Auto-Search for 10 minutes from now."
                                    )
                                    s_interval = 10 * 60
                                else:
                                    s_interval = comicarr.CONFIG.SEARCH_INTERVAL * 60
                                nextrun_stamp = utctimestamp() + s_interval
                            else:
                                comicarr.SCHED.pause_job("search")
                            jobstore = jbst
                            break
                        elif job == "RSS Feeds" and "rss" in jb.lower():
                            if any(ky == "rss" for ky, vl in comicarr.FORCE_STATUS.items()):
                                comicarr.RSS_STATUS = comicarr.FORCE_STATUS["rss"]
                                comicarr.FORCE_STATUS.pop("rss")

                            if comicarr.RSS_STATUS != "Paused":
                                nextrun_stamp = utctimestamp() + (int(comicarr.CONFIG.RSS_CHECKINTERVAL) * 60)
                            else:
                                comicarr.SCHED.pause_job("rss")
                            comicarr.SCHED_RSS_LAST = last_run_completed
                            jobstore = jbst
                            break
                        elif job == "Weekly Pullist" and "weekly" in jb.lower():
                            if any(ky == "weekly" for ky, vl in comicarr.FORCE_STATUS.items()):
                                comicarr.WEEKLY_STATUS = comicarr.FORCE_STATUS["weekly"]
                                comicarr.FORCE_STATUS.pop("weekly")

                            if comicarr.WEEKLY_STATUS != "Paused":
                                if comicarr.CONFIG.ALT_PULL == 2:
                                    wkt = 4
                                else:
                                    wkt = 24
                                nextrun_stamp = utctimestamp() + (wkt * 60 * 60)
                            else:
                                comicarr.SCHED.pause_job("weekly")
                            comicarr.SCHED_WEEKLY_LAST = last_run_completed
                            jobstore = jbst
                            break
                        elif job == "Check Version" and "version" in jb.lower():
                            if any(ky == "version" for ky, vl in comicarr.FORCE_STATUS.items()):
                                comicarr.VERSION_STATUS = comicarr.FORCE_STATUS["version"]
                                comicarr.FORCE_STATUS.pop("version")

                            if comicarr.VERSION_STATUS != "Paused":
                                nextrun_stamp = utctimestamp() + (comicarr.CONFIG.CHECK_GITHUB_INTERVAL * 60)
                            else:
                                comicarr.SCHED.pause_job("version")
                            jobstore = jbst
                            break
                        elif job == "Folder Monitor" and "monitor" in jb.lower():
                            if any(ky == "monitor" for ky, vl in comicarr.FORCE_STATUS.items()):
                                comicarr.MONITOR_STATUS = comicarr.FORCE_STATUS["monitor"]
                                comicarr.FORCE_STATUS.pop("monitor")

                            if comicarr.MONITOR_STATUS != "Paused":
                                nextrun_stamp = utctimestamp() + (int(comicarr.CONFIG.DOWNLOAD_SCAN_INTERVAL) * 60)
                            else:
                                comicarr.SCHED.pause_job("monitor")
                            jobstore = jbst
                            break

                    if jobstore is not None:
                        if nextrun_stamp is not None:
                            nextrun_date = datetime.datetime.utcfromtimestamp(nextrun_stamp)
                            jobstore.modify(next_run_time=nextrun_date)
                            nextrun_date = nextrun_date.replace(microsecond=0)
                    else:
                        # if the rss is enabled after startup, we have to re-set it up...
                        nextrun_stamp = utctimestamp() + (int(comicarr.CONFIG.RSS_CHECKINTERVAL) * 60)
                        nextrun_date = datetime.datetime.utcfromtimestamp(nextrun_stamp)
                        comicarr.SCHED_RSS_LAST = last_run_completed

                if nextrun_date is not None:
                    logger.fdebug("ReScheduled job: %s to %s" % (job, comicarr.helpers.utc_date_to_local(nextrun_date)))
                lastrun_comp = datetime.datetime.utcfromtimestamp(last_run_completed)
                lastrun_comp = lastrun_comp.replace(microsecond=0)
                # if it's completed, then update the last run time to the ending time of the job
                updateVals = {
                    "prev_run_timestamp": last_run_completed,
                    "prev_run_datetime": lastrun_comp,
                    "last_run_completed": "True",
                    "next_run_timestamp": nextrun_stamp,
                    "next_run_datetime": nextrun_date,
                    "status": status,
                }

            logger.fdebug("Job update for %s: %s" % (updateCtrl, updateVals))
            db.upsert("jobhistory", updateVals, updateCtrl)


def stupidchk():
    with db.get_engine().connect() as conn:
        result_active = conn.execute(select(func.count()).select_from(comics).where(comics.c.Status == "Active"))
        comicarr.COUNT_COMICS = result_active.scalar()
        result_other = conn.execute(
            select(func.count()).select_from(comics).where(comics.c.Status.in_(["Loading", "Paused"]))
        )
        comicarr.EN_OOMICS = result_other.scalar()


def newznab_test(name, host, ssl, apikey):
    from xml.dom.minidom import parseString

    params = {"t": "search", "apikey": apikey, "o": "xml"}

    if not host.endswith("api"):
        if not host.endswith("/"):
            host += "/"
        host = urljoin(host, "api")
        logger.fdebug("[TEST-NEWZNAB] Appending `api` to end of host: %s" % host)
    headers = {"User-Agent": str(comicarr.USER_AGENT)}
    logger.info("host: %s" % host)
    try:
        r = requests.get(host, params=params, headers=headers, verify=bool(ssl))
    except Exception as e:
        logger.warn("Unable to connect: %s" % e)
        return
    else:
        try:
            data = parseString(r.content)
        except Exception as e:
            logger.warn("[WARNING] Error attempting to test: %s" % e)

        try:
            error_code = data.getElementsByTagName("error")[0].attributes["code"].value
        except Exception:
            logger.info("Connected - Status code returned: %s" % r.status_code)
            if r.status_code == 200:
                return True
            else:
                logger.warn("Received response - Status code returned: %s" % r.status_code)
                return False

        code = error_code
        description = data.getElementsByTagName("error")[0].attributes["description"].value
        logger.info("[ERROR:%s] - %s" % (code, description))
        return False


def torznab_test(name, host, ssl, apikey):
    from xml.dom.minidom import parseString

    params = {"t": "search", "apikey": apikey, "o": "xml"}

    if host[-1:] == "/":
        host = host[:-1]
    headers = {"User-Agent": str(comicarr.USER_AGENT)}
    logger.info("host: %s" % host)
    try:
        r = requests.get(host, params=params, headers=headers, verify=bool(ssl))
    except Exception as e:
        logger.warn("Unable to connect: %s" % e)
        return
    else:
        try:
            data = parseString(r.content)
        except Exception as e:
            logger.warn("[WARNING] Error attempting to test: %s" % e)

        try:
            error_code = data.getElementsByTagName("error")[0].attributes["code"].value
        except Exception:
            logger.info("Connected - Status code returned: %s" % r.status_code)
            if r.status_code == 200:
                return True
            else:
                logger.warn("Received response - Status code returned: %s" % r.status_code)
                return False

        code = error_code
        description = data.getElementsByTagName("error")[0].attributes["description"].value
        logger.info("[ERROR:%s] - %s" % (code, description))
        return False


def get_free_space(folder):
    min_threshold = 100000000  # threshold for minimum amount of freespace available (#100mb)
    if platform.system() == "Windows":
        free_bytes = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(folder), None, None, ctypes.pointer(free_bytes))
        dst_freesize = free_bytes.value
    else:
        st = os.statvfs(folder)
        dst_freesize = st.f_bavail * st.f_frsize
    logger.fdebug("[FREESPACE-CHECK] %s has %s free" % (folder, sizeof_fmt(dst_freesize)))
    if min_threshold > dst_freesize:
        logger.warn("[FREESPACE-CHECK] There is only %s space left on %s" % (dst_freesize, folder))
        return False
    else:
        return True


def sizeof_fmt(num, suffix="B"):
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, "Yi", suffix)


def getImage(comicid, url, issueid=None, thumbnail_path=None, apicall=False, overwrite=False):

    if thumbnail_path is None:
        if os.path.exists(comicarr.CONFIG.CACHE_DIR):
            pass
        else:
            # let's make the dir.
            try:
                os.makedirs(str(comicarr.CONFIG.CACHE_DIR))
                if apicall is False:
                    logger.info("Cache Directory successfully created at: %s" % comicarr.CONFIG.CACHE_DIR)

            except OSError:
                if apicall is False:
                    logger.error(
                        "Could not create cache dir. Check permissions of cache dir: %s" % comicarr.CONFIG.CACHE_DIR
                    )

        coverfile = os.path.join(comicarr.CONFIG.CACHE_DIR, str(comicid) + ".jpg")
    else:
        coverfile = thumbnail_path

    # if cover has '+' in url it's malformed, we need to replace '+' with '%20' to retrieve properly.

    # new CV API restriction - one api request / second.(probably unecessary here, but it doesn't hurt)
    if comicarr.CONFIG.CVAPI_RATE is None or comicarr.CONFIG.CVAPI_RATE < 2:
        time.sleep(2)
    else:
        time.sleep(comicarr.CONFIG.CVAPI_RATE)

    if apicall is False:
        logger.info("Attempting to retrieve the comic image for series")
    try:
        r = requests.get(url, params=None, stream=True, verify=comicarr.CONFIG.CV_VERIFY, headers=comicarr.CV_HEADERS)
    except Exception as e:
        if apicall is False:
            logger.warn("[ERROR: %s] Unable to download image from CV URL link: %s" % (e, url))
        coversize = 0
        statuscode = "400"
    else:
        statuscode = str(r.status_code)
        if apicall is False:
            logger.fdebug("comic image retrieval status code: %s" % statuscode)

        if statuscode != "200":
            if apicall is False:
                logger.warn(
                    "Unable to download image from CV URL link: %s [Status Code returned: %s]" % (url, statuscode)
                )
            coversize = 0
        else:
            if os.path.exists(coverfile) and overwrite:
                try:
                    os.remove(coverfile)
                except Exception:
                    pass

            with open(coverfile, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk:  # filter out keep-alive new chunks
                        f.write(chunk)
                        f.flush()

            statinfo = os.stat(coverfile)
            coversize = statinfo.st_size

        # quick test for image integrity
        try:
            Image.open(coverfile)
        except OSError:
            logger.warn("Truncated image retrieved - trying alternate image file.")
            return {"coversize": coversize, "status": "retry"}

        return {"coversize": coversize, "status": "success"}

    if any([int(coversize) < 10000, statuscode != "200"]) and thumbnail_path is None:
        try:
            if statuscode != "200":
                if apicall is False:
                    logger.info(
                        "Trying to grab an alternate cover due to problems trying to retrieve the main cover image."
                    )
            else:
                if apicall is False:
                    logger.info("Image size invalid [%s bytes] - trying to get alternate cover image." % coversize)
        except Exception:
            if apicall is False:
                logger.info("Image size invalid [%s bytes] - trying to get alternate cover image." % coversize)

        if apicall is False:
            logger.fdebug("invalid image link is here: %s" % url)

        if os.path.exists(coverfile):
            os.remove(coverfile)

        return {"coversize": coversize, "status": "retry"}
    else:
        return {"coversize": coversize, "status": "failed"}


def publisherImages(publisher):
    comicpublisher = None
    if comicarr.CONFIG.INTERFACE == "default":
        # these are specific images taht are better displayed in the default theme.
        if any([publisher == "Image", publisher == "Image Comics"]):
            comicpublisher = {
                "publisher_image": "images/publisherlogos/logo-imagecomics.png",
                "publisher_image_alt": "Image",
                "publisher_imageH": "125",
                "publisher_imageW": "75",
            }
        elif publisher == "IDW Publishing":
            comicpublisher = {
                "publisher_image": "images/publisherlogos/logo-idwpublish.png",
                "publisher_image_alt": "IDW",
                "publisher_imageH": "50",
                "publisher_imageW": "100",
            }
        elif publisher == "Boom! Studios":
            comicpublisher = {
                "publisher_image": "images/publisherlogos/logo-boom.jpg",
                "publisher_image_alt": "Boom!",
                "publisher_imageH": "50",
                "publisher_imageW": "100",
            }

    else:
        # --- for carbon theme (any non-white theme)
        if any([publisher == "Image", publisher == "Image Comics"]):
            comicpublisher = {
                "publisher_image": "images/publisherlogos/logo-imagecomics_carbon.png",
                "publisher_image_alt": "Image",
                "publisher_imageH": "125",
                "publisher_imageW": "75",
            }
        elif publisher == "IDW Publishing":
            comicpublisher = {
                "publisher_image": "images/publisherlogos/logo-idwpublish_carbon.png",
                "publisher_image_alt": "IDW",
                "publisher_imageH": "50",
                "publisher_imageW": "100",
            }
        elif publisher == "Boom! Studios":
            comicpublisher = {
                "publisher_image": "images/publisherlogos/logo-boom_carbon.png",
                "publisher_image_alt": "Boom!",
                "publisher_imageH": "50",
                "publisher_imageW": "100",
            }

    if comicpublisher is not None:
        return comicpublisher

    # --- all other logos are safe for current interface changes.
    if publisher == "DC Comics":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-dccomics.png",
            "publisher_image_alt": "DC",
            "publisher_imageH": "75",
            "publisher_imageW": "75",
        }
    elif publisher == "Marvel":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-marvel.png",
            "publisher_image_alt": "Marvel",
            "publisher_imageH": "50",
            "publisher_imageW": "100",
        }
    elif publisher == "Dark Horse Comics" or publisher == "Dark Horse":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-darkhorse.png",
            "publisher_image_alt": "DarkHorse",
            "publisher_imageH": "100",
            "publisher_imageW": "75",
        }
    elif publisher == "Icon Comics":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-iconcomics.png",
            "publisher_image_alt": "Icon",
            "publisher_imageH": "100",
            "publisher_imageW": "100",
        }
    elif publisher == "Magnetic Press":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-magneticpress.png",
            "publisher_image_alt": "Magnetic Press",
            "publisher_imageH": "100",
            "publisher_imageW": "100",
        }
    elif publisher == "Max":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-max.png",
            "publisher_image_alt": "Max Comics",
            "publisher_imageH": "120",
            "publisher_imageW": "80",
        }
    elif publisher == "Rebellion":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-rebellion.png",
            "publisher_image_alt": "Rebellion",
            "publisher_imageH": "75",
            "publisher_imageW": "100",
        }
    elif publisher == "Red5":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-red5comics.png",
            "publisher_image_alt": "Red5",
            "publisher_imageH": "50",
            "publisher_imageW": "100",
        }
    elif publisher == "Vertigo":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-vertigo.png",
            "publisher_image_alt": "Vertigo",
            "publisher_imageH": "50",
            "publisher_imageW": "100",
        }
    elif publisher == "Shadowline":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-shadowline.png",
            "publisher_image_alt": "Shadowline",
            "publisher_imageH": "50",
            "publisher_imageW": "150",
        }
    elif publisher == "Archie Comics":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-archiecomics.png",
            "publisher_image_alt": "Archie",
            "publisher_imageH": "75",
            "publisher_imageW": "75",
        }
    elif publisher == "Oni Press":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-onipress.jpg",
            "publisher_image_alt": "Oni Press",
            "publisher_imageH": "50",
            "publisher_imageW": "100",
        }
    elif publisher == "Tokyopop":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-tokyopop.jpg",
            "publisher_image_alt": "Tokyopop",
            "publisher_imageH": "100",
            "publisher_imageW": "50",
        }
    elif publisher == "Midtown Comics":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-midtowncomics.jpg",
            "publisher_image_alt": "Midtown",
            "publisher_imageH": "50",
            "publisher_imageW": "100",
        }
    elif publisher == "Skybound":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-skybound.jpg",
            "publisher_image_alt": "Skybound",
            "publisher_imageH": "50",
            "publisher_imageW": "100",
        }
    elif publisher == "Dynamite Entertainment":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-dynamite.png",
            "publisher_image_alt": "Dynamite",
            "publisher_imageH": "50",
            "publisher_imageW": "125",
        }
    elif publisher == "Top Cow":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-topcow.png",
            "publisher_image_alt": "Top Cow",
            "publisher_imageH": "100",
            "publisher_imageW": "100",
        }
    elif publisher == "Cartoon Books":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-cartoonbooks.jpg",
            "publisher_image_alt": "Cartoon Books",
            "publisher_imageH": "75",
            "publisher_imageW": "90",
        }
    elif publisher == "Valiant":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-valiant.png",
            "publisher_image_alt": "Valiant",
            "publisher_imageH": "100",
            "publisher_imageW": "100",
        }
    elif publisher == "Action Lab":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-actionlabs.png",
            "publisher_image_alt": "Action Lab",
            "publisher_imageH": "100",
            "publisher_imageW": "100",
        }
    elif publisher == "Aspen MLT":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-aspen.png",
            "publisher_image_alt": "Aspen MLT",
            "publisher_imageH": "65",
            "publisher_imageW": "65",
        }
    elif publisher == "Zenescope Entertainment":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-zenescope.png",
            "publisher_image_alt": "Zenescope",
            "publisher_imageH": "125",
            "publisher_imageW": "125",
        }
    elif publisher == "2000 ad":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-2000ad.jpg",
            "publisher_image_alt": "2000 AD",
            "publisher_imageH": "75",
            "publisher_imageW": "50",
        }
    elif publisher == "Aardvark":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-aardvark.png",
            "publisher_image_alt": "Aardvark",
            "publisher_imageH": "90",
            "publisher_imageW": "106",
        }
    elif publisher == "Abstract Studio":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-abstract.png",
            "publisher_image_alt": "Abstract Studio",
            "publisher_imageH": "100",
            "publisher_imageW": "100",
        }
    elif publisher == "Aftershock Comics":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-aftershock.png",
            "publisher_image_alt": "Aftershock",
            "publisher_imageH": "100",
            "publisher_imageW": "75",
        }
    elif publisher == "Avatar Press":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-avatarpress.jpg",
            "publisher_image_alt": "Avatar Press",
            "publisher_imageH": "100",
            "publisher_imageW": "75",
        }
    elif publisher == "Benitez Productions":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-benitez.png",
            "publisher_image_alt": "Benitez",
            "publisher_imageH": "75",
            "publisher_imageW": "125",
        }
    elif publisher == "Boundless Comics":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-boundless.png",
            "publisher_image_alt": "Boundless",
            "publisher_imageH": "75",
            "publisher_imageW": "75",
        }
    elif publisher == "Darby Pop":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-darbypop.png",
            "publisher_image_alt": "Darby Pop",
            "publisher_imageH": "75",
            "publisher_imageW": "125",
        }
    elif publisher == "Devil's Due":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-devilsdue.png",
            "publisher_image_alt": "Devil's Due",
            "publisher_imageH": "75",
            "publisher_imageW": "75",
        }
    elif publisher == "Joe Books":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-joebooks.png",
            "publisher_image_alt": "Joe Books",
            "publisher_imageH": "100",
            "publisher_imageW": "100",
        }
    elif publisher == "Titan Comics":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-titan.png",
            "publisher_image_alt": "Titan",
            "publisher_imageH": "75",
            "publisher_imageW": "75",
        }
    elif publisher == "Viz":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-viz.png",
            "publisher_image_alt": "Viz",
            "publisher_imageH": "50",
            "publisher_imageW": "50",
        }
    elif publisher == "Warp Graphics":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-warpgraphics.png",
            "publisher_image_alt": "Warp Graphics",
            "publisher_imageH": "125",
            "publisher_imageW": "75",
        }
    elif any([publisher == "WildStorm", publisher == "Wildstorm"]):
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-wildstorm.png",
            "publisher_image_alt": "Wildstorm",
            "publisher_imageH": "75",
            "publisher_imageW": "75",
        }
    elif publisher == "AWA Studios":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-awa.png",
            "publisher_image_alt": "AWA Studios",
            "publisher_imageH": "75",
            "publisher_imageW": "125",
        }
    elif publisher == "Bongo":
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-bongo.png",
            "publisher_image_alt": "Bongo",
            "publisher_imageH": "79",
            "publisher_imageW": "125",
        }

    if comicpublisher is None:
        comicpublisher = {
            "publisher_image": "images/publisherlogos/logo-blank_publisher.png",
            "publisher_image_alt": None,
            "publisher_imageH": "0",
            "publisher_imageW": "0",
        }

    return comicpublisher


def lookupthebitches(filelist, folder, nzbname, nzbid, prov, hash, pulldate):
    watchlist = listLibrary()
    matchlist = []
    # get the weeknumber/year for the pulldate
    dt = datetime.datetime.strptime(pulldate, "%Y-%m-%d")
    weeknumber = dt.strftime("%U")
    year = dt.strftime("%Y")
    for f in filelist:
        file = re.sub(folder, "", f).strip()
        pp = comicarr.filechecker.FileChecker(justparse=True, file=file)
        parsedinfo = pp.listFiles()
        if parsedinfo["parse_status"] == "success":
            dyncheck = re.sub(r"[\|\s]", "", parsedinfo["dynamic_name"].lower()).strip()
            check = db.select_one(
                select(weekly).where(
                    weekly.c.DynamicName == dyncheck,
                    weekly.c.weeknumber == weeknumber,
                    weekly.c.year == year,
                    weekly.c.STATUS != "Downloaded",
                )
            )
            if check is not None:
                logger.fdebug("[%s] found match: %s #%s" % (file, check["COMIC"], check["ISSUE"]))
                matchlist.append(
                    {
                        "comicname": check["COMIC"],
                        "issue": check["ISSUE"],
                        "comicid": check["ComicID"],
                        "issueid": check["IssueID"],
                        "dynamicname": check["DynamicName"],
                    }
                )
        else:
            logger.fdebug("[%s] unable to match to the pull: %s" % (file, parsedinfo))

    if len(matchlist) > 0:
        for x in matchlist:
            if all([x["comicid"] not in watchlist, comicarr.CONFIG.PACK_0DAY_WATCHLIST_ONLY is False]):
                oneoff = True
                mode = "pullwant"
            elif all([x["comicid"] not in watchlist, comicarr.CONFIG.PACK_0DAY_WATCHLIST_ONLY is True]):
                continue
            else:
                oneoff = False
                mode = "want"
            comicarr.updater.nzblog(x["issueid"], nzbname, x["comicname"], id=nzbid, prov=prov, oneoff=oneoff)
            comicarr.updater.foundsearch(x["comicid"], x["issueid"], mode=mode, provider=prov, hash=hash)


def ignored_publisher_check(publisher):
    if publisher is not None:
        if comicarr.CONFIG.IGNORED_PUBLISHERS is not None and any(
            x
            for x in comicarr.CONFIG.IGNORED_PUBLISHERS
            if any(
                [
                    x.lower() == publisher.lower(),
                    ("*" in x and re.sub(r"\*", "", x.lower()).strip() in publisher.lower()),
                ]
            )
        ):
            logger.fdebug("Ignored publisher [%s]. Ignoring this result." % publisher)
            return True
    return False


def DateAddedFix():
    DA_A = datetime.datetime.today()
    DateAdded = DA_A.strftime("%Y-%m-%d")

    with db.get_engine().begin() as conn:
        # Batch UPDATE for issues table
        conn.execute(
            update(issues).where(issues.c.Status == "Wanted", issues.c.DateAdded.is_(None)).values(DateAdded=DateAdded)
        )
        # Batch UPDATE for annuals table
        conn.execute(
            update(annuals)
            .where(annuals.c.Status == "Wanted", annuals.c.DateAdded.is_(None), annuals.c.Deleted != 1)
            .values(DateAdded=DateAdded)
        )


def statusChange(status_from, status_to, comicid=None, bulk=False, api=True):
    the_list = []
    if bulk is False:  # type(comicid) != list:
        sc = db.select_all(select(issues.c.IssueID).where(issues.c.ComicID == comicid, issues.c.Status == status_from))
        for s in sc:
            the_list.append({"table": "issues", "issueid": s["IssueID"]})
        if comicarr.CONFIG.ANNUALS_ON:
            ac = db.select_all(
                select(annuals.c.IssueID).where(annuals.c.ComicID == comicid, annuals.c.Status == status_from)
            )
            for s in ac:
                the_list.append({"table": "annuals", "issueid": s["IssueID"]})
    else:
        if comicid == "All":
            sc = db.select_all(select(issues.c.IssueID).where(issues.c.Status == status_from))
            for s in sc:
                the_list.append({"table": "issues", "issueid": s["IssueID"]})
            if comicarr.CONFIG.ANNUALS_ON:
                ac = db.select_all(select(annuals.c.IssueID).where(annuals.c.Status == status_from))
                for s in ac:
                    the_list.append({"table": "annuals", "issueid": s["IssueID"]})

        else:
            for x in comicid:
                sc = db.select_all(
                    select(issues.c.IssueID).where(issues.c.ComicID == x, issues.c.Status == status_from)
                )
                for s in sc:
                    the_list.append({"table": "issues", "issueid": s["IssueID"]})
                if comicarr.CONFIG.ANNUALS_ON:
                    ac = db.select_all(
                        select(annuals.c.IssueID).where(annuals.c.ComicID == x, annuals.c.Status == status_from)
                    )
                    for s in ac:
                        the_list.append({"table": "annuals", "issueid": s["IssueID"]})

    # logger.info('the_list: %s' % the_list)
    # for genlist in chunker(the_list, 200):
    #    tmpsql = "SELECT IssueID FROM issues WHERE Status=? AND ComicID in ({seq})".format(status_from, seq=','.join(['?'] *(len(genlist) -1)))
    #    chkthis = myDB.upsert("issues", {'Status': status_to}, dict(myDB.select(tmpsql, genlist))) #select(tmpsql, genlist)
    #    logger.info('succeeded')

    # this probably won't scale well, but atm it's the best that can be done
    cnt = 0
    for x in the_list:
        try:
            db.upsert(x["table"], {"Status": status_to}, {"IssueID": x["issueid"], "Status": status_from})
        except Exception:
            pass
        else:
            cnt += 1

    rtnline = "Updated %s Issues from a status of %s to %s" % (cnt, status_from, status_to)
    logger.info(rtnline)

    return rtnline


def file_ops(path, dst, arc=False, one_off=False, multiple=False):
    #    # path = source path + filename
    #    # dst = destination path + filename
    #    # arc = to denote if the file_operation is being performed as part of a story arc or not where the series exists on the watchlist already
    #    # one-off = if the file_operation is being performed where it is either going into the grabbab_dst or story arc folder

    #    #get the crc of the file prior to the operation and then compare after to ensure it's complete.
    #    crc_check = comicarr.filechecker.crc(path)
    #    #will be either copy / move

    softlink_type = "absolute"

    if any([one_off, arc]):
        if multiple is True:
            action_op = "copy"
        else:
            action_op = comicarr.CONFIG.ARC_FILEOPS
        if comicarr.CONFIG.ARC_FILEOPS_SOFTLINK_RELATIVE is True:
            softlink_type = "relative"
    else:
        action_op = comicarr.CONFIG.FILE_OPTS

    if action_op == "copy" or (arc is True and any([action_op == "copy", action_op == "move"])):
        try:
            shutil.copy(path, dst)
        #        if crc_check == comicarr.filechecker.crc(dst):
        except Exception as e:
            logger.error("[%s] error : %s" % (action_op, e))
            return False
        return True

    elif action_op == "move":
        try:
            shutil.move(path, dst)
        #        if crc_check == comicarr.filechecker.crc(dst):
        except Exception as e:
            logger.error("[MOVE] error : %s" % e)
            return False
        return True

    elif any([action_op == "hardlink", action_op == "softlink"]):
        if "windows" not in comicarr.OS_DETECT.lower():
            # if it's an arc, then in needs to go reverse since we want to keep the src files (in the series directory)
            if action_op == "hardlink":
                # Open a file
                try:
                    fd = os.open(path, os.O_RDWR | os.O_CREAT)
                    os.close(fd)

                    # Now create another copy of the above file.
                    os.link(path, dst)
                    logger.info("Created hard link successfully!!")
                except OSError as e:
                    if e.errno == errno.EXDEV:
                        logger.warn(
                            "["
                            + str(e)
                            + "] Hardlinking failure. Could not create hardlink - dropping down to copy mode so that this operation can complete. Intervention is required if you wish to continue using hardlinks."
                        )
                        try:
                            shutil.copy(path, dst)
                            logger.fdebug("Successfully copied file to : " + dst)
                            return True
                        except Exception as e:
                            logger.error("[COPY] error : %s" % e)
                            return False
                    else:
                        logger.warn(
                            "["
                            + str(e)
                            + "] Hardlinking failure. Could not create hardlink - Intervention is required if you wish to continue using hardlinks."
                        )
                        return False

                hardlinks = os.lstat(dst).st_nlink
                if hardlinks > 1:
                    logger.info("Created hard link [" + str(hardlinks) + "] successfully!! (" + dst + ")")
                else:
                    logger.warn("Hardlink cannot be verified. You should probably verify that it is created properly.")

                return True

            elif action_op == "softlink":
                try:
                    # first we need to copy the file to the new location, then create the symlink pointing from new -> original
                    if not arc:
                        shutil.move(path, dst)
                        if os.path.lexists(path):
                            os.remove(path)
                        if softlink_type == "absolute":
                            os.symlink(dst, path)
                            logger.fdebug("Successfully created softlink [" + dst + " --> " + path + "]")
                        else:
                            os.symlink(os.path.relpath(dst, os.path.dirname(path)), path)
                            logger.fdebug(
                                "Successfully created (relative) softlink ["
                                + os.path.relpath(dst, os.path.dirname(path))
                                + " --> "
                                + path
                                + "]"
                            )

                    else:
                        if softlink_type == "absolute":
                            os.symlink(path, dst)
                            logger.fdebug("Successfully created softlink [" + path + " --> " + dst + "]")
                        else:
                            os.symlink(os.path.relpath(path, os.path.dirname(dst)), dst)
                            logger.fdebug(
                                "Successfully created (relative) softlink ["
                                + os.path.relpath(path, os.path.dirname(dst))
                                + " --> "
                                + dst
                                + "]"
                            )
                except OSError as e:
                    # if e.errno == errno.EEXIST:
                    #    os.remove(dst)
                    #    os.symlink( path, dst )
                    # else:
                    logger.warn(
                        "["
                        + str(e)
                        + "] Unable to create symlink. Dropping down to copy mode so that this operation can continue."
                    )
                    try:
                        shutil.copy(dst, path)
                        logger.fdebug("Successfully copied file [" + dst + " --> " + path + "]")
                    except Exception as e:
                        logger.error("[COPY] error : %s" % e)
                        return False

                return True

        else:
            # Not ready just yet.
            pass

            # softlinks = shortcut (normally junctions are called softlinks, but for this it's being called a softlink)
            # hardlinks = MUST reside on the same drive as the original
            # junctions = not used (for directories across same machine only but different drives)

            # option 1
            # this one needs to get tested
            # import ctypes
            # kdll = ctypes.windll.LoadLibrary("kernel32.dll")
            # kdll.CreateSymbolicLinkW(path, dst, 0)

            # option 2
            if comicarr.CONFIG.FILE_OPTS == "hardlink":
                try:
                    os.system(r"mklink /H dst path")
                    logger.fdebug("Successfully hardlinked file [" + dst + " --> " + path + "]")
                except OSError as e:
                    logger.warn(
                        "["
                        + e
                        + "] Unable to create symlink. Dropping down to copy mode so that this operation can continue."
                    )
                    try:
                        shutil.copy(dst, path)
                        logger.fdebug("Successfully copied file [" + dst + " --> " + path + "]")
                    except:
                        return False

            elif comicarr.CONFIG.FILE_OPTS == "softlink":  # ie. shortcut.
                try:
                    shutil.move(path, dst)
                    if os.path.lexists(path):
                        os.remove(path)
                    os.system(r"mklink dst path")
                    logger.fdebug("Successfully created symlink [" + dst + " --> " + path + "]")
                except OSError as e:
                    raise e
                    logger.warn(
                        "["
                        + e
                        + "] Unable to create softlink. Dropping down to copy mode so that this operation can continue."
                    )
                    try:
                        shutil.copy(dst, path)
                        logger.fdebug("Successfully copied file [" + dst + " --> " + path + "]")
                    except:
                        return False

    else:
        return False


def log_that_exception(except_info):

    # snip the log here and get the last 100 lines as quick leadup glance.
    leadup = tail_that_log()

    # logger.info('[LEADUP_LOG] %s' % leadup)
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
    logdate = now()
    db.upsert("exceptions_log", gather_info, {"date": logdate})

    # write the leadup log lines that were tailed above to the external file here...
    fileline = db.select_one(
        select(text("rowid"), exceptions_log.c.date).select_from(exceptions_log).where(exceptions_log.c.date == logdate)
    )
    with open(os.path.join(comicarr.CONFIG.LOG_DIR, "specific_" + str(fileline["rowid"]) + ".log"), "w") as f:
        f.writelines(leadup)
        f.write(except_info.get("traceback", None))


def tail_that_log():
    """Tail a file and get X lines from the end"""
    # place holder for the lines found
    lines_found = []

    f = open(os.path.join(comicarr.CONFIG.LOG_DIR, "comicarr.log"), "r")
    lines = 100
    buffer = 4098

    # block counter will be multiplied by buffer
    # to get the block size from the end
    block_counter = -1

    # loop until we find X lines
    while len(lines_found) <= lines:
        try:
            f.seek(block_counter * buffer, os.SEEK_END)
        except IOError:  # either file is too small, or too many lines requested
            f.seek(0)
            lines_found = f.readlines()
            break

        lines_found = f.readlines()

        # we found enough lines, get out
        # Removed this line because it was redundant the while will catch
        # it, I left it for history
        # if len(lines_found) > lines:
        #    break

        # decrement the block counter to get the
        # next X bytes
        block_counter -= 1

    return lines_found[-lines:]


# Magic numbers for checks below
# Reference: https://www.garykessler.net/library/file_sigs.html
magic_numbers = {
    "PDF": bytes([0x25, 0x50, 0x44, 0x46]),
    "ZIP": bytes([0x50, 0x4B, 0x03, 0x04]),
    "RAR": bytes([0x52, 0x61, 0x72, 0x21, 0x1A, 0x07]),  # Should cover both v4 and v5
    "7Z": bytes([0x37, 0x7A, 0xBC, 0xAF, 0x27, 0x1C]),
}


def check_file_condition(file_path):
    """Use magic numbers to confirm a file type, and do some sanity checks for quality of
        the file (CRC checks, etc.)

    Args:
        file_path (str): Location of the file to check

    Returns:
        dict: A dictionary containing a status (True/False for good/bad file), type (known file type),
            and quality (descriptive string)
    """
    logger.fdebug(f"Checking file condition of {file_path}")

    max_number_length = max(len(m) for m in magic_numbers.values())
    try:
        with open(file_path, "rb") as file:
            header = file.read(max_number_length)
    except Exception as e:
        logger.error(f"Could not open {file_path} to check for file type")
        return {"status": False, "type": "unknown", "quality": f"Failed to open file to check quality {e}."}

    if header.startswith(magic_numbers["ZIP"]):
        try:
            with zipfile.ZipFile(file_path, mode="r") as zf:
                test_result = zf.testzip()
                if test_result is not None:
                    return {"status": False, "type": "ZIP", "quality": f"CRC error in file {test_result}."}
        except Exception as e:
            logger.fdebug("Issue working with zip file.  Likely a broken archive.")
            return {"status": False, "type": "ZIP", "quality": f"Error processing zip compressed file: {e}."}

        return {"status": True, "type": "ZIP", "quality": "Good condition."}
    elif header.startswith(magic_numbers["RAR"]):
        try:
            with rarfile.RarFile(file_path, mode="r") as rarf:
                test_result = rarf.testrar()
                if test_result is not None:
                    return {"status": False, "type": "RAR", "quality": f"CRC error in file {test_result}."}
        except Exception as e:
            logger.fdebug("Issue working with rar file.  Likely a broken archive.")
            return {"status": False, "type": "RAR", "quality": f"Error processing rar compressed file: {e}."}

        return {"status": True, "type": "RAR", "quality": "Good condition."}
    elif header.startswith(magic_numbers["7Z"]):
        return {"status": True, "type": "7Z", "quality": "File is using 7zip compression."}
    elif header.startswith(magic_numbers["PDF"]):
        return {"status": True, "type": "PDF", "quality": "PDF file.  No quality checks performed."}
    else:
        return {"status": False, "type": "unknown", "quality": "Unknown file type, unknown condition"}


from threading import Thread


class ThreadWithReturnValue(Thread):
    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None, Verbose=None):
        if kwargs is None:
            kwargs = {}
        Thread.__init__(self, group, target, name, args, kwargs, Verbose)
        self._return = None

    def run(self):
        if self._Thread__target is not None:
            self._return = self._Thread__target(*self._Thread__args, **self._Thread__kwargs)

    def join(self):
        Thread.join(self)
        return self._return
