#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Story Arcs domain service — arc CRUD, reading list, upcoming.

Module-level functions (not classes) — matches existing codebase style.
"""

import datetime
import os
import random
import re
import threading
import time

import requests

import comicarr
from comicarr import db, helpers, logger
from comicarr.app.storyarcs import queries as arc_queries
from comicarr.tables import comics, issues, storyarcs

ALLOWED_ARC_STATUSES = {"Wanted", "Read", "Skipped"}


def _build_arc_summary(row):
    """Build a summary dict from an arc row with aggregated stats."""
    total = row["Total"] or 0
    have = row["Have"] or 0
    try:
        percent = round((have * 100.0) / total, 1) if total > 0 else 0
    except (ZeroDivisionError, TypeError):
        percent = 0

    min_year = row["min_year"]
    max_year = row["max_year"]
    if min_year is None or max_year is None:
        span_years = None
    elif min_year == max_year:
        span_years = str(max_year)
    else:
        span_years = "%s - %s" % (min_year, max_year)

    return {
        "StoryArcID": row["StoryArcID"],
        "StoryArc": row["StoryArc"],
        "TotalIssues": total,
        "Have": have,
        "Total": total,
        "percent": percent,
        "SpanYears": span_years,
        "CV_ArcID": row["CV_ArcID"],
        "Publisher": row["Publisher"],
        "ArcImage": row["ArcImage"],
    }


def list_arcs(custom_only=False):
    """List all story arcs with aggregated stats and computed fields."""
    rows = arc_queries.list_arcs(custom_only=custom_only)
    return [_build_arc_summary(row) for row in rows]


def get_arc_detail(arc_id):
    """Get a single story arc with summary stats and all issues."""
    arc_row = arc_queries.get_arc_stats(arc_id)
    if arc_row is None:
        return None

    arc_summary = _build_arc_summary(arc_row)
    issues = arc_queries.get_arc_issues(arc_id)

    return {"arc": arc_summary, "issues": issues}


def delete_arc(arc_id, arc_name=None, delete_type=None):
    """Delete an entire story arc."""
    arc_queries.delete_arc(arc_id, arc_name=arc_name, delete_type=delete_type)
    logger.info("[DELETE-ARC] Removed %s from Story Arcs" % arc_id)
    return {"success": True}


def delete_arc_issue(issue_arc_id, manual=None):
    """Remove a single issue from a story arc (soft-delete by default)."""
    arc_queries.soft_delete_arc_issue(issue_arc_id, manual=manual)
    logger.info("[DELETE-ARC] Removed %s from the Story Arc" % issue_arc_id)
    return {"success": True}


def set_issue_status(issue_arc_id, status):
    """Update the status of a single arc issue."""
    if status not in ALLOWED_ARC_STATUSES:
        return {"success": False, "error": "Invalid status"}

    arc_queries.set_issue_status(issue_arc_id, status)
    return {"success": True}


def want_all_issues(arc_id):
    """Mark all eligible arc issues as Wanted and trigger search."""
    queued, skipped = arc_queries.want_all_issues(arc_id)

    # Trigger search in background if any were queued
    if queued > 0:
        threading.Thread(target=_read_get_wanted, args=(arc_id,)).start()

    return {"success": True, "data": {"queued": queued, "skipped": skipped}}


def refresh_arc(arc_id):
    """Refresh a story arc from ComicVine in the background."""
    arc_row = arc_queries.get_arc_for_refresh(arc_id)
    if arc_row is None:
        return {"success": False, "error": "Story arc not found"}

    threading.Thread(
        target=_add_story_arc,
        kwargs={
            "arcid": arc_row["StoryArcID"],
            "cvarcid": arc_row["CV_ArcID"],
            "storyarcname": arc_row["StoryArc"],
            "storyarcissues": None,
            "arclist": None,
            "arcrefresh": True,
        },
    ).start()

    return {"success": True, "message": "Refreshing %s from ComicVine" % arc_row["StoryArc"]}


# ---------------------------------------------------------------------------
# Extracted from webserve.WebInterface (ReadGetWanted, addStoryArc)
# ---------------------------------------------------------------------------


def _read_get_wanted(StoryArcID):
    """Queue story arc issues as Wanted and add to search queue.

    Extracted from WebInterface.ReadGetWanted — standalone, no CherryPy deps.
    """
    stupdate = []
    add_to_search_queue = []
    wantedlist = db.raw_select_all(
        "SELECT * FROM storyarcs WHERE StoryArcID=? AND Manual != 'deleted' AND Status != 'Downloaded' AND Status !='Archived' AND Status !='Snatched'",
        [StoryArcID],
    )
    if wantedlist is not None:
        for want in wantedlist:
            issuechk = db.raw_select_one(
                "SELECT a.Type, a.ComicYear, b.ComicName, b.Issue_Number, b.ComicID, b.IssueID FROM comics as a INNER JOIN issues as b on a.ComicID = b.ComicID WHERE b.IssueID=?",
                [want["IssueArcID"]],
            )
            SARC = want["StoryArc"]
            IssueArcID = want["IssueArcID"]
            if issuechk is None:
                s_comicid = want["ComicID"]
                s_issueid = want["IssueArcID"]
                actual_issueid = None
                BookType = want["Type"]
                stdate = want["ReleaseDate"]
                issdate = want["IssueDate"]
                logger.fdebug("-- NOT a watched series queue.")
                logger.fdebug("%s -- #%s" % (want["ComicName"], want["IssueNumber"]))
                logger.fdebug("Story Arc %s : queueing the selected issue..." % SARC)
                logger.fdebug("IssueArcID : %s" % IssueArcID)
                logger.fdebug("ComicID: %s --- IssueID: %s" % (s_comicid, s_issueid))
                logger.fdebug("ReleaseDate: %s --- IssueDate: %s" % (stdate, issdate))
                issueyear = want["IssueYEAR"]
                logger.fdebug("IssueYear: %s" % issueyear)
                if issueyear is None or issueyear == "None":
                    try:
                        logger.fdebug("issdate:" + str(issdate))
                        issueyear = issdate[:4]
                        if not issueyear.startswith("19") and not issueyear.startswith("20"):
                            issueyear = stdate[:4]
                    except Exception as e:
                        logger.fdebug("[STORYARC] Error parsing issue year: %s" % e)
                        issueyear = stdate[:4]

                passinfo = {
                    "issueid": s_issueid,
                    "comicname": want["ComicName"],
                    "seriesyear": want["SeriesYear"],
                    "comicid": s_comicid,
                    "issuenumber": want["IssueNumber"],
                    "booktype": BookType,
                }
            else:
                s_comicid = issuechk["ComicID"]
                s_issueid = issuechk["IssueID"]
                actual_issueid = None
                logger.fdebug("-- watched series queue.")
                logger.fdebug("%s --- #%s" % (issuechk["ComicName"], issuechk["Issue_Number"]))
                passinfo = {
                    "issueid": s_issueid,
                    "comicname": issuechk["ComicName"],
                    "seriesyear": issuechk["SeriesYear"],
                    "comicid": s_comicid,
                    "issuenumber": issuechk["Issue_Number"],
                    "booktype": issuechk["Type"],
                }

            add_to_search_queue.append(passinfo)

            logger.fdebug(
                "Marking %s #%s (%s) as Wanted for future searches."
                % (want["ComicName"], want["IssueNumber"], want["SeriesYear"])
            )
            stupdate.append({"Status": "Wanted", "IssueArcID": IssueArcID, "IssueID": actual_issueid})

    watchlistchk = db.raw_select_all(
        "SELECT * FROM storyarcs WHERE StoryArcID=? AND Manual != 'deleted' AND Status='Wanted'", [StoryArcID]
    )
    if watchlistchk is not None:
        for watchchk in watchlistchk:
            logger.fdebug("Watchlist hit - %s" % watchchk["ComicName"])
            issuechk = db.raw_select_one(
                "SELECT a.Type, a.ComicYear, b.ComicName, b.Issue_Number, b.ComicID, b.IssueID FROM comics as a INNER JOIN issues as b on a.ComicID = b.ComicID WHERE b.IssueID=?",
                [watchchk["IssueArcID"]],
            )
            SARC = watchchk["StoryArc"]
            IssueArcID = watchchk["IssueArcID"]
            if issuechk is None:
                try:
                    s_comicid = watchchk["ComicID"]
                except Exception as e:
                    logger.fdebug("[STORYARC] Error getting ComicID: %s" % e)
                    s_comicid = None

                try:
                    s_issueid = watchchk["IssueArcID"]
                except Exception as e:
                    logger.fdebug("[STORYARC] Error getting IssueArcID: %s" % e)
                    s_issueid = None

                actual_issueid = None
                logger.fdebug("-- NOT a watched series queue.")
                logger.fdebug("%s -- #%s" % (watchchk["ComicName"], watchchk["IssueNumber"]))
                logger.fdebug("Story Arc : %s queueing up the selected issue..." % SARC)
                logger.fdebug("IssueArcID : %s" % IssueArcID)
                try:
                    issueyear = watchchk["IssueYEAR"]
                    logger.fdebug("issueYEAR : %s" % issueyear)
                except Exception as e:
                    logger.fdebug("[STORYARC] Error getting IssueYEAR: %s" % e)
                    try:
                        issueyear = watchchk["IssueDate"][:4]
                    except Exception as e:
                        logger.fdebug("[STORYARC] Error getting IssueDate year: %s" % e)
                        issueyear = watchchk["ReleaseDate"][:4]

                passinfo = {
                    "issueid": s_issueid,
                    "comicname": watchchk["ComicName"],
                    "seriesyear": watchchk["SeriesYear"],
                    "comicid": s_comicid,
                    "issuenumber": watchchk["IssueNumber"],
                    "booktype": watchchk["Type"],
                }

            else:
                s_comicid = issuechk["ComicID"]
                s_issueid = issuechk["IssueID"]
                actual_issueid = issuechk["IssueID"]
                logger.fdebug("-- watched series queue.")
                logger.fdebug("%s -- #%s" % (issuechk["ComicName"], issuechk["Issue_Number"]))
                passinfo = {
                    "issueid": s_issueid,
                    "comicname": issuechk["ComicName"],
                    "seriesyear": issuechk["SeriesYear"],
                    "comicid": s_comicid,
                    "issuenumber": issuechk["Issue_Number"],
                    "booktype": issuechk["Type"],
                }

            add_to_search_queue.append(passinfo)

            stupdate.append({"Status": "Wanted", "IssueArcID": IssueArcID, "IssueID": actual_issueid})

    if len(stupdate) > 0:
        logger.fdebug("%s issues need to get updated to Wanted Status" % len(stupdate))
        for st in stupdate:
            ctrlVal = {"IssueArcID": st["IssueArcID"]}
            newVal = {"Status": st["Status"]}
            db.upsert("storyarcs", newVal, ctrlVal)
            if st["IssueID"]:
                ctrlVal = {"IssueID": st["IssueID"]}
                db.upsert("issues", newVal, ctrlVal)
    for item in add_to_search_queue:
        comicarr.SEARCH_QUEUE.put(item)


def _arc_watchlist(StoryArcID=None):
    """Search watchlist for matches belonging to a story arc.

    Extracted from WebInterface.ArcWatchlist — standalone, no CherryPy deps.
    """
    from comicarr import filechecker

    if StoryArcID:
        ArcWatch = db.raw_select_all("SELECT * FROM storyarcs WHERE StoryArcID=?", [StoryArcID])
    else:
        ArcWatch = db.raw_select_all("SELECT * FROM storyarcs")

    if ArcWatch is None:
        logger.info("No Story Arcs to search")
    else:
        arcname = ArcWatch[0]["StoryArc"]
        arcdir = helpers.filesafe(arcname)
        if StoryArcID is None:
            StoryArcID = ArcWatch[0]["StoryArcID"]
        arcpub = ArcWatch[0]["Publisher"]
        if arcpub is None:
            arcpub = ArcWatch[0]["IssuePublisher"]

        logger.info("arcpub: %s" % arcpub)
        dstloc = helpers.arcformat(arcdir, helpers.spantheyears(StoryArcID), arcpub)

        if dstloc is not None:
            if not os.path.isdir(dstloc):
                if comicarr.CONFIG.STORYARCDIR:
                    logger.info("Story Arc Directory [%s] does not exist! - attempting to create now." % dstloc)
                else:
                    logger.info(
                        "Story Arc Grab-Bag Directory [%s] does not exist! - attempting to create now." % dstloc
                    )
                checkdirectory = filechecker.validateAndCreateDirectory(dstloc, True)
                if not checkdirectory:
                    logger.warn("Error trying to validate/create directory. Aborting this process at this time.")
                    return

            if all([comicarr.CONFIG.CVINFO, comicarr.CONFIG.STORYARCDIR]):
                if not os.path.isfile(os.path.join(dstloc, "cvinfo")) or comicarr.CONFIG.CV_ONETIMER:
                    logger.fdebug("Generating cvinfo file for story-arc.")
                    with open(os.path.join(dstloc, "cvinfo"), "w") as text_file:
                        if any([ArcWatch[0]["StoryArcID"] == ArcWatch[0]["CV_ArcID"], ArcWatch[0]["CV_ArcID"] is None]):
                            cvinfo_arcid = ArcWatch[0]["StoryArcID"]
                        else:
                            cvinfo_arcid = ArcWatch[0]["CV_ArcID"]
                        text_file.write(str(cvinfo_arcid))


def _add_story_arc(
    arcid,
    arcrefresh=False,
    cvarcid=None,
    arclist=None,
    storyarcname=None,
    storyarcyear=None,
    storyarcpublisher=None,
    storyarcissues=None,
    desc=None,
    image=None,
):
    """Add or refresh a story arc from ComicVine.

    Extracted from WebInterface.addStoryArc — standalone, no CherryPy deps.
    """
    from comicarr import filechecker, mb

    module = "[STORY ARC]"
    iss_arcids = []

    if cvarcid is None:
        arc_chk = db.raw_select_all("SELECT * FROM storyarcs WHERE StoryArcID=?", [arcid])
    else:
        arc_chk = db.raw_select_all("SELECT * FROM storyarcs WHERE CV_ArcID=?", [cvarcid])

    if not arc_chk:
        if arcrefresh:
            logger.warn(
                module
                + " Unable to retrieve Story Arc ComicVine ID from the db. Unable to refresh Story Arc at this time."
            )
            return
        else:
            logger.fdebug(
                module + " No match in db based on ComicVine ID. Making sure and checking against Story Arc Name."
            )
            arc_chk = db.raw_select_all("SELECT * FROM storyarcs WHERE StoryArc=?", [storyarcname])
            if arc_chk:
                logger.warn(module + " " + storyarcname + " already exists on your Story Arc Watchlist!")
                return
    else:
        if arcrefresh:
            logger.info(
                module
                + "["
                + str(arcid)
                + "] Successfully found Story Arc ComicVine ID [4045-"
                + str(cvarcid)
                + "] within db. Preparing to refresh Story Arc."
            )
            for issarc in arc_chk:
                iss_arcids.append(
                    {"IssueArcID": issarc["IssueArcID"], "IssueID": issarc["IssueID"], "Manual": issarc["Manual"]}
                )
            arcinfo = mb.storyarcinfo(cvarcid)
            if len(arcinfo) > 1:
                arclist = arcinfo["arclist"]
            else:
                logger.warn(module + " Unable to retrieve issue details at this time. Something is probably wrong.")
                return

    # Ensure storyarcs cache dir exists
    if not os.path.isdir(os.path.join(comicarr.CONFIG.CACHE_DIR, "storyarcs")):
        checkdirectory = filechecker.validateAndCreateDirectory(
            os.path.join(comicarr.CONFIG.CACHE_DIR, "storyarcs"), True
        )
        if not checkdirectory:
            logger.warn("Error trying to validate/create cache storyarc directory. Aborting this process at this time.")
            return

    coverfile = os.path.join(comicarr.CONFIG.CACHE_DIR, "storyarcs", str(cvarcid) + "-banner.jpg")

    if comicarr.CONFIG.CVAPI_RATE is None or comicarr.CONFIG.CVAPI_RATE < 2:
        time.sleep(2)
    else:
        time.sleep(comicarr.CONFIG.CVAPI_RATE)

    logger.info("Attempting to retrieve the comic image for series")
    if arcrefresh:
        imageurl = arcinfo["comicimage"]
    else:
        imageurl = image

    logger.info("imageurl: %s" % imageurl)
    if imageurl and imageurl.startswith("http"):
        try:
            r = requests.get(
                imageurl, params=None, stream=True, verify=comicarr.CONFIG.CV_VERIFY, headers=comicarr.CV_HEADERS
            )
        except Exception:
            logger.warn("Unable to download image from CV URL link - possibly no arc picture is present: %s" % imageurl)
        else:
            logger.fdebug("comic image retrieval status code: %s" % r.status_code)

            if str(r.status_code) != "200":
                logger.warn(
                    "Unable to download image from CV URL link: %s [Status Code returned: %s]"
                    % (imageurl, r.status_code)
                )
            else:
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    from io import BytesIO

                    buf = BytesIO(r.content)
                    gzip.GzipFile(fileobj=buf)

                with open(coverfile, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:
                            f.write(chunk)
                            f.flush()

    arc_results = comicarr.cv.getComic(comicid=None, rtype="issue", arcid=arcid, arclist=arclist)
    logger.fdebug("%s Arcresults: %s" % (module, arc_results))
    logger.fdebug("%s Arclist: %s" % (module, arclist))
    if len(arc_results) > 0:
        issuedata = []
        if storyarcissues is None:
            storyarcissues = len(arc_results["issuechoice"])
        if arcid is None:
            storyarcid = str(random.randint(1000, 9999)) + str(storyarcissues)
        else:
            storyarcid = arcid
        n = 0
        cidlist = ""
        iscnt = int(storyarcissues)
        while n <= iscnt:
            try:
                arcval = arc_results["issuechoice"][n]
            except IndexError:
                break
            comicname = arcval["ComicName"]
            st_d = comicarr.filechecker.FileChecker(watchcomic=comicname)
            st_dyninfo = st_d.dynamic_replace(comicname)
            dynamic_name = re.sub(r"[\|\s]", "", st_dyninfo["mod_seriesname"].lower()).strip()

            issname = arcval["Issue_Name"]
            issid = str(arcval["IssueID"])
            comicid = str(arcval["ComicID"])
            cid_count = cidlist.count(comicid) + 1
            a_end = 0
            i = 0
            while i < cid_count:
                a = cidlist.find(comicid, a_end)
                a_end = cidlist.find("|", a)
                if a_end == -1:
                    a_end = len(cidlist)
                a_length = cidlist[a : a_end - 1]

                if a == -1 and len(a_length) != len(comicid):
                    if n == 0:
                        cidlist += str(comicid)
                    else:
                        cidlist += "|" + str(comicid)
                    break
                i += 1

            st_issueid = None
            manual_mod = None
            if arcrefresh:
                for aid in iss_arcids:
                    if aid["IssueID"] == issid:
                        st_issueid = aid["IssueArcID"]
                        manual_mod = aid["Manual"]
                        break

            if st_issueid is None:
                st_issueid = str(storyarcid) + "_" + str(random.randint(1000, 9999))
            issnum = arcval["Issue_Number"]
            issdate = str(arcval["Issue_Date"])
            digitaldate = str(arcval["Digital_Date"])
            storedate = str(arcval["Store_Date"])

            int_issnum = helpers.issuedigits(issnum)

            findorder = arclist.find(issid)
            if findorder != -1:
                ros = arclist.find("|", findorder + 1)
                if ros != -1:
                    roslen = arclist[findorder:ros]
                else:
                    roslen = arclist[findorder:]
                rosre = re.sub(issid, "", roslen)
                readingorder = int(re.sub(r"[\,\|]", "", rosre).strip())
            else:
                readingorder = 0
            logger.fdebug("[%s] issueid: %s - findorder#: %s" % (readingorder, issid, findorder))

            issuedata.append(
                {
                    "ComicID": comicid,
                    "IssueID": issid,
                    "StoryArcID": storyarcid,
                    "IssueArcID": st_issueid,
                    "ComicName": comicname,
                    "DynamicName": dynamic_name,
                    "IssueName": issname,
                    "Issue_Number": issnum,
                    "IssueDate": issdate,
                    "ReleaseDate": storedate,
                    "DigitalDate": digitaldate,
                    "ReadingOrder": readingorder,
                    "Int_IssueNumber": int_issnum,
                    "Manual": manual_mod,
                }
            )
            n += 1
        comicid_results = comicarr.cv.getComic(comicid=None, rtype="comicyears", comicidlist=cidlist)
        logger.fdebug("%s Initiating issue updating - just the info" % module)

        for AD in issuedata:
            seriesYear = "None"
            issuePublisher = "None"
            seriesVolume = "None"

            if AD["IssueName"] is None:
                IssueName = "None"
            else:
                IssueName = AD["IssueName"][:70]

            for cid in comicid_results:
                if cid["ComicID"] == AD["ComicID"]:
                    seriesYear = cid["SeriesYear"]
                    issuePublisher = cid["Publisher"]
                    seriesVolume = cid["Volume"]
                    bookType = cid["Type"]
                    seriesAliases = cid["Aliases"]
                    if storyarcpublisher is None:
                        storyarcpublisher = issuePublisher
                    break

            newCtrl = {"IssueID": AD["IssueID"], "StoryArcID": AD["StoryArcID"]}
            newVals = {
                "ComicID": AD["ComicID"],
                "IssueArcID": AD["IssueArcID"],
                "StoryArc": storyarcname,
                "ComicName": AD["ComicName"],
                "Volume": seriesVolume,
                "DynamicComicName": AD["DynamicName"],
                "IssueName": IssueName,
                "IssueNumber": AD["Issue_Number"],
                "Publisher": storyarcpublisher,
                "TotalIssues": storyarcissues,
                "ReadingOrder": AD["ReadingOrder"],
                "IssueDate": AD["IssueDate"],
                "ReleaseDate": AD["ReleaseDate"],
                "DigitalDate": AD["DigitalDate"],
                "SeriesYear": seriesYear,
                "IssuePublisher": issuePublisher,
                "CV_ArcID": arcid,
                "Int_IssueNumber": AD["Int_IssueNumber"],
                "Type": bookType,
                "Aliases": seriesAliases,
                "Manual": AD["Manual"],
            }

            db.upsert("storyarcs", newVals, newCtrl)

    # Run the Search for Watchlist matches now.
    logger.fdebug(module + " Now searching your watchlist for matches belonging to this story arc.")
    _arc_watchlist(storyarcid)
    if arcrefresh:
        logger.info("%s Successfully Refreshed %s" % (module, storyarcname))
        comicarr.GLOBAL_MESSAGES = {
            "status": "success",
            "event": "storyarc_added",
            "storyarcname": storyarcname,
            "storyarcid": storyarcid,
            "message": "Successfully refreshed %s" % storyarcname,
        }
    else:
        logger.info("%s Successfully Added %s" % (module, storyarcname))
        comicarr.GLOBAL_MESSAGES = {
            "status": "success",
            "event": "storyarc_added",
            "storyarcname": storyarcname,
            "storyarcid": storyarcid,
            "message": "Successfully added %s" % storyarcname,
        }


# ---------------------------------------------------------------------------
# Reading list
# ---------------------------------------------------------------------------


def get_readlist():
    """Get all reading list entries."""
    return arc_queries.get_readlist()


def add_to_readlist(issue_id):
    """Add an issue to the reading list."""
    from comicarr import readinglist

    read = readinglist.Readinglist(IssueID=issue_id)
    result = read.addtoreadlist()
    if result is not None:
        return {"success": result.get("status") == "success", "message": result.get("message", "")}
    return {"success": True}


def remove_from_readlist(issue_id):
    """Remove an issue from the reading list."""
    arc_queries.remove_readlist_issue(issue_id)
    logger.info("[DELETE-READ-ISSUE] Removed %s from Reading List" % issue_id)
    return {"success": True}


def clear_read_issues():
    """Remove all issues marked as Read from the reading list."""
    arc_queries.remove_all_read()
    logger.info("[DELETE-ALL-READ] Removed all Read issues from Reading List")
    return {"success": True}


# ---------------------------------------------------------------------------
# Upcoming
# ---------------------------------------------------------------------------


def get_upcoming(include_downloaded=False):
    """Get upcoming issues for the current week."""
    today = datetime.date.today()
    if today.strftime("%U") == "00":
        weekday = 0 if today.isoweekday() == 7 else today.isoweekday()
        sunday = today - datetime.timedelta(days=weekday)
        week = sunday.strftime("%U")
        year = sunday.strftime("%Y")
    else:
        week = today.strftime("%U")
        year = today.strftime("%Y")

    return arc_queries.get_upcoming(week, year, include_downloaded=include_downloaded)


# --- Extracted from helpers.py ---


def listStoryArcs():
    library = {}
    # Get Distinct CV Arc IDs
    from sqlalchemy import select

    stmt = select(storyarcs.c.CV_ArcID).distinct()
    rows = db.select_all(stmt)
    for row in rows:
        library[row["CV_ArcID"]] = {"comicid": row["CV_ArcID"]}
    return library


def manualArc(issueid, reading_order, storyarcid):
    from operator import itemgetter

    from sqlalchemy import select

    from comicarr.helpers import issuedigits

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


def updatearc_locs(storyarcid, arc_issues):
    from sqlalchemy import select

    from comicarr.helpers import file_ops, rename_param, renamefile_readingorder

    module = "[UPDATEARC-LOCS]"
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
                    except Exception:
                        continue

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
    from sqlalchemy import Integer, case, cast, func, select

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
    from comicarr.helpers import filesafe, replace_all

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
