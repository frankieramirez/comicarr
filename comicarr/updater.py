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
import operator
import queue as queue_module
import re
import sys
import time
from collections.abc import Mapping

from sqlalchemy import select

import comicarr
from comicarr import db, helpers, logger
from comicarr.app.common import series_kind
from comicarr.app.metadata import cv, series_metadata
from comicarr.app.series import rescan
from comicarr.tables import (
    annuals,
    comics,
    issues,
    jobhistory,
)


def addvialist(queue, ledger=None, maintenance=None):
    from comicarr.app.acquisition.maintenance import MaintenanceBlocked, MaintenanceController, maintenance_retry_delay
    from comicarr.app.acquisition.models import ItemOutcome
    from comicarr.app.acquisition.runs import RunLedger

    worker_maintenance = maintenance
    while True:
        try:
            item = queue.get(timeout=1)
        except queue_module.Empty:
            from comicarr import importer

            if importer.refresh_worker_should_retire(queue):
                break
            continue

        command_ledger = None
        run_id = None
        comicid = None
        try:
            if item == "exit":
                break
            if not isinstance(item, Mapping):
                raise ValueError("refresh command must be an object")

            values = {str(key).lower(): value for key, value in item.items()}
            comicid = values.get("comicid")
            if comicid in (None, ""):
                raise ValueError("refresh command is missing comicid")
            comicname = values.get("comicname")
            seriesyear = values.get("seriesyear")
            display_year = seriesyear if seriesyear not in (None, "") else "Unknown"
            r_mode = values.get("r_mode")
            run_id = values.get("run_id")

            if run_id:
                command_ledger = ledger or RunLedger()
                ledger_item = command_ledger.get_item(run_id, "series", comicid)
                if ledger_item is None:
                    raise ValueError("refresh command references an unknown durable obligation")
                if ItemOutcome(ledger_item["state"]).terminal:
                    continue
                if ledger_item["state"] == ItemOutcome.RUNNING.value:
                    continue

            if r_mode is None and comicarr.IMPORTLOCK:
                queue.put(item)
                logger.info("[MASS-REFRESH] Import is active; deliberately requeued %s before claim" % comicid)
                time.sleep(1)
                continue

            if command_ledger and run_id:
                if not command_ledger.claim_item(run_id, "series", comicid):
                    continue

            if worker_maintenance is None:
                worker_maintenance = MaintenanceController()
            lease_context = worker_maintenance.lease(
                "refresh-worker",
                work_kind="metadata_refresh",
                entity_type="series",
                entity_id=comicid,
            )
            with lease_context as lease:
                time.sleep(3)
                if r_mode == "updateissuedata":
                    logger.info(
                        "[MASS-REFRESH][WEEKLY-UPDATER] Now updating series data for %s (%s) [%s] "
                        % (comicname, display_year, comicid)
                    )
                    worker_maintenance.assert_lease_current(lease)
                    comicarr.importer.updateissuedata(
                        comicid,
                        comicname,
                        calledfrom=values["calledfrom"],
                        serieslast_updated=values["serieslast_updated"],
                    )
                elif r_mode == "manualannual":
                    logger.info(
                        "[MASS-REFRESH][WEEKLY-UPDATER][AnnualID:%s] Now updating series data for %s (%s) [%s] "
                        % (values["manual_comicid"], comicname, display_year, comicid)
                    )
                    worker_maintenance.assert_lease_current(lease)
                    comicarr.importer.manualAnnual(
                        values["manual_comicid"],
                        comicname,
                        comicyear=seriesyear,
                        comicid=comicid,
                        forceadd=True,
                        serieslast_updated=values["serieslast_updated"],
                    )
                else:
                    logger.info(
                        "[MASS-REFRESH][1/%s] Now refreshing %s (%s) [%s] "
                        % (queue.qsize() + 1, comicname, display_year, comicid)
                    )
                    worker_maintenance.assert_lease_current(lease)
                    dbUpdate([comicid], calledfrom="refresh")
            if command_ledger and run_id:
                command_ledger.record_outcome(run_id, "series", comicid, ItemOutcome.SUCCEEDED)
        except Exception as e:
            if isinstance(e, MaintenanceBlocked):
                requeued = None
                if command_ledger and run_id and comicid is not None:
                    requeued = command_ledger.record_requeue(run_id, "series", comicid, reason=str(e))
                queue.put(item)
                time.sleep(maintenance_retry_delay((requeued or {}).get("attempt_count", 1)))
                continue
            if command_ledger and run_id and comicid is not None:
                command_ledger.record_outcome(run_id, "series", comicid, ItemOutcome.FAILED, reason=str(e))
            logger.error("[MASS-REFRESH] Refresh command failed; continuing worker: %s" % e)
        finally:
            try:
                queue.task_done()
            except (AttributeError, ValueError):
                pass
    return False


