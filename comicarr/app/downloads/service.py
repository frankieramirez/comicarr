#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Downloads domain service — history, post-processing, DDL queue.

Module-level functions wrapping postprocessor.py (~5k lines) and
download client interactions.
"""

import datetime
import os
import re
import time
import zipfile
from pathlib import Path

import rarfile

import comicarr
from comicarr import db, getcomics, logger, nzbget, process, sabnzbd
from comicarr.app.downloads import queries as dl_queries
from comicarr.downloaders import mediafire, mega, pixeldrain
from comicarr.tables import annuals, comics, ddl_info, issues, storyarcs, weekly

# ---------------------------------------------------------------------------
# Download history
# ---------------------------------------------------------------------------


def get_history(limit=None, offset=None):
    """Get download history, optionally paginated."""
    if limit is not None:
        paginated = dl_queries.get_history(limit=limit, offset=offset)
        return {
            "history": paginated["results"],
            "pagination": {
                "total": paginated["total"],
                "limit": paginated["limit"],
                "offset": paginated["offset"],
                "has_more": paginated["has_more"],
            },
        }
    return dl_queries.get_history()


def clear_history(status_type=None):
    """Clear download history entries."""
    dl_queries.clear_history(status_type=status_type)
    if status_type:
        logger.info("[DOWNLOADS] Cleared history entries with status: %s" % status_type)
    else:
        logger.info("[DOWNLOADS] Cleared all history entries")
    return {"success": True}


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


def force_process(
    nzb_name,
    nzb_folder,
    failed=False,
    issueid=None,
    comicid=None,
    ddl=False,
    oneoff=False,
    apc_version=None,
    comicrn_version=None,
):
    """Queue a download for post-processing.

    For standard API calls, queues to PP_QUEUE for background processing.
    For ComicRN/APC compatibility, calls WebInterface.post_process directly.
    """
    if apc_version is not None:
        # ComicRN/APC compatibility mode — direct processing
        logger.info("[API] Api Call from ComicRN detected - initiating script post-processing.")
        import queue as queue_mod
        import threading

        from comicarr import postprocessor

        pp_queue = queue_mod.Queue()
        if failed == "0":
            failed = False
        elif failed == "1":
            failed = True

        if not failed:
            pp = postprocessor.PostProcessor(nzb_name, nzb_folder, queue=pp_queue)
            thread_ = threading.Thread(target=pp.Process, name="Post-Processing")
            thread_.start()
            thread_.join()
        return {"success": True}

    # Standard mode — queue for background processing
    logger.info("Received API Request for PostProcessing %s [%s]. Queueing..." % (nzb_name, nzb_folder))
    comicarr.PP_QUEUE.put(
        {
            "nzb_name": nzb_name,
            "nzb_folder": nzb_folder,
            "issueid": issueid,
            "failed": failed,
            "oneoff": oneoff,
            "comicid": comicid,
            "apicall": True,
            "ddl": ddl,
        }
    )
    return {"success": True, "message": "Successfully submitted request for post-processing for %s" % nzb_name}


def process_issue(comicid, folder, issueid=None):
    """Post-process a specific issue."""
    from comicarr import process

    try:
        fp = process.Process(comicid, folder, issueid)
        result = fp.post_process()
        return {"success": True, "data": result}
    except Exception as e:
        logger.error("[DOWNLOADS] Error processing issue: %s" % e)
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# DDL queue management
# ---------------------------------------------------------------------------


def get_ddl_queue():
    """Get current DDL download queue."""
    return dl_queries.get_ddl_queue()


def delete_ddl_item(item_id):
    """Remove an item from the DDL queue."""
    dl_queries.delete_ddl_item(item_id)
    logger.info("[DOWNLOADS] Removed DDL item: %s" % item_id)
    return {"success": True}


def requeue_ddl_item(item_id):
    """Requeue a failed DDL download."""
    item = dl_queries.get_ddl_item(item_id)
    if not item:
        return {"success": False, "error": "DDL item not found: %s" % item_id}

    dl_queries.update_ddl_status(item_id, "Queued")
    logger.info("[DOWNLOADS] Requeued DDL item: %s" % item_id)
    return {"success": True}


def queue_ddl_download(item_id, link, site):
    """Queue a direct download link for processing.

    Inserts/updates ddl_info and puts the item on the DDL_QUEUE.
    """
    import datetime as dt

    vals = {
        "link": link,
        "site": site,
        "status": "Queued",
        "updated_date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    db.upsert("ddl_info", vals, {"id": item_id})

    comicarr.DDL_QUEUE.put(
        {
            "id": item_id,
            "link": link,
            "site": site,
        }
    )

    logger.info("[DOWNLOADS] Queued DDL download: %s (site=%s)" % (item_id, site))
    return {"success": True, "message": "DDL download queued: %s" % item_id}


def get_issue_file_path(issue_id):
    """Resolve the on-disk file path for an issue.

    Returns (path, filename) tuple or (None, None) if not found.
    Checks primary ComicLocation and MULTIPLE_DEST_DIRS secondary.
    """
    issue = dl_queries.get_issue_file_info(issue_id)
    if not issue:
        return None, None

    if not issue.get("Location") or not issue.get("ComicLocation"):
        return None, None

    pathfile = os.path.join(issue["ComicLocation"], issue["Location"])
    if os.path.isfile(pathfile):
        return pathfile, issue["Location"]

    # Check secondary destination directories
    if comicarr.CONFIG.MULTIPLE_DEST_DIRS:
        try:
            secondary = os.path.join(
                comicarr.CONFIG.MULTIPLE_DEST_DIRS,
                os.path.basename(issue["ComicLocation"]),
            )
            alt_path = os.path.join(secondary, issue["Location"])
            if os.path.isfile(alt_path):
                return alt_path, issue["Location"]
        except Exception:
            pass

    return None, None


# --- Extracted from helpers.py ---


def rename_param(comicid, comicname, issue, ofilename, comicyear=None, issueid=None, annualize=None, arc=False):
    from sqlalchemy import select

    from comicarr.helpers import filesafe, fullmonth, issuedigits, replace_all

    comicid = str(comicid)

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

    if arc:
        issuenum = issuenzb["IssueNumber"]
        issuedate = issuenzb["IssueDate"]
        publisher = issuenzb["IssuePublisher"]
        series = issuenzb["ComicName"]
        seriesfilename = series
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
        comversion = None
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

    issue_except = "None"
    valid_spaces = (".", "-")
    for issexcept in comicarr.ISSUE_EXCEPTIONS:
        if issexcept.lower() in issuenum.lower():
            logger.fdebug("ALPHANUMERIC EXCEPTION : [" + issexcept + "]")
            v_chk = [v for v in valid_spaces if v in issuenum]
            if v_chk:
                iss_space = v_chk[0]
            else:
                iss_space = ""
            if issexcept == "NOW":
                if "!" in issuenum:
                    issuenum = re.sub(r"\!", "", issuenum)
            issue_except = iss_space + issexcept
            logger.fdebug("issue_except denoted as : %s" % issue_except)
            if issuenum.lower() != issue_except.lower():
                issuenum = re.sub("[^0-9]", "", issuenum)
                if any([issuenum == "", issuenum is None]):
                    issuenum = issue_except
            break

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
            issueno = iss
        else:
            if len(iss_decval) == 1:
                iss = iss_b4dec + "." + iss_decval
            else:
                iss = iss_b4dec + "." + iss_decval.rstrip("0")
            issueno = iss_b4dec
    else:
        iss = issuenum
        issueno = iss

    if comicarr.CONFIG.ZERO_LEVEL is False:
        zeroadd = ""
    else:
        if any([comicarr.CONFIG.ZERO_LEVEL_N == "none", comicarr.CONFIG.ZERO_LEVEL_N is None]):
            zeroadd = ""
        elif comicarr.CONFIG.ZERO_LEVEL_N == "0x":
            zeroadd = "0"
        elif comicarr.CONFIG.ZERO_LEVEL_N == "00x":
            zeroadd = "00"

    prettycomiss = None

    if issueno.isalpha():
        prettycomiss = str(issueno)
    else:
        try:
            x = float(issuenum)
            if x < 0:
                prettycomiss = "-" + str(zeroadd) + str(issueno[1:])
            elif x == 9999999999:
                issuenum = "infinity"
            elif x >= 0:
                pass
            else:
                raise ValueError
        except ValueError:
            logger.warn("Unable to properly determine issue number [ %s]" % issueno)
            return

    if all([prettycomiss is None, len(str(issueno)) > 0]):
        if int(issueno) < 10:
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
        elif int(issueno) >= 10 and int(issueno) < 100:
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
        else:
            if issuenum == "infinity":
                prettycomiss = "infinity"
            else:
                if "." in iss:
                    if int(iss_decval) > 0:
                        issueno = str(iss)
                prettycomiss = str(issueno)
            if issue_except != "None":
                prettycomiss = str(prettycomiss) + issue_except
    elif len(str(issueno)) == 0:
        prettycomiss = str(issueno)

    if comicarr.CONFIG.UNICODE_ISSUENUMBER:
        prettycomiss = unicodeissue

    issueyear = issuedate[:4]
    month = issuedate[5:7].replace("-", "").strip()
    month_name = fullmonth(month)
    if month_name is None:
        month_name = "None"

    if comversion is None:
        comversion = "None"
    if comversion == "None":
        chunk_f_f = re.sub(r"\$VolumeN", "", comicarr.CONFIG.FILE_FORMAT)
        chunk_f = re.compile(r"\s+")
        chunk_file_format = chunk_f.sub(" ", chunk_f_f)
    else:
        chunk_file_format = comicarr.CONFIG.FILE_FORMAT

    if annualize is None:
        chunk_f_f = re.sub(r"\$Annual", "", chunk_file_format)
        chunk_f = re.compile(r"\s+")
        chunk_file_format = chunk_f.sub(" ", chunk_f_f)
    else:
        if comicarr.CONFIG.ANNUALS_ON:
            if "annual" in series.lower():
                if "$Annual" not in chunk_file_format:
                    pass
                else:
                    chunk_f_f = re.sub(r"\$Annual", "", chunk_file_format)
                    chunk_f = re.compile(r"\s+")
                    chunk_file_format = chunk_f.sub(" ", chunk_f_f)
            else:
                if "$Annual" not in chunk_file_format:
                    prettycomiss = "Annual %s" % prettycomiss
        else:
            if "annual" in series.lower():
                if "$Annual" not in chunk_file_format:
                    pass
                else:
                    chunk_f_f = re.sub(r"\$Annual", "", chunk_file_format)
                    chunk_f = re.compile(r"\s+")
                    chunk_file_format = chunk_f.sub(" ", chunk_f_f)
            else:
                if "$Annual" not in chunk_file_format:
                    prettycomiss = "Annual %s" % prettycomiss

    seriesfilename = seriesfilename
    filebad = [":", ",", "/", "?", "!", "'", '"', r"\*"]
    for dbd in filebad:
        if dbd in seriesfilename:
            if any([dbd == "/", dbd == "*"]):
                repthechar = "-"
            else:
                repthechar = ""
            seriesfilename = seriesfilename.replace(dbd, repthechar)

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
        if ofilename.lower().endswith(extensions):
            nfilename = ofilename[:-4]
        else:
            nfilename = ofilename
    else:
        nfilename = replace_all(chunk_file_format, file_values)
        if comicarr.CONFIG.REPLACE_SPACES:
            nfilename = nfilename.replace(" ", comicarr.CONFIG.REPLACE_CHAR)

    nfilename = re.sub(r"[\,\:]", "", nfilename) + ext.lower()

    if comicarr.CONFIG.LOWERCASE_FILENAMES:
        nfilename = nfilename.lower()
        dst = os.path.join(comlocation, nfilename)
    else:
        dst = os.path.join(comlocation, nfilename)

    rename_this = {"destination_dir": dst, "nfilename": nfilename, "issueid": issueid, "comicid": comicid}
    return rename_this


def renamefile_readingorder(readorder):
    logger.fdebug("readingorder#: " + str(readorder))
    if int(readorder) < 10:
        readord = "00" + str(readorder)
    elif int(readorder) >= 10 and int(readorder) <= 99:
        readord = "0" + str(readorder)
    else:
        readord = str(readorder)
    return readord


def duplicate_filecheck(filename, ComicID=None, IssueID=None, StoryArcID=None, rtnval=None):
    from sqlalchemy import select

    logger.info("[DUPECHECK] Duplicate check for " + filename)
    try:
        filesz = os.path.getsize(filename)
    except OSError:
        logger.warn("[DUPECHECK] File cannot be located in location specified.")
        return {"action": None}

    if IssueID:
        dupchk = db.select_one(select(issues).where(issues.c.IssueID == IssueID))
    if dupchk is None:
        dupchk = db.select_one(select(annuals).where(annuals.c.IssueID == IssueID, annuals.c.Deleted != 1))
        if dupchk is None:
            logger.info("[DUPECHECK] Unable to find corresponding Issue within the DB.")
            return {"action": None}

    series = db.select_one(select(comics).where(comics.c.ComicID == dupchk["ComicID"]))

    if dupchk["Status"] == "Downloaded" or dupchk["Status"] == "Archived":
        try:
            dupsize = dupchk["ComicSize"]
        except Exception:
            rtnval = {"action": "write"}

        if dupsize is None:
            havechk = db.select_one(select(comics).where(comics.c.ComicID == ComicID))
            if havechk:
                if havechk["Have"] > havechk["Total"]:
                    cid = [ComicID]
                    comicarr.updater.dbUpdate(ComicIDList=cid, calledfrom="dupechk")
                    return duplicate_filecheck(filename, ComicID, IssueID, StoryArcID)
                else:
                    if rtnval is not None:
                        return rtnval
                    else:
                        rtnval = {"action": "dont_dupe"}
                        comicarr.updater.forceRescan(ComicID)
                        chk1 = duplicate_filecheck(filename, ComicID, IssueID, StoryArcID, rtnval)
                        rtnval = chk1
            else:
                rtnval = {"action": "dupe_file", "to_dupe": os.path.join(series["ComicLocation"], dupchk["Location"])}
        else:
            fixed = False
            fixed_file = re.findall(r"[(]f\d{1}[)]", filename.lower())
            fixed_db_file = re.findall(r"[(]f\d{1}[)]", dupchk["Location"].lower())
            if all([fixed_file, not fixed_db_file]):
                fixed = True
                rtnval = {"action": "dupe_src", "to_dupe": os.path.join(series["ComicLocation"], dupchk["Location"])}
            elif all([fixed_db_file, not fixed_file]):
                fixed = True
                rtnval = {"action": "dupe_file", "to_dupe": filename}
            elif int(dupsize) == 0:
                if dupchk["Status"] == "Archived":
                    rtnval = {"action": "dupe_file", "to_dupe": filename}
                    return rtnval

            tmp_dupeconstraint = comicarr.CONFIG.DUPECONSTRAINT
            if not fixed and (comicarr.CONFIG.DUPECONSTRAINT == "filesize" or tmp_dupeconstraint == "filesize"):
                if filesz <= int(dupsize) and int(dupsize) != 0:
                    rtnval = {"action": "dupe_file", "to_dupe": filename}
                else:
                    rtnval = {
                        "action": "dupe_src",
                        "to_dupe": os.path.join(series["ComicLocation"], dupchk["Location"]),
                    }
    else:
        rtnval = {"action": "write"}
    return rtnval


def issue_find_ids(ComicName, ComicID, pack, IssueNumber, pack_id):
    from sqlalchemy import select

    from comicarr.helpers import issuedigits

    issuelist = db.select_all(select(issues).where(issues.c.ComicID == ComicID))

    if "Annual" not in pack:
        if "," not in pack:
            packlist = pack.split(" ")
            pack = re.sub("#", "", pack).strip()
        else:
            packlist = [x.strip() for x in pack.split(",")]
        plist = []
        pack_issues = []
        for pl in packlist:
            pl = re.sub("#", "", pl).strip()
            if "-" in pl:
                le_range = list(range(int(pack[: pack.find("-")]), int(pack[pack.find("-") + 1 :]) + 1))
                for x in le_range:
                    if not [y for y in plist if y == x]:
                        plist.append(int(x))
            else:
                if not [x for x in plist if x == int(pl)]:
                    plist.append(int(pl))

        for pi in plist:
            if type(pi) == list:
                for x in pi:
                    pack_issues.append(x)
            else:
                pack_issues.append(pi)
        pack_issues.sort()
    else:
        tmp_pack = re.sub("[annual/annuals/+]", "", pack.lower()).strip()
        pack_issues_numbers = re.findall(r"\d+", tmp_pack)
        pack_issues = list(range(int(pack_issues_numbers[0]), int(pack_issues_numbers[1]) + 1))

    iss = {}
    issueinfo = []
    write_valids = []

    Int_IssueNumber = issuedigits(IssueNumber)
    valid = False
    ignores = []
    for iss_item in pack_issues:
        int_iss = issuedigits(str(iss_item))
        for xb in issuelist:
            if xb["Status"] != "Downloaded":
                if xb["Int_IssueNumber"] == int_iss:
                    if Int_IssueNumber == xb["Int_IssueNumber"]:
                        valid = True
                    issueinfo.append({"issueid": xb["IssueID"], "int_iss": int_iss, "issuenumber": xb["Issue_Number"]})
                    write_valids.append({"issueid": xb["IssueID"], "pack_id": pack_id})
                    break
            else:
                ignores.append(iss_item)

    if valid:
        for wv in write_valids:
            comicarr.PACK_ISSUEIDS_DONT_QUEUE[wv["issueid"]] = wv["pack_id"]

    iss["issues"] = issueinfo

    if len(iss["issues"]) == len(pack_issues):
        logger.fdebug(
            "Complete issue count of %s issues are available within this pack for %s" % (len(pack_issues), ComicName)
        )

    iss["issue_range"] = pack_issues
    iss["valid"] = valid
    return iss


def reverse_the_pack_snatch(pack_id, comicid):
    logger.info(
        "[REVERSE UNO] Reversal of issues marked as Snatched via pack download reversing due to invalid link retrieval.."
    )
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


def ddl_downloader(queue):
    from sqlalchemy import delete

    from comicarr.helpers import check_file_condition

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
                comicarr.DDL_QUEUED.add(item["id"])
            try:
                link_type_failure[item["id"]].append(item["link_type_failure"])
            except Exception:
                pass

            logger.info("Now loading request from DDL queue: %s" % item["series"])
            ctrlval = {"id": item["id"]}
            val = {"status": "Downloading", "updated_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
            db.upsert("ddl_info", val, ctrlval)

            if item["site"] == "DDL(GetComics)":
                try:
                    remote_filesize = item["remote_filesize"]
                except Exception:
                    try:
                        from comicarr.helpers import human2bytes

                        remote_filesize = human2bytes(re.sub("/s", "", item["size"][:-1]).strip())
                    except Exception:
                        remote_filesize = 0

                if any([item["link_type"] == "GC-Main", item["link_type"] == "GC_Mirror"]):
                    ddz = getcomics.GC()
                    ddzstat = ddz.downloadit(
                        item["id"], item["link"], item["mainlink"], item["resume"], item["issueid"], remote_filesize
                    )
                elif item["link_type"] == "GC-Mega":
                    meganz = mega.MegaNZ()
                    ddzstat = meganz.ddl_download(item["link"], None, item["id"], item["issueid"], item["link_type"])
                elif item["link_type"] == "GC-Media":
                    mediaf = mediafire.MediaFire()
                    ddzstat = mediaf.ddl_download(item["link"], item["id"], item["issueid"])
                elif item["link_type"] == "GC-Pixel":
                    pdrain = pixeldrain.PixelDrain()
                    ddzstat = pdrain.ddl_download(item["link"], item["id"], item["issueid"])

            elif item["site"] == "DDL(External)":
                meganz = mega.MegaNZ()
                ddzstat = meganz.ddl_download(
                    item["link"], item["filename"], item["id"], item["issueid"], item["link_type"]
                )

            if ddzstat["success"] and ddzstat["filename"] is not None:
                filecondition = check_file_condition(ddzstat["path"])
                if not filecondition["status"]:
                    ddzstat["success"] = False
                    ddzstat["link_type_failure"] = item["link_type"]

            if ddzstat["success"] is True:
                tdnow = datetime.datetime.now()
                nval = {"status": "Completed", "updated_date": tdnow.strftime("%Y-%m-%d %H:%M")}
                db.upsert("ddl_info", nval, ctrlval)

            if all([ddzstat["success"] is True, comicarr.CONFIG.POST_PROCESSING is True]):
                try:
                    if ddzstat["filename"] is None:
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

                comicarr.DDL_QUEUED.discard(item["id"])
                comicarr.DDL_STUCK_NOTIFIED.discard(item["id"])
                try:
                    link_type_failure.pop(item["id"])
                except KeyError:
                    pass
                try:
                    pck_cnt = 0
                    if item["comicinfo"][0]["pack"] is True:
                        for x, y in dict(comicarr.PACK_ISSUEIDS_DONT_QUEUE).items():
                            if y == item["id"]:
                                pck_cnt += 1
                                del comicarr.PACK_ISSUEIDS_DONT_QUEUE[x]
                except Exception:
                    pass
                ddl_cleanup(item["id"])

            elif all([ddzstat["success"] is True, comicarr.CONFIG.POST_PROCESSING is False]):
                ddl_cleanup(item["id"])
            else:
                if item["site"] == "DDL(GetComics)":
                    try:
                        ddzstat["links_exhausted"]
                    except KeyError:
                        try:
                            link_type_failure[item["id"]].append(item["link_type"])
                        except KeyError:
                            link_type_failure[item["id"]] = [item["link_type"]]
                        ggc = getcomics.GC(comicid=item["comicid"], issueid=item["issueid"], oneoff=item["oneoff"])
                        ggc.parse_downloadresults(
                            item["id"],
                            item["mainlink"],
                            item["comicinfo"],
                            item["packinfo"],
                            link_type_failure[item["id"]],
                        )
                    else:
                        nval = {"status": "Failed", "updated_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
                        db.upsert("ddl_info", nval, ctrlval)
                        reverse_the_pack_snatch(item["id"], item["comicid"])
                        link_type_failure.pop(item["id"])
                        comicarr.DDL_STUCK_NOTIFIED.discard(item["id"])
                        ddl_cleanup(item["id"])
                else:
                    with db.get_engine().begin() as conn:
                        conn.execute(delete(ddl_info).where(ddl_info.c.ID == item["id"]))
                    comicarr.DDL_STUCK_NOTIFIED.discard(item["id"])
                    comicarr.search.FailedMark(
                        item["issueid"], item["comicid"], item["id"], ddzstat["filename"], item["site"]
                    )
        else:
            time.sleep(5)


def ddl_cleanup(id):
    tlnk = "getcomics-%s.html" % id
    try:
        os.remove(os.path.join(comicarr.CONFIG.CACHE_DIR, "html_cache", tlnk))
    except Exception:
        logger.fdebug("[HTML-cleanup] Unable to remove html used for item from html_cache folder.")


def ddl_health_check():
    if not comicarr.CONFIG.DDL_STUCK_NOTIFY:
        return
    if not comicarr.CONFIG.ENABLE_DDL:
        return

    from sqlalchemy import select

    from comicarr.app.system.service import notify_ddl_stuck

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
            if item["ID"] in comicarr.DDL_STUCK_NOTIFIED:
                continue
            logger.warn(
                "[DDL-HEALTH] Download stuck for %d minutes: %s (%s)" % (int(age_minutes), item["series"], item["ID"])
            )
            notify_ddl_stuck(item, int(age_minutes))
            comicarr.DDL_STUCK_NOTIFIED.add(item["ID"])


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
            queue.put(item)
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
                item["nzb_name"], item["nzb_folder"], item["failed"], item["issueid"], item["comicid"], item["apicall"]
            )
        pp = pprocess.post_process()
        if pp is not None:
            if pp["mode"] == "stop":
                comicarr.APILOCK.release()
        if comicarr.APILOCK.locked():
            logger.info("Another item is post-processing still...")
            time.sleep(15)


def worker_main(queue):
    import queue as queue_module

    from comicarr.app.search.service import torrentinfo

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
                    "nzb_folder": snstat["copied_filepath"],
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
                logger.warn("There are no NZB Completed Download handlers enabled.")
                break
            cdh_monitor(queue, item, nzstat)
        else:
            time.sleep(5)


def cdh_monitor(queue, item, nzstat, readd=False):
    from comicarr.helpers import check_file_condition

    known_nzb_id = item["nzo_id"] if (comicarr.USE_SABNZBD is True) else item["NZBID"]
    if any([nzstat["status"] == "file not found", nzstat["status"] == "double-pp"]):
        logger.warn("Unable to complete post-processing call due to not finding file. [%s]" % item)
    elif nzstat["status"] == "nzb removed" or "unhandled status" in str(nzstat["status"]).lower():
        if readd is True:
            logger.warn("NZB seems to have been in a staging process. Will requeue: %s." % known_nzb_id)
            comicarr.RETURN_THE_NZBQUEUE.put(item)
        else:
            logger.warn("NZB seems to have been removed from queue: %s" % known_nzb_id)
    elif nzstat["status"] == "failed_in_sab":
        logger.warn("Failure returned from SAB for %s" % known_nzb_id)
    elif nzstat["status"] == "queue_paused":
        if comicarr.USE_SABNZBD is True:
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
                nzstat["failed"] = True
        if nzstat["failed"] is False:
            logger.info("File successfully downloaded - now initiating completed downloading handling.")
        else:
            logger.info("File failed - now initiating completed failed downloading handling.")
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


def lookupthebitches(filelist, folder, nzbname, nzbid, prov, hash, pulldate):
    from sqlalchemy import select

    from comicarr.app.series.service import listLibrary

    watchlist = listLibrary()
    matchlist = []
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
                matchlist.append(
                    {
                        "comicname": check["COMIC"],
                        "issue": check["ISSUE"],
                        "comicid": check["ComicID"],
                        "issueid": check["IssueID"],
                        "dynamicname": check["DynamicName"],
                    }
                )

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


# Magic numbers for file type detection
magic_numbers = {
    "PDF": bytes([0x25, 0x50, 0x44, 0x46]),
    "ZIP": bytes([0x50, 0x4B, 0x03, 0x04]),
    "RAR": bytes([0x52, 0x61, 0x72, 0x21, 0x1A, 0x07]),
    "7Z": bytes([0x37, 0x7A, 0xBC, 0xAF, 0x27, 0x1C]),
}


def check_file_condition(file_path):
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
            return {"status": False, "type": "ZIP", "quality": f"Error processing zip compressed file: {e}."}
        return {"status": True, "type": "ZIP", "quality": "Good condition."}
    elif header.startswith(magic_numbers["RAR"]):
        try:
            with rarfile.RarFile(file_path, mode="r") as rarf:
                test_result = rarf.testrar()
                if test_result is not None:
                    return {"status": False, "type": "RAR", "quality": f"CRC error in file {test_result}."}
        except Exception as e:
            return {"status": False, "type": "RAR", "quality": f"Error processing rar compressed file: {e}."}
        return {"status": True, "type": "RAR", "quality": "Good condition."}
    elif header.startswith(magic_numbers["7Z"]):
        return {"status": True, "type": "7Z", "quality": "File is using 7zip compression."}
    elif header.startswith(magic_numbers["PDF"]):
        return {"status": True, "type": "PDF", "quality": "PDF file.  No quality checks performed."}
    else:
        return {"status": False, "type": "unknown", "quality": "Unknown file type, unknown condition"}
