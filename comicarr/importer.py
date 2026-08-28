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

import datetime
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping

import sqlalchemy.exc
from sqlalchemy import select, text

import comicarr
from comicarr import (
    cv,
    db,
    filechecker,
    filers,
    helpers,
    logger,
    mb,
    moveit,
    parseit,
    search,
    series_kind,
    series_metadata,
    updater,
)
from comicarr.app.core.workers import start_background_thread
from comicarr.tables import annuals, comics, issues


def _mass_add_runtime_context():
    """Return the active canonical runtime, if the process has one."""
    from comicarr.app.core.runtime import get_runtime_if_initialized

    ctx = get_runtime_if_initialized()
    return ctx if ctx is not None and not ctx.disposed else None


def _set_mass_add_pool(ctx, pool):
    """Publish the same MASS_ADD worker reference to runtime and legacy code."""
    if ctx is None:
        comicarr.MASS_ADD = pool
        return

    from comicarr.app.core.runtime import set_runtime_field

    set_runtime_field(ctx, "mass_add_pool", pool)


def _set_mass_refresh_pool(ctx, pool):
    """Publish the same MASS_REFRESH worker reference to runtime and legacy code."""
    if ctx is None:
        comicarr.MASS_REFRESH = pool
        return

    from comicarr.app.core.runtime import set_runtime_field

    set_runtime_field(ctx, "mass_refresh_pool", pool)


def is_exists(comicid):

    with db.get_engine().connect() as conn:
        stmt = select(comics.c.ComicID, comics.c.ComicName).where(comics.c.ComicID == comicid)
        comiclist = [dict(row._mapping) for row in conn.execute(stmt)]

    if any(comicid in x for x in comiclist):
        logger.info(comiclist[0]["ComicName"] + " is already in the database.")
        return False
    else:
        return False


def _emit_add_activity(status, comicid, comicname=None, reason_detail=None):
    """Narrate a series add. Failures must not be swallowed silently."""
    try:
        from comicarr.app.activity.producers import emit_series_activity

        emit_series_activity(
            "add",
            status,
            comicid,
            comicname=comicname,
            reason_code="import_failed" if status == "failed" else None,
            reason_detail=reason_detail,
        )
    except Exception as e:
        logger.fdebug("[ACTIVITY] add.%s emit skipped: %s" % (status, e))


def addvialist(seriesQueue, issueWantQueue):
    while True:
        if seriesQueue.qsize() >= 1:
            time.sleep(3)
            item = seriesQueue.get(True)
            if item == "exit":
                break
            seriesyear = item.get("seriesyear")
            if item["comicname"] is not None:
                if seriesyear is not None:
                    logger.info(
                        "[MASS-ADD][1/%s] Now adding %s (%s) [%s] "
                        % (seriesQueue.qsize() + 1, item["comicname"], seriesyear, item["comicid"])
                    )
                else:
                    logger.info(
                        "[MASS-ADD][1/%s] Now adding %s [%s] "
                        % (seriesQueue.qsize() + 1, item["comicname"], item["comicid"])
                    )
            else:
                logger.info("[MASS-ADD][1/%s] Now adding ComicID: %s " % (seriesQueue.qsize() + 1, item["comicid"]))

            try:
                if "suppress_addall" in item.keys():
                    addComictoDB(item["comicid"], suppress_addall=item["suppress_addall"])
                else:
                    addComictoDB(item["comicid"])
            except Exception as e:
                logger.error("[MASS-ADD] Failed adding %s: %s" % (item["comicid"], e))
                _emit_add_activity("failed", item["comicid"], comicname=item.get("comicname"), reason_detail=str(e))
        elif issueWantQueue.qsize() > 0:
            time.sleep(1)
            issueItem = issueWantQueue.get(True)
            markIssueWantedById(issueItem)
        else:
            seriesQueue.put("exit")
    return False


def markIssueWantedById(issueId):
    with db.get_engine().connect() as conn:
        stmt = (
            select(
                issues.c.IssueID,
                comics.c.ComicName,
                issues.c.Issue_Number,
                comics.c.ComicID,
                comics.c.ComicYear,
                issues.c.Status,
            )
            .select_from(issues.join(comics, issues.c.ComicID == comics.c.ComicID, isouter=True))
            .where(issues.c.IssueID == issueId)
        )
        issue = next((dict(row._mapping) for row in conn.execute(stmt)), None)

    annual_check = False
    if issue is None:
        with db.get_engine().connect() as conn:
            stmt = (
                select(
                    annuals.c.IssueID,
                    comics.c.ComicName,
                    annuals.c.ReleaseComicName,
                    annuals.c.Issue_Number,
                    comics.c.ComicID,
                    comics.c.ComicYear,
                    annuals.c.Status,
                )
                .select_from(annuals.join(comics, annuals.c.ComicID == comics.c.ComicID, isouter=True))
                .where(annuals.c.IssueID == issueId)
                .where(annuals.c.Deleted == 0)
            )
            issue = next((dict(row._mapping) for row in conn.execute(stmt)), None)

        if issue is None:
            logger.warning(
                f"Tried setting wanted status for issue with ID {issueId} in MASS-ADD thread but could not find issue"
            )
            return
        else:
            annual_check = True
            comicname = issue["ReleaseComicName"]
            issuenumber = issue["Issue_Number"]
            comicid = issue["ComicID"]
    else:
        comicname = issue["ComicName"]
        issuenumber = issue["Issue_Number"]
        comicid = issue["ComicID"]

    match issue["Status"]:
        case "Downloaded" | "Wanted" | "Snatched" | "Failed":
            logger.info(
                f"Tried setting wanted status for {comicname} [ID:{comicid}] issue #{issuenumber} in MASS-ADD thread but it is already in the {issue['Status']} state"
            )
            return
        case _:
            logger.info(
                f"Changing status of {comicname} [ID:{comicid}] issue #{issuenumber} from {issue['Status']} to Wanted"
            )

    controlValueDict = {"IssueID": issueId}
    newValueDict = {"Status": "Wanted"}

    if annual_check:
        db.upsert("annuals", newValueDict, controlValueDict)
    else:
        db.upsert("issues", newValueDict, controlValueDict)

    logger.fdebug(f"Finished changing status of {comicname} [ID:{comicid}] issue #{issuenumber} to Wanted")


