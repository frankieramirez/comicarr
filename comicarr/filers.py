# -*- coding: utf-8 -*-

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

import calendar
import datetime
import os
import pathlib
import re
import time

from sqlalchemy import or_, select

import comicarr
from comicarr import db, filechecker, helpers, logger
from comicarr.tables import annuals, comics, issues, storyarcs, weekly


class FileHandlers(object):
    def __init__(self, comic=None, issue=None, ComicID=None, IssueID=None, arcID=None, entity_type=None):

        self.weekly = None
        if ComicID is not None:
            self.comicid = ComicID
            self.comic = db.select_one(select(comics).where(comics.c.ComicID == ComicID))
            if not self.comic:
                self.weekly = db.select_one(
                    select(weekly).where((weekly.c.ComicID == ComicID) & (weekly.c.IssueID == IssueID))
                )
                if not self.weekly:
                    self.comic = None
        elif comic is not None:
            self.comic = comic
            self.comicid = None
        else:
            self.comic = None
            self.comicid = None

        if IssueID is not None:
            self.issueid = IssueID
            if entity_type == "annual":
                self.issue = db.select_one(
                    select(annuals).where(
                        annuals.c.IssueID == IssueID,
                        or_(annuals.c.Deleted.is_(None), annuals.c.Deleted != 1),
                    )
                )
            else:
                self.issue = db.select_one(select(issues).where(issues.c.IssueID == IssueID))
                if not self.issue and entity_type != "issue" and comicarr.CONFIG.ANNUALS_ON:
                    self.issue = db.select_one(
                        select(annuals).where(
                            annuals.c.IssueID == IssueID,
                            or_(annuals.c.Deleted.is_(None), annuals.c.Deleted != 1),
                        )
                    )
            if not self.issue:
                self.issue = None
        elif issue is not None:
            self.issue = issue
            self.issueid = None
        else:
            self.issue = None
            self.issueid = None

        if arcID is not None:
            self.arcid = arcID
            self.arc = db.select_one(select(storyarcs).where(storyarcs.c.IssueArcID == arcID))
        else:
            self.arc = None
            self.arcid = None

    def folder_create(self, booktype=None, update_loc=None, secondary=None, imprint=None):

        if update_loc is not None:
            comic_location = update_loc["temppath"]
            enforce_format = update_loc["tempff"]
            folder_format = update_loc["tempformat"]
            comicid = update_loc["comicid"]
        else:
            comic_location = comicarr.CONFIG.DESTINATION_DIR
            enforce_format = False
            folder_format = comicarr.CONFIG.FOLDER_FORMAT

        if folder_format is None:
            folder_format = "$Series ($Year)"

        publisher = re.sub("!", "", self.comic["ComicPublisher"])
        publisher = helpers.filesafe(publisher)

        if comicarr.OS_DETECT == "Windows":
            if "/" in folder_format:
                folder_format = re.sub("/", "\\", folder_format).strip()
        else:
            if "\\" in folder_format:
                folder_format = folder_format.replace("\\", "/").strip()

        if publisher is not None:
            if publisher.endswith("."):
                publisher = publisher[:-1]

        u_comicnm = self.comic["ComicName"]
        comicname_filesafe = helpers.filesafe(u_comicnm)
        comicdir = comicname_filesafe

        series = comicdir
        if any([series.endswith("."), series.endswith(".."), series.endswith("..."), series.endswith("....")]):
            if series.endswith("...."):
                series = series[:-4]
            elif series.endswith("..."):
                series = series[:-3]
            elif series.endswith(".."):
                series = series[:-2]
            elif series.endswith("."):
                series = series[:-1]

        if booktype is not None:
            if self.comic["Corrected_Type"] is not None:
                if self.comic["Corrected_Type"] != booktype:
                    booktype = booktype
                else:
                    booktype = self.comic["Corrected_Type"]
            else:
                booktype = booktype
        else:
            booktype = self.comic["Type"]

        if any([booktype is None, booktype == "None", booktype == "Print"]) or all(
            [booktype != "Print", comicarr.CONFIG.FORMAT_BOOKTYPE is False]
        ):
            chunk_fb = re.sub(r"\$Type", "", folder_format)
            chunk_b = re.compile(r"\s+")
            chunk_folder_format = chunk_b.sub(" ", chunk_fb)
            if booktype != "Print":
                booktype = "None"
        else:
            chunk_folder_format = folder_format

        if self.comic["ComicVersion"] is None:
            comicVol = "None"
        else:
            if booktype != "Print":
                comicVol = self.comic["ComicVersion"]
            else:
                comicVol = self.comic["ComicVersion"]
            if comicVol is None:
                comicVol = "None"

        if comicVol == "None":
            chunk_f_f = re.sub(r"\$VolumeN", "", chunk_folder_format)
            chunk_f = re.compile(r"\s+")
            chunk_folder_format = chunk_f.sub(" ", chunk_f_f)

        if any([imprint is None, imprint == "None"]):
            imprint = self.comic["PublisherImprint"]
        if any([imprint is None, imprint == "None"]):
            chunk_f_f = re.sub(r"\$Imprint", "", chunk_folder_format)
            chunk_f = re.compile(r"\s+")
            chunk_folder_format = chunk_f.sub(" ", chunk_f_f)

        chunk_folder_format = re.sub(r"\(\)|\[\]", "", chunk_folder_format).strip()
        ccf = chunk_folder_format.find("/ ")
        if ccf != -1:
            chunk_folder_format = chunk_folder_format[: ccf + 1] + chunk_folder_format[ccf + 2 :]
        ccf = chunk_folder_format.find(r"\ ")
        if ccf != -1:
            chunk_folder_format = chunk_folder_format[: ccf + 1] + chunk_folder_format[ccf + 2 :]
        ccf = chunk_folder_format.find(" /")
        if ccf != -1:
            chunk_folder_format = chunk_folder_format[:ccf] + chunk_folder_format[ccf + 1 :]
        ccf = chunk_folder_format.find(" \\")
        if ccf != -1:
            chunk_folder_format = chunk_folder_format[:ccf] + chunk_folder_format[ccf + 1 :]

        chunk_folder_format = re.sub(r"\s+", " ", chunk_folder_format)

        values = {
            "$Series": series,
            "$Publisher": publisher,
            "$Imprint": imprint,
            "$Year": self.comic["ComicYear"],
            "$series": series.lower(),
            "$publisher": publisher.lower(),
            "$VolumeY": "V" + self.comic["ComicYear"],
            "$VolumeN": comicVol.upper(),
            "$Type": booktype,
        }

        if update_loc is not None:
            ccdir = pathlib.PurePath(comic_location)
            ddir = pathlib.PurePath(comicarr.CONFIG.DESTINATION_DIR)
            dlc = pathlib.PurePath(self.comic["ComicLocation"])
            path_convert = True
            i = 0
            bb = []
            while i < len(dlc.parts):
                try:
                    if dlc.parts[i] == ddir.parts[i]:
                        i += 1
                        continue
                    else:
                        bb.append(dlc.parts[i])
                        i += 1
                except IndexError:
                    bb.append(dlc.parts[i])
                    i += 1
            bb_tuple = pathlib.PurePath(os.path.sep.join(bb))
            try:
                com_base = pathlib.PurePath(dlc).relative_to(ddir)
            except ValueError:
                dir_fix = []
                dir_parts = pathlib.PurePath(dlc).parts
                for dp in dir_parts:
                    try:
                        if self.comic["ComicYear"] is not None:
                            if self.comic["ComicYear"] in dp:
                                break
                        if self.comic["ComicName"] is not None:
                            if self.comic["ComicName"] in dp:
                                break
                        if self.comic["ComicPublisher"] is not None:
                            if self.comic["ComicPublisher"] in dp:
                                break
                        if self.comic["PublisherImprint"] is not None:
                            if self.comic["PublisherImprint"] in dp:
                                break
                        if self.comic["ComicVersion"] is not None:
                            if self.comic["ComicVersion"] in dp:
                                break
                        dir_fix.append(dp)
                    except:
                        pass

                if len(dir_fix) > 0:
                    spath = ""
                    t = 0
                    while t < len(dir_parts):
                        newpath = os.path.join(spath, dir_parts[t])
                        t += 1
                    com_base = newpath
            if comicarr.OS_DETECT == "Windows":
                p_path = pathlib.PureWindowsPath(ccdir)
            else:
                p_path = pathlib.PurePosixPath(ccdir)
            if enforce_format is True:
                first = helpers.replace_all(chunk_folder_format, values)
                if comicarr.CONFIG.REPLACE_SPACES:
                    first = first.replace(" ", comicarr.CONFIG.REPLACE_CHAR)
                comlocation = str(p_path.joinpath(first))
            else:
                comlocation = str(p_path.joinpath(com_base))

            return {"comlocation": comlocation, "path_convert": path_convert, "comicid": comicid}
        else:
            if secondary is not None:
                ppath = secondary
            else:
                ppath = comicarr.CONFIG.DESTINATION_DIR

            ddir = pathlib.PurePath(ppath)
            i = 0
            bb = []
            while i < len(ddir.parts):
                try:
                    bb.append(ddir.parts[i])
                    i += 1
                except IndexError:
                    break

            bb2 = bb[0]
            bb.pop(0)
            bb_tuple = pathlib.PurePath(os.path.sep.join(bb))
            if comicarr.OS_DETECT == "Windows":
                p_path = pathlib.PureWindowsPath(pathlib.PurePath(bb2).joinpath(bb_tuple))
            else:
                p_path = pathlib.PurePosixPath(pathlib.PurePath(bb2).joinpath(bb_tuple))

            first = helpers.replace_all(chunk_folder_format, values)

            if comicarr.CONFIG.REPLACE_SPACES:
                first = first.replace(" ", comicarr.CONFIG.REPLACE_CHAR)
            comlocation = str(p_path.joinpath(first))
            com_parentdir = str(p_path.joinpath(first).parent)

            if comlocation == "":
                logger.error("There is no Comic Location Path specified - please specify one in Config/Web Interface.")
                return

            return {"comlocation": comlocation, "subpath": bb_tuple, "com_parentdir": com_parentdir}

    def series_folder_collision_detection(self, comlocation, comicid, booktype, comicyear, volume):
        stmt = select(comics).where(
            comics.c.ComicLocation.ilike("%" + comlocation + "%") & (comics.c.ComicID != comicid)
        )
        chk = db.select_all(stmt)

        tryit = None
        if chk:
            for ck in chk:
                comloc = ck["ComicLocation"]
                if comloc == comlocation:
                    logger.info(
                        "[SERIES_FOLDER_COLLISION_DETECTION] %s already exists for %s (%s)."
                        % (ck["ComicLocation"], ck["ComicName"], ck["ComicYear"])
                    )
                    tmp_ff = os.path.basename(comicarr.CONFIG.FOLDER_FORMAT)
                    if ck["ComicYear"] != comicyear:
                        volumeyear = True
                    else:
                        volumeyear = False
                    if "$Type" not in tmp_ff and booktype != ck["Type"]:
                        logger.fdebug(
                            "[SERIES_FOLDER_COLLISION_DETECTION] Trying to rename using BookType declaration."
                        )
                        new_format = "%s [%s]" % (tmp_ff, "$Type")
                    elif "$Volume" not in tmp_ff:
                        logger.fdebug("[SERIES_FOLDER_COLLISION_DETECTION] Trying to rename using Volume declaration.")
                        volume_choice = "$VolumeY"
                        if volumeyear is False:
                            if volume is None:
                                volume_choice = "$VolumeY"
                            else:
                                volume_choice = "$VolumeN"
                        t_name = tmp_ff.find("$Series")
                        if t_name != -1:
                            new_format = "%s %s %s" % (
                                tmp_ff[: t_name + len("$Series") :],
                                volume_choice,
                                tmp_ff[t_name + len("$Series") + 1 :],
                            )

                    self.comic = {
                        "ComicPublisher": ck["ComicPublisher"],
                        "PublisherImprint": ck["PublisherImprint"],
                        "Corrected_Type": ck["Corrected_Type"],
                        "Type": booktype,
                        "ComicYear": comicyear,
                        "ComicName": ck["ComicName"],
                        "ComicLocation": ck["ComicLocation"],
                        "ComicVersion": volume,
                    }

                    update_loc = {
                        "temppath": comicarr.CONFIG.DESTINATION_DIR,
                        "tempff": True,
                        "tempformat": new_format,
                        "comicid": ck["ComicID"],
                    }
                    tryit = self.folder_create(update_loc=update_loc)
                    break

        logger.fdebug("tryit_response: %s" % (tryit,))
        return tryit

    def secondary_folders(self, comiclocation, secondary=None):
        if not secondary:
            secondary = comicarr.CONFIG.MULTIPLE_DEST_DIRS

        secondary_main = self.folder_create(secondary=secondary)
        secondaryfolders = secondary_main["comlocation"]

        if not os.path.exists(secondaryfolders):
            tmpbase = os.path.basename(comiclocation)
            tmpath = os.path.join(secondary_main["com_parentdir"], tmpbase)

            if os.path.exists(tmpath):
                secondaryfolders = tmpath

        return secondaryfolders

    def walk_the_walk(self):
        folder_location = comicarr.CONFIG.FOLDER_CACHE_LOCATION
        if folder_location is None:
            return {"status": False}

        logger.info("checking locally...")
        filelist = None

        logger.info("check_folder_cache: %s" % (comicarr.CHECK_FOLDER_CACHE))
        if comicarr.CHECK_FOLDER_CACHE is not None:
            rd = comicarr.CHECK_FOLDER_CACHE
            rd_mins = rd + datetime.timedelta(seconds=600)
            rd_now = datetime.datetime.utcfromtimestamp(time.time())
            if calendar.timegm(rd_mins.utctimetuple()) > calendar.timegm(rd_now.utctimetuple()):
                logger.info("using cached folder listing since < 10 minutes since last file check.")
                filelist = comicarr.FOLDER_CACHE

        if filelist is None:
            logger.info("generating new directory listing for folder_cache")
            flc = filechecker.FileChecker(folder_location, justparse=True, pp_mode=True)
            comicarr.FOLDER_CACHE = flc.listFiles()
            comicarr.CHECK_FOLDER_CACHE = datetime.datetime.utcfromtimestamp(helpers.utctimestamp())

        local_status = False
        filepath = None
        filename = None
        for fl in comicarr.FOLDER_CACHE["comiclist"]:
            logger.info("fl: %s" % (fl,))
            if self.arc is not None:
                comicname = self.arc["ComicName"]
                corrected_type = None
                alternatesearch = None
                booktype = self.arc["Type"]
                publisher = self.arc["Publisher"]
                issuenumber = self.arc["IssueNumber"]
                issuedate = self.arc["IssueDate"]
                self.arc["IssueName"]
                self.arc["Status"]
            elif self.comic is not None:
                comicname = self.comic["ComicName"]
                booktype = self.comic["Type"]
                corrected_type = self.comic["Corrected_Type"]
                alternatesearch = self.comic["AlternateSearch"]
                publisher = self.comic["ComicPublisher"]
                issuenumber = self.issue["Issue_Number"]
                issuedate = self.issue["IssueDate"]
                self.issue["IssueName"]
                self.issue["Status"]
            else:
                comicname = self.weekly["COMIC"]
                booktype = self.weekly["format"]
                corrected_type = None
                alternatesearch = None
                publisher = self.weekly["PUBLISHER"]
                issuenumber = self.weekly["ISSUE"]
                issuedate = self.weekly["SHIPDATE"]
                self.weekly["STATUS"]

            if booktype is not None:
                if (
                    all([booktype != "Print", booktype != "Digital", booktype != "None", booktype is not None])
                    and corrected_type != "Print"
                ) or any([corrected_type == "TPB", corrected_type == "GN", corrected_type == "HC"]):
                    if booktype == "One-Shot" and corrected_type is None:
                        booktype = "One-Shot"
                    else:
                        if booktype == "GN" and corrected_type is None:
                            booktype = "GN"
                        elif booktype == "HC" and corrected_type is None:
                            booktype = "HC"
                        else:
                            booktype = "TPB"

            wm = filechecker.FileChecker(watchcomic=comicname, Publisher=publisher, AlternateSearch=alternatesearch)
            watchmatch = wm.matchIT(fl)

            logger.info("watchmatch: %s" % (watchmatch,))

            if watchmatch["process_status"] == "fail":
                continue

            if watchmatch["justthedigits"] is not None:
                temploc = watchmatch["justthedigits"].replace("_", " ")
                if "Director's Cut" not in temploc:
                    temploc = re.sub("[\\#']", "", temploc)
            else:
                if any([booktype == "TPB", booktype == "GN", booktype == "HC", booktype == "One-Shot"]):
                    temploc = "1"
                else:
                    temploc = None
                    continue

            int_iss = helpers.issuedigits(issuenumber)
            issuedate[:4]

            if temploc is not None:
                fcdigit = helpers.issuedigits(temploc)
            elif (
                any([booktype == "TPB", booktype == "GN", booktype == "GC", booktype == "One-Shot"]) and temploc is None
            ):
                fcdigit = helpers.issuedigits("1")

            if int(fcdigit) == int_iss:
                logger.fdebug("[%s] Issue match - #%s" % (self.issueid, self.issue["Issue_Number"]))
                local_status = True
                if watchmatch["sub"] is None:
                    filepath = watchmatch["comiclocation"]
                    filename = watchmatch["comicfilename"]
                else:
                    filepath = os.path.join(watchmatch["comiclocation"], watchmatch["sub"])
                    filename = watchmatch["comicfilename"]
                break

        return {"status": local_status, "filename": filename, "filepath": filepath}
