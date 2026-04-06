#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Series domain service — comic CRUD, issue management, imports.

Module-level functions (not classes) — matches existing codebase style.
"""

import datetime
import os
import queue
import re
import shutil
import threading

import sqlalchemy

import comicarr
from comicarr import db, logger
from comicarr.app.series import queries as series_queries
from comicarr.tables import annuals, comics, issues, oneoffhistory, storyarcs, weekly

# ---------------------------------------------------------------------------
# Series CRUD
# ---------------------------------------------------------------------------


def list_comics(ctx, limit=None, offset=None):
    """List all comics, optionally with pagination."""
    if limit is not None:
        paginated = series_queries.list_comics_paginated(limit, offset=offset or 0)
        return {
            "comics": paginated["results"],
            "pagination": {
                "total": paginated["total"],
                "limit": paginated["limit"],
                "offset": paginated["offset"],
                "has_more": paginated["has_more"],
            },
        }
    return series_queries.list_comics()


def get_comic_detail(ctx, comic_id):
    """Get a single comic with its issues and annuals."""
    comic = series_queries.get_comic(comic_id)
    issues = series_queries.get_issues(comic_id)

    annuals_on = getattr(ctx.config, "ANNUALS_ON", False) if ctx.config else False
    annuals_list = series_queries.get_annuals(comic_id) if annuals_on else []

    return {"comic": comic, "issues": issues, "annuals": annuals_list}


def add_comic(ctx, comic_id):
    """Add a comic to the watchlist (background thread via importer)."""
    # Strip CV prefix if present
    if comic_id.startswith("4050-"):
        comic_id = re.sub("4050-", "", comic_id).strip()

    from comicarr import importer

    try:
        watch = [{"comicid": comic_id, "comicname": None}]
        importer.importer_thread(watch)
    except Exception as e:
        logger.error("[SERIES] Error adding comic %s: %s" % (comic_id, e))
        return {"success": False, "error": str(e)}

    return {"success": True, "message": "Successfully queued up adding id: %s" % comic_id}


def delete_comic(ctx, comic_id, delete_directory=False):
    """Delete a comic series with optional directory deletion."""
    # Strip CV prefix if present
    if comic_id.startswith("4050-"):
        comic_id = re.sub("4050-", "", comic_id).strip()

    comic = series_queries.get_comic_for_delete(comic_id)
    if not comic:
        return {"success": False, "error": "ComicID %s not found in watchlist" % comic_id}

    logger.fdebug("Deletion request received for %s (%s) [%s]" % (comic["ComicName"], comic["ComicYear"], comic_id))

    try:
        series_queries.delete_comic(comic_id)

        if delete_directory and comic.get("ComicLocation"):
            if os.path.exists(comic["ComicLocation"]):
                shutil.rmtree(comic["ComicLocation"])
                logger.fdebug("[SERIES-DELETE] Comic Location (%s) successfully deleted" % comic["ComicLocation"])
            else:
                logger.fdebug("[SERIES-DELETE] Comic Location (%s) does not exist" % comic["ComicLocation"])

    except Exception as e:
        logger.error("Unable to delete ComicID: %s. Error: %s" % (comic_id, e))
        return {"success": False, "error": "Unable to delete ComicID: %s" % comic_id}

    logger.fdebug(
        "[SERIES-DELETE] Successfully deleted %s (%s) [%s]" % (comic["ComicName"], comic["ComicYear"], comic_id)
    )
    return {
        "success": True,
        "message": "Successfully deleted %s (%s) [%s]" % (comic["ComicName"], comic["ComicYear"], comic_id),
    }


def pause_comic(ctx, comic_id):
    """Set comic status to Paused."""
    series_queries.pause_comic(comic_id)
    return {"success": True}


def resume_comic(ctx, comic_id):
    """Set comic status to Active."""
    series_queries.resume_comic(comic_id)
    return {"success": True}


def refresh_comic(ctx, comic_id):
    """Refresh comic metadata in the background."""
    from comicarr import importer

    # Support comma-separated list of IDs
    id_list = [cid.strip() for cid in comic_id.split(",") if cid.strip()]

    watch = []
    already_added = []
    notfound = []

    for cid in id_list:
        if cid.startswith("4050-"):
            cid = re.sub("4050-", "", cid).strip()

        chkdb = series_queries.get_comic_for_refresh(cid)
        if not chkdb:
            notfound.append({"comicid": cid})
        elif cid in comicarr.REFRESH_QUEUE.queue:
            already_added.append({"comicid": cid, "comicname": chkdb["ComicName"]})
        else:
            watch.append({"comicid": cid, "comicname": chkdb["ComicName"]})

    if notfound:
        return {"success": False, "error": "Unable to locate IDs for Refreshing: %s" % notfound}

    if not watch:
        if already_added:
            return {"success": True, "message": "Already queued for refresh"}
        return {"success": False, "error": "No comics to refresh"}

    try:
        importer.refresh_thread(watch)
    except Exception as e:
        logger.warn("[SERIES-REFRESH] Unable to refresh: %s" % e)
        return {"success": False, "error": "Unable to refresh: %s" % str(e)}

    return {"success": True, "message": "Refresh submitted for %s" % comic_id}


# ---------------------------------------------------------------------------
# Issue management
# ---------------------------------------------------------------------------


def queue_issue(ctx, issue_id):
    """Mark an issue as Wanted and trigger search."""
    from comicarr import search

    series_queries.queue_issue(issue_id)
    search.searchforissue(issue_id)
    return {"success": True}


def unqueue_issue(ctx, issue_id):
    """Mark an issue as Skipped."""
    series_queries.unqueue_issue(issue_id)
    return {"success": True}


def get_wanted(ctx, limit=None, offset=None, include_story_arcs=False):
    """Get all wanted issues, optionally with story arcs and annuals."""
    # Issues
    if limit is not None:
        paginated = series_queries.get_wanted_issues(limit=limit, offset=offset)
        result = {
            "issues": paginated["results"],
            "pagination": {
                "total": paginated["total"],
                "limit": paginated["limit"],
                "offset": paginated["offset"],
                "has_more": paginated["has_more"],
            },
        }
    else:
        result = {"issues": series_queries.get_wanted_issues()}

    # Story arcs
    if include_story_arcs:
        upcoming_storyarcs = getattr(ctx.config, "UPCOMING_STORYARCS", False) if ctx.config else False
        if upcoming_storyarcs:
            result["story_arcs"] = series_queries.get_wanted_storyarc_issues()

    # Annuals
    annuals_on = getattr(ctx.config, "ANNUALS_ON", False) if ctx.config else False
    if annuals_on:
        result["annuals"] = series_queries.get_wanted_annuals()

    return result


# ---------------------------------------------------------------------------
# Import management
# ---------------------------------------------------------------------------


def get_import_pending(ctx, limit=50, offset=0, include_ignored=False):
    """Get pending import files grouped by DynamicName/Volume."""
    return series_queries.get_import_pending(limit=limit, offset=offset, include_ignored=include_ignored)


def match_import(ctx, imp_ids, comic_id, issue_id=None):
    """Manually match import files to a comic series."""
    comic_name = series_queries.get_comic_name(comic_id) or "Unknown"

    matched = 0
    for imp_id in imp_ids:
        imp_id = imp_id.strip()
        if not imp_id:
            continue
        series_queries.match_import(imp_id, comic_id, comic_name, issue_id=issue_id)
        matched += 1

    return {"matched": matched, "comic_id": comic_id, "comic_name": comic_name}


def ignore_import(ctx, imp_ids, ignore=True):
    """Mark import files as ignored or unignored."""
    updated = 0
    for imp_id in imp_ids:
        imp_id = imp_id.strip()
        if not imp_id:
            continue
        series_queries.ignore_import(imp_id, ignore=ignore)
        updated += 1

    return {"updated": updated, "ignored": ignore}


def delete_import(ctx, imp_ids):
    """Delete import records."""
    deleted = 0
    for imp_id in imp_ids:
        imp_id = imp_id.strip()
        if not imp_id:
            continue
        series_queries.delete_import(imp_id)
        deleted += 1

    return {"deleted": deleted}


def refresh_import(ctx):
    """Trigger an import directory scan in the background."""
    from comicarr import librarysync

    import_dir = getattr(comicarr.CONFIG, "IMPORT_DIR", None) if comicarr.CONFIG else None
    if not import_dir:
        return {"success": False, "error": "Import directory not configured"}

    try:
        logger.info("[SERIES-IMPORT] Starting import directory scan for: %s" % import_dir)
        import_queue = queue.Queue()
        threading.Thread(target=librarysync.scanLibrary, name="API-ImportScan", args=[import_dir, import_queue]).start()
        return {"success": True, "message": "Import scan started for: %s" % import_dir}
    except Exception as e:
        logger.error("[SERIES-IMPORT] Error: %s" % e)
        return {"success": False, "error": "Failed to start import scan: %s" % str(e)}


def manga_library_scan(ctx):
    """Trigger a manga library scan in the background."""
    from comicarr import mangasync

    manga_dir = getattr(comicarr.CONFIG, "MANGA_DIR", None) if comicarr.CONFIG else None
    if not manga_dir:
        return {"success": False, "error": "Manga directory not configured"}

    try:
        logger.info("[MANGA-SCAN] Starting manga library scan for: %s" % manga_dir)
        threading.Thread(target=mangasync.mangaScan, name="API-MangaScan").start()
        return {"success": True, "message": "Manga scan started for: %s" % manga_dir}
    except Exception as e:
        logger.error("[MANGA-SCAN] Error: %s" % e)
        return {"success": False, "error": "Failed to start manga scan: %s" % str(e)}


# --- Extracted from helpers.py ---


def ComicSort(comicorder=None, sequence=None, imported=None):
    from sqlalchemy import select

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


def updateComicLocation():
    from sqlalchemy import select

    from comicarr.helpers import filesafe, replace_all

    if comicarr.CONFIG.NEWCOM_DIR is not None:
        logger.info("Performing a one-time mass update to Comic Location")
        checkdirectory = comicarr.filechecker.validateAndCreateDirectory(comicarr.CONFIG.NEWCOM_DIR, create=True)
        if not checkdirectory:
            logger.warn("Error trying to validate/create directory. Aborting this process at this time.")
            return
        dirlist = db.select_all(select(comics))
        comloc = []

        if dirlist is not None:
            for dl in dirlist:
                u_comicnm = dl["ComicName"]
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

                ccdir = re.sub(r"[\\|/]", "%&", comicarr.CONFIG.NEWCOM_DIR)
                ddir = re.sub(r"[\\|/]", "%&", comicarr.CONFIG.DESTINATION_DIR)
                dlc = re.sub(r"[\\|/]", "%&", dl["ComicLocation"])

                if comicarr.CONFIG.FFTONEWCOM_DIR:
                    if comicarr.CONFIG.FOLDER_FORMAT == "":
                        comlocation = re.sub(ddir, ccdir, dlc).strip()
                    else:
                        first = replace_all(folderformat, values)
                        if comicarr.CONFIG.REPLACE_SPACES:
                            first = first.replace(" ", comicarr.CONFIG.REPLACE_CHAR)
                        comlocation = os.path.join(comicarr.CONFIG.NEWCOM_DIR, first).strip()

                else:
                    comlocation = re.sub(ddir, ccdir, dlc).strip()

                try:
                    com_done = re.sub("%&", os.sep.encode().decode("unicode-escape"), comlocation).strip()
                except Exception as e:
                    logger.warn("[%s] error during conversion: %s" % (comlocation, e))
                    com_done = comlocation.replace("%&", os.sep).strip()

                comloc.append({"comlocation": com_done, "origlocation": dl["ComicLocation"], "comicid": dl["ComicID"]})

            if len(comloc) > 0:
                if comicarr.CONFIG.FFTONEWCOM_DIR:
                    logger.info(
                        "FFTONEWCOM_DIR is enabled. Applying the existing folder format to ALL directories regardless of existing location paths"
                    )
                else:
                    logger.info(
                        "FFTONEWCOM_DIR is not enabled. I will keep existing subdirectory paths, and will only change the actual Comic Location in the path."
                    )
                    logger.fdebug(" (ie. /mnt/Comics/Marvel/Hush-(2012) to /mnt/mynewLocation/Marvel/Hush-(2012) ")

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
        comicarr.CONFIG.LOCMOVE = False
        comicarr.CONFIG.writeconfig(values={"locmove": False})
    else:
        logger.info("No new ComicLocation path specified - not updating. Set NEWCOMD_DIR in config.ini")
    return


def checkthepub(ComicID):
    from sqlalchemy import select

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
                return comicarr.CONFIG.BIGGIE_PUB

        return comicarr.CONFIG.INDIE_PUB


def annual_update():
    from sqlalchemy import select

    annuallist = db.select_all(select(annuals).where(annuals.c.Deleted != 1))
    if annuallist is None:
        logger.info("no annuals to update.")
        return

    cnames = []
    for ann in annuallist:
        coms = db.select_one(select(comics).where(comics.c.ComicID == ann["ComicID"]))
        cnames.append({"ComicID": ann["ComicID"], "ComicName": coms["ComicName"]})

    i = 0
    for cns in cnames:
        ctrlVal = {"ComicID": cns["ComicID"]}
        newVal = {"ComicName": cns["ComicName"]}
        db.upsert("annuals", newVal, ctrlVal)
        i += 1

    logger.info(str(i) + " series have been updated in the annuals table.")
    return


_havetotals_cache = None
_havetotals_cache_time = 0


def havetotals(refreshit=None):
    global _havetotals_cache, _havetotals_cache_time
    import time

    from sqlalchemy import delete, func, select

    from comicarr.helpers import today

    # Return cached result if fresh (< 30s) and not a single-comic refresh
    now = time.monotonic()
    if _havetotals_cache is not None and (now - _havetotals_cache_time) < 30 and not refreshit:
        return _havetotals_cache

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
        comiclist.append(
            {
                "ComicID": comicref["ComicID"],
                "Have": comicref["Have"],
                "Total": comicref["Total"],
                "TotalAnnuals": comicref["TotalAnnuals"],
            }
        )

    for comic in comiclist:
        try:
            totalissues = comic["Total"]
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
                return True
            else:
                return False

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
                if "-" in latestdate[:3]:
                    st_date = latestdate.find("-")
                    st_remainder = latestdate[st_date + 1 :]
                    st_year = latestdate[:st_date]
                    year = "20" + st_year
                    latestdate = str(year) + "-" + str(st_remainder)
                c_date = datetime.date(int(latestdate[:4]), int(latestdate[5:7]), 1)
                n_date = datetime.date.today()
                recentchk = (n_date - c_date).days
                if comic["NewPublish"] is True:
                    recentstatus = "Continuing"
                else:
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
        except Exception:
            comictype = None

        if any([comic["ComicVersion"] is None, comic["ComicVersion"] == "None", comic["ComicVersion"] == ""]):
            cversion = None
        else:
            cversion = comic["ComicVersion"]

        if comic["ComicImage"] is None:
            comicImage = "cache/%s.jpg" % comic["ComicID"]
        else:
            comicImage = comic["ComicImage"]

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

    if not refreshit:
        _havetotals_cache = comics_list
        _havetotals_cache_time = now

    return comics_list


def listPull(weeknumber, year):
    from sqlalchemy import select

    library = {}
    rows = db.select_all(select(weekly.c.ComicID).where(weekly.c.weeknumber == weeknumber, weekly.c.year == year))
    for row in rows:
        library[row["ComicID"]] = row["ComicID"]
    return library


def listLibrary(comicid=None):
    from sqlalchemy import select

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
        except Exception:
            pass
        try:
            name = row["ComicName"]
            year = row["ComicYear"]
            if name and year:
                name_key = "name:" + name.lower().strip() + ":" + str(year).strip()
                library[name_key] = {"comicid": row["ComicID"], "status": row["Status"]}
        except Exception:
            pass

    return library


def listoneoffs(weeknumber, year):
    from sqlalchemy import select

    library = []
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


def listIssues(weeknumber, year):
    from sqlalchemy import select

    library = []
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

    return library


def incr_snatched(ComicID):
    from sqlalchemy import select

    incr_count = db.select_one(select(comics.c.Have).where(comics.c.ComicID == ComicID))
    logger.fdebug("Incrementing HAVE count total to : " + str(incr_count["Have"] + 1))
    newCtrl = {"ComicID": ComicID}
    newVal = {"Have": incr_count["Have"] + 1}
    db.upsert("comics", newVal, newCtrl)
    return


def get_issue_title(IssueID=None, ComicID=None, IssueNumber=None, IssueArcID=None):
    from sqlalchemy import select

    from comicarr.helpers import issuedigits

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


def latestdate_fix():
    from sqlalchemy import select

    from comicarr.helpers import filesafe

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
        try:
            if latestdate[8:] == "":
                if len(latestdate) <= 7:
                    finddash = latestdate.find("-")
                    if finddash != 4:  # format of mm-yyyy
                        lat_month = latestdate[:finddash]
                        lat_year = latestdate[finddash + 1 :]
                    else:  # format of yyyy-mm
                        lat_month = latestdate[finddash + 1 :]
                        lat_year = latestdate[:finddash]

                    latestdate = (lat_year) + "-" + str(lat_month) + "-01"
                    datefix.append({"comicid": cl["ComicID"], "latestdate": latestdate})
        except Exception:
            datefix.append({"comicid": cl["ComicID"], "latestdate": "0000-00-00"})

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


def latestdate_update():
    from sqlalchemy import select

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

    for a in ablist:
        logger.info(a)
        newVal = {"LatestDate": a["LatestDate"], "LatestIssue": a["LatestIssue"]}
        ctrlVal = {"ComicID": a["ComicID"]}
        logger.info("updating latest date for : " + a["ComicID"] + " to " + a["LatestDate"] + " #" + a["LatestIssue"])
        db.upsert("comics", newVal, ctrlVal)


def latestissue_update():
    from sqlalchemy import select

    from comicarr.helpers import issuedigits

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


def DateAddedFix():
    from sqlalchemy import update

    DA_A = datetime.datetime.today()
    DateAdded = DA_A.strftime("%Y-%m-%d")

    with db.get_engine().begin() as conn:
        conn.execute(
            update(issues).where(issues.c.Status == "Wanted", issues.c.DateAdded.is_(None)).values(DateAdded=DateAdded)
        )
        conn.execute(
            update(annuals)
            .where(annuals.c.Status == "Wanted", annuals.c.DateAdded.is_(None), annuals.c.Deleted != 1)
            .values(DateAdded=DateAdded)
        )


def statusChange(status_from, status_to, comicid=None, bulk=False, api=True):
    from sqlalchemy import select

    the_list = []
    if bulk is False:
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


def issue_status(IssueID):
    from sqlalchemy import select

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