def addComictoDB(
    comicid,
    mismatch=None,
    pullupd=None,
    imported=None,
    ogcname=None,
    calledfrom=None,
    annload=None,
    chkwant=None,
    issuechk=None,
    issuetype=None,
    latestissueinfo=None,
    csyear=None,
    fixed_type=None,
    suppress_addall=None,
):

    provider = series_kind.provider_of(comicid)
    if provider is series_kind.SeriesProvider.MANGADEX:
        return addMangaToDB(comicid, imported=imported, calledfrom=calledfrom)
    if provider is series_kind.SeriesProvider.MYANIMELIST:
        return addMangaToDB_MAL(comicid, imported=imported, calledfrom=calledfrom)

    from comicarr import metron

    if metron.is_metron_id(comicid):
        metron_id = metron.strip_metron_prefix(comicid)
        cv_comicid = metron.get_cv_id(metron_id)
        if not cv_comicid:
            raise ValueError(
                "Metron series %s has no ComicVine mapping - cannot add. "
                "Try disabling Metron search and re-searching via ComicVine." % metron_id
            )
        logger.info("[METRON] Resolved Metron series %s to ComicVine volume %s" % (metron_id, cv_comicid))
        comicid = cv_comicid

    controlValueDict = {"ComicID": comicid}

    with db.get_engine().connect() as conn:
        stmt = select(comics).where(comics.c.ComicID == comicid)
        dbcomic = next((dict(row._mapping) for row in conn.execute(stmt)), None)

    bypass = True
    if dbcomic is not None:
        if chkwant is not None:
            logger.fdebug(
                "ComicID: " + str(comicid) + " already exists. Not adding from the future pull list at this time."
            )
            return "Exists"
        if dbcomic["Status"] == "Active":
            series_status = "Active"
        elif dbcomic["Status"] == "Paused":
            series_status = "Paused"
        else:
            series_status = "Loading"

        newValueDict = {"Status": "Loading"}
        comlocation = dbcomic["ComicLocation"]
        if comlocation is None:
            bypass = False
        else:
            lastissueid = dbcomic["LatestIssueID"]
            serieslast_updated = dbcomic["LastUpdated"]
            aliases = dbcomic["AlternateSearch"]
            logger.info("aliases currently: %s" % aliases)
            old_description = dbcomic["DescriptionEdit"]

            FirstImageSize = dbcomic["FirstImageSize"]

            if not latestissueinfo:
                latestissueinfo = []
                latestissueinfo.append({"latestiss": dbcomic["LatestIssue"], "latestdate": dbcomic["LatestDate"]})

            if comicarr.CONFIG.CREATE_FOLDERS is True:
                checkdirectory = filechecker.validateAndCreateDirectory(comlocation, True)
                if not checkdirectory:
                    logger.warn("Error trying to validate/create directory. Aborting this process at this time.")
                    return {"status": "incomplete"}
            oldcomversion = dbcomic["ComicVersion"]
            db_check_values = {
                "comicname": dbcomic["ComicName"],
                "comicyear": dbcomic["ComicYear"],
                "publisher": dbcomic["ComicPublisher"],
                "detailurl": dbcomic["DetailURL"],
                "total_count": dbcomic["Total"],
            }

    if dbcomic is None or bypass is False:
        newValueDict = {"ComicName": "Comic ID: %s" % (comicid), "Status": "Loading"}
        if all([imported is not None, imported != "None", comicarr.CONFIG.IMP_PATHS is True]):
            try:
                comlocation = os.path.dirname(imported["filelisting"][0]["comiclocation"])
            except Exception:
                comlocation = None
        else:
            comlocation = None
        oldcomversion = None
        series_status = "Loading"
        serieslast_updated = None
        lastissueid = None
        aliases = None
        FirstImageSize = 0
        old_description = None
        db_check_values = None

    db.upsert("comics", newValueDict, controlValueDict)

    if all([pullupd is None, calledfrom != "maintenance"]):
        helpers.ComicSort(comicorder=comicarr.COMICSORT, imported=comicid)

    comic = cv.getComic(comicid, "comic", series=True)

    if not comic:
        logger.warn("Error fetching comic. ID for : " + comicid)
        if dbcomic is None:
            newValueDict = {"ComicName": "Fetch failed, try refreshing. (%s)" % (comicid), "Status": "Active"}
        else:
            if series_status == "Active" or series_status == "Loading":
                newValueDict = {"Status": "Active"}
            else:
                newValueDict = {"Status": "Paused"}
        db.upsert("comics", newValueDict, controlValueDict)
        return {"status": "incomplete"}

    if comic["ComicName"].startswith("The "):
        sortname = comic["ComicName"][4:]
    else:
        sortname = comic["ComicName"]

    if db_check_values is not None:
        if comic["ComicURL"] != db_check_values["detailurl"]:
            logger.warn(
                "[CORRUPT-COMICID-DETECTION-ENABLED] ComicID may have been removed from CV"
                " and replaced with an entirely different series/volume. Checking some values"
                " to make sure before proceeding..."
            )
            i_choose_violence = cv.check_that_biatch(comicid, db_check_values, comic)
            if i_choose_violence:
                db.upsert("comics", {"Status": "Paused", "cv_removed": 1}, {"ComicID": comicid})
                return {"status": "incomplete"}

    comic["Corrected_Type"] = fixed_type
    if fixed_type is not None and fixed_type != comic["Type"]:
        logger.info("Forced Comic Type to : %s" % comic["Corrected_Type"])

    logger.info("Now adding/updating: " + comic["ComicName"])
    if not comicarr.CONFIG.CV_ONLY:
        if mismatch == "no" or mismatch is None:
            gcdinfo = parseit.GCDScraper(comic["ComicName"], comic["ComicYear"], comic["ComicIssues"], comicid)
            if gcdinfo == "No Match":
                updater.no_searchresults(comicid)
                nomatch = "true"
                logger.info(
                    "There was an error when trying to add " + comic["ComicName"] + " (" + comic["ComicYear"] + ")"
                )
                return nomatch
            else:
                pass

        elif mismatch == "yes":
            with db.get_engine().connect() as conn:
                CV_EXcomicid = next(
                    (
                        dict(row._mapping)
                        for row in conn.execute(text("SELECT * from exceptions WHERE ComicID=:p0"), {"p0": comicid})
                    ),
                    None,
                )
            if CV_EXcomicid["variloop"] is None:
                pass
            else:
                CV_EXcomicid["variloop"]
                NewComicID = CV_EXcomicid["NewComicID"]
                CV_EXcomicid["GComicID"]
                resultURL = "/series/" + str(NewComicID) + "/"
                gcdinfo = parseit.GCDdetails(
                    comseries=None,
                    resultURL=resultURL,
                    vari_loop=0,
                    ComicID=comicid,
                    TotalIssues=0,
                    issvariation="no",
                    resultPublished=None,
                )

    CV_NoYearGiven = "no"
    if any(
        [
            comic["ComicYear"] is None,
            comic["ComicYear"] == "0000",
            comic["ComicYear"][-1:] == "-",
            comic["ComicYear"] == "2099",
        ]
    ):
        if comicarr.CONFIG.CV_ONLY:
            logger.info("Uh-oh. I cannot find a Series Year for this series. I am going to try analyzing deeper.")
            SeriesYear = cv.getComic(comicid, "firstissue", comic["FirstIssueID"])
            if not SeriesYear or SeriesYear == "2099":
                try:
                    if int(comic["ComicYear"]) == 2099:
                        logger.fdebug(
                            "Incorrect Series year detected (%s) ..."
                            " Correcting to current year as this is probably a new series" % (comic["ComicYear"])
                        )
                        SeriesYear = str(datetime.datetime.now().year)
                except Exception:
                    return
            if SeriesYear == "0000":
                logger.info(
                    "Ok - I could not find a Series Year at all. Loading in the issue data now and will figure out the Series Year."
                )
                CV_NoYearGiven = "yes"
                issued = cv.getComic(comicid, "issue")
                if not issued:
                    return
                SeriesYear = issued["firstdate"][:4]
        else:
            SeriesYear = gcdinfo["SeriesYear"]
    else:
        SeriesYear = comic["ComicYear"]

    if any([int(SeriesYear) > int(datetime.datetime.now().year) + 1, int(SeriesYear) == 2099]) and csyear is not None:
        logger.info(
            "Corrected year of "
            + str(SeriesYear)
            + " to corrected year for series that was manually entered previously of "
            + str(csyear)
        )
        SeriesYear = csyear

    logger.info("Sucessfully retrieved details for " + comic["ComicName"])

    weeklyissue_check = []

    if oldcomversion is not None:
        if re.sub(r"[^0-9]", "", oldcomversion).strip() == comic["incorrect_volume"]:
            oldcomversion = None
    if any([oldcomversion is None, oldcomversion == "None"]):
        logger.info("Previous version detected as None - seeing if update required")
        if comic["ComicVersion"].isdigit():
            comicVol = "v" + comic["ComicVersion"]
            logger.info("Updated version to :" + str(comicVol))
            if all([comicarr.CONFIG.SETDEFAULTVOLUME is False, comicVol == "v1"]):
                comicVol = None
        else:
            if comicarr.CONFIG.SETDEFAULTVOLUME is True:
                comicVol = "v1"
            else:
                comicVol = None
    else:
        comicVol = oldcomversion
        if all([comicarr.CONFIG.SETDEFAULTVOLUME is True, comicVol is None]):
            comicVol = "v1"

    comicIssues = comic["ComicIssues"]

    logger.fdebug("comicIssues: %s" % comicIssues)
    logger.fdebug("seriesyear: %s / currentyear: %s" % (SeriesYear, helpers.today()[:4]))
    logger.fdebug("comicType: %s" % comic["Type"])
    if all(
        [
            int(comicIssues) == 1,
            SeriesYear < helpers.today()[:4],
            comic["Type"] != "One-Shot",
            comic["Type"] != "TPB",
            comic["Type"] != "HC",
            comic["Type"] != "GN",
        ]
    ):
        logger.info("Determined to be a one-shot issue. Forcing Edition to One-Shot")
        booktype = "One-Shot"
    else:
        if comic["Type"] == "None":
            booktype = None
        else:
            booktype = comic["Type"]

    u_comicnm = comic["ComicName"]
    comicname_filesafe = helpers.filesafe(u_comicnm)

    dir_rename = False

    if comlocation is None:
        comic_values = {
            "ComicName": comic["ComicName"],
            "ComicPublisher": comic["ComicPublisher"],
            "PublisherImprint": comic["PublisherImprint"],
            "ComicYear": SeriesYear,
            "ComicVersion": comicVol,
            "Type": booktype,
            "Corrected_Type": comic["Corrected_Type"],
        }

        dothedew = filers.FileHandlers(comic=comic_values)
        comvalues = dothedew.folder_create()
        comlocation = comvalues["comlocation"]
        comvalues["subpath"]

        sck = filers.FileHandlers(comic=comic_values)
        scheck = sck.series_folder_collision_detection(comlocation, comicid, booktype, SeriesYear, comicVol)
        if scheck is not None:
            comlocation = scheck["comlocation"]
    else:
        comlocation.replace(comicarr.CONFIG.DESTINATION_DIR, "").strip()

        if comic["ComicYear"] == "2099" and SeriesYear:
            badyears = [i.start() for i in re.finditer("2099", comlocation)]
            num_bad = len(badyears)
            if num_bad == 1:
                new_location = re.sub("2099", SeriesYear, comlocation)
                dir_rename = True
            elif num_bad > 1:
                new_location = (
                    comlocation[: badyears[num_bad - 1]] + SeriesYear + comlocation[badyears[num_bad - 1] + 1 :]
                )
                dir_rename = True

        if dir_rename and all([new_location != comlocation, os.path.isdir(comlocation)]):
            logger.fdebug("Attempting to rename existing location [%s]" % (comlocation))
            try:
                if not os.path.exists(os.path.split(os.path.split(new_location)[0])[0]):
                    logger.fdebug("making directory: %s" % os.path.split(os.path.split(new_location)[0])[0])
                    os.mkdir(os.path.split(os.path.split(new_location)[0])[0])
                if not os.path.exists(os.path.split(new_location)[0]):
                    logger.fdebug("making directory: %s" % os.path.split(new_location)[0])
                    os.mkdir(os.path.split(new_location)[0])
                logger.info("Renaming directory: %s --> %s" % (comlocation, new_location))
                shutil.move(comlocation, new_location)
            except Exception as e:
                if "No such file or directory" in e:
                    if comicarr.CONFIG.CREATE_FOLDERS:
                        checkdirectory = filechecker.validateAndCreateDirectory(new_location, True)
                        if not checkdirectory:
                            logger.warn(
                                "Error trying to validate/create directory. Aborting this process at this time."
                            )
                else:
                    logger.warn("Unable to rename existing directory: %s" % e)

    if not dir_rename and comlocation is not None:
        if os.path.isdir(comlocation):
            logger.info("Directory (" + comlocation + ") already exists! Continuing...")
        else:
            if comicarr.CONFIG.CREATE_FOLDERS is True:
                checkdirectory = filechecker.validateAndCreateDirectory(comlocation, True)
                if not checkdirectory:
                    logger.warn("Error trying to validate/create directory. Aborting this process at this time.")
                    return {"status": "incomplete"}
    else:
        logger.warn(
            "Comic Location path has not been specified as required in your configuration. Aborting this process at this time."
        )
        return {"status": "incomplete"}

    if not comicarr.CONFIG.CV_ONLY:
        if gcdinfo["gcdvariation"] == "cv":
            comicIssues = str(int(comic["ComicIssues"]) + 1)

    cimage = os.path.join(comicarr.CONFIG.CACHE_DIR, str(comicid) + ".jpg")
    if comicarr.CONFIG.ALTERNATE_LATEST_SERIES_COVERS is False or not os.path.isfile(cimage):
        cimage = os.path.join(comicarr.CONFIG.CACHE_DIR, str(comicid) + ".jpg")
        PRComicImage = os.path.join("cache", str(comicid) + ".jpg")
        ComicImage = helpers.replacetheslash(PRComicImage)
        coversize = 0
        if os.path.isfile(cimage):
            statinfo = os.stat(cimage)
            coversize = statinfo.st_size

        if FirstImageSize != 0 and (os.path.isfile(cimage) is True and FirstImageSize == coversize):
            logger.fdebug("Cover already exists for series. Not redownloading.")
        else:
            covercheck = helpers.getImage(comicid, comic["ComicImage"])
            FirstImageSize = covercheck["coversize"]
            if covercheck["status"] == "retry":
                logger.info("Attempting to retrieve alternate comic image for the series.")
                covercheck = helpers.getImage(comicid, comic["ComicImageALT"])

        if comicarr.CONFIG.COMIC_COVER_LOCAL is True:
            cloc_it = []
            if comlocation is not None and all(
                [os.path.isdir(comlocation) is True, os.path.isfile(os.path.join(comlocation, "cover.jpg")) is False]
            ):
                cloc_it.append(comlocation)

            if all([comicarr.CONFIG.MULTIPLE_DEST_DIRS is not None, comicarr.CONFIG.MULTIPLE_DEST_DIRS != "None"]):
                if all(
                    [
                        os.path.isdir(os.path.join(comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(comlocation)))
                        is True,
                        os.path.isfile(
                            os.path.join(comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(comlocation), "cover.jpg")
                        )
                        is False,
                    ]
                ):
                    cloc_it.append(os.path.join(comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(comlocation)))
                else:
                    ff = comicarr.filers.FileHandlers(comic=comic)
                    cloc = ff.secondary_folders(comlocation)
                    if os.path.isfile(os.path.join(cloc, "cover.jpg")) is False:
                        cloc_it.append(cloc)

            for clocit in cloc_it:
                try:
                    comiclocal = os.path.join(clocit, "cover.jpg")
                    shutil.copyfile(cimage, comiclocal)
                    if comicarr.CONFIG.ENFORCE_PERMS:
                        filechecker.setperms(comiclocal)
                except IOError as e:
                    if "No such file or directory" not in str(e):
                        logger.error(
                            "[%s] Unable to save cover (%s) into series directory (%s) at this time."
                            % (e, cimage, comiclocal)
                        )

    else:
        ComicImage = None

    if comicarr.CONFIG.COVER_FOLDER_LOCAL is True:
        if comic["ComicImageThumbnail"] != "None":
            if not os.path.exists(os.path.join(comlocation, "folder.jpg")):
                th_check = helpers.getImage(
                    comicid, comic["ComicImageThumbnail"], thumbnail_path=os.path.join(comlocation, "folder.jpg")
                )
                if th_check["status"] == "success":
                    logger.fdebug("Thumbnail image successfully stored as %s" % os.path.join(comlocation, "folder.jpg"))
        else:
            logger.fdebug("Thumbnail not present on CV. Not storing locallly.")

    as_d = filechecker.FileChecker(watchcomic=comic["ComicName"])
    as_dinfo = as_d.dynamic_replace(comic["ComicName"])
    tmpseriesname = as_dinfo["mod_seriesname"]
    dynamic_seriesname = re.sub(r"[\|\s]", "", tmpseriesname.lower()).strip()

    if comic["Issue_List"] != "None":
        issue_list = json.dumps(comic["Issue_List"])
    else:
        issue_list = None

    if comic["Aliases"] != "None":
        if all([aliases is not None, aliases != "None"]):
            for x in aliases.split("##"):
                aliaschk = [x for y in comic["Aliases"].split("##") if y == x]
                if aliaschk and x not in aliases.split("##"):
                    aliases += "##" + "".join(x)
                else:
                    if x not in aliases.split("##"):
                        aliases += "##" + x
        else:
            aliases = comic["Aliases"]
    else:
        aliases = aliases

    Cdesc = comic["ComicDescription"]
    if Cdesc != "None":
        cdes_find = Cdesc.find("Collected")
        cdes_removed = Cdesc[:cdes_find]
    else:
        cdes_removed = None

    controlValueDict = {"ComicID": comicid}
    newValueDict = {
        "ComicName": comic["ComicName"],
        "ComicSortName": sortname,
        "ComicName_Filesafe": comicname_filesafe,
        "DynamicComicName": dynamic_seriesname,
        "ComicYear": SeriesYear,
        "ComicImage": ComicImage,
        "FirstImageSize": FirstImageSize,
        "ComicImageURL": comic.get("ComicImage", ""),
        "ComicImageALTURL": comic.get("ComicImageALT", ""),
        "Total": comicIssues,
        "ComicVersion": comicVol,
        "ComicLocation": comlocation,
        "ComicPublisher": comic["ComicPublisher"],
        "Description": cdes_removed,
        "DescriptionEdit": old_description,
        "PublisherImprint": comic["PublisherImprint"],
        "DetailURL": comic["ComicURL"],
        "AlternateSearch": aliases,
        "ComicPublished": None,
        "Type": booktype,
        "Corrected_Type": comic["Corrected_Type"],
        "Collects": issue_list,
        "DateAdded": helpers.today(),
        "Status": "Loading",
    }

    db.upsert("comics", newValueDict, controlValueDict)

    if all([pullupd is None, calledfrom != "maintenance"]):
        helpers.ComicSort(sequence="update")

    if CV_NoYearGiven == "no":
        issued = cv.getComic(comicid, "issue")
        if issued is None:
            logger.warn("Unable to retrieve data from ComicVine. Get your own API key already!")
            return {"status": "incomplete"}
    logger.info("Successfully retrieved issue details for " + comic["ComicName"])

    updateddata = updateissuedata(
        comicid,
        comic["ComicName"],
        issued,
        comicIssues,
        calledfrom,
        SeriesYear=SeriesYear,
        latestissueinfo=latestissueinfo,
        serieslast_updated=serieslast_updated,
        series_status=series_status,
        suppress_addall=suppress_addall,
    )
    try:
        if updateddata["status"] == "failure":
            logger.warn(
                "Unable to properly retrieve issue details - this is usually due to either irregular issue numbering, or problems with CV"
            )
            return {"status": "incomplete"}
    except Exception:
        pass

    issuedata = updateddata["issuedata"]
    anndata = updateddata["annualchk"]
    updateddata["nostatus"]
    json_updated = updateddata["json_updated"]
    importantdates = updateddata["importantdates"]
    if issuedata is None:
        logger.warn(
            "Unable to complete Refreshing / Adding issue data - this WILL create future problems if not addressed."
        )
        return {"status": "incomplete"}

    if any([calledfrom is None, calledfrom == "maintenance"]):
        issue_collection(issuedata, nostatus="False", serieslast_updated=serieslast_updated)
        if anndata:
            manualAnnual(annchk=anndata, series_status=series_status)

    if comicarr.CONFIG.ALTERNATE_LATEST_SERIES_COVERS is True:
        cimage = os.path.join(comicarr.CONFIG.CACHE_DIR, comicid + ".jpg")
        coversize = 0
        if os.path.isfile(cimage):
            statinfo = os.stat(cimage)
            coversize = statinfo.st_size

        if os.path.isfile(cimage) and all([FirstImageSize != 0, FirstImageSize == coversize]):
            logger.fdebug("Cover already exists for series. Not redownloading.")
        else:
            image_it(comicid, importantdates["LatestIssueID"], comlocation, comic["ComicImage"])
    else:
        logger.fdebug(
            "no update required - lastissueid [%s] = latestissueid [%s]"
            % (lastissueid, importantdates["LatestIssueID"])
        )

    if (comicarr.CONFIG.CVINFO or (comicarr.CONFIG.CV_ONLY and comicarr.CONFIG.CVINFO)) and os.path.isdir(comlocation):
        if os.path.isfile(os.path.join(comlocation, "cvinfo")) is False:
            with open(os.path.join(comlocation, "cvinfo"), "w") as text_file:
                text_file.write(str(comic["ComicURL"]))

    if calledfrom == "weekly":
        logger.info(
            "Successfully refreshed "
            + comic["ComicName"]
            + " ("
            + str(SeriesYear)
            + "). Returning to Weekly issue comparison."
        )
        logger.info("Update issuedata for " + str(issuechk) + " of : " + str(weeklyissue_check))
        return {
            "status": "complete",
            "issuedata": issuedata,
        }

    elif calledfrom == "dbupdate":
        logger.info("returning to dbupdate module")
        return {
            "status": "complete",
            "issuedata": issuedata,
            "anndata": anndata,
        }

    elif calledfrom == "weeklycheck":
        logger.info(
            "Successfully refreshed "
            + comic["ComicName"]
            + " ("
            + str(SeriesYear)
            + "). Returning to Weekly issue update."
        )
        return

    logger.info("Updating complete for: " + comic["ComicName"])

    latestiss = importantdates["LatestIssue"]
    importantdates["LatestDate"]
    lastpubdate = importantdates["LastPubDate"]
    series_status = importantdates["SeriesStatus"]
    if imported is None or imported == "None" or imported == "futurecheck":
        pass
    else:
        if comicarr.CONFIG.IMP_MOVE:
            logger.info("Mass import - Move files")
            moveit.movefiles(comicid, comlocation, imported)
        else:
            logger.info("Mass import - Moving not Enabled. Setting Archived Status for import.")
            moveit.archivefiles(comicid, comlocation, imported)

    with db.get_engine().connect() as conn:
        stmt = (
            select(issues.c.Status)
            .where(issues.c.ComicID == comicid)
            .where(issues.c.Int_IssueNumber == helpers.issuedigits(latestiss))
        )
        statbefore = next((dict(row._mapping) for row in conn.execute(stmt)), None)

    logger.fdebug("issue: " + latestiss + " status before chk :" + str(statbefore["Status"]))
    updater.forceRescan(comicid)

    if not json_updated and comicarr.CONFIG.SERIES_METADATA_LOCAL is True:
        sm = series_metadata.metadata_Series(comicid, bulk=False, api=False)
        sm.update_metadata()

    with db.get_engine().connect() as conn:
        stmt = (
            select(issues.c.Status)
            .where(issues.c.ComicID == comicid)
            .where(issues.c.Int_IssueNumber == helpers.issuedigits(latestiss))
        )
        statafter = next((dict(row._mapping) for row in conn.execute(stmt)), None)

    logger.fdebug("issue: " + latestiss + " status after chk :" + str(statafter["Status"]))

    logger.fdebug("pullupd: " + str(pullupd))
    logger.fdebug("lastpubdate: " + str(lastpubdate))
    logger.fdebug("series_status: " + str(series_status))
    if pullupd is None:
        if comicarr.CONFIG.AUTOWANT_UPCOMING and lastpubdate == "Present" and series_status == "Active":
            logger.fdebug("latestissue: #" + str(latestiss))
            with db.get_engine().connect() as conn:
                stmt = (
                    select(issues)
                    .where(issues.c.ComicID == comicid)
                    .where(issues.c.Int_IssueNumber == helpers.issuedigits(latestiss))
                )
                chkstats = next((dict(row._mapping) for row in conn.execute(stmt)), None)

            if chkstats is None:
                if comicarr.CONFIG.ANNUALS_ON:
                    with db.get_engine().connect() as conn:
                        stmt = (
                            select(annuals)
                            .where(annuals.c.ComicID == comicid)
                            .where(annuals.c.Int_IssueNumber == helpers.issuedigits(latestiss))
                            .where(annuals.c.Deleted == 0)
                        )
                        chkstats = next((dict(row._mapping) for row in conn.execute(stmt)), None)

            if chkstats:
                logger.fdebug("latestissue status: " + chkstats["Status"])
                if (
                    chkstats["Status"] == "Skipped"
                    or chkstats["Status"] == "Wanted"
                    or chkstats["Status"] == "Snatched"
                ):
                    logger.info("Checking this week pullist for new issues of " + comic["ComicName"])
                    if comic["ComicName"] != comicname_filesafe:
                        cn_pull = comicname_filesafe
                    else:
                        cn_pull = comic["ComicName"]
                    updater.newpullcheck(ComicName=cn_pull, ComicID=comicid, issue=latestiss)

                if calledfrom != "maintenance":
                    results = []
                    with db.get_engine().connect() as conn:
                        stmt = select(issues).where(issues.c.ComicID == comicid).where(issues.c.Status == "Wanted")
                        issresults = [dict(row._mapping) for row in conn.execute(stmt)]

                    if issresults:
                        for issr in issresults:
                            results.append(
                                {
                                    "IssueID": issr["IssueID"],
                                    "Issue_Number": issr["Issue_Number"],
                                    "Status": issr["Status"],
                                }
                            )
                    if comicarr.CONFIG.ANNUALS_ON:
                        with db.get_engine().connect() as conn:
                            stmt = (
                                select(annuals)
                                .where(annuals.c.ComicID == comicid)
                                .where(annuals.c.Status == "Wanted")
                                .where(annuals.c.Deleted == 0)
                            )
                            an_results = [dict(row._mapping) for row in conn.execute(stmt)]

                        if an_results:
                            for ar in an_results:
                                results.append(
                                    {
                                        "IssueID": ar["IssueID"],
                                        "Issue_Number": ar["Issue_Number"],
                                        "Status": ar["Status"],
                                    }
                                )

                    if results:
                        logger.info("Attempting to grab wanted issues for : " + comic["ComicName"])
                        search_list = []
                        for result in results:
                            logger.fdebug("Searching for : " + str(result["Issue_Number"]))
                            logger.fdebug("Status of : " + str(result["Status"]))
                            search_list.append(result["IssueID"])
                        if len(search_list) > 0:
                            start_background_thread(
                                search.searchIssueIDList,
                                args=(search_list,),
                                name="ImportWantedSearch",
                            )
                    else:
                        logger.info("No issues marked as wanted for " + comic["ComicName"])

                    logger.info("Finished grabbing what I could.")
                else:
                    logger.info("Already have the latest issue : #" + str(latestiss))

    if chkwant is not None:
        with db.get_engine().connect() as conn:
            stmt = select(issues).where(issues.c.ComicID == comicid).where(issues.c.Status == "Skipped")
            chkresults = [dict(row._mapping) for row in conn.execute(stmt)]

        if chkresults:
            logger.info("[FROM THE FUTURE CHECKLIST] Attempting to grab wanted issues for : " + comic["ComicName"])
            for result in chkresults:
                for chkit in chkwant:
                    logger.fdebug("checking " + chkit["IssueNumber"] + " against " + result["Issue_Number"])
                    if chkit["IssueNumber"] == result["Issue_Number"]:
                        logger.fdebug("Searching for : " + result["Issue_Number"])
                        logger.fdebug("Status of : " + str(result["Status"]))
                        search.searchforissue(result["IssueID"])
        else:
            logger.info("No issues marked as wanted for " + comic["ComicName"])

        logger.info("Finished grabbing what I could.")

    if imported == "futurecheck":
        logger.info("Returning to Future-Check module to complete the add & remove entry.")
        return
    elif all([imported is not None, imported != "None"]):
        logger.info("Successfully imported : " + comic["ComicName"])
        return

    if calledfrom == "addbyid":
        try:
            from comicarr.app.activity.producers import emit_series_activity

            emit_series_activity(
                "add",
                "succeeded",
                comicid,
                comicname=comic["ComicName"],
                seriesyear=SeriesYear,
            )
        except Exception as e:
            logger.fdebug("[ACTIVITY] add.succeeded emit skipped: %s" % e)
        logger.info(
            "Sucessfully added %s (%s) to the watchlist by directly using the ComicVine ID"
            % (comic["ComicName"], SeriesYear)
        )
        return {"status": "complete"}
    elif calledfrom == "maintenance":
        logger.info("Sucessfully added %s (%s) to the watchlist" % (comic["ComicName"], SeriesYear))
        return {"status": "complete", "comicname": comic["ComicName"], "year": SeriesYear}
    else:
        try:
            from comicarr.app.activity.producers import emit_series_activity

            emit_series_activity(
                "add",
                "succeeded",
                comicid,
                comicname=comic["ComicName"],
                seriesyear=SeriesYear,
            )
        except Exception as e:
            logger.fdebug("[ACTIVITY] add.succeeded emit skipped: %s" % e)
        logger.info("Sucessfully added %s (%s) to the watchlist" % (comic["ComicName"], SeriesYear))
        return {"status": "complete"}


