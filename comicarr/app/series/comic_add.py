#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Add a comic series from ComicVine, and re-read or extend one already added.

Moved from ``comicarr/importer.py`` (#1464). The old names map as follows:
``addComictoDB`` is ``add_comic``, ``updateissuedata`` is ``update_issue_data``,
``issue_collection`` is ``store_issue_rows``, ``manualAnnual`` is
``add_manual_annual``, ``annual_check`` is ``check_annuals``, ``image_it`` is
``fetch_series_image``, ``markSeriesWanted`` is ``mark_series_wanted`` and
``markIssueWantedById`` is ``mark_issue_wanted``. Other modules add a series
through ``app/series/add.py``.
"""

import datetime
import json
import os
import re
import shutil

import sqlalchemy.exc
from sqlalchemy import select

import comicarr
from comicarr.app.common import configured as configured
from comicarr.app.common import dates as common_dates
from comicarr.app.common import series_kind
from comicarr.app.common import strings as common_strings
from comicarr.app.core import db, logger
from comicarr.app.core.tables import annuals, comics, issues
from comicarr.app.core.workers import start_background_thread
from comicarr.app.downloads import snatch_record
from comicarr.app.library import directories, filechecker, filers, moveit
from comicarr.app.manga import add as manga_add
from comicarr.app.metadata import cv, series_metadata
from comicarr.app.metadata import service as metadata_service
from comicarr.app.metadata.series_type import resolve_series_edition
from comicarr.app.search import engine as search
from comicarr.app.search import mb
from comicarr.app.series import rescan
from comicarr.app.series import service as series_service
from comicarr.app.series.add_activity import emit_add_activity
from comicarr.app.weekly import pull


def mark_series_wanted(comicid):
    """Mark every issue and annual of a series Wanted, right after its add.

    Run by the mass-add worker for an add queued with ``want``; issues already
    Downloaded, Wanted, Snatched or Failed keep their status.
    """
    issue_ids = [row["IssueID"] for row in db.select_all(select(issues.c.IssueID).where(issues.c.ComicID == comicid))]
    issue_ids += [
        row["IssueID"]
        for row in db.select_all(
            select(annuals.c.IssueID).where(
                annuals.c.ComicID == comicid, annuals.c.Deleted.is_(None) | (annuals.c.Deleted != 1)
            )
        )
    ]
    if not issue_ids:
        logger.warning("[MASS-ADD] No issues found to mark Wanted for ComicID %s" % comicid)
    for issue_id in issue_ids:
        mark_issue_wanted(issue_id)


def mark_issue_wanted(issueId):
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

    check_annuals = False
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
                .where(annuals.c.Deleted.is_(None) | (annuals.c.Deleted != 1))
            )
            issue = next((dict(row._mapping) for row in conn.execute(stmt)), None)

        if issue is None:
            logger.warning(
                f"Tried setting wanted status for issue with ID {issueId} in MASS-ADD thread but could not find issue"
            )
            return
        else:
            check_annuals = True
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

    if check_annuals:
        db.upsert("annuals", newValueDict, controlValueDict)
    else:
        db.upsert("issues", newValueDict, controlValueDict)

    logger.fdebug(f"Finished changing status of {comicname} [ID:{comicid}] issue #{issuenumber} to Wanted")


def add_comic(
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
    location=None,
    metadata_only=False,
):

    if metadata_only:
        from comicarr.app.imports.metadata import add_series_metadata

        return add_series_metadata(comicid)

    provider = series_kind.provider_of(comicid)
    if provider is series_kind.SeriesProvider.MANGADEX:
        return manga_add.add_mangadex(comicid, imported=imported, calledfrom=calledfrom, location=location)
    if provider is series_kind.SeriesProvider.MYANIMELIST:
        return manga_add.add_myanimelist(comicid, imported=imported, calledfrom=calledfrom, location=location)

    from comicarr.app.metadata import metron

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
                checkdirectory = directories.validateAndCreateDirectory(comlocation, True)
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
        newValueDict = {"Status": "Loading"}
        if dbcomic is None:
            # Only a new series gets the placeholder name: a series already in
            # the library keeps its name, so a failed fetch cannot rename it
            # (#1346).
            newValueDict["ComicName"] = "Comic ID: %s" % (comicid)
        if location:
            comlocation = location
        elif all([imported is not None, imported != "None", comicarr.CONFIG.IMP_PATHS is True]):
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
        series_service.ComicSort(comicorder=comicarr.COMICSORT, imported=comicid)

    comic = cv.getComic(comicid, "comic", series=True)

    if not comic:
        logger.warn("Error fetching comic. ID for : " + comicid)
        if dbcomic is None or str(dbcomic.get("ComicName") or "").startswith(("Fetch failed", "Comic ID:")):
            # A retry of a failed add fails the same way: keep the marker so
            # the next add retries instead of finding the series "in the library".
            newValueDict = {"ComicName": "Fetch failed, try refreshing. (%s)" % (comicid), "Status": "Active"}
            failed_add = True
        else:
            # Restore the status the series had before this run set it to
            # Loading; series_status is reset above for a series with no
            # folder, which would otherwise un-pause it (#1346).
            if str(dbcomic.get("Status") or "") == "Paused":
                newValueDict = {"Status": "Paused"}
            elif series_status == "Active" or series_status == "Loading":
                newValueDict = {"Status": "Active"}
            else:
                newValueDict = {"Status": "Paused"}
            failed_add = False
        db.upsert("comics", newValueDict, controlValueDict)
        if failed_add:
            # Only a new (or still-placeholder) series is a failed add; a
            # failed refresh of a series already in the library is not.
            emit_add_activity("failed", comicid, reason_detail="Metadata provider fetch failed")
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
    CV_NoYearGiven = "no"
    if any(
        [
            comic["ComicYear"] is None,
            comic["ComicYear"] == "0000",
            comic["ComicYear"][-1:] == "-",
            comic["ComicYear"] == "2099",
        ]
    ):
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
    logger.fdebug("seriesyear: %s / currentyear: %s" % (SeriesYear, common_dates.today()[:4]))
    logger.fdebug("comicType: %s" % comic["Type"])
    booktype = resolve_series_edition(
        series_type=comic["Type"],
        issue_count=comicIssues,
        series_year=SeriesYear,
        current_year=common_dates.today()[:4],
        volume=comic.get("ComicVersion"),
        description=comic.get("ComicDescription"),
        series_name=comic.get("ComicName"),
    )
    if booktype == "One-Shot" and comic["Type"] not in ("One-Shot", "TPB", "HC", "GN"):
        logger.info("Determined to be a one-shot issue. Forcing Edition to One-Shot")
    elif booktype in ("TPB", "HC", "GN") and comic["Type"] not in ("TPB", "HC", "GN", "One-Shot"):
        logger.info("Determined to be a collected volume. Setting Edition to %s" % booktype)

    u_comicnm = comic["ComicName"]
    comicname_filesafe = common_strings.filesafe(u_comicnm)

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

        if comic["ComicYear"] == "2099" and SeriesYear and not (dbcomic or {}).get("dirlocked"):
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
                        checkdirectory = directories.validateAndCreateDirectory(new_location, True)
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
                checkdirectory = directories.validateAndCreateDirectory(comlocation, True)
                if not checkdirectory:
                    logger.warn("Error trying to validate/create directory. Aborting this process at this time.")
                    return {"status": "incomplete"}
    else:
        logger.warn(
            "Comic Location path has not been specified as required in your configuration. Aborting this process at this time."
        )
        return {"status": "incomplete"}

    cimage = os.path.join(comicarr.CONFIG.CACHE_DIR, str(comicid) + ".jpg")
    if comicarr.CONFIG.ALTERNATE_LATEST_SERIES_COVERS is False or not os.path.isfile(cimage):
        cimage = os.path.join(comicarr.CONFIG.CACHE_DIR, str(comicid) + ".jpg")
        PRComicImage = os.path.join("cache", str(comicid) + ".jpg")
        ComicImage = common_strings.replacetheslash(PRComicImage)
        coversize = 0
        if os.path.isfile(cimage):
            statinfo = os.stat(cimage)
            coversize = statinfo.st_size

        if FirstImageSize != 0 and (os.path.isfile(cimage) is True and FirstImageSize == coversize):
            logger.fdebug("Cover already exists for series. Not redownloading.")
        else:
            covercheck = metadata_service.getImage(comicid, comic["ComicImage"])
            FirstImageSize = covercheck["coversize"]
            if covercheck["status"] == "retry":
                logger.info("Attempting to retrieve alternate comic image for the series.")
                covercheck = metadata_service.getImage(comicid, comic["ComicImageALT"])

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
                    ff = filers.FileHandlers(comic=comic)
                    cloc = ff.secondary_folders(comlocation)
                    if os.path.isfile(os.path.join(cloc, "cover.jpg")) is False:
                        cloc_it.append(cloc)

            for clocit in cloc_it:
                try:
                    comiclocal = os.path.join(clocit, "cover.jpg")
                    shutil.copyfile(cimage, comiclocal)
                    if comicarr.CONFIG.ENFORCE_PERMS:
                        directories.setperms(comiclocal)
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
                th_check = metadata_service.getImage(
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
        "dirlocked": 1 if location else (dbcomic or {}).get("dirlocked"),
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
        "DateAdded": common_dates.today(),
        "Status": "Loading",
    }

    db.upsert("comics", newValueDict, controlValueDict)

    if all([pullupd is None, calledfrom != "maintenance"]):
        series_service.ComicSort(sequence="update")

    if CV_NoYearGiven == "no":
        issued = cv.getComic(comicid, "issue")
        if issued is None:
            logger.warn("Unable to retrieve data from ComicVine. Get your own API key already!")
            return {"status": "incomplete"}
    logger.info("Successfully retrieved issue details for " + comic["ComicName"])

    updateddata = update_issue_data(
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
        store_issue_rows(issuedata, nostatus="False", serieslast_updated=serieslast_updated)
        if anndata:
            add_manual_annual(annchk=anndata, series_status=series_status)

    if comicarr.CONFIG.ALTERNATE_LATEST_SERIES_COVERS is True:
        cimage = os.path.join(comicarr.CONFIG.CACHE_DIR, comicid + ".jpg")
        coversize = 0
        if os.path.isfile(cimage):
            statinfo = os.stat(cimage)
            coversize = statinfo.st_size

        if os.path.isfile(cimage) and all([FirstImageSize != 0, FirstImageSize == coversize]):
            logger.fdebug("Cover already exists for series. Not redownloading.")
        else:
            fetch_series_image(comicid, importantdates["LatestIssueID"], comlocation, comic["ComicImage"])
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
            .where(issues.c.Int_IssueNumber == configured.issuedigits(latestiss))
        )
        statbefore = next((dict(row._mapping) for row in conn.execute(stmt)), None)

    logger.fdebug("issue: " + latestiss + " status before chk :" + str(statbefore["Status"]))
    rescan.rescan_series(comicid)

    if not json_updated and comicarr.CONFIG.SERIES_METADATA_LOCAL is True:
        sm = series_metadata.metadata_Series(comicid, bulk=False, api=False)
        sm.update_metadata()

    with db.get_engine().connect() as conn:
        stmt = (
            select(issues.c.Status)
            .where(issues.c.ComicID == comicid)
            .where(issues.c.Int_IssueNumber == configured.issuedigits(latestiss))
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
                    .where(issues.c.Int_IssueNumber == configured.issuedigits(latestiss))
                )
                chkstats = next((dict(row._mapping) for row in conn.execute(stmt)), None)

            if chkstats is None:
                if comicarr.CONFIG.ANNUALS_ON:
                    with db.get_engine().connect() as conn:
                        stmt = (
                            select(annuals)
                            .where(annuals.c.ComicID == comicid)
                            .where(annuals.c.Int_IssueNumber == configured.issuedigits(latestiss))
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
                    pull.match_new_series(cn_pull, comicid, issue=latestiss)

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


def store_issue_rows(issuedata, nostatus, serieslast_updated=None, suppress_addall=None):
    try:
        serieslast_updated = datetime.datetime.strptime(serieslast_updated, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
    except Exception:
        pass

    logger.fdebug("issue_collection: %s issue(s), nostatus=%s" % (len(issuedata or []), nostatus))

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
                    newValueDict["DateAdded"] = common_dates.today()
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


def add_manual_annual(
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
                except Exception:
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
            "Int_IssueNumber": configured.issuedigits(ann["Issue_Number"]),
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


def update_issue_data(
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

    annualchk = check_annuals(comicname, SeriesYear, comicid, issuetype, issuechk, annualchk, series_status)
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
            except Exception:
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
                            snatch_record.no_searchresults(comicid)
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
                if int_issnum > configured.issuedigits(latestiss):
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
            store_issue_rows(
                issuedata, nostatus="False", serieslast_updated=serieslast_updated, suppress_addall=suppress_addall
            )
        else:
            logger.fdebug("initiating issue updating - just the info")
            store_issue_rows(
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
            stmonth = common_dates.fullmonth(firstdate[5:7])

        if all([latest_stdate is not None, latest_stdate != "0000-00-00"]):
            p_date = datetime.date(int(latestdate[:4]), int(latestdate[5:7]), 1)
            s_date = datetime.date(int(latest_stdate[:4]), int(latest_stdate[5:7]), 1)
            if s_date > p_date:
                latestdate = latest_stdate

        ltyear = re.sub("/s", "", latestdate[:4])
        if latestdate[5:7] == "00":
            ltmonth = "?"
        else:
            ltmonth = common_dates.fullmonth(latestdate[5:7])

        try:
            c_date = datetime.date(int(latestdate[:4]), int(latestdate[5:7]), 1)
        except Exception:
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

        if recentchk <= series_service.checkthepub(comicid):
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
        "intLatestIssue": configured.issuedigits(latestiss),
        "LatestIssueID": latestissueid,
        "LatestDate": latestdate,
        "LastUpdated": common_dates.now(),
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


def check_annuals(ComicName, SeriesYear, comicid, issuetype, issuechk, annualslist, series_status):
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
                tmp_the_annuals = add_manual_annual(
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
    sresults = mb.findComic(annComicName, mode, issue=None, check_annuals=True)
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
                        except Exception:
                            cleanname = "None"
                        issid = str(firstval["Issue_ID"])
                        issnum = str(firstval["Issue_Number"])
                        issname = cleanname
                        issdate = str(firstval["Issue_Date"])
                        stdate = str(firstval["Store_Date"])
                        digdate = str(firstval["Digital_Date"])
                        int_issnum = configured.issuedigits(issnum)

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
        add_manual_annual(annchk=annualslist, series_status=series_status)
        return annualslist

    elif sresults is None or len(sresults) == 0:
        logger.fdebug("[IMPORTER-ANNUAL] - No results, removing the year from the agenda and re-querying.")
        sresults = mb.findComic(annComicName, mode, issue=None, check_annuals=True)
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


def fetch_series_image(comicid, latestissueid, comlocation, ComicImage):

    cimage = os.path.join(comicarr.CONFIG.CACHE_DIR, str(comicid) + ".jpg")
    imageurl = cv.getComic(comicid, "image", issueid=latestissueid)
    if imageurl is None:
        return
    covercheck = metadata_service.getImage(comicid, imageurl["image"])
    if covercheck["status"] == "retry":
        logger.fdebug("Attempting to retrieve a different comic image for this particular issue.")
        if imageurl["image_alt"] is not None:
            covercheck = metadata_service.getImage(comicid, imageurl["image_alt"])
        else:
            if not os.path.isfile(cimage):
                logger.fdebug(
                    "Failed to retrieve issue image, possibly because not available. Reverting back to series image."
                )
                covercheck = metadata_service.getImage(comicid, ComicImage)
    PRComicImage = os.path.join("cache", str(comicid) + ".jpg")
    ComicImage = common_strings.replacetheslash(PRComicImage)

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
                ff = filers.FileHandlers(ComicID=comicid)
                cloc = ff.secondary_folders(comlocation)
                if os.path.isfile(os.path.join(cloc, "cover.jpg")) is False:
                    cloc_it.append(cloc)

        for clocit in cloc_it:
            try:
                comiclocal = os.path.join(clocit, "cover.jpg")
                shutil.copyfile(cimage, comiclocal)
                if comicarr.CONFIG.ENFORCE_PERMS:
                    directories.setperms(comiclocal)
            except IOError as e:
                if "No such file or directory" not in str(e):
                    logger.error(
                        "[%s] Error saving cover (%s) into series directory (%s) at this time" % (e, cimage, comiclocal)
                    )

    db.upsert("comics", {"ComicImage": ComicImage}, {"ComicID": comicid})
