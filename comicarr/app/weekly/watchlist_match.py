#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Match pull-list entries against watched series and set issue status.

Moved from ``comicarr/updater.py`` (#1461). ``weeklypull`` calls
``upcoming_update``, ``weekly_update`` and ``latest_update`` while it walks
the pull list.
"""

import datetime
import re

from sqlalchemy import func, select, text

from comicarr.app.common import configured as configured
from comicarr.app.core import db, logger, runtime
from comicarr.app.core.tables import annuals, comics, issues, upcoming, weekly
from comicarr.app.series import add, refresh
from comicarr.app.weekly import locg


def latest_update(ComicID, LatestIssue, LatestDate, ReleaseComicID=None):
    logger.fdebug(str(ComicID) + " - updating latest_date to : " + str(LatestDate))
    cid = ComicID
    if runtime.current().config.ANNUALS_ON:
        logger.fdebug("checking for releasecomicid %s reference in annuals table" % ReleaseComicID)
        db_check = db.select_one(select(annuals.c.ComicID).where(annuals.c.ReleaseComicID == ReleaseComicID))
        if not db_check:
            logger.fdebug("Annual has not been added yet to series")
        else:
            cid = db_check["ComicID"]
            logger.fdebug("ReleaseComicID found of %s linking to series %s" % (ReleaseComicID, cid))
            if cid != ComicID:
                cid = ComicID

    latestCTRLValueDict = {"ComicID": cid}
    newlatestDict = {
        "LatestIssue": str(LatestIssue),
        "intLatestIssue": configured.issuedigits(LatestIssue),
        "LatestDate": str(LatestDate),
    }
    db.upsert("comics", newlatestDict, latestCTRLValueDict)


def upcoming_update(
    ComicID,
    ComicName,
    IssueNumber,
    IssueDate,
    forcecheck=None,
    futurepull=None,
    altissuenumber=None,
    weekinfo=None,
    releasecomicid=None,
):
    dspComicName = ComicName
    if "annual" in ComicName.lower():
        year_check = re.findall(r"(\d{4})(?=[\s]|annual\b|$)", ComicName, flags=re.I)
        if year_check:
            ann_line = "%s annual" % year_check[0]
            logger.fdebug("ann_line: %s" % ann_line)
            adjComicName = re.sub(ann_line, "", ComicName, flags=re.I).strip()
        else:
            adjComicName = re.sub("\\bannual\\b", "", ComicName, flags=re.I).strip()
        logger.fdebug("annual detected - adjusting name to : %s" % adjComicName)
    else:
        adjComicName = ComicName
    controlValue = {"ComicID": ComicID}
    newValue = {
        "ComicName": adjComicName,
        "IssueNumber": str(IssueNumber),
        "DisplayComicName": dspComicName,
        "IssueDate": str(IssueDate),
    }

    if runtime.current().config.ALT_PULL != 2 or runtime.current().pullbyfile is True:
        lastupdatechk = db.select_one(select(comics).where(comics.c.ComicID == ComicID))
        if lastupdatechk is None:
            pass
        else:
            c_date = lastupdatechk["LastUpdated"]
            if c_date is None:
                logger.error(
                    lastupdatechk["ComicName"]
                    + " failed during a previous add /refresh. Please either delete and readd the series, or try a refresh of the series."
                )
                return
            c_obj_date = datetime.datetime.strptime(c_date, "%Y-%m-%d %H:%M:%S")
            n_date = datetime.datetime.now()
            absdiff = abs(n_date - c_obj_date)
            hours = (absdiff.days * 24 * 60 * 60 + absdiff.seconds) / 3600.0
    else:
        if runtime.current().config.PULL_REFRESH is None:
            runtime.current().config.PULL_REFRESH = datetime.datetime.today().replace(second=0, microsecond=0)
        logger.fdebug("pull_refresh: " + str(runtime.current().config.PULL_REFRESH))
        c_obj_date = datetime.datetime.strptime(str(runtime.current().config.PULL_REFRESH), "%Y-%m-%d %H:%M:%S")
        n_date = datetime.datetime.now()
        absdiff = abs(n_date - c_obj_date)
        hours = (absdiff.days * 24 * 60 * 60 + absdiff.seconds) / 3600.0

    if any(["annual" in ComicName.lower(), "special" in ComicName.lower()]):
        if runtime.current().config.ANNUALS_ON:
            logger.info("checking: " + str(ComicID) + " -- issue#: " + str(IssueNumber))
            issuechk = db.select_one(
                select(annuals).where((annuals.c.ReleaseComicID == ComicID) & (annuals.c.Issue_Number == IssueNumber))
            )
        else:
            logger.fdebug(
                "Non-standard issue detected (annual/special/etc), but Annual Integration is not enabled. Ignoring result."
            )
            return
    else:
        issuechk = db.select_one(
            select(issues).where((issues.c.ComicID == ComicID) & (issues.c.Issue_Number == IssueNumber))
        )
    if issuechk is None and altissuenumber is not None:
        logger.info("altissuenumber is : " + str(altissuenumber))
        issuechk = db.select_one(
            select(issues).where(
                (issues.c.ComicID == ComicID) & (issues.c.Int_IssueNumber == configured.issuedigits(altissuenumber))
            )
        )

    if issuechk is not None:
        if issuechk["Issue_Number"] == IssueNumber or issuechk["Issue_Number"] == altissuenumber:
            og_status = issuechk["Status"]
            wk_info = configured.weekly_info(weekinfo["weeknumber"], weekinfo["year"])
            if all([issuechk["ReleaseDate"] is not None, issuechk["ReleaseDate"] != "0000-00-00"]):
                issue_checkdate = issuechk["ReleaseDate"]
            elif all([issuechk["DigitalDate"] is not None, issuechk["DigitalDate"] != "0000-00-00"]):
                issue_checkdate = issuechk["DigitalDate"]
            else:
                issue_checkdate = issuechk["IssueDate"]

            wkds = datetime.datetime.strptime(wk_info["startweek"], "%B %d, %Y")
            wkstr = wkds - datetime.timedelta(days=2)
            wk_start = wkstr.strftime("%Y-%m-%d")

            wkde = datetime.datetime.strptime(wk_info["endweek"], "%B %d, %Y")
            wkend = wkde + datetime.timedelta(days=2)
            wk_end = wkend.strftime("%Y-%m-%d")

            if issue_checkdate != "0000-00-00" and not (
                re.sub("-", "", wk_end) >= re.sub("-", "", issue_checkdate) >= re.sub("-", "", wk_start)
            ):
                logger.info(
                    "[IssueDate:%s] is not within the range of [Pulldate:%s - %s]. Incorrect match being imposed by WS - please log an issue if this has not fixed itself within a few hours"
                    % (issue_checkdate, wk_info["startweek"], wk_info["endweek"])
                )
                if IssueNumber is not None:
                    presentline = "%s #%s" % (ComicName, IssueNumber)
                else:
                    presentline = "%s" % (ComicName)
                logger.info("[%s][comicid: %s][issueid: %s] " % (presentline, ComicID, issuechk["IssueID"]))
                if issuechk["Status"] == "Wanted":
                    control = {"IssueID": issuechk["IssueID"]}
                    newchk = {"Status": "Skipped"}
                    db.upsert("issues", newchk, control)
                return {"Status": "incorrect_match", "ComicID": ComicID, "IssueID": issuechk["IssueID"]}
            else:
                whackness = refresh.refresh_series_metadata([ComicID], calledfrom="weekly")
                if any([whackness, og_status is None]):
                    if any(
                        [
                            issuechk["Status"] == "Downloaded",
                            issuechk["Status"] == "Archived",
                            issuechk["Status"] == "Snatched",
                        ]
                    ):
                        logger.fdebug(
                            "Forcibly maintaining status of : "
                            + og_status
                            + " for #"
                            + issuechk["Issue_Number"]
                            + " to ensure integrity."
                        )
                    logger.fdebug(
                        "Comic series has an incorrect total count. Forcily refreshing series to ensure data is current."
                    )
                    refresh.refresh_series_metadata([ComicID])
                    issuechk = db.select_one(
                        select(issues).where(
                            (issues.c.ComicID == ComicID)
                            & (issues.c.Int_IssueNumber == configured.issuedigits(IssueNumber))
                        )
                    )
                    if issuechk["Status"] != og_status and (
                        issuechk["Status"] != "Downloaded"
                        or issuechk["Status"] != "Archived"
                        or issuechk["Status"] != "Snatched"
                    ):
                        logger.fdebug(
                            "Forcibly changing status of %s back to %s for #%s to stop repeated downloads."
                            % (issuechk["Status"], og_status, issuechk["Issue_Number"])
                        )
                    else:
                        logger.fdebug(
                            "[%s] / [%s] Status has not changed during refresh or is marked as being Wanted/Skipped correctly."
                            % (issuechk["Status"], og_status)
                        )
                        og_status = issuechk["Status"]
                else:
                    logger.fdebug("Comic series already up-to-date ... no need to refresh at this time.")

                logger.fdebug(
                    "Available to be marked for download - checking..."
                    + adjComicName
                    + " Issue: "
                    + str(issuechk["Issue_Number"])
                )
                logger.fdebug("...Existing status: " + og_status)
                control = {"IssueID": issuechk["IssueID"]}
                newValue["IssueID"] = issuechk["IssueID"]
                if og_status == "Snatched":
                    values = {"Status": "Snatched"}
                    newValue["Status"] = "Snatched"
                elif og_status == "Downloaded":
                    values = {"Status": "Downloaded"}
                    newValue["Status"] = "Downloaded"

                elif og_status == "Wanted":
                    values = {"Status": "Wanted"}
                    newValue["Status"] = "Wanted"
                elif og_status == "Archived":
                    values = {"Status": "Archived"}
                    newValue["Status"] = "Archived"
                elif og_status == "Failed":
                    if runtime.current().config.FAILED_DOWNLOAD_HANDLING:
                        if runtime.current().config.FAILED_AUTO:
                            values = {"Status": "Wanted"}
                            newValue["Status"] = "Wanted"
                        else:
                            values = {"Status": "Failed"}
                            newValue["Status"] = "Failed"
                    else:
                        values = {"Status": "Skipped"}
                        newValue["Status"] = "Skipped"
                else:
                    values = {"Status": "Skipped"}
                    newValue["Status"] = "Skipped"
        else:
            logger.fdebug("Issues do not match for some reason...weekly new issue: %s" % IssueNumber)
            return

    if issuechk is None:
        if futurepull is None:
            og_status = None
            if runtime.current().config.ALT_PULL != 2 or runtime.current().pullbyfile is True:
                logger.fdebug(
                    adjComicName
                    + " Issue: "
                    + str(IssueNumber)
                    + " not present in listings to mark for download...updating comic and adding to Upcoming Wanted Releases."
                )
                upco_results = db.select_one(
                    select(func.count()).select_from(upcoming).where(upcoming.c.ComicID == ComicID)
                )
                upco_iss = list(upco_results.values())[0] if upco_results else 0
                if int(upco_iss) > 0:
                    newKey = {"ComicID": ComicID}
                    newVal = {"not_updated_db": str(upco_iss)}
                    db.upsert("comics", newVal, newKey)
                elif int(upco_iss) <= 0 and lastupdatechk["not_updated_db"]:
                    newKey = {"ComicID": ComicID}
                    newVal = {"not_updated_db": ""}
                    db.upsert("comics", newVal, newKey)

                if hours > 5 or forcecheck == "yes":
                    logger.fdebug("Now Refreshing comic " + ComicName + " to make sure it is up-to-date")
                    if ComicID[:1] == "G":
                        logger.warn(
                            "[GCD] %s was added from the Grand Comics Database, which Comicarr can no longer read."
                            % ComicID
                        )
                    else:
                        add.update_issue_data(ComicID, ComicName, calledfrom="weeklycheck")
                else:
                    logger.fdebug(
                        "It has not been longer than 5 hours since we last did this...we will wait so we do not hammer things."
                    )
            else:
                logger.fdebug(
                    "[WEEKLY-PULL] Walksoftly has been enabled. ComicID/IssueID control given to the ninja to monitor."
                )
                logger.fdebug("hours: " + str(hours) + " -- forcecheck: " + str(forcecheck))
                if hours > 2 or forcecheck == "yes":
                    logger.fdebug("weekinfo:" + str(weekinfo))
                    runtime.current().config.PULL_REFRESH = datetime.datetime.today().replace(second=0, microsecond=0)
                    locg.locg(weeknumber=str(weekinfo["weeknumber"]), year=str(weekinfo["year"]))

            logger.fdebug("linking ComicID to Pull-list to reflect status.")
            downstats = {"ComicID": ComicID, "IssueID": None, "Status": None}
            return downstats
        else:
            with db.get_engine().begin() as conn:
                result = conn.execute(
                    text("UPDATE future SET Status=:status WHERE ComicID=:cid"),
                    {"status": "Wanted", "cid": ComicID},
                )
                if result.rowcount == 0:
                    conn.execute(
                        text("INSERT INTO future (ComicID, Status) VALUES (:cid, :status)"),
                        {"cid": ComicID, "status": "Wanted"},
                    )
            return

    if runtime.current().config.AUTOWANT_UPCOMING:
        if og_status is None:
            newValue["Status"] = "Wanted"
            logger.fdebug(
                "...Changing Status to Wanted and throwing it in the Upcoming section since it is not published yet."
            )
        elif og_status == "Skipped":
            newValue["Status"] = "Wanted"
            values = {"Status": "Wanted"}
            logger.fdebug("...New status of Wanted")
        elif og_status == "Wanted":
            logger.fdebug("...Status already Wanted .. not changing.")
        else:
            logger.fdebug("...Already have issue - keeping existing status of : " + og_status)

    if issuechk is None:
        db.upsert("upcoming", newValue, controlValue)
        logger.fdebug("updating Pull-list to reflect status.")
        downstats = {"Status": newValue["Status"], "ComicID": ComicID, "IssueID": None}
        return downstats

    else:
        logger.fdebug("--attempt to find errant adds to Wanted list")
        logger.fdebug("UpcomingNewValue: " + str(newValue))
        logger.fdebug("UpcomingcontrolValue: " + str(controlValue))
        if issuechk["IssueDate"] == "0000-00-00" and newValue["IssueDate"] != "0000-00-00":
            logger.fdebug("Found a 0000-00-00 issue - force updating series to try and get it proper.")
            dateVal = {
                "IssueDate": newValue["IssueDate"],
                "ComicName": issuechk["ComicName"],
                "Status": newValue["Status"],
                "IssueNumber": issuechk["Issue_Number"],
            }
            logger.fdebug(
                "updating date in upcoming table to : " + str(newValue["IssueDate"]) + "[" + newValue["Status"] + "]"
            )
            logger.fdebug("ComicID:" + str(controlValue))
            db.upsert("upcoming", dateVal, controlValue)
            logger.fdebug(
                "Temporarily putting the Issue Date for "
                + str(issuechk["Issue_Number"])
                + " to "
                + str(newValue["IssueDate"])
            )
            values = {"IssueDate": newValue["IssueDate"]}

        if any(["annual" in ComicName.lower(), "special" in ComicName.lower()]):
            db.upsert("annuals", values, control)
        else:
            db.upsert("issues", values, control)

        if any(
            [
                og_status == "Downloaded",
                og_status == "Archived",
                og_status == "Snatched",
                og_status == "Wanted",
                newValue["Status"] == "Wanted",
            ]
        ):
            logger.fdebug("updating Pull-list to reflect status change: " + og_status + "[" + newValue["Status"] + "]")
            if og_status != "Skipped":
                downstats = {"Status": og_status, "ComicID": issuechk["ComicID"], "IssueID": issuechk["IssueID"]}
            else:
                downstats = {
                    "Status": newValue["Status"],
                    "ComicID": issuechk["ComicID"],
                    "IssueID": issuechk["IssueID"],
                }
            return downstats


def weekly_update(ComicName, IssueNumber, CStatus, CID, weeknumber, year, altissuenumber=None):
    logger.fdebug(
        "Weekly Update for week "
        + str(weeknumber)
        + "-"
        + str(year)
        + " : "
        + str(ComicName)
        + " #"
        + str(IssueNumber)
        + " to a status of "
        + str(CStatus)
    )

    if altissuenumber:
        logger.fdebug(
            "weekly_update of table : "
            + str(ComicName)
            + " (Alternate Issue #):"
            + str(altissuenumber)
            + " to a status of "
            + str(CStatus)
        )

    issuecheck = db.select_one(
        select(weekly).where(
            (weekly.c.COMIC == ComicName)
            & (weekly.c.ISSUE == IssueNumber)
            & (weekly.c.weeknumber == int(weeknumber))
            & (weekly.c.year == year)
        )
    )

    if issuecheck is not None:
        controlValue = {"COMIC": str(ComicName), "ISSUE": str(IssueNumber), "weeknumber": int(weeknumber), "year": year}

        logger.info("controlValue:" + str(controlValue))
        try:
            if CID["IssueID"]:
                cidissueid = CID["IssueID"]
            else:
                cidissueid = None
        except Exception:
            cidissueid = None

        logger.info("CStatus:" + str(CStatus))

        if CStatus:
            newValue = {"STATUS": CStatus}

        else:
            if runtime.current().config.AUTOWANT_UPCOMING:
                newValue = {"STATUS": "Wanted"}
            else:
                newValue = {"STATUS": "Skipped"}

        newValue["ComicID"] = CID["ComicID"]
        newValue["IssueID"] = cidissueid

        logger.info("newValue:" + str(newValue))

        db.upsert("weekly", newValue, controlValue)