def _upsert_placeholder_manga_chapters(mangaid, manga_name, total):
    """Create deterministic placeholder rows for missing integer chapters."""
    if total <= 0:
        return 0

    existing_chapters = set()
    rows = db.select_all(
        select(issues.c.Int_IssueNumber, issues.c.ChapterNumber, issues.c.Issue_Number).where(
            issues.c.ComicID == mangaid
        )
    )
    for row in rows:
        int_issue_number = row.get("Int_IssueNumber")
        if int_issue_number is None:
            chapter_number = row.get("ChapterNumber") or row.get("Issue_Number")
            if chapter_number is not None:
                int_issue_number = helpers.issuedigits(str(chapter_number))
        if int_issue_number is not None:
            existing_chapters.add(int_issue_number)

    created = 0
    for chapter_number in range(1, total + 1):
        chapter_number_str = str(chapter_number)
        if helpers.issuedigits(chapter_number_str) in existing_chapters:
            continue

        placeholder_id = "%s-ch%s" % (mangaid, chapter_number_str)
        placeholder_values = {
            "IssueID": placeholder_id,
            "ComicID": mangaid,
            "ComicName": manga_name,
            "Issue_Number": chapter_number_str,
            "IssueName": "Chapter %s" % chapter_number_str,
            "Status": "Skipped",
            "Int_IssueNumber": helpers.issuedigits(chapter_number_str),
            "ChapterNumber": chapter_number_str,
            "DateAdded": helpers.now(),
        }
        db.upsert("issues", placeholder_values, {"IssueID": placeholder_id})
        created += 1

    return created


def _populate_manga_chapters(mangaid, manga_name, mangadex_uuid, mal_num_chapters, controlValueDict):
    """Shared helper: fetch chapters and set Total/Have for a manga series.

    Uses a multi-source approach:
    1. Language-filtered chapters from MangaDex (for detailed issue rows)
    2. Language-unfiltered aggregate from MangaDex (for authoritative Total)
    3. MAL num_chapters as fallback (when MangaDex is unavailable)
    4. Explicit 0 as terminal default (never leaves Total/Have as NULL)

    On refresh, existing chapter rows keep their Status and DateAdded so
    Downloaded/Snatched/Wanted/etc. survive metadata updates; only new
    chapters get the default Status. Have is reset to 0 here and
    recalculated by forceRescan after a refresh.

    Args:
        mangaid: The comic ID used in the database (e.g. 'md-xxx' or 'mal-xxx')
        manga_name: Display name for logging
        mangadex_uuid: MangaDex UUID for chapter fetching (None if unavailable)
        mal_num_chapters: Chapter count from MAL (None if not from MAL)
        controlValueDict: Dict used as WHERE clause for db.upsert
    """
    from comicarr import mangadex

    issue_count = 0
    latest_chapter = None
    latest_date = None

    existing_issue_ids = {
        row["IssueID"]
        for row in db.select_all(select(issues.c.IssueID).where(issues.c.ComicID == mangaid))
        if row.get("IssueID")
    }

    if mangadex_uuid:
        mdex_id = series_kind.strip_prefix(mangadex_uuid)

        logger.info("[MANGA-IMPORT] Fetching chapters for: %s" % manga_name)
        chapters = mangadex.get_all_chapters(mdex_id)

        if chapters:
            for chapter in chapters:
                chapter_num = chapter.get("chapter")
                if chapter_num is None:
                    continue

                issue_id = "%s-ch%s" % (mangaid, chapter_num)

                release_date = (
                    chapter.get("release_date") or chapter.get("publish_at", "")[:10]
                    if chapter.get("publish_at")
                    else None
                )

                issue_values = {
                    "IssueID": issue_id,
                    "ComicID": mangaid,
                    "ComicName": manga_name,
                    "Issue_Number": str(chapter_num),
                    "IssueName": chapter.get("title") or ("Chapter %s" % chapter_num),
                    "ReleaseDate": release_date,
                    "IssueDate": release_date,
                    "Int_IssueNumber": helpers.issuedigits(chapter_num),
                    "ChapterNumber": str(chapter_num),
                    "VolumeNumber": str(chapter.get("volume")) if chapter.get("volume") else None,
                }
                if issue_id not in existing_issue_ids:
                    issue_status = "Skipped"
                    if comicarr.CONFIG.AUTOWANT_ALL:
                        issue_status = "Wanted"
                    issue_values["Status"] = issue_status
                    issue_values["DateAdded"] = helpers.now()

                db.upsert("issues", issue_values, {"IssueID": issue_id})
                issue_count += 1

                try:
                    chapter_float = float(chapter_num)
                    if latest_chapter is None:
                        latest_chapter = chapter_num
                        latest_date = release_date
                    else:
                        try:
                            if chapter_float > float(latest_chapter):
                                latest_chapter = chapter_num
                                latest_date = release_date
                        except ValueError:
                            latest_chapter = chapter_num
                            latest_date = release_date
                except ValueError:
                    if latest_chapter is None:
                        latest_chapter = chapter_num
                        latest_date = release_date

            logger.info("[MANGA-IMPORT] Added %d chapters for %s" % (issue_count, manga_name))

        total_from_aggregate = mangadex.get_total_chapter_count(mdex_id)

        if total_from_aggregate > 0:
            total = max(total_from_aggregate, issue_count)

        else:
            total = issue_count
    else:
        logger.warn("[MANGA-IMPORT] No MangaDex UUID for %s — cannot fetch chapters" % manga_name)
        total = 0

    if total == 0 and mal_num_chapters is not None:
        try:
            total = int(float(mal_num_chapters))
            logger.info("[MANGA-IMPORT] Using MAL chapter count for %s: %d" % (manga_name, total))
        except (ValueError, TypeError):
            logger.error("[MANGA-IMPORT] Invalid MAL chapter count for %s: %s" % (manga_name, mal_num_chapters))

    placeholder_count = _upsert_placeholder_manga_chapters(mangaid, manga_name, total)
    if placeholder_count:
        logger.info(
            "[MANGA-IMPORT] Generated %d missing placeholder chapters for %s (total: %d, detailed: %d)"
            % (placeholder_count, manga_name, total, issue_count)
        )

    update_values = {
        "Total": total,
        "Have": 0,
        "LatestIssue": str(latest_chapter) if latest_chapter else "0",
        "LatestDate": latest_date or "Unknown",
    }
    db.upsert("comics", update_values, controlValueDict)

    if total == 0:
        logger.warn(
            "[MANGA-IMPORT] 0 chapters found for %s (languages: %s). "
            "Check MangaDex content rating and language settings."
            % (manga_name, comicarr.CONFIG.MANGADEX_LANGUAGES or "en")
        )

    return {"total": total, "issue_count": issue_count, "latest_chapter": latest_chapter}