def dbUpdate(ComicIDList=None, calledfrom=None, sched=False):
    if comicarr.IMPORTLOCK:
        logger.info("Import is currently running - deferring this until the next scheduled run sequence.")
        return
    if ComicIDList is None:
        if comicarr.CONFIG.UPDATE_ENDED:
            logger.info(
                "Updating only Continuing Series (option enabled) - this might cause problems with the pull-list matching for rebooted series"
            )
            comiclist = []
            stmt = (
                select(
                    comics.c.LatestDate,
                    comics.c.ComicPublished,
                    comics.c.ForceContinuing,
                    comics.c.NewPublish,
                    comics.c.LastUpdated,
                    comics.c.ComicID,
                    comics.c.ComicName,
                    comics.c.Corrected_SeriesYear,
                    comics.c.Corrected_Type,
                    comics.c.ContentType,
                    comics.c.ComicYear,
                    comics.c.Status,
                )
                .where((comics.c.Status == "Active") | (comics.c.Status == "Loading"))
                .order_by(comics.c.LastUpdated.desc(), comics.c.LatestDate.asc())
            )
            completelist = db.select_all(stmt)
            for comlist in completelist:
                if comlist["LatestDate"] is None:
                    recentstatus = "Loading"
                elif (
                    comlist["ComicPublished"] is None
                    or comlist["ComicPublished"] == ""
                    or comlist["LatestDate"] is None
                ):
                    recentstatus = "Unknown"
                elif comlist["ForceContinuing"] == 1:
                    recentstatus = "Continuing"
                elif "present" in comlist["ComicPublished"].lower() or (helpers.today()[:4] in comlist["LatestDate"]):
                    latestdate = comlist["LatestDate"]
                    c_date = datetime.date(int(latestdate[:4]), int(latestdate[5:7]), 1)
                    n_date = datetime.date.today()
                    recentchk = (n_date - c_date).days
                    if comlist["NewPublish"]:
                        recentstatus = "Continuing"
                    else:
                        if recentchk < 55:
                            recentstatus = "Continuing"
                        else:
                            recentstatus = "Ended"
                else:
                    recentstatus = "Ended"

                if recentstatus == "Continuing":
                    comiclist.append(
                        {
                            "LatestDate": comlist["LatestDate"],
                            "LastUpdated": comlist["LastUpdated"],
                            "ComicID": comlist["ComicID"],
                            "ComicName": comlist["ComicName"],
                            "ComicYear": comlist["ComicYear"],
                            "Status": comlist["Status"],
                            "Corrected_SeriesYear": comlist["Corrected_SeriesYear"],
                            "Corrected_Type": comlist["Corrected_Type"],
                            "ContentType": comlist["ContentType"],
                        }
                    )

        else:
            stmt = (
                select(
                    comics.c.LatestDate,
                    comics.c.LastUpdated,
                    comics.c.ComicID,
                    comics.c.ComicName,
                    comics.c.ComicYear,
                    comics.c.Corrected_SeriesYear,
                    comics.c.Corrected_Type,
                    comics.c.ContentType,
                    comics.c.Status,
                )
                .where((comics.c.Status == "Active") | (comics.c.Status == "Loading"))
                .order_by(comics.c.LastUpdated.desc(), comics.c.LatestDate.asc())
            )
            comiclist = db.select_all(stmt)
    else:
        comiclisting = ComicIDList
        stmt = (
            select(
                comics.c.ComicID,
                comics.c.ComicName,
                comics.c.ComicYear,
                comics.c.Corrected_SeriesYear,
                comics.c.Corrected_Type,
                comics.c.ContentType,
                comics.c.LastUpdated,
                comics.c.Status,
            )
            .where(comics.c.ComicID.in_(comiclisting))
            .order_by(comics.c.LastUpdated.desc(), comics.c.LatestDate.asc())
        )
        comiclist = db.select_all(stmt)

    if all([sched is False, calledfrom is None]):
        logger.info("Starting update for %i active comics" % len(comiclist))

    cnt = 1

    if sched is True:
        logger.fdebug(
            "Refresh sequence set to fire every %s minutes for %s day(s)"
            % (comicarr.CONFIG.DBUPDATE_INTERVAL, comicarr.CONFIG.REFRESH_CACHE)
        )

    for comic in sorted(
        comiclist, key=lambda x: x if isinstance(operator.itemgetter("LastUpdated"), str) else "", reverse=True
    ):
        dspyear = comic["ComicYear"]
        csyear = None
        fixed_type = None

        if comic["Corrected_Type"] is not None:
            fixed_type = comic["Corrected_Type"]

        if comic["Corrected_SeriesYear"] is not None:
            csyear = comic["Corrected_SeriesYear"]
            if int(csyear) != int(comic["ComicYear"]):
                comic["ComicYear"] = csyear
                dspyear = csyear

        if ComicIDList is None:
            ComicID = comic["ComicID"]
            ComicName = comic["ComicName"]
            c_date = comic["LastUpdated"]
            if c_date is None:
                logger.error(
                    ComicName
                    + " failed during a previous add /refresh as it has no Last Update timestamp. Forcing refresh now."
                )
            else:
                c_obj_date = datetime.datetime.strptime(c_date, "%Y-%m-%d %H:%M:%S")
                n_date = datetime.datetime.now()
                absdiff = abs(n_date - c_obj_date)
                hours = (absdiff.days * 24 * 60 * 60 + absdiff.seconds) / 3600.0
                cache_hours = comicarr.CONFIG.REFRESH_CACHE * 24
                if hours < cache_hours:
                    cnt += 1
                    continue
            logger.info("[%s/%s] Refreshing :%s (%s) [%s]" % (cnt, len(comiclist), ComicName, dspyear, ComicID))
        else:
            ComicID = comic["ComicID"]
            ComicName = comic["ComicName"]
            logger.info("Refreshing/Updating: %s (%s) [%s]" % (ComicName, dspyear, ComicID))

        pause_status = False
        if comic["Status"] == "Paused":
            pause_status = True

        lastupdated = "0000-00-00"
        if comic["LastUpdated"] is not None:
            lastupdated = datetime.datetime.strptime(comic["LastUpdated"], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")

        mismatch = "no"
        if series_kind.provider_of(ComicID) in series_kind.MANGA_PROVIDERS or series_kind.is_manga(comic):
            chkstatus = comicarr.importer.addComictoDB(ComicID, mismatch)
            if chkstatus["status"] != "complete":
                logger.warn(
                    "There was an error when refreshing this series - Make sure directories are writable/exist, and check the logs for any errors/problems."
                )
                try:
                    from comicarr.app.activity.producers import emit_series_activity

                    emit_series_activity(
                        "refresh",
                        "failed",
                        ComicID,
                        comicname=ComicName,
                        seriesyear=dspyear,
                        reason_code="refresh_failed",
                    )
                except Exception as emit_err:
                    logger.fdebug("[ACTIVITY] refresh.failed emit skipped: %s" % emit_err)
                return
            try:
                rescan.rescan_series(ComicID)
            except Exception as e:
                logger.error("[MANGA-REFRESH] folder rescan failed for %s: %s" % (ComicID, e))
                try:
                    from comicarr.app.activity.producers import emit_series_activity
                    from comicarr.app.common.redaction import redact_sensitive_text

                    emit_series_activity(
                        "refresh",
                        "failed",
                        ComicID,
                        comicname=ComicName,
                        seriesyear=dspyear,
                        reason_code="rescan_failed",
                        reason_detail=redact_sensitive_text(str(e))[:1000],
                    )
                except Exception as emit_err:
                    logger.fdebug("[ACTIVITY] refresh.failed emit skipped: %s" % emit_err)
                return
        elif ComicID[:1] == "G":
            # Grand Comics Database series can no longer refresh: the GCD
            # scraper was removed with the site's search (ADR-0007, #1404).
            logger.warn(
                "[GCD] %s was added from the Grand Comics Database, which Comicarr can no longer read. "
                "Add the series again from ComicVine to keep it up to date." % ComicID
            )
            return
        else:
            if comicarr.CONFIG.CV_ONETIMER == 1:
                logger.fdebug("CV_OneTimer option enabled...")
                logger.fdebug("Gathering the status of all issues for the series.")
                iss_list = db.select_all(select(issues).where(issues.c.ComicID == ComicID))

                if not iss_list:
                    logger.fdebug("No issue data available. This is Whack.")
                    whack = True
                else:
                    logger.fdebug("Checking how out of whack the series is.")
                    whack = helpers.havetotals(refreshit=ComicID)

                if calledfrom == "weekly":
                    if whack:
                        logger.info(
                            "Series is out of whack. Forcibly refreshing series to ensure everything is in order."
                        )
                        return True
                    else:
                        return False

                annload = []

                if comicarr.CONFIG.ANNUALS_ON:
                    annual_load = db.select_all(
                        select(annuals).where((annuals.c.ComicID == ComicID) & (annuals.c.Deleted != 1))
                    )
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
                    iss_list += annual_load
                logger.fdebug("Refreshing the series and pulling in new data using only CV.")

                lastissuedate = db.select_one(
                    select(issues.c.IssueDate, issues.c.ReleaseDate)
                    .where(issues.c.ComicID == ComicID)
                    .order_by(issues.c.IssueDate.desc())
                    .limit(1)
                )
                if not lastissuedate:
                    last_issuedate = "0000-00-00"
                else:
                    last_issuedate = lastissuedate["IssueDate"]
                    if any([last_issuedate is None, last_issuedate == "0000-00-00"]):
                        last_issuedate = lastissuedate["ReleaseDate"]

                if not whack:
                    chkstatus = comicarr.importer.addComictoDB(
                        ComicID, mismatch, calledfrom="dbupdate", annload=annload, csyear=csyear, fixed_type=fixed_type
                    )
                    if chkstatus["status"] == "complete":
                        logger.fdebug("Deleting all old issue data to make sure new data is clean...")
                        with db.get_engine().begin() as conn:
                            conn.execute(issues.delete().where(issues.c.ComicID == ComicID))
                            conn.execute(annuals.delete().where(annuals.c.ComicID == ComicID))
                        comicarr.importer.issue_collection(
                            chkstatus["issuedata"], nostatus="True", serieslast_updated=lastupdated
                        )
                        if chkstatus["anndata"] is not None:
                            comicarr.importer.manualAnnual(annchk=chkstatus["anndata"])
                    else:
                        logger.warn(
                            "There was an error when refreshing this series - Make sure directories are writable/exist, and check the logs for any errors/problems."
                        )
                        try:
                            from comicarr.app.activity.producers import emit_series_activity

                            emit_series_activity(
                                "refresh",
                                "failed",
                                ComicID,
                                comicname=ComicName,
                                seriesyear=dspyear,
                                reason_code="refresh_failed",
                            )
                        except Exception as emit_err:
                            logger.fdebug("[ACTIVITY] refresh.failed emit skipped: %s" % emit_err)
                        return

                    issues_new = db.select_all(select(issues).where(issues.c.ComicID == ComicID))
                    ann_list = []
                    if comicarr.CONFIG.ANNUALS_ON:
                        annuals_list = db.select_all(select(annuals).where(annuals.c.ComicID == ComicID))
                        ann_list += annuals_list
                        issues_new += annuals_list

                    logger.fdebug("Attempting to put the Status' back how they were.")
                    icount = 0
                    fndissue = []
                    nowdate = datetime.datetime.now()
                    now_week = datetime.datetime.strftime(nowdate, "%Y%U")
                    for issue in iss_list:
                        for issuenew in issues_new:
                            try:
                                if issuenew["IssueID"] == issue["IssueID"]:
                                    newVAL = None
                                    ctrlVAL = {"IssueID": issue["IssueID"]}
                                    if any(
                                        [issuenew["Status"] != issue["Status"], issue["IssueDate_Edit"] is not None]
                                    ):
                                        if issuenew["Status"] is None and (
                                            issue["Status"] == "Downloaded" or issue["Status"] == "Archived"
                                        ):
                                            newVAL = {
                                                "Location": issue["Location"],
                                                "ComicSize": issue["ComicSize"],
                                                "Status": issue["Status"],
                                            }
                                        elif issuenew["Status"] == "Downloaded" or issue["Status"] == "Snatched":
                                            newVAL = {"Location": issue["Location"], "ComicSize": issue["ComicSize"]}
                                            if issuenew["Status"] == "Downloaded":
                                                newVAL["Status"] = issuenew["Status"]
                                            else:
                                                newVAL["Status"] = issue["Status"]

                                        elif issue["Status"] == "Archived":
                                            newVAL = {
                                                "Status": issue["Status"],
                                                "Location": issue["Location"],
                                                "ComicSize": issue["ComicSize"],
                                            }
                                        else:
                                            newVAL = {"Status": issue["Status"]}

                                    if all([issuenew["Status"] is None, issue["Status"] == "Skipped"]):
                                        if issuenew["ReleaseDate"] == "0000-00-00":
                                            dk = re.sub("-", "", issue["IssueDate"]).strip()
                                        else:
                                            dk = re.sub("-", "", issuenew["ReleaseDate"]).strip()
                                        if dk == "00000000":
                                            logger.warn(
                                                "Issue Data is invalid for Issue Number %s. Marking this issue as Skipped"
                                                % issue["Issue_Number"]
                                            )
                                            newVAL = {"Status": "Skipped"}
                                        else:
                                            datechk = datetime.datetime.strptime(dk, "%Y%m%d")
                                            issue_week = datetime.datetime.strftime(datechk, "%Y%U")
                                            if pause_status is True:
                                                newVAL = {"Status": issue["Status"]}
                                                logger.fdebug(
                                                    "[PAUSE-CATCH-STATUS] Series is Paused - keeping status of %s for #%s"
                                                    % (issue["Status"], issue["Issue_Number"])
                                                )
                                            else:
                                                if comicarr.CONFIG.AUTOWANT_ALL:
                                                    newVAL = {"Status": "Wanted"}
                                                elif lastupdated is None:
                                                    logger.fdebug("serieslast_updated is None. Setting to Skipped")
                                                    newVAL = {"Status": "Skipped"}
                                                elif issue_week >= now_week and comicarr.CONFIG.AUTOWANT_UPCOMING:
                                                    logger.fdebug(
                                                        "Issue_week: %s -- now_week: %s" % (issue_week, now_week)
                                                    )
                                                    logger.fdebug(
                                                        "Issue date [%s] is in/beyond current week - marking as Wanted."
                                                        % dk
                                                    )
                                                    newVAL = {"Status": "Wanted"}
                                                elif all(
                                                    [
                                                        int(re.sub("-", "", lastupdated).strip()) < int(dk),
                                                        comicarr.CONFIG.AUTOWANT_UPCOMING is True,
                                                    ]
                                                ):
                                                    logger.info(
                                                        "Autowant upcoming triggered for issue #%s"
                                                        % issuenew["Issue_Number"]
                                                    )
                                                    newVAL = {"Status": "Wanted"}
                                                else:
                                                    newVAL = {"Status": "Skipped"}

                                    if newVAL is not None:
                                        if issue["IssueDate_Edit"] is not None:
                                            if issue["IssueDate_Edit"] == "0000-00-00":
                                                logger.fdebug(
                                                    "[#%s] Reverting previously edited Issue Date and replacing with CV Issue Date."
                                                    % issue["Issue_Number"]
                                                )
                                                newVAL["IssueDate"] = issue["IssueDate"]
                                                newVAL["IssueDate_Edit"] = None
                                            else:
                                                if issue["IssueDate_Edit"].endswith("s"):
                                                    issue_type = "store"
                                                    newVAL["ReleaseDate"] = issue["ReleaseDate"]
                                                else:
                                                    issue_type = "cover"
                                                    newVAL["IssueDate"] = issue["IssueDate"]
                                                logger.fdebug(
                                                    "[#%s] Detected manually edited %s Issue Date."
                                                    % (issue_type, issue["Issue_Number"])
                                                )
                                                logger.fdebug(
                                                    "new value : "
                                                    + str(issue["IssueDate"])
                                                    + " ... cv value : "
                                                    + str(issuenew["IssueDate"])
                                                )
                                                newVAL["IssueDate_Edit"] = issue["IssueDate_Edit"]

                                        if any(d["IssueID"] == str(issue["IssueID"]) for d in ann_list):
                                            logger.fdebug(
                                                "annual detected for "
                                                + str(issue["IssueID"])
                                                + " #: "
                                                + str(issue["Issue_Number"])
                                            )
                                            db.upsert("annuals", newVAL, ctrlVAL)
                                        else:
                                            db.upsert("issues", newVAL, ctrlVAL)
                                        fndissue.append({"IssueID": issue["IssueID"]})
                                        icount += 1
                                        break
                            except (RuntimeError, TypeError, ValueError, OSError) as e:
                                logger.warn("Something is out of whack somewhere with the series: %s" % e)
                            except:
                                logger.warn("Unexpected Error: %s" % sys.exc_info()[0])
                                raise

                    logger.info(
                        "In the process of converting the data to CV, I changed the status of "
                        + str(icount)
                        + " issues."
                    )

                    issuesnew = db.select_all(
                        select(issues).where(
                            (issues.c.ComicID == ComicID) & (issues.c.Status == None)  # noqa: E711
                        )
                    )

                    newiss = []

                    for iss in issuesnew:
                        if iss["ReleaseDate"] == "0000-00-00":
                            dk = re.sub("-", "", iss["IssueDate"]).strip()
                        else:
                            dk = re.sub("-", "", iss["ReleaseDate"]).strip()
                        if dk == "00000000":
                            logger.warn(
                                "Issue Data is invalid for Issue Number %s. Marking this issue as Skipped"
                                % iss["Issue_Number"]
                            )
                            newstatus = "Skipped"
                        else:
                            datechk = datetime.datetime.strptime(dk, "%Y%m%d")
                            issue_week = datetime.datetime.strftime(datechk, "%Y%U")
                            logger.info("issue_week: %s" % issue_week)
                            if pause_status is True:
                                newstatus = "Skipped"
                                logger.fdebug(
                                    "[PAUSE-ISSUE-CATCH-STATUS] Series is Paused, but new issue detected - setting status of %s for #%s"
                                    % (iss["Status"], iss["Issue_Number"])
                                )
                            else:
                                if comicarr.CONFIG.AUTOWANT_ALL:
                                    logger.fdebug("autowant all")
                                    newstatus = "Wanted"
                                elif lastupdated is None:
                                    logger.fdebug("serieslast_updated is None. Setting to Skipped")
                                    newstatus = "Skipped"
                                elif issue_week >= now_week and comicarr.CONFIG.AUTOWANT_UPCOMING:
                                    logger.fdebug("Issue_week: %s -- now_week: %s" % (issue_week, now_week))
                                    logger.fdebug("Issue date [%s] is in/beyond current week - marking as Wanted." % dk)
                                    newstatus = "Wanted"
                                elif all(
                                    [
                                        int(re.sub("-", "", lastupdated).strip()) < int(dk),
                                        comicarr.CONFIG.AUTOWANT_UPCOMING is True,
                                    ]
                                ):
                                    logger.info("Autowant upcoming triggered for issue #%s" % issue["Issue_Number"])
                                    newstatus = "Wanted"
                                else:
                                    logger.info("setting to Skipped")
                                    newstatus = "Skipped"
                        logger.fdebug("[#%s]status is : %s" % (iss["Issue_Number"], newstatus))

                        newiss.append({"IssueID": iss["IssueID"], "Status": newstatus, "Annual": False})

                    if comicarr.CONFIG.ANNUALS_ON:
                        annualsnew = db.select_all(
                            select(annuals).where(
                                (annuals.c.ComicID == ComicID) & (annuals.c.Status == None)  # noqa: E711
                            )
                        )

                        for ann in annualsnew:
                            ann_date = ann["ReleaseDate"]
                            if not ann_date or ann_date == "0000-00-00":
                                ann_date = ann["IssueDate"] or "0000-00-00"
                            dk = re.sub("-", "", ann_date).strip()
                            try:
                                datechk = datetime.datetime.strptime(dk, "%Y%m%d")
                            except ValueError:
                                # A malformed date (2026-02-30) is as unusable as 0000-00-00.
                                dk = "00000000"
                            if dk == "00000000":
                                logger.warn(
                                    "Issue Data is invalid for Issue Number %s. Marking this issue as Skipped"
                                    % ann["Issue_Number"]
                                )
                                newstatus = "Skipped"
                            else:
                                issue_week = datetime.datetime.strftime(datechk, "%Y%U")
                                logger.info("issue_week: %s" % issue_week)
                                if pause_status is True:
                                    newstatus = ann["Status"]
                                    logger.fdebug(
                                        "[PAUSE-ANNUAL-CATCH-STATUS] Series is Paused - keeping status of %s for #%s"
                                        % (ann["Status"], ann["Issue_Number"])
                                    )
                                else:
                                    if comicarr.CONFIG.AUTOWANT_ALL:
                                        logger.fdebug("autowant all")
                                        newstatus = "Wanted"
                                    elif lastupdated is None:
                                        logger.fdebug("serieslast_updated is None. Setting to Skipped")
                                        newstatus = "Skipped"
                                    elif issue_week >= now_week and comicarr.CONFIG.AUTOWANT_UPCOMING:
                                        logger.fdebug("Issue_week: %s -- now_week: %s" % (issue_week, now_week))
                                        logger.fdebug(
                                            "Issue date [%s] is in/beyond current week - marking as Wanted." % dk
                                        )
                                        newstatus = "Wanted"
                                    elif all(
                                        [
                                            int(re.sub("-", "", lastupdated).strip()) < int(dk),
                                            comicarr.CONFIG.AUTOWANT_UPCOMING is True,
                                        ]
                                    ):
                                        logger.info("Autowant upcoming triggered for issue #%s" % ann["Issue_Number"])
                                        newstatus = "Wanted"
                                    else:
                                        logger.info("setting to Skipped")
                                        newstatus = "Skipped"
                            logger.fdebug("[#%s]status is : %s" % (ann["Issue_Number"], newstatus))

                            newiss.append({"IssueID": ann["IssueID"], "Status": newstatus, "Annual": True})

                    if len(newiss) > 0:
                        for newi in newiss:
                            ctrlVAL = {"IssueID": newi["IssueID"]}
                            newVAL = {"Status": newi["Status"]}
                            if newi["Annual"]:
                                db.upsert("annuals", newVAL, ctrlVAL)
                            else:
                                db.upsert("issues", newVAL, ctrlVAL)

                    logger.info(
                        "I have added " + str(len(newiss)) + " new issues for this series that were not present before."
                    )
                    rescan.rescan_series(ComicID)

                    if not calledfrom == "json_api" and comicarr.CONFIG.SERIES_METADATA_LOCAL is True:
                        sm = series_metadata.metadata_Series(ComicID, bulk=False, api=False)
                        sm.update_metadata()

                else:
                    chkstatus = comicarr.importer.addComictoDB(ComicID, mismatch, annload=annload, csyear=csyear)

            else:
                chkstatus = comicarr.importer.addComictoDB(ComicID, mismatch)

        cnt += 1
        if calledfrom == "refresh":
            try:
                from comicarr.app.activity.producers import emit_series_activity

                emit_series_activity(
                    "refresh",
                    "succeeded",
                    ComicID,
                    comicname=ComicName,
                    seriesyear=dspyear,
                )
            except Exception as emit_err:
                logger.fdebug("[ACTIVITY] refresh.succeeded emit skipped: %s" % emit_err)
        if sched is True:
            # A scheduled pass refreshes one stale series per tick.
            break
        if calledfrom != "refresh" and len(comiclist) > 1:
            time.sleep(15)

    logger.fdebug("Update complete")


def watchlist_updater(calledfrom=None, sched=False):

    last_date = None
    last_run = None

    chk_time = db.select_one(
        select(
            jobhistory.c.prev_run_datetime,
            jobhistory.c.last_run_completed,
            jobhistory.c.last_date,
            jobhistory.c.prev_run_timestamp,
        ).where(jobhistory.c.JobName == "DB Updater")
    )

    last_runtimestamp = None
    if chk_time:
        last_run = chk_time["last_date"]
        last_date = chk_time["prev_run_datetime"]
        last_runtimestamp = chk_time["prev_run_timestamp"]
    elif comicarr.DB_BACKFILL is True:
        ld = datetime.datetime.today()
        lastrun = ld - datetime.timedelta(weeks=comicarr.CONFIG.BACKFILL_LENGTH)
        last_date = datetime.datetime.strftime(lastrun, "%Y-%m-%d %H:%M:%S")
        logger.info(
            "[BACKFILL-UPDATE][%s weeks] Setting backfill date to : %s. Anything that has "
            " been updated since this date will get refreshed. Let's GoOoo"
            % (comicarr.CONFIG.BACKFILL_LENGTH, last_date)
        )

    if last_run is not None:
        last_dater = datetime.datetime.utcfromtimestamp(last_run)
        last_date = datetime.datetime.strftime(last_dater, "%Y-%m-%d %H:%M:%S")
    elif last_runtimestamp is not None:
        rd = datetime.datetime.utcfromtimestamp(last_runtimestamp)
        rd_mins = rd + datetime.timedelta(seconds=900)
        rd_now = datetime.datetime.utcfromtimestamp(time.time())
        if calendar.timegm(rd_mins.utctimetuple()) > calendar.timegm(rd_now.utctimetuple()):
            logger.info("[BACKFILL-UPDATE] Update ran < 15 minutes ago. Not running.")
            return

    helpers.job_management(write=True, job="DB Updater", current_run=helpers.utctimestamp(), status="Running")
    comicarr.UPDATER_STATUS = "Running"

    logger.info("[BACKFILL-UPDATE] last date set to : %s" % last_date)

    try:
        update_list = cv.getComic(comicid=None, rtype="db_updater", dateinfo=last_date)
        if update_list is False:
            logger.warn(
                "[BACKFILL-UPDATE] CV is having problems atm. Deferring backfill"
                " job until next db update scheduled run time."
            )
            comicarr.DB_BACKFILL = False
            helpers.job_management(
                write=True, job="DB Updater", last_run_completed=helpers.utctimestamp(), status="Waiting"
            )
            comicarr.UPDATER_STATUS = "Waiting"
            return
    except Exception:
        logger.warn(
            "[BACKFILL-UPDATE] CV is having problems atm. Deferring backfill"
            " job until next db update scheduled run time."
        )
        comicarr.DB_BACKFILL = False
        helpers.job_management(
            write=True, job="DB Updater", last_run_completed=helpers.utctimestamp(), status="Waiting"
        )
        comicarr.UPDATER_STATUS = "Waiting"
        return

    if update_list["count"] == 0:
        logger.info("[BACKFILL-UPDATE] Nothing new has been posted to any series in your watchlist")
        helpers.job_management(write=True, job="DB Updater", current_run=helpers.utctimestamp(), status="Waiting")
        comicarr.UPDATER_STATUS = "Waiting"
        return

    set_the_bar = False

    if update_list["totalcount"] >= 1500:
        set_the_bar = True
        if comicarr.DB_BACKFILL is False:
            logger.info(
                "[BACKFILL-UPDATE] %s items returned since last CV update run. Will run every"
                " %s minutes grabbing the next 1500 results each time"
                % (update_list["totalcount"], comicarr.CONFIG.BACKFILL_TIMESPAN)
            )
            comicarr.DB_BACKFILL = True

    library = {}

    if comicarr.CONFIG.ANNUALS_ON is True:
        ann_stmt = (
            select(
                comics.c.ComicName,
                comics.c.ComicID,
                comics.c.ComicYear,
                annuals.c.ReleaseComicID,
                comics.c.Status,
                comics.c.LastUpdated,
                comics.c.Total,
            )
            .select_from(comics.outerjoin(annuals, comics.c.ComicID == annuals.c.ComicID))
            .group_by(comics.c.ComicID)
        )
        list_rows = db.select_all(ann_stmt)
    else:
        list_rows = db.select_all(
            select(
                comics.c.ComicName,
                comics.c.ComicID,
                comics.c.Status,
                comics.c.ComicYear,
                comics.c.LastUpdated,
                comics.c.Total,
            ).group_by(comics.c.ComicID)
        )

    prev_failed_updates = []
    popthecheck = []
    for row in list_rows:
        try:
            comicvine_id = int(row["ComicID"])
        except (TypeError, ValueError):
            logger.fdebug(
                "[BACKFILL-UPDATE] Skipping non-ComicVine series id %s during ComicVine update" % row["ComicID"]
            )
            continue

        if row["ComicName"] is None and comicarr.CONFIG.ANNUALS_ON:
            logger.fdebug("Popping the check for: %s" % row["ComicID"])
            popthecheck.append(
                {"comicid": row["ComicID"], "comicname": row["ComicName"], "seriesyear": row["ComicYear"]}
            )
            continue
        elif not row["LastUpdated"] and all(
            ["ComicID" not in row["ComicName"], row["Status"] != "Loading", row["ComicName"] is not None]
        ):
            prev_failed_updates.append(
                {"comicid": comicvine_id, "comicname": row["ComicName"], "seriesyear": row["ComicYear"]}
            )
        else:
            try:
                tm = datetime.datetime.strptime(row["LastUpdated"], "%Y-%m-%d %H:%M:%S")
            except Exception:
                prev_failed_updates.append(
                    {"comicid": comicvine_id, "comicname": row["ComicName"], "seriesyear": row["ComicYear"]}
                )
            else:
                library[comicvine_id] = {
                    "comicid": row["ComicID"],
                    "status": row["Status"],
                    "comicname": row["ComicName"],
                    "seriesyear": row["ComicYear"],
                    "lastupdated": calendar.timegm(tm.utctimetuple()),
                    "total": row["Total"],
                }
        try:
            if row["ReleaseComicID"] is not None and all(
                ["ComicID" not in row["ComicName"], row["Status"] != "Loading", row["ComicName"] is not None]
            ):
                library[row["ReleaseComicID"]] = {"comicid": row["ComicID"], "status": row["Status"]}
        except:
            pass

    if len(popthecheck) > 0:
        logger.fdebug("doing the popcheck")
        for pc in popthecheck:
            pc_row = db.select_one(
                select(annuals.c.ComicName, annuals.c.ComicID, annuals.c.Status).where(
                    (annuals.c.ReleaseComicID == pc["comicid"]) & (annuals.c.ComicName != None)  # noqa: E711
                )
            )
            if not pc_row:
                prev_failed_updates.append(
                    {"comicid": int(pc["comicid"]), "comicname": pc["comicname"], "seriesyear": pc["seriesyear"]}
                )
                continue

    to_check = []
    loaddate_stamp = None
    cntr = int(update_list["count"])
    cntr_chk = 1
    for x in update_list["results"]:
        if all([set_the_bar is True, loaddate_stamp is None, cntr_chk == cntr]) or loaddate_stamp is not None:
            loaddate = datetime.datetime.strptime(x["last_updated"], "%Y-%m-%d %H:%M:%S")
            loaddate_stamp = calendar.timegm(loaddate.utctimetuple())

        try:
            if x["comicid"]["id"] in library:
                tm = datetime.datetime.strptime(x["last_updated"], "%Y-%m-%d %H:%M:%S")
                if all(
                    [
                        library[x["comicid"]["id"]]["lastupdated"] < calendar.timegm(tm.utctimetuple()),
                    ]
                ):
                    x_check = [yy for yy in to_check if yy["comicid"] == x["comicid"]["id"]]
                    if not x_check:
                        to_check.append(
                            {
                                "comicid": x["comicid"]["id"],
                                "comicname": library[x["comicid"]["id"]]["comicname"],
                                "seriesyear": library[x["comicid"]["id"]]["seriesyear"],
                            }
                        )
            cntr_chk += 1
        except Exception:
            logger.fdebug(
                "[BACKFILL-UPDATE] Unable to properly determine item [%s] due to invalid CV entry"
                " - ignoring (this should be fine)" % (x,)
            )
            pass

    if len(to_check) > 0:
        logger.info("[BACKFILL-UPDATE] [%s] series to update: %s" % (len(to_check), to_check))
    if len(prev_failed_updates) > 0:
        logger.info(
            "[BACKFILL-UPDATE] [%s] series need to be updated due to previous"
            " failures: %s" % (len(prev_failed_updates), prev_failed_updates)
        )
        try:
            to_check = dict(to_check, **prev_failed_updates)
        except Exception:
            to_check = prev_failed_updates
    else:
        logger.info("[BACKFILL-UPDATE] No previous failures on updates detected (checked against %s items)" % (cntr))

    logger.info("[BACKFILL-UPDATE] Setting last update date to: %s" % loaddate_stamp)

    watch = []
    for x in to_check:
        if {"comicid": x["comicid"], "comicname": x["comicname"]} not in comicarr.REFRESH_QUEUE.queue:
            watch.append({"comicid": x["comicid"], "comicname": x["comicname"], "seriesyear": x["seriesyear"]})

    if len(watch) > 0:
        logger.info("[SHIZZLE-WHIZZLE] Now queueing to refresh %s series" % (len(watch)))
        try:
            comicarr.importer.refresh_thread(watch)
        except Exception:
            pass

    db.upsert("jobhistory", {"last_date": loaddate_stamp}, {"JobName": "DB Updater"})
    if loaddate_stamp is not None:
        logger.info(
            "[BACKFILL-UPDATE] [%s/%s] Setting last date update point temporarily to %s [%s]"
            % (
                update_list["count"],
                update_list["totalcount"],
                datetime.datetime.strftime(datetime.datetime.utcfromtimestamp(loaddate_stamp), "%Y-%m-%d %H:%M:%S"),
                loaddate_stamp,
            )
        )

    helpers.job_management(write=True, job="DB Updater", last_run_completed=helpers.utctimestamp(), status="Waiting")
    comicarr.UPDATER_STATUS = "Waiting"

    if comicarr.DB_BACKFILL is True and loaddate_stamp is None:
        comicarr.DB_BACKFILL = False
    return