def addMangaToDB(mangaid, imported=None, calledfrom=None):
    """
    Add a manga from MangaDex to the database.

    Args:
        mangaid: MangaDex manga ID (prefixed with 'md-')
        imported: Import information if coming from file import
        calledfrom: Calling context

    Returns:
        dict with status information
    """
    from comicarr import mangadex
    from comicarr.config import get_manga_destination

    logger.info("[MANGADEX] Adding manga with ID: %s" % mangaid)

    mangadex_uuid = series_kind.strip_prefix(mangaid)

    controlValueDict = {"ComicID": mangaid}

    with db.get_engine().connect() as conn:
        stmt = select(comics).where(comics.c.ComicID == mangaid)
        dbmanga = next((dict(row._mapping) for row in conn.execute(stmt)), None)

    if dbmanga is not None:
        if dbmanga["Status"] == "Active":
            series_status = "Active"
        elif dbmanga["Status"] == "Paused":
            series_status = "Paused"
        else:
            series_status = "Loading"
        comlocation = dbmanga["ComicLocation"]
    else:
        series_status = "Loading"
        comlocation = None

    db.upsert("comics", {"Status": "Loading"}, controlValueDict)

    manga = mangadex.get_manga_details(mangaid)

    if not manga:
        logger.error("[MANGADEX] Error fetching manga details for: %s" % mangaid)
        if dbmanga is not None:
            restore_status = series_status if series_status != "Loading" else "Active"
            db.upsert("comics", {"Status": restore_status}, controlValueDict)
        else:
            db.upsert(
                "comics",
                {"ComicName": "Fetch failed, try refreshing. (%s)" % mangaid, "Status": "Active"},
                controlValueDict,
            )
        _emit_add_activity("failed", mangaid, reason_detail="MangaDex details fetch failed")
        return {"status": "incomplete"}

    manga_name = manga.get("name", "Unknown")
    manga_year = manga.get("year") or "0000"
    description = manga.get("description", "No description available")

    logger.info("[MANGADEX] Now adding: %s (%s)" % (manga_name, manga_year))

    if manga_name.startswith("The "):
        sortname = manga_name[4:]
    else:
        sortname = manga_name

    dynamic_name = helpers.filesafe(re.sub(r"[\'\!\@\#\$\%\:\;\/\\]", "", manga_name).lower())

    manga_dest = get_manga_destination()
    if manga_dest and not comlocation:
        folder_format = comicarr.CONFIG.FOLDER_FORMAT or "$Series ($Year)"
        folder_name = folder_format.replace("$Series", manga_name).replace("$Year", str(manga_year))
        folder_name = helpers.filesafe(folder_name)
        comlocation = os.path.join(manga_dest, folder_name)

        if comicarr.CONFIG.CREATE_FOLDERS:
            checkdirectory = filechecker.validateAndCreateDirectory(comlocation, True)
            if not checkdirectory:
                logger.warn("[MANGADEX] Error creating directory for %s" % manga_name)
    elif comlocation is None:
        comlocation = None

    md_status = manga.get("status", "unknown")
    status_mapping = {"ongoing": "Continuing", "completed": "Ended", "hiatus": "Continuing", "cancelled": "Ended"}
    comic_published = status_mapping.get(md_status, "Unknown")

    comic_values = {
        "ComicID": mangaid,
        "ComicName": manga_name,
        "ComicSortName": sortname,
        "ComicYear": str(manga_year),
        "Status": series_status if series_status != "Loading" else "Active",
        "ComicPublished": comic_published,
        "ComicPublisher": manga.get("author", "Unknown"),
        "Description": description[:4000] if description else None,
        "ComicImage": manga.get("cover_url"),
        "ComicImageURL": manga.get("cover_url"),
        "DetailURL": manga.get("url"),
        "DynamicComicName": dynamic_name,
        "ComicLocation": comlocation,
        "Type": "Manga",
        "ContentType": (
            dbmanga["ContentType"]
            if dbmanga is not None and dbmanga.get("ContentType") in ("comic", "manga")
            else "manga"
        ),
        "ReadingDirection": "rtl",
        "MetadataSource": "mangadex",
        "ExternalID": mangadex_uuid,
        "MangaDexID": mangadex_uuid,
        "LastUpdated": helpers.now(),
        "DateAdded": helpers.today() if dbmanga is None else dbmanga.get("DateAdded", helpers.today()),
    }

    alt_titles = manga.get("alt_titles", [])
    if alt_titles:
        comic_values["AlternateSearch"] = "##".join(alt_titles[:5])

    db.upsert("comics", comic_values, controlValueDict)

    cover_url = manga.get("cover_url")
    if cover_url:
        try:
            covercheck = helpers.getImage(mangaid, cover_url)
            if covercheck["status"] == "retry":
                logger.info("[MANGADEX] Retrying alternate cover image for: %s" % manga_name)
            elif covercheck["status"] == "success":
                db.upsert(
                    "comics",
                    {"ComicImage": helpers.replacetheslash(os.path.join("cache", str(mangaid) + ".jpg"))},
                    controlValueDict,
                )
        except Exception as e:
            logger.warn("[MANGADEX] Failed to cache cover for %s: %s" % (manga_name, e))

    _populate_manga_chapters(mangaid, manga_name, mangadex_uuid, None, controlValueDict)

    helpers.ComicSort(comicorder=comicarr.COMICSORT, imported=mangaid)

    logger.info("[MANGADEX] Successfully added manga: %s" % manga_name)
    _emit_add_activity("succeeded", mangaid, comicname=manga_name)

    return {"status": "complete", "comicid": mangaid, "comicname": manga_name, "content_type": "manga"}


def addMangaToDB_MAL(mangaid, imported=None, calledfrom=None):
    """Add a manga from MyAnimeList to the database, with chapters from MangaDex.

    1. Fetch metadata from MAL (title, images, synopsis, status, authors)
    2. Find corresponding MangaDex entry for chapter data
    3. Store in comics table with MetadataSource="mal"
    4. Fetch chapters from MangaDex and store as issues

    Args:
        mangaid: MAL manga ID (prefixed with 'mal-')
        imported: Import information if coming from file import
        calledfrom: Calling context

    Returns:
        dict with status information
    """
    from comicarr import mangadex, myanimelist
    from comicarr.config import get_manga_destination

    logger.info("[MAL] Adding manga with ID: %s" % mangaid)

    mal_numeric_id = series_kind.strip_prefix(mangaid)
    mangaid = series_kind.add_prefix(mangaid, series_kind.SeriesProvider.MYANIMELIST)

    controlValueDict = {"ComicID": mangaid}

    with db.get_engine().connect() as conn:
        stmt = select(comics).where(comics.c.ComicID == mangaid)
        dbmanga = next((dict(row._mapping) for row in conn.execute(stmt)), None)

    if dbmanga is not None:
        if dbmanga["Status"] == "Active":
            series_status = "Active"
        elif dbmanga["Status"] == "Paused":
            series_status = "Paused"
        else:
            series_status = "Loading"
        comlocation = dbmanga["ComicLocation"]
    else:
        series_status = "Loading"
        comlocation = None

    db.upsert("comics", {"Status": "Loading"}, controlValueDict)

    manga = myanimelist.get_manga_details(mangaid)

    if not manga:
        logger.error("[MAL] Error fetching manga details for: %s" % mangaid)
        if dbmanga is not None:
            restore_status = series_status if series_status != "Loading" else "Active"
            db.upsert("comics", {"Status": restore_status}, controlValueDict)
        else:
            db.upsert(
                "comics",
                {"ComicName": "Fetch failed, try refreshing. (%s)" % mangaid, "Status": "Active"},
                controlValueDict,
            )
        _emit_add_activity("failed", mangaid, reason_detail="MyAnimeList details fetch failed")
        return {"status": "incomplete"}

    manga_name = manga.get("name", "Unknown")
    manga_year = manga.get("year") or "0000"
    description = manga.get("description", "No description available")

    logger.info("[MAL] Now adding: %s (%s)" % (manga_name, manga_year))

    if manga_name.startswith("The "):
        sortname = manga_name[4:]
    else:
        sortname = manga_name

    dynamic_name = helpers.filesafe(re.sub(r"[\'\!\@\#\$\%\:\;\/\\]", "", manga_name).lower())

    manga_dest = get_manga_destination()
    if manga_dest and not comlocation:
        folder_format = comicarr.CONFIG.FOLDER_FORMAT or "$Series ($Year)"
        folder_name = folder_format.replace("$Series", manga_name).replace("$Year", str(manga_year))
        folder_name = helpers.filesafe(folder_name)
        comlocation = os.path.join(manga_dest, folder_name)

        if comicarr.CONFIG.CREATE_FOLDERS:
            checkdirectory = filechecker.validateAndCreateDirectory(comlocation, True)
            if not checkdirectory:
                logger.warn("[MAL] Error creating directory for %s" % manga_name)
    elif comlocation is None:
        comlocation = None

    md_status = manga.get("status", "unknown")
    status_mapping = {"ongoing": "Continuing", "completed": "Ended", "hiatus": "Continuing", "cancelled": "Ended"}
    comic_published = status_mapping.get(md_status, "Unknown")

    mangadex_uuid = mangadex.find_by_mal_id(
        mal_numeric_id,
        title_hint=manga_name,
        alternate_titles=manga.get("alt_titles", []),
    )

    comic_values = {
        "ComicID": mangaid,
        "ComicName": manga_name,
        "ComicSortName": sortname,
        "ComicYear": str(manga_year),
        "Status": series_status if series_status != "Loading" else "Active",
        "ComicPublished": comic_published,
        "ComicPublisher": manga.get("author", "Unknown"),
        "Description": description[:4000] if description else None,
        "ComicImage": manga.get("cover_url"),
        "ComicImageURL": manga.get("cover_url"),
        "DetailURL": manga.get("url"),
        "DynamicComicName": dynamic_name,
        "ComicLocation": comlocation,
        "Type": "Manga",
        "ContentType": (
            dbmanga["ContentType"]
            if dbmanga is not None and dbmanga.get("ContentType") in ("comic", "manga")
            else "manga"
        ),
        "ReadingDirection": "rtl",
        "MetadataSource": "mal",
        "ExternalID": mal_numeric_id,
        "MalID": mal_numeric_id,
        "MangaDexID": mangadex_uuid,
        "LastUpdated": helpers.now(),
        "DateAdded": helpers.today() if dbmanga is None else dbmanga.get("DateAdded", helpers.today()),
    }

    alt_titles = manga.get("alt_titles", [])
    if alt_titles:
        comic_values["AlternateSearch"] = "##".join(alt_titles[:5])

    db.upsert("comics", comic_values, controlValueDict)

    cover_url = manga.get("cover_url")
    if cover_url:
        try:
            covercheck = helpers.getImage(mangaid, cover_url)
            if covercheck["status"] == "retry":
                logger.info("[MAL] Retrying alternate cover image for: %s" % manga_name)
            elif covercheck["status"] == "success":
                db.upsert(
                    "comics",
                    {"ComicImage": helpers.replacetheslash(os.path.join("cache", str(mangaid) + ".jpg"))},
                    controlValueDict,
                )
        except Exception as e:
            logger.warn("[MAL] Failed to cache cover for %s: %s" % (manga_name, e))

    mal_num_chapters = manga.get("last_chapter")
    _populate_manga_chapters(mangaid, manga_name, mangadex_uuid, mal_num_chapters, controlValueDict)

    helpers.ComicSort(comicorder=comicarr.COMICSORT, imported=mangaid)

    logger.info("[MAL] Successfully added manga: %s" % manga_name)
    _emit_add_activity("succeeded", mangaid, comicname=manga_name)

    return {"status": "complete", "comicid": mangaid, "comicname": manga_name, "content_type": "manga"}


def GCDimport(gcomicid, pullupd=None, imported=None, ogcname=None):

    gcdcomicid = gcomicid

    controlValueDict = {"ComicID": gcdcomicid}

    with db.get_engine().connect() as conn:
        stmt = select(
            comics.c.ComicName,
            comics.c.ComicYear,
            comics.c.Total,
            comics.c.ComicPublished,
            comics.c.ComicImage,
            comics.c.ComicLocation,
            comics.c.ComicPublisher,
        ).where(comics.c.ComicID == gcomicid)
        comic = next((dict(row._mapping) for row in conn.execute(stmt)), None)

    ComicName = comic["ComicName"]
    ComicYear = comic["ComicYear"]
    ComicIssues = comic["Total"]
    ComicPublished = comic["ComicPublished"]
    comlocation = comic["ComicLocation"]
    ComicPublisher = comic["ComicPublisher"]

    newValueDict = {"Status": "Loading"}
    db.upsert("comics", newValueDict, controlValueDict)

    if not comic:
        logger.warn("Error fetching comic. ID for : " + gcdcomicid)
        if dbcomic is None:
            newValueDict = {"ComicName": "Fetch failed, try refreshing. (%s)" % (gcdcomicid), "Status": "Active"}
        else:
            newValueDict = {"Status": "Active"}
        db.upsert("comics", newValueDict, controlValueDict)
        return

    if pullupd is None:
        helpers.ComicSort(comicorder=comicarr.COMICSORT, imported=gcomicid)

    if ComicName.startswith("The "):
        sortname = ComicName[4:]
    else:
        sortname = ComicName

    logger.info("Now adding/updating: " + ComicName)
    comicid = gcomicid[1:]
    resultURL = "/series/" + str(comicid) + "/"
    gcdinfo = parseit.GCDdetails(
        comseries=None,
        resultURL=resultURL,
        vari_loop=0,
        ComicID=gcdcomicid,
        TotalIssues=ComicIssues,
        issvariation=None,
        resultPublished=None,
    )
    if gcdinfo == "No Match":
        logger.warn("No matching result found for " + ComicName + " (" + ComicYear + ")")
        updater.no_searchresults(gcomicid)
        nomatch = "true"
        return nomatch
    logger.info("Sucessfully retrieved details for " + ComicName)

    ComicImage = gcdinfo["ComicImage"]

    if comlocation is None:
        u_comicnm = ComicName
        u_comicname = u_comicnm.encode("ascii", "ignore").strip()
        if ":" in u_comicname or "/" in u_comicname or "," in u_comicname:
            comicdir = u_comicname
            if ":" in comicdir:
                comicdir = comicdir.replace(":", "")
            if "/" in comicdir:
                comicdir = comicdir.replace("/", "-")
            if "," in comicdir:
                comicdir = comicdir.replace(",", "")
        else:
            comicdir = u_comicname

        series = comicdir
        publisher = ComicPublisher
        year = ComicYear

        values = {
            "$Series": series,
            "$Publisher": publisher,
            "$Year": year,
            "$series": series.lower(),
            "$publisher": publisher.lower(),
            "$Volume": year,
        }

        if comicarr.CONFIG.FOLDER_FORMAT == "":
            comlocation = comicarr.CONFIG.DESTINATION_DIR + "/" + comicdir + " (" + comic["ComicYear"] + ")"
        else:
            comlocation = (
                comicarr.CONFIG.DESTINATION_DIR + "/" + helpers.replace_all(comicarr.CONFIG.FOLDER_FORMAT, values)
            )

        if comicarr.CONFIG.DESTINATION_DIR == "":
            logger.error("There is no general directory specified - please specify in Config/Post-Processing.")
            return
        if comicarr.CONFIG.REPLACE_SPACES:
            comlocation = comlocation.replace(" ", comicarr.CONFIG.REPLACE_CHAR)

    if os.path.isdir(comlocation):
        logger.info("Directory (" + comlocation + ") already exists! Continuing...")
    else:
        if comicarr.CONFIG.CREATE_FOLDERS is True:
            checkdirectory = filechecker.validateAndCreateDirectory(comlocation, True)
            if not checkdirectory:
                logger.warn("Error trying to validate/create directory. Aborting this process at this time.")
                return

    comicIssues = gcdinfo["totalissues"]

    if os.path.exists(comicarr.CONFIG.CACHE_DIR):
        pass
    else:
        try:
            os.makedirs(str(comicarr.CONFIG.CACHE_DIR))
            logger.info("Cache Directory successfully created at: " + str(comicarr.CONFIG.CACHE_DIR))

        except OSError:
            logger.error("Could not create cache dir : " + str(comicarr.CONFIG.CACHE_DIR))

    coverfile = os.path.join(comicarr.CONFIG.CACHE_DIR, str(gcomicid) + ".jpg")

    if comicarr.CONFIG.CVAPI_RATE is None or comicarr.CONFIG.CVAPI_RATE < 2:
        time.sleep(2)
    else:
        time.sleep(comicarr.CONFIG.CVAPI_RATE)

    urllib.request.urlretrieve(str(ComicImage), str(coverfile))
    try:
        with open(str(coverfile)):
            ComicImage = os.path.join("cache", str(gcomicid) + ".jpg")

            logger.info("Sucessfully retrieved cover for " + ComicName)
            if comicarr.CONFIG.COMIC_COVER_LOCAL and os.path.isdir(comlocation):
                comiclocal = os.path.join(comlocation, "cover.jpg")
                shutil.copy(ComicImage, comiclocal)
    except IOError:
        logger.error("Unable to save cover locally at this time.")

    controlValueDict = {"ComicID": gcomicid}
    newValueDict = {
        "ComicName": ComicName,
        "ComicSortName": sortname,
        "ComicYear": ComicYear,
        "Total": comicIssues,
        "ComicLocation": comlocation,
        "ComicImage": ComicImage,
        "ComicImageURL": comic.get("ComicImage", ""),
        "ComicImageALTURL": comic.get("ComicImageALT", ""),
        "DateAdded": helpers.today(),
        "Status": "Loading",
    }

    db.upsert("comics", newValueDict, controlValueDict)

    if pullupd is None:
        helpers.ComicSort(sequence="update")

    logger.info("Successfully retrieved issue details for " + ComicName)
    iscnt = int(comicIssues)
    issdate = []
    int_issnum = []
    latestiss = "0"
    latestdate = "0000-00-00"
    logger.info("Now adding/updating issues for " + ComicName)
    bb = 0
    while bb <= iscnt:
        try:
            gcdval = gcdinfo["gcdchoice"][bb]
        except IndexError:
            if gcdinfo["gcdvariation"] == "gcd":
                issdate = "0000-00-00"
                int_issnum = int(issis / 1000)
            break
        if "nn" in str(gcdval["GCDIssue"]):
            logger.warn("Non Series detected (Graphic Novel, etc) - cannot proceed at this time.")
            updater.no_searchresults(comicid)
            return
        elif "." in str(gcdval["GCDIssue"]):
            issst = str(gcdval["GCDIssue"]).find(".")
            issb4dec = str(gcdval["GCDIssue"])[:issst]
            decis = str(gcdval["GCDIssue"])[issst + 1 :]
            if len(decis) == 1:
                decisval = int(decis) * 10
                issaftdec = str(decisval)
            if len(decis) == 2:
                decisval = int(decis)
                issaftdec = str(decisval)
            if int(issaftdec) == 0:
                issaftdec = "00"
            gcd_issue = issb4dec + "." + issaftdec
            gcdis = (int(issb4dec) * 1000) + decisval
        else:
            gcdis = int(str(gcdval["GCDIssue"])) * 1000
            gcd_issue = str(gcdval["GCDIssue"])
        int_issnum = int(gcdis / 1000)
        issdate = str(gcdval["GCDDate"])
        issid = "G" + str(gcdval["IssueID"])
        if gcdval["GCDDate"] > latestdate:
            latestiss = str(gcd_issue)
            latestdate = str(gcdval["GCDDate"])

        with db.get_engine().connect() as conn:
            stmt = select(issues).where(issues.c.IssueID == issid)
            iss_exists = next((dict(row._mapping) for row in conn.execute(stmt)), None)

        if iss_exists is None:
            newValueDict["DateAdded"] = helpers.today()

        if "?" in str(issdate):
            issdate = "0000-00-00"

        controlValueDict = {"IssueID": issid}
        newValueDict = {
            "ComicID": gcomicid,
            "ComicName": ComicName,
            "Issue_Number": gcd_issue,
            "IssueDate": issdate,
            "Int_IssueNumber": int_issnum,
        }

        if comicarr.CONFIG.AUTOWANT_ALL:
            newValueDict["Status"] = "Wanted"
        elif issdate > helpers.today() and comicarr.CONFIG.AUTOWANT_UPCOMING:
            newValueDict["Status"] = "Wanted"
        else:
            newValueDict["Status"] = "Skipped"

        if iss_exists:
            newValueDict["Status"] = iss_exists["Status"]

        db.upsert("issues", newValueDict, controlValueDict)
        bb += 1

    controlValueStat = {"ComicID": gcomicid}
    newValueStat = {
        "Status": "Active",
        "LatestIssue": latestiss,
        "LatestDate": latestdate,
        "LastUpdated": helpers.now(),
    }

    db.upsert("comics", newValueStat, controlValueStat)

    if comicarr.CONFIG.CVINFO and os.path.isdir(comlocation):
        if not os.path.exists(comlocation + "/cvinfo"):
            with open(comlocation + "/cvinfo", "w") as text_file:
                text_file.write("http://comicvine.gamespot.com/volume/49-" + str(comicid))

    logger.info("Updating complete for: " + ComicName)

    if imported is None or imported == "None":
        pass
    else:
        if comicarr.CONFIG.IMP_MOVE:
            logger.info("Mass import - Move files")
            moveit.movefiles(gcomicid, comlocation, ogcname)
        else:
            logger.info("Mass import - Moving not Enabled. Setting Archived Status for import.")
            moveit.archivefiles(gcomicid, ogcname)

    updater.forceRescan(gcomicid)

    if pullupd is None:
        if comicarr.CONFIG.AUTOWANT_UPCOMING and "Present" in ComicPublished:
            logger.info("Checking this week's pullist for new issues of " + ComicName)
            updater.newpullcheck(comic["ComicName"], gcomicid)

        with db.get_engine().connect() as conn:
            stmt = select(issues).where(issues.c.ComicID == gcomicid).where(issues.c.Status == "Wanted")
            results = [dict(row._mapping) for row in conn.execute(stmt)]

        if results:
            logger.info("Attempting to grab wanted issues for : " + ComicName)

            for result in results:
                foundNZB = "none"
                if (
                    comicarr.CONFIG.NZBSU
                    or comicarr.CONFIG.DOGNZB
                    or comicarr.CONFIG.EXPERIMENTAL
                    or comicarr.CONFIG.NEWZNAB
                ) and (comicarr.CONFIG.SAB_HOST):
                    foundNZB = search.searchforissue(result["IssueID"])
                    if foundNZB == "yes":
                        updater.foundsearch(result["ComicID"], result["IssueID"])
        else:
            logger.info("No issues marked as wanted for " + ComicName)

        logger.info("Finished grabbing what I could.")


def issue_collection(issuedata, nostatus, serieslast_updated=None, suppress_addall=None):
    try:
        serieslast_updated = datetime.datetime.strptime(serieslast_updated, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
    except Exception:
        pass

    logger.info("nostatus: %s" % nostatus)
    logger.info("issuedata: %s" % (issuedata))

    nowdate = datetime.datetime.now()
    now_week = datetime.datetime.strftime(nowdate, "%Y%U")

    if issuedata:
        with db.get_engine().connect() as conn:
            stmt = (
                select(issues.c.IssueDate, issues.c.ReleaseDate)
                .where(issues.c.ComicID == issuedata[0]["ComicID"])
                .order_by(issues.c.IssueDate.desc())
                .limit(1)
            )
            isslastdate = next((dict(row._mapping) for row in conn.execute(stmt)), None)

        if not isslastdate:
            lastchkdate = "0000-00-00"
        else:
            lastchkdate = isslastdate["IssueDate"]
            if any([lastchkdate is None, lastchkdate == "0000-00-00"]):
                lastchkdate = isslastdate["ReleaseDate"]

        for issue in issuedata:
            controlValueDict = {"IssueID": issue["IssueID"]}
            newValueDict = {
                "ComicID": issue["ComicID"],
                "ComicName": issue["ComicName"],
                "IssueName": issue["IssueName"],
                "Issue_Number": issue["Issue_Number"],
                "IssueDate": issue["IssueDate"],
                "ReleaseDate": issue["ReleaseDate"],
                "DigitalDate": issue["DigitalDate"],
                "Int_IssueNumber": issue["Int_IssueNumber"],
                "AltIssueNumber": issue["AltIssueNumber"],
                "ImageURL": issue["ImageURL"],
                "ImageURL_ALT": issue["ImageURL_ALT"],
            }

            with db.get_engine().connect() as conn:
                stmt = select(issues).where(issues.c.IssueID == issue["IssueID"])
                iss_exists = next((dict(row._mapping) for row in conn.execute(stmt)), None)

            dbwrite = "issues"

            if nostatus == "False":
                if iss_exists is None:
                    newValueDict["DateAdded"] = helpers.today()
                    if issue["ReleaseDate"] == "0000-00-00":
                        dk = re.sub("-", "", issue["IssueDate"]).strip()
                    else:
                        dk = re.sub("-", "", issue["ReleaseDate"]).strip()
                    if dk == "00000000":
                        logger.warn(
                            "Issue Data is invalid for Issue Number %s. Marking this issue as Skipped"
                            % issue["Issue_Number"]
                        )
                        newValueDict["Status"] = "Skipped"
                    else:
                        datechk = datetime.datetime.strptime(dk, "%Y%m%d")
                        issue_week = datetime.datetime.strftime(datechk, "%Y%U")
                        if issue["SeriesStatus"] == "Paused":
                            newValueDict["Status"] = "Skipped"
                            logger.fdebug(
                                "[PAUSE-CHECK-ISSUE-STATUS] Series is paused, setting status for new issue #%s to Skipped"
                                % (issue["Issue_Number"])
                            )
                        else:
                            if comicarr.CONFIG.AUTOWANT_ALL and not suppress_addall:
                                newValueDict["Status"] = "Wanted"
                            elif serieslast_updated is None:
                                newValueDict["Status"] = "Skipped"
                            elif issue_week >= now_week and comicarr.CONFIG.AUTOWANT_UPCOMING:
                                logger.fdebug("[Marking as Wanted] week %s >= week %s" % (now_week, issue_week))
                                newValueDict["Status"] = "Wanted"
                            elif all(
                                [
                                    int(re.sub("-", "", serieslast_updated).strip()) < int(dk),
                                    comicarr.CONFIG.AUTOWANT_UPCOMING is True,
                                ]
                            ):
                                logger.info("Autowant upcoming triggered for issue #%s" % issue["Issue_Number"])
                                newValueDict["Status"] = "Wanted"
                            else:
                                newValueDict["Status"] = "Skipped"
                else:
                    if any([iss_exists["Status"] is None, iss_exists["Status"] == "None"]):
                        is_status = "Skipped"
                    else:
                        is_status = iss_exists["Status"]
                    newValueDict["Status"] = is_status

            else:
                pass

            try:
                db.upsert(dbwrite, newValueDict, controlValueDict)
            except sqlalchemy.exc.InterfaceError:
                logger.error("Something went wrong - I cannot add the issue information into my DB.")
                with db.get_engine().begin() as conn:
                    conn.execute(comics.delete().where(comics.c.ComicID == issue["ComicID"]))
                return


def manualAnnual(
    manual_comicid=None,
    comicname=None,
    comicyear=None,
    comicid=None,
    annchk=None,
    manualupd=False,
    deleted=False,
    forceadd=False,
    serieslast_updated=None,
    series_status=None,
):

    try:
        serieslast_updated = datetime.datetime.strptime(serieslast_updated, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
    except Exception:
        pass

    if annchk is None:
        nowdate = datetime.datetime.now()
        now_week = datetime.datetime.strftime(nowdate, "%Y%U")
        annchk = []
        issueid = manual_comicid
        logger.fdebug(str(issueid) + " added to series list as an Annual")
        sr = cv.getComic(manual_comicid, "comic")
        if sr is None and forceadd is False:
            return
        logger.fdebug(
            "Attempting to integrate "
            + sr["ComicName"]
            + " ("
            + str(issueid)
            + ") to the existing series of "
            + comicname
            + "("
            + str(comicyear)
            + ")"
        )
        if len(sr) == 0:
            logger.fdebug("Could not find any information on the series indicated : " + str(manual_comicid))
            return
        else:
            n = 0
            issued = cv.getComic(re.sub("4050-", "", manual_comicid).strip(), "issue")
            if not issued:
                return
            if int(sr["ComicIssues"]) == 0 and len(issued["issuechoice"]) == 1:
                noissues = 1
            else:
                noissues = sr["ComicIssues"]
            logger.fdebug("there are " + str(noissues) + " annuals within this series.")
            while n < int(noissues):
                try:
                    firstval = issued["issuechoice"][n]
                except IndexError:
                    break
                try:
                    cleanname = firstval["Issue_Name"]
                except:
                    cleanname = "None"

                if firstval["Store_Date"] == "0000-00-00":
                    dk = re.sub("-", "", firstval["Issue_Date"]).strip()
                else:
                    dk = re.sub("-", "", firstval["Store_Date"]).strip()
                if dk == "00000000":
                    logger.warn(
                        "Issue Data is invalid for Issue Number %s. Marking this issue as Skipped"
                        % firstval["Issue_Number"]
                    )
                    astatus = "Skipped"
                else:
                    datechk = datetime.datetime.strptime(dk, "%Y%m%d")
                    issue_week = datetime.datetime.strftime(datechk, "%Y%U")
                    if series_status == "Paused":
                        astatus = "Skipped"
                    else:
                        if comicarr.CONFIG.AUTOWANT_ALL:
                            astatus = "Wanted"
                        elif serieslast_updated is None:
                            astatus = "Skipped"
                        elif issue_week >= now_week and comicarr.CONFIG.AUTOWANT_UPCOMING:
                            logger.fdebug("[Marking as Wanted] week %s >= week %s" % (now_week, issue_week))
                            astatus = "Wanted"
                        elif all(
                            [
                                int(re.sub("-", "", serieslast_updated).strip()) < int(dk),
                                comicarr.CONFIG.AUTOWANT_UPCOMING is True,
                            ]
                        ):
                            logger.info("Autowant upcoming triggered for issue #%s" % firstval["Issue_Number"])
                            astatus = "Wanted"
                        else:
                            astatus = "Skipped"

                annchk.append(
                    {
                        "IssueID": str(firstval["Issue_ID"]),
                        "ComicID": comicid,
                        "ReleaseComicID": re.sub("4050-", "", manual_comicid).strip(),
                        "ComicName": comicname,
                        "Issue_Number": str(firstval["Issue_Number"]),
                        "IssueName": cleanname,
                        "IssueDate": str(firstval["Issue_Date"]),
                        "ReleaseDate": str(firstval["Store_Date"]),
                        "DigitalDate": str(firstval["Digital_Date"]),
                        "Status": astatus,
                        "ReleaseComicName": sr["ComicName"],
                        "Deleted": deleted,
                    }
                )
                n += 1

        if manualupd is True:
            return annchk

    for ann in annchk:
        newCtrl = {"IssueID": ann["IssueID"]}
        newVals = {
            "Issue_Number": ann["Issue_Number"],
            "Int_IssueNumber": helpers.issuedigits(ann["Issue_Number"]),
            "IssueDate": ann["IssueDate"],
            "ReleaseDate": ann["ReleaseDate"],
            "DigitalDate": ann["DigitalDate"],
            "IssueName": ann["IssueName"],
            "ComicID": ann["ComicID"],
            "ReleaseComicID": ann["ReleaseComicID"],
            "ComicName": ann["ComicName"],
            "ReleaseComicName": ann["ReleaseComicName"],
            "Status": ann["Status"],
            "Deleted": ann["Deleted"],
        }
        db.upsert("annuals", newVals, newCtrl)
    if len(annchk) > 0:
        logger.info(
            "Successfully integrated " + str(len(annchk)) + " annuals into the series: " + annchk[0]["ComicName"]
        )
    return


def updateissuedata(
    comicid,
    comicname=None,
    issued=None,
    comicIssues=None,
    calledfrom=None,
    issuechk=None,
    issuetype=None,
    SeriesYear=None,
    latestissueinfo=None,
    serieslast_updated=None,
    series_status=None,
    suppress_addall=None,
):
    annualchk = []
    weeklyissue_check = []

    logger.fdebug("issuedata call references...")
    logger.fdebug("comicid: %s" % comicid)
    logger.fdebug("comicname: %s" % comicname)
    logger.fdebug("comicissues: %s" % comicIssues)
    logger.fdebug("calledfrom: %s" % calledfrom)
    logger.fdebug("issuechk: %s" % issuechk)
    logger.fdebug("latestissueinfo: %s" % latestissueinfo)
    logger.fdebug("issuetype: %s" % issuetype)

    if series_status is None and comicid is not None:
        with db.get_engine().connect() as conn:
            stmt = select(comics.c.Status).where(comics.c.ComicID == comicid)
            chk_series_status = next((dict(row._mapping) for row in conn.execute(stmt)), None)

        if chk_series_status is not None:
            series_status = chk_series_status["Status"]
        else:
            series_status = "Active"

    if comicIssues is None:
        comic = cv.getComic(comicid, "comic", series=True)
        if comic is None:
            logger.warn(
                "Error retrieving from ComicVine - either the site is down or you are not using your own CV API key"
            )
            return {"status": "failure"}

        if comicIssues is None:
            comicIssues = comic["ComicIssues"]
        if SeriesYear is None:
            SeriesYear = comic["ComicYear"]
        if comicname is None:
            comicname = comic["ComicName"]
    if issued is None:
        issued = cv.getComic(comicid, "issue")
        if issued is None:
            logger.warn(
                "Error retrieving from ComicVine - either the site is down or you are not using your own CV API key"
            )
            return {"status": "failure"}

    annualchk = annual_check(comicname, SeriesYear, comicid, issuetype, issuechk, annualchk, series_status)
    if annualchk is None:
        annualchk = []
    logger.fdebug("Finished Annual checking.")

    n = 0
    iscnt = int(comicIssues)
    issid = []
    issnum = []
    issname = []
    issdate = []
    issuedata = []
    latestiss = "-999999999"
    latestdate = "0000-00-00"
    latest_stdate = "0000-00-00"
    latestissueid = None
    firstdate = "2099-00-00"
    legacy_num = None
    logger.info("Now adding/updating issues for " + comicname)

    if iscnt > 0:
        while n <= iscnt:
            try:
                firstval = issued["issuechoice"][n]
            except IndexError:
                break
            except Exception:
                logger.warn("Unable to parse issue details for series - ComicVine is probably having problems.")
                return {"status": "failure"}
            try:
                cleanname = firstval["Issue_Name"]
            except:
                cleanname = "None"
            issid = str(firstval["Issue_ID"])
            issnum = firstval["Issue_Number"]
            issname = cleanname
            issdate = str(firstval["Issue_Date"])
            storedate = str(firstval["Store_Date"])
            digitaldate = str(firstval["Digital_Date"])
            int_issnum = None
            if issnum.isdigit():
                int_issnum = int(issnum) * 1000
            else:
                if "a.i." in issnum.lower() or "ai" in issnum.lower():
                    issnum = re.sub(r"\.", "", issnum)
                if "au" in issnum.lower():
                    int_issnum = (int(issnum[:-2]) * 1000) + ord("a") + ord("u")
                elif "inh" in issnum.lower():
                    int_issnum = (int(issnum[:-4]) * 1000) + ord("i") + ord("n") + ord("h")
                elif "now" in issnum.lower():
                    int_issnum = (int(issnum[:-4]) * 1000) + ord("n") + ord("o") + ord("w")
                elif "bey" in issnum.lower():
                    int_issnum = (int(issnum[:-4]) * 1000) + ord("b") + ord("e") + ord("y")
                elif "mu" in issnum.lower():
                    int_issnum = (int(issnum[:-3]) * 1000) + ord("m") + ord("u")
                elif "lr" in issnum.lower():
                    int_issnum = (int(issnum[:-3]) * 1000) + ord("l") + ord("r")
                elif "hu" in issnum.lower():
                    int_issnum = (int(issnum[:-3]) * 1000) + ord("h") + ord("u")
                elif "deaths" in issnum.lower():
                    int_issnum = (
                        (int(issnum[:-7]) * 1000) + ord("d") + ord("e") + ord("a") + ord("t") + ord("h") + ord("s")
                    )
                elif "\xbd" in issnum:
                    tmpiss = re.sub("[^0-9]", "", issnum).strip()
                    if len(tmpiss) > 0:
                        int_issnum = (int(tmpiss) + 0.5) * 1000
                    else:
                        int_issnum = 0.5 * 1000
                    logger.fdebug("1/2 issue detected :" + issnum + " === " + str(int_issnum))
                elif "\xbc" in issnum:
                    int_issnum = 0.25 * 1000
                elif "\xbe" in issnum:
                    int_issnum = 0.75 * 1000
                elif "\u221e" in issnum:
                    int_issnum = 9999999999 * 1000
                elif "." in issnum or "," in issnum:
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
                    if issaftdec[-1:] == ".":
                        logger.fdebug(
                            "Trailing decimal located within issue number. Irrelevant to numbering. Obliterating."
                        )
                        issaftdec = issaftdec[:-1]
                    try:
                        int_issnum = (int(issb4dec) * 1000) + (int(issaftdec) * 10)
                    except ValueError:
                        try:
                            ordtot = 0
                            if any(ext == issaftdec.upper() for ext in comicarr.ISSUE_EXCEPTIONS):
                                logger.fdebug("issue_exception detected..")
                                inu = 0
                                while inu < len(issaftdec):
                                    ordtot += ord(issaftdec[inu].lower())
                                    inu += 1
                                int_issnum = (int(issb4dec) * 1000) + ordtot
                        except Exception as e:
                            logger.warn("error: %s" % e)
                            ordtot = 0
                        if ordtot == 0:
                            logger.error("This has no issue # for me to get - Either a Graphic Novel or one-shot.")
                            updater.no_searchresults(comicid)
                            return {"status": "failure"}
                elif all(["[" in issnum, "]" in issnum]):
                    issnum_tmp = issnum.find("[")
                    int_issnum = int(issnum[:issnum_tmp].strip()) * 1000
                    legacy_num = issnum[issnum_tmp + 1 : issnum.find("]")]
                else:
                    try:
                        x = float(issnum)
                        if x < 0:
                            logger.fdebug(
                                "I have encountered a negative issue #: " + str(issnum) + ". Trying to accomodate."
                            )
                            logger.fdebug("value of x is : " + str(x))
                            int_issnum = (int(x) * 1000) - 1
                        else:
                            raise ValueError
                    except ValueError:
                        x = 0
                        tstord = None
                        issno = None
                        invchk = "false"
                        if issnum.lower() != "preview":
                            while x < len(issnum):
                                if issnum[x].isalpha():
                                    tstord = issnum[x:].rstrip()
                                    tstord = re.sub(r"[\-\,\.\+]", "", tstord).rstrip()
                                    issno = issnum[:x].rstrip()
                                    issno = re.sub(r"[\-\,\.\+]", "", issno).rstrip()
                                    try:
                                        float(issno)
                                    except ValueError:
                                        if len(issnum) == 1 and issnum.isalpha():
                                            logger.fdebug("detected lone alpha issue. Attempting to figure this out.")
                                            break
                                        logger.fdebug(
                                            "[" + issno + "] invalid numeric for issue - cannot be found. Ignoring."
                                        )
                                        issno = None
                                        tstord = None
                                        invchk = "true"
                                    break
                                x += 1

                        if all([tstord is not None, issno is not None, int_issnum is None]):
                            a = 0
                            ordtot = 0
                            if len(issnum) == 1 and issnum.isalpha():
                                int_issnum = ord(tstord.lower())
                            else:
                                while a < len(tstord):
                                    ordtot += ord(tstord[a].lower())
                                    a += 1
                                int_issnum = (int(issno) * 1000) + ordtot
                        elif invchk == "true":
                            if any(
                                [
                                    issnum.lower() == "omega",
                                    issnum.lower() == "alpha",
                                    issnum.lower() == "fall 2005",
                                    issnum.lower() == "spring 2005",
                                    issnum.lower() == "summer 2006",
                                    issnum.lower() == "winter 2009",
                                ]
                            ):
                                issnum = re.sub("[0-9]+", "", issnum).strip()
                                inu = 0
                                ordtot = 0
                                while inu < len(issnum):
                                    ordtot += ord(issnum[inu].lower())
                                    inu += 1
                                int_issnum = ordtot
                            else:
                                logger.fdebug("this does not have an issue # that I can parse properly.")
                                return {"status": "failure"}
                        else:
                            match = re.match(r"(?P<first>\d+)\s?[-&/\\]\s?(?P<last>\d+)", issnum)
                            if int_issnum is not None:
                                pass
                            elif match:
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
                                    ordtot += ord(issnum[inu].lower())
                                    inu += 1
                                int_issnum = ordtot
                            else:
                                logger.error(
                                    issnum + " this has an alpha-numeric in the issue # which I cannot account for."
                                )
                                return {"status": "failure"}
            if any([firstval["Issue_Date"] >= latestdate, storedate >= latestdate]):
                if int_issnum > helpers.issuedigits(latestiss):
                    latestiss = issnum
                    latestissueid = issid
                if firstval["Issue_Date"] != "0000-00-00":
                    latestdate = str(firstval["Issue_Date"])
                    latest_stdate = storedate
                else:
                    latestdate = storedate
                    latest_stdate = storedate

            if firstval["Issue_Date"] < firstdate and firstval["Issue_Date"] != "0000-00-00":
                firstdate = str(firstval["Issue_Date"])

            if issuechk is not None and issuetype == "series":
                logger.fdebug("comparing " + str(issuechk) + " .. to .. " + str(int_issnum))
                if issuechk == int_issnum:
                    weeklyissue_check.append(
                        {
                            "Int_IssueNumber": int_issnum,
                            "Issue_Number": issnum,
                            "IssueDate": issdate,
                            "ReleaseDate": storedate,
                            "ComicID": comicid,
                            "IssueID": issid,
                        }
                    )

            issuedata.append(
                {
                    "ComicID": comicid,
                    "SeriesStatus": series_status,
                    "IssueID": issid,
                    "ComicName": comicname,
                    "IssueName": issname,
                    "Issue_Number": issnum,
                    "IssueDate": issdate,
                    "ReleaseDate": storedate,
                    "DigitalDate": digitaldate,
                    "Int_IssueNumber": int_issnum,
                    "AltIssueNumber": legacy_num,
                    "ImageURL": firstval["Image"],
                    "ImageURL_ALT": firstval["ImageALT"],
                }
            )

            n += 1

    if calledfrom == "futurecheck" and len(issuedata) == 0:
        logger.fdebug(
            "This is a NEW series with no issue data - skipping issue updating for now, and assigning generic information so things don't break"
        )
        latestdate = latestissueinfo[0]["latestdate"]
        latestiss = latestissueinfo[0]["latestiss"]
        lastpubdate = "Present"
        publishfigure = str(SeriesYear) + " - " + str(lastpubdate)
    else:
        if len(issuedata) >= 1 and not calledfrom == "dbupdate":
            logger.fdebug("initiating issue updating - info & status")
            issue_collection(
                issuedata, nostatus="False", serieslast_updated=serieslast_updated, suppress_addall=suppress_addall
            )
        else:
            logger.fdebug("initiating issue updating - just the info")
            issue_collection(
                issuedata, nostatus="True", serieslast_updated=serieslast_updated, suppress_addall=suppress_addall
            )

        styear = str(SeriesYear)
        if firstdate is not None:
            if SeriesYear != firstdate[:4]:
                if firstdate[:4] == "2099":
                    logger.fdebug(
                        "Series start date (%s) differs from First Issue start date as First Issue date is unknown - assuming Series Year as Start Year (even though CV might say previous year - it's all gravy)."
                        % (SeriesYear)
                    )
                else:
                    logger.fdebug(
                        "Series start date (%s) cannot be properly determined and/or it might cross over into different year (%s) - assuming store date of first issue (%s) as Start Year (even though CV might say previous year - it's all gravy)."
                        % (SeriesYear, firstdate[:4], firstdate)
                    )
                if firstdate == "2099-00-00":
                    firstdate = "%s-01-01" % SeriesYear
                styear = str(firstdate[:4])

        if firstdate[5:7] == "00":
            stmonth = "?"
        else:
            stmonth = helpers.fullmonth(firstdate[5:7])

        if all([latest_stdate is not None, latest_stdate != "0000-00-00"]):
            p_date = datetime.date(int(latestdate[:4]), int(latestdate[5:7]), 1)
            s_date = datetime.date(int(latest_stdate[:4]), int(latest_stdate[5:7]), 1)
            if s_date > p_date:
                latestdate = latest_stdate

        ltyear = re.sub("/s", "", latestdate[:4])
        if latestdate[5:7] == "00":
            ltmonth = "?"
        else:
            ltmonth = helpers.fullmonth(latestdate[5:7])

        try:
            c_date = datetime.date(int(latestdate[:4]), int(latestdate[5:7]), 1)
        except:
            logger.error(
                "Cannot determine Latest Date for given series. This is most likely due to an issue having a date of : 0000-00-00"
            )
            latestdate = str(SeriesYear) + "-01-01"
            logger.error(
                "Setting Latest Date to be " + str(latestdate) + ". You should inform CV that the issue data is stale."
            )
            c_date = datetime.date(int(latestdate[:4]), int(latestdate[5:7]), 1)

        n_date = datetime.date.today()
        recentchk = (n_date - c_date).days

        if recentchk <= helpers.checkthepub(comicid):
            lastpubdate = "Present"
        else:
            if ltmonth == "?":
                if ltyear == "0000":
                    lastpubdate = "?"
                else:
                    lastpubdate = str(ltyear)
            elif ltyear == "0000":
                lastpubdate = "?"
            else:
                lastpubdate = str(ltmonth) + " " + str(ltyear)

        if stmonth == "?" and ("?" in lastpubdate and "0000" in lastpubdate):
            lastpubdate = "Present"
            newpublish = True
            publishfigure = str(styear) + " - " + str(lastpubdate)
        else:
            newpublish = False
            if lastpubdate == "%s %s" % (stmonth, styear):
                publishfigure = "%s %s" % (stmonth, styear)
            else:
                publishfigure = "%s %s - %s" % (stmonth, styear, lastpubdate)

        if stmonth == "?" and styear == "?" and lastpubdate == "0000" and comicIssues == "0":
            logger.info("No available issue data - I believe this is a NEW series.")
            latestdate = latestissueinfo[0]["latestdate"]
            latestiss = latestissueinfo[0]["latestiss"]
            lastpubdate = "Present"
            publishfigure = str(SeriesYear) + " - " + str(lastpubdate)

    if series_status == "Loading":
        series_status = "Active"

    controlValueStat = {"ComicID": comicid}

    newValueStat = {
        "Status": series_status,
        "Total": comicIssues,
        "ComicPublished": publishfigure,
        "NewPublish": newpublish,
        "LatestIssue": latestiss,
        "intLatestIssue": helpers.issuedigits(latestiss),
        "LatestIssueID": latestissueid,
        "LatestDate": latestdate,
        "LastUpdated": helpers.now(),
    }

    db.upsert("comics", newValueStat, controlValueStat)

    importantdates = {}
    importantdates["LatestIssue"] = latestiss
    importantdates["LatestIssueID"] = latestissueid
    importantdates["LatestDate"] = latestdate
    importantdates["LatestStoreDate"] = latest_stdate
    importantdates["LastPubDate"] = lastpubdate
    importantdates["SeriesStatus"] = series_status
    importantdates["ComicPublished"] = publishfigure
    importantdates["NewPublish"] = newpublish

    if comicarr.CONFIG.SERIES_METADATA_LOCAL is True:
        sm = series_metadata.metadata_Series(comicid, bulk=False, api=False)
        sm.update_metadata()

    if calledfrom == "weeklycheck":
        return weeklyissue_check

    elif len(issuedata) >= 1 and not calledfrom == "dbupdate":
        return {
            "issuedata": issuedata,
            "annualchk": annualchk,
            "importantdates": importantdates,
            "json_updated": True,
            "nostatus": False,
        }

    elif calledfrom == "dbupdate":
        return {
            "issuedata": issuedata,
            "annualchk": annualchk,
            "importantdates": importantdates,
            "json_updated": True,
            "nostatus": True,
        }

    else:
        return importantdates


def annual_check(ComicName, SeriesYear, comicid, issuetype, issuechk, annualslist, series_status):
    annualids = []
    annload = []

    nowdate = datetime.datetime.now()
    now_week = datetime.datetime.strftime(nowdate, "%Y%U")

    with db.get_engine().connect() as conn:
        stmt = select(annuals).where(annuals.c.ComicID == comicid)
        annual_load = [dict(row._mapping) for row in conn.execute(stmt)]

    logger.fdebug("checking annual db")
    for annthis in annual_load:
        if not any(d["ReleaseComicID"] == annthis["ReleaseComicID"] for d in annload):
            annload.append(
                {
                    "ReleaseComicID": annthis["ReleaseComicID"],
                    "ReleaseComicName": annthis["ReleaseComicName"],
                    "ComicID": annthis["ComicID"],
                    "ComicName": annthis["ComicName"],
                    "Deleted": bool(annthis["Deleted"]),
                }
            )

    if annload is None:
        pass
    else:
        for manchk in annload:
            if manchk["ReleaseComicID"] is not None or manchk["ReleaseComicID"] is not None:
                tmp_the_annuals = manualAnnual(
                    manchk["ReleaseComicID"],
                    ComicName,
                    SeriesYear,
                    comicid,
                    manualupd=True,
                    deleted=manchk["Deleted"],
                    series_status=series_status,
                )
                if tmp_the_annuals:
                    annualslist += tmp_the_annuals
            annualids.append(manchk["ReleaseComicID"])

    annualcomicname = re.sub(r"[\,\:]", "", ComicName)

    if annualcomicname.lower().startswith("the"):
        annComicName = annualcomicname[4:] + " annual"
    else:
        annComicName = annualcomicname + " annual"
    mode = "series"

    annualyear = SeriesYear
    logger.fdebug("[IMPORTER-ANNUAL] - Annual Year:" + str(annualyear))
    sresults = mb.findComic(annComicName, mode, issue=None, annual_check=True)
    if not sresults:
        return

    annual_types_ignore = {
        "paperback",
        "collecting",
        "reprinting",
        "reprints",
        "collected edition",
        "print edition",
        "hardcover",
        "hc",
        "tpb",
        "gn",
        "graphic novel",
        "available in print",
        "collects",
    }

    if len(sresults) > 0:
        logger.fdebug("[IMPORTER-ANNUAL] - there are " + str(len(sresults)) + " results.")
        num_res = 0
        while num_res < len(sresults):
            sr = sresults[num_res]
            sr_description = sr.get("description") or ""
            for x in annual_types_ignore:
                if x in sr_description.lower():
                    test_id_position = sr_description.find(comicid)
                    if test_id_position >= sr_description.lower().find(x) or test_id_position == -1:
                        logger.fdebug(
                            "[IMPORTER-ANNUAL] - tradeback/collected edition detected - skipping " + str(sr["comicid"])
                        )
                        continue

            if comicid in sr_description:
                logger.fdebug(
                    "[IMPORTER-ANNUAL] - " + str(comicid) + " found. Assuming it is part of the greater collection."
                )
                issueid = sr["comicid"]
                logger.fdebug("[IMPORTER-ANNUAL] - " + str(issueid) + " added to series list as an Annual")
                if issueid in annualids:
                    logger.fdebug(
                        "[IMPORTER-ANNUAL] - " + str(issueid) + " already exists within current annual list for series."
                    )
                    num_res += 1
                    continue
                issued = cv.getComic(issueid, "issue")
                if issued is None or len(issued) == 0:
                    logger.fdebug("[IMPORTER-ANNUAL] - Could not find any annual information...")
                    pass
                else:
                    n = 0
                    if int(sr["issues"]) == 0 and len(issued["issuechoice"]) == 1:
                        sr_issues = 1
                    else:
                        if int(sr["issues"]) != len(issued["issuechoice"]):
                            sr_issues = len(issued["issuechoice"])
                        else:
                            sr_issues = sr["issues"]
                    logger.fdebug("[IMPORTER-ANNUAL] - There are " + str(sr_issues) + " annuals in this series.")
                    while n < int(sr_issues):
                        try:
                            firstval = issued["issuechoice"][n]
                        except IndexError:
                            break
                        try:
                            cleanname = firstval["Issue_Name"]
                        except:
                            cleanname = "None"
                        issid = str(firstval["Issue_ID"])
                        issnum = str(firstval["Issue_Number"])
                        issname = cleanname
                        issdate = str(firstval["Issue_Date"])
                        stdate = str(firstval["Store_Date"])
                        digdate = str(firstval["Digital_Date"])
                        int_issnum = helpers.issuedigits(issnum)

                        with db.get_engine().connect() as conn:
                            stmt = select(annuals).where(annuals.c.IssueID == issid)
                            iss_exists = next((dict(row._mapping) for row in conn.execute(stmt)), None)

                        if iss_exists is None:
                            if stdate == "0000-00-00":
                                dk = re.sub("-", "", issdate).strip()
                            else:
                                dk = re.sub("-", "", stdate).strip()
                            if dk == "00000000":
                                logger.warn(
                                    "Issue Data is invalid for Issue Number %s. Marking this issue as Skipped"
                                    % firstval["Issue_Number"]
                                )
                                astatus = "Skipped"
                            else:
                                datechk = datetime.datetime.strptime(dk, "%Y%m%d")
                                issue_week = datetime.datetime.strftime(datechk, "%Y%U")
                                if series_status == "Paused":
                                    astatus = "Skipped"
                                else:
                                    if comicarr.CONFIG.AUTOWANT_ALL:
                                        astatus = "Wanted"
                                    elif issue_week >= now_week and comicarr.CONFIG.AUTOWANT_UPCOMING is True:
                                        astatus = "Wanted"
                                    else:
                                        astatus = "Skipped"
                        else:
                            astatus = iss_exists["Status"]

                        annualslist.append(
                            {
                                "Issue_Number": issnum,
                                "Int_IssueNumber": int_issnum,
                                "IssueDate": issdate,
                                "ReleaseDate": stdate,
                                "DigitalDate": digdate,
                                "IssueName": issname,
                                "ComicID": comicid,
                                "IssueID": issid,
                                "ComicName": ComicName,
                                "ReleaseComicID": re.sub("4050-", "", firstval["Comic_ID"]).strip(),
                                "ReleaseComicName": sr["name"],
                                "Deleted": False,
                                "Status": astatus,
                            }
                        )

                        n += 1
            num_res += 1
        manualAnnual(annchk=annualslist, series_status=series_status)
        return annualslist

    elif sresults is None or len(sresults) == 0:
        logger.fdebug("[IMPORTER-ANNUAL] - No results, removing the year from the agenda and re-querying.")
        sresults = mb.findComic(annComicName, mode, issue=None, annual_check=True)
        if not sresults:
            return
        elif len(sresults) == 1:
            sr = sresults[0]
            logger.fdebug(
                "[IMPORTER-ANNUAL] - " + str(comicid) + " found. Assuming it is part of the greater collection."
            )
        else:
            pass
    else:
        logger.fdebug("[IMPORTER-ANNUAL] - Returning results to screen - more than one possibility")
        for sr in sresults:
            if annualyear < sr["comicyear"]:
                logger.fdebug("[IMPORTER-ANNUAL] - " + str(annualyear) + " is less than " + str(sr["comicyear"]))
            if int(sr["issues"]) > (2013 - int(sr["comicyear"])):
                logger.fdebug("[IMPORTER-ANNUAL] - Issue count is wrong")


def image_it(comicid, latestissueid, comlocation, ComicImage):

    cimage = os.path.join(comicarr.CONFIG.CACHE_DIR, str(comicid) + ".jpg")
    imageurl = comicarr.cv.getComic(comicid, "image", issueid=latestissueid)
    if imageurl is None:
        return
    covercheck = helpers.getImage(comicid, imageurl["image"])
    if covercheck["status"] == "retry":
        logger.fdebug("Attempting to retrieve a different comic image for this particular issue.")
        if imageurl["image_alt"] is not None:
            covercheck = helpers.getImage(comicid, imageurl["image_alt"])
        else:
            if not os.path.isfile(cimage):
                logger.fdebug(
                    "Failed to retrieve issue image, possibly because not available. Reverting back to series image."
                )
                covercheck = helpers.getImage(comicid, ComicImage)
    PRComicImage = os.path.join("cache", str(comicid) + ".jpg")
    ComicImage = helpers.replacetheslash(PRComicImage)

    if comicarr.CONFIG.COMIC_COVER_LOCAL is True:
        cloc_it = []
        if comlocation is not None and all(
            [os.path.isdir(comlocation) is True, os.path.isfile(os.path.join(comlocation, "cover.jpg")) is False]
        ):
            cloc_it.append(comlocation)
        elif all([comicarr.CONFIG.MULTIPLE_DEST_DIRS is not None, comicarr.CONFIG.MULTIPLE_DEST_DIRS != "None"]):
            if all(
                [
                    os.path.isdir(os.path.join(comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(comlocation)))
                    is True,
                    os.path.isfile(
                        os.path.join(comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(comlocation), "cover.jpg")
                    )
                    is False,
                ]
            ):
                cloc_it.append(os.path.join(comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(comlocation)))
            else:
                ff = comicarr.filers.FileHandlers(ComicID=comicid)
                cloc = ff.secondary_folders(comlocation)
                if os.path.isfile(os.path.join(cloc, "cover.jpg")) is False:
                    cloc_it.append(cloc)

        for clocit in cloc_it:
            try:
                comiclocal = os.path.join(clocit, "cover.jpg")
                shutil.copyfile(cimage, comiclocal)
                if comicarr.CONFIG.ENFORCE_PERMS:
                    filechecker.setperms(comiclocal)
            except IOError as e:
                if "No such file or directory" not in str(e):
                    logger.error(
                        "[%s] Error saving cover (%s) into series directory (%s) at this time" % (e, cimage, comiclocal)
                    )

    db.upsert("comics", {"ComicImage": ComicImage}, {"ComicID": comicid})


def importer_thread(serieslist):

    if type(serieslist) != list:
        serieslist = [(serieslist)]

    threaded_call = True

    ctx = _mass_add_runtime_context()
    add_list = ctx.add_list if ctx is not None else comicarr.ADD_LIST
    issue_watch_list = ctx.issue_watch_list if ctx is not None else comicarr.ISSUE_WATCH_LIST

    for series in serieslist:
        add_list.put(series)

    try:
        pool = ctx.mass_add_pool if ctx is not None else comicarr.MASS_ADD
        if pool.is_alive():
            logger.info(
                "[MASS-ADD] MASS_ADD thread already running. Adding an additional %s items to existing queue"
                % len(serieslist)
            )
            threaded_call = False
    except Exception:
        pass

    if threaded_call is True:
        logger.info("[MASS-ADD] MASS_ADD thread not started. Started & submitting.")
        pool = threading.Thread(target=addvialist, args=(add_list, issue_watch_list), name="mass-add")
        _set_mass_add_pool(ctx, pool)
        pool.start()


def issue_watcher_thread(issuelist):
    if type(issuelist) != list:
        issuelist = [issuelist]

    ctx = _mass_add_runtime_context()
    issue_watch_list = ctx.issue_watch_list if ctx is not None else comicarr.ISSUE_WATCH_LIST
    for issue in issuelist:
        issue_watch_list.put(issue)


_REFRESH_WORKER_LOCK = threading.RLock()


def _start_refresh_worker():
    """Start the on-demand worker under the same lock used for retirement."""
    with _REFRESH_WORKER_LOCK:
        ctx = _mass_add_runtime_context()
        worker = ctx.mass_refresh_pool if ctx is not None else getattr(comicarr, "MASS_REFRESH", None)
        if worker is not None and getattr(worker, "is_alive", lambda: False)():
            return False
        logger.info("[MASS-REFRESH] MASS_REFRESH thread not started. Started & submitting.")
        refresh_queue = ctx.refresh_queue if ctx is not None else comicarr.REFRESH_QUEUE
        worker = threading.Thread(target=updater.addvialist, args=(refresh_queue,), name="mass-refresh")
        _set_mass_refresh_pool(ctx, worker)
        worker.start()
        return True


def refresh_worker_should_retire(refresh_queue):
    """Atomically decide whether an idle refresh worker may exit.

    Producers hold the same lock while enqueueing and checking liveness, so a
    command cannot land between the worker's empty check and its retirement.
    """
    with _REFRESH_WORKER_LOCK:
        if not refresh_queue.empty():
            return False
        ctx = _mass_add_runtime_context()
        worker = ctx.mass_refresh_pool if ctx is not None else getattr(comicarr, "MASS_REFRESH", None)
        if worker is threading.current_thread():
            _set_mass_refresh_pool(ctx, None)
        return True


def _handoff_refresh_items(queue_items, *, start_worker, maintenance=None):
    from comicarr.app.acquisition.maintenance import MaintenanceController

    if not queue_items:
        return
    controller = maintenance or MaintenanceController()
    with controller.lease(
        "refresh-producer",
        work_kind="refresh_queue_handoff",
        entity_type="run",
        entity_id=queue_items[0]["run_id"],
    ) as lease:
        controller.assert_lease_current(lease)
        with _REFRESH_WORKER_LOCK:
            ctx = _mass_add_runtime_context()
            refresh_queue = ctx.refresh_queue if ctx is not None else comicarr.REFRESH_QUEUE
            for queue_item in queue_items:
                refresh_queue.put(queue_item)
            if start_worker:
                _start_refresh_worker()


def _refresh_payload(raw_values):
    if not isinstance(raw_values, Mapping):
        raise ValueError("refresh command must be an object")
    values = {str(key).lower(): value for key, value in raw_values.items()}
    comicid = values.get("comicid")
    if comicid in (None, ""):
        raise ValueError("refresh command is missing comicid")
    payload = {
        "comicid": str(comicid),
        "comicname": values.get("comicname"),
        "seriesyear": values.get("seriesyear"),
    }
    for field in ("r_mode", "calledfrom", "serieslast_updated", "manual_comicid"):
        if field in values:
            payload[field] = values[field]
    return payload


def refresh_thread(
    serieslist,
    *,
    ledger=None,
    run_id=None,
    trigger="refresh_thread",
    start_worker=True,
    maintenance=None,
):
    """Persist refresh obligations before handing them to the worker queue."""
    from comicarr.app.acquisition.models import DispatchState
    from comicarr.app.acquisition.runs import RunLedger

    if not isinstance(serieslist, list):
        serieslist = [serieslist]
    if not serieslist:
        return None

    ledger = ledger or RunLedger()
    effective_run_id = str(run_id or uuid.uuid4())
    ledger.create_run(effective_run_id, command_kind="refresh", trigger=trigger, scope_type="series_batch")
    queued = []
    for raw_item in serieslist:
        payload = _refresh_payload(raw_item)
        ledger.accept_item(
            effective_run_id,
            entity_type="series",
            entity_id=payload["comicid"],
            payload=payload,
        )
        queue_item = {**payload, "run_id": effective_run_id}
        queued.append(queue_item)
    try:
        _handoff_refresh_items(queued, start_worker=start_worker, maintenance=maintenance)
    except Exception:
        ledger.record_dispatch(effective_run_id, DispatchState.ERROR)
        raise
    ledger.record_dispatch(effective_run_id, DispatchState.ACCEPTED)
    return effective_run_id


def replay_refresh_obligations(*, ledger=None, start_worker=True, maintenance=None):
    """Restore accepted/running refresh obligations after a process restart."""
    from comicarr.app.acquisition.models import DispatchState, ItemOutcome
    from comicarr.app.acquisition.runs import RunLedger

    ledger = ledger or RunLedger()
    queue_items = []
    replayed_run_ids = set()
    for item in ledger.list_recoverable_items("refresh"):
        run_id = item["run_id"]
        entity_id = item["entity_id"]
        if not ledger.claim_recovery(item):
            continue
        try:
            payload = _refresh_payload(item["payload"] or {})
        except ValueError as e:
            ledger.record_outcome(run_id, "series", entity_id, ItemOutcome.QUARANTINED, reason=str(e))
            continue
        if item["state"] == ItemOutcome.RUNNING.value:
            ledger.record_requeue(run_id, "series", entity_id, reason="worker restart", replay=True)
        queue_items.append({**payload, "run_id": run_id})
        replayed_run_ids.add(run_id)
    _handoff_refresh_items(queue_items, start_worker=start_worker, maintenance=maintenance)
    for run_id in replayed_run_ids:
        ledger.record_dispatch(run_id, DispatchState.ACCEPTED)
    return len(queue_items)
