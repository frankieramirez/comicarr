#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Folder rescan: re-read a series folder and reconcile issue status and totals.

Moved from ``comicarr/updater.py`` (#1459). ``app/series/rescan.py`` is the
seam other modules call; postprocessing reads ``totals`` from here.
"""

import datetime
import os
import re
import shlex

from sqlalchemy import bindparam, func, select, update

import comicarr
from comicarr import db, filechecker
from comicarr.app.common import configured as configured
from comicarr.app.common import dates as common_dates
from comicarr.app.common import series_kind
from comicarr.app.common import utilities as common_utilities
from comicarr.app.core import logger
from comicarr.app.library import directories, filers
from comicarr.tables import annuals, comics, issues


def _bulk_update_issue_rows(table, rows, fields):
    """Persist issue updates without colliding with SQLAlchemy's SET bind names."""
    if not rows:
        return

    params = [
        {
            **{f"_value_{field}": row[field] for field in fields},
            "_issue_id": row["IssueID"],
        }
        for row in rows
    ]
    stmt = (
        update(table)
        .where(table.c.IssueID == bindparam("_issue_id"))
        .values(**{field: bindparam(f"_value_{field}") for field in fields})
    )
    with db.get_engine().begin() as conn:
        conn.execute(stmt, params)


def force_rescan(ComicID, archive=None, module=None, recheck=False):
    if module is None:
        module = ""
    module += "[FILE-RESCAN]"
    rescan = db.select_one(select(comics).where(comics.c.ComicID == ComicID))
    if rescan and (series_kind.is_manga(rescan) or series_kind.provider_of(ComicID) in series_kind.MANGA_PROVIDERS):
        from comicarr.app.manga.rescan import rescan_manga_series

        rescan_manga_series(rescan, directory=archive or rescan.get("ComicLocation"))
        return
    from comicarr.app.acquisition.evidence import has_verified_library_file
    from comicarr.app.series.location import retained_locations

    retained = retained_locations(rescan)

    def left_behind(row):
        return bool(retained) and has_verified_library_file(None, row["Location"], retained)

    if rescan["AlternateSearch"] is not None:
        altnames = rescan["AlternateSearch"] + "##"
    else:
        altnames = ""

    pause_status = False
    if rescan["Status"] == "Paused":
        pause_status = True

    if (
        all(
            [
                rescan["Type"] != "Print",
                rescan["Type"] != "Digital",
                rescan["Type"] != "None",
                rescan["Type"] is not None,
            ]
        )
        and rescan["Corrected_Type"] != "Print"
    ) or any(
        [
            rescan["Corrected_Type"] == "TPB",
            rescan["Corrected_Type"] == "HC",
            rescan["Corrected_Type"] == "GN",
            rescan["Corrected_Type"] == "One-Shot",
        ]
    ):
        if rescan["Type"] == "One-Shot" and rescan["Corrected_Type"] is None:
            booktype = "One-Shot"
        else:
            if rescan["Type"] == "GN" and rescan["Corrected_Type"] is None:
                booktype = "GN"
            elif rescan["Type"] == "HC" and rescan["Corrected_Type"] is None:
                booktype = "HC"
            else:
                booktype = "TPB"
    else:
        booktype = "Print"

    annscan = db.select_all(select(annuals).where((annuals.c.ComicID == ComicID) & (annuals.c.Deleted != 1)))
    if annscan is None:
        pass
    else:
        for ascan in annscan:
            if ascan["ReleaseComicName"] not in altnames:
                altnames += ascan["ReleaseComicName"] + "!!" + ascan["ReleaseComicID"] + "##"
        altnames = altnames[:-2]
    logger.info(
        module
        + " Now checking files for "
        + rescan["ComicName"]
        + " ("
        + str(rescan["ComicYear"])
        + ") in "
        + rescan["ComicLocation"]
    )
    fca = []
    if archive is None:
        tval = filechecker.FileChecker(
            dir=rescan["ComicLocation"],
            watchcomic=rescan["ComicName"],
            Publisher=rescan["ComicPublisher"],
            AlternateSearch=altnames,
        )
        tmpval = tval.listFiles()
        comiccnt = int(tmpval["comiccount"])
        fca.append(tmpval)
        try:
            if all([comicarr.CONFIG.MULTIPLE_DEST_DIRS is not None, comicarr.CONFIG.MULTIPLE_DEST_DIRS != "None"]):
                if os.path.exists(
                    os.path.join(comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(rescan["ComicLocation"]))
                ):
                    secondary_folders = os.path.join(
                        comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(rescan["ComicLocation"])
                    )
                else:
                    ff = filers.FileHandlers(ComicID=ComicID)
                    secondary_folders = ff.secondary_folders(rescan["ComicLocation"])

                logger.fdebug(module + "multiple_dest_dirs:" + comicarr.CONFIG.MULTIPLE_DEST_DIRS)
                logger.fdebug(module + "dir: " + rescan["ComicLocation"])
                logger.fdebug(module + "os.path.basename: " + os.path.basename(rescan["ComicLocation"]))
                logger.info(
                    module
                    + " Now checking files for "
                    + rescan["ComicName"]
                    + " ("
                    + str(rescan["ComicYear"])
                    + ") in :"
                    + secondary_folders
                )
                mvals = filechecker.FileChecker(
                    dir=secondary_folders,
                    watchcomic=rescan["ComicName"],
                    Publisher=rescan["ComicPublisher"],
                    AlternateSearch=altnames,
                )
                tmpv = mvals.listFiles()
                logger.fdebug(module + "tmpv filecount: " + str(tmpv["comiccount"]))
                comiccnt += int(tmpv["comiccount"])
                fca.append(tmpv)
        except Exception:
            pass
    else:
        arcval = filechecker.FileChecker(
            dir=archive,
            watchcomic=rescan["ComicName"],
            Publisher=rescan["ComicPublisher"],
            AlternateSearch=rescan["AlternateSearch"],
        )
        files_arc = arcval.listFiles()
        fca.append(files_arc)
        comiccnt = int(files_arc["comiccount"])

    fcb = []
    fc = {}

    is_cnt = db.select_one(select(func.count()).select_from(issues).where(issues.c.ComicID == ComicID))
    iscnt = list(is_cnt.values())[0] if is_cnt else 0

    for ca in fca:
        i = 0
        while True:
            try:
                cla = ca["comiclist"][i]
            except (IndexError, KeyError):
                break

            try:
                if (
                    all([booktype == "TPB", iscnt > 1])
                    or all([booktype == "GN", iscnt > 1])
                    or all([booktype == "HC", iscnt > 1])
                    or all([booktype == "One-Shot", iscnt == 1, cla["JusttheDigits"] is None])
                ):
                    if cla["SeriesVolume"] is not None:
                        just_the_digits = re.sub("[^0-9]", "", cla["SeriesVolume"]).strip()
                    elif cla["JusttheDigits"] is None:
                        just_the_digits = None
                    else:
                        just_the_digits = re.sub("[^0-9]", "", cla["JusttheDigits"]).strip()
                else:
                    just_the_digits = cla["JusttheDigits"]
            except Exception as e:
                logger.warn(
                    "[Exception: %s] Unable to properly match up/retrieve issue number (or volume) for this [CS: %s]"
                    % (e, cla)
                )
            else:
                fcb.append(
                    {
                        "ComicFilename": cla["ComicFilename"],
                        "ComicLocation": cla["ComicLocation"],
                        "ComicSize": cla["ComicSize"],
                        "JusttheDigits": just_the_digits,
                        "AnnualComicID": cla["AnnualComicID"],
                    }
                )
            i += 1

    fc["comiclist"] = fcb

    havefiles = 0
    if comicarr.CONFIG.ANNUALS_ON:
        an_cnt = db.select_one(
            select(func.count()).select_from(annuals).where((annuals.c.ComicID == ComicID) & (annuals.c.Deleted != 1))
        )
        anncnt = list(an_cnt.values())[0] if an_cnt else 0
    else:
        anncnt = 0
    fccnt = comiccnt
    fcnew = []
    fn = 0
    issuedupechk = []
    annualdupechk = []
    mc_issue = []
    mc_issuenumber = []
    multiple_check = db.select_all(
        select(issues)
        .where(issues.c.ComicID == ComicID)
        .group_by(issues.c.Int_IssueNumber)
        .having(func.count(issues.c.Int_IssueNumber) > 1)
    )

    if len(multiple_check) == 0:
        logger.fdebug("No issues with identical issue numbering were detected for this series")
        mc_issuenumber = None
    else:
        logger.fdebug("Multiple issues with identical numbering were detected. Attempting to accomodate.")
        for mc in multiple_check:
            mc_issuenumber.append({"Int_IssueNumber": mc["Int_IssueNumber"]})

    if mc_issuenumber is not None:
        for mciss in mc_issuenumber:
            mchk = db.select_all(
                select(issues).where(
                    (issues.c.ComicID == ComicID) & (issues.c.Int_IssueNumber == mciss["Int_IssueNumber"])
                )
            )
            for mck in mchk:
                mc_issue.append(
                    {
                        "Int_IssueNumber": mck["Int_IssueNumber"],
                        "IssueYear": (mck["IssueDate"] or "")[:4],
                        "IssueID": mck["IssueID"],
                    }
                )

    mc_annual = []
    mc_annualnumber = []

    if comicarr.CONFIG.ANNUALS_ON:
        mult_ann_check = db.select_all(
            select(annuals)
            .where((annuals.c.ComicID == ComicID) & (annuals.c.Deleted != 1))
            .group_by(annuals.c.Int_IssueNumber)
            .having(func.count(annuals.c.Int_IssueNumber) > 1)
        )

        if len(mult_ann_check) == 0:
            logger.fdebug(
                "[ANNUAL-CHK] No annuals with identical issue numbering across annual volumes were detected for this series"
            )
            mc_annualnumber = None
        else:
            logger.fdebug(
                "[ANNUAL-CHK] Multiple annuals with identical numbering were detected across multiple annual volumes. Attempting to accomodate."
            )
            for mc in mult_ann_check:
                mc_annualnumber.append({"Int_IssueNumber": mc["Int_IssueNumber"]})

        if mc_annualnumber is not None:
            for mcann in mc_annualnumber:
                achk = db.select_all(
                    select(annuals).where(
                        (annuals.c.ComicID == ComicID)
                        & (annuals.c.Int_IssueNumber == mcann["Int_IssueNumber"])
                        & (annuals.c.Deleted != 1)
                    )
                )
                for ack in achk:
                    mc_annual.append(
                        {
                            "Int_IssueNumber": ack["Int_IssueNumber"],
                            "IssueYear": (ack["IssueDate"] or "")[:4],
                            "IssueID": ack["IssueID"],
                            "ReleaseComicID": ack["ReleaseComicID"],
                        }
                    )

    issID_to_ignore = []
    issID_to_ignore.append(str(ComicID))
    annID_to_ignore = []
    annID_to_ignore.append(str(ComicID))
    ANNComicID = None
    d_annuals = []
    d_issues = []

    reissues = db.select_all(select(issues).where(issues.c.ComicID == ComicID))

    a_start = datetime.datetime.now()
    while fn < fccnt:
        haveissue = "no"
        issuedupe = "no"
        annualdupe = "no"
        try:
            tmpfc = fc["comiclist"][fn]
        except IndexError:
            logger.fdebug(module + " Unable to properly retrieve a file listing for the given series.")
            logger.fdebug(module + " Probably because the filenames being scanned are not in a parseable format")
            if fn == 0:
                return
            else:
                break

        if tmpfc["JusttheDigits"] is not None:
            temploc = tmpfc["JusttheDigits"].replace("_", " ")
            if "Director's Cut" not in temploc:
                temploc = re.sub("[\\#']", "", temploc)
            logger.fdebug("temploc: %s" % temploc)
        else:
            if any([booktype == "TPB", booktype == "GN", booktype == "HC", booktype == "One-Shot"]):
                temploc = "1"
            else:
                temploc = None
                logger.warn(
                    "The filename [%s] does not have a valid issue number, and the Edition of the series is %s. You might need to Forcibly Mark the Series as TPB/GN and try this again."
                    % (tmpfc["ComicFilename"], rescan["Type"])
                )
                fn += 1
                continue

        if all(["annual" not in temploc.lower(), "special" not in temploc.lower()]):
            extensions = (".cbr", ".cbz", ".cb7")
            if temploc.lower().endswith(extensions):
                logger.fdebug(module + " Removed extension for issue: " + temploc)
                temploc = temploc[:-4]
            fcnew_af = re.findall(r"[^\()]+", temploc)
            p = shlex.quote(fcnew_af[0])
            fcnew = shlex.split(p)

            len(fcnew)
            n = 0
            while True:
                try:
                    reiss = reissues[n]
                    int_iss = None
                except IndexError:
                    break
                int_iss = configured.issuedigits(reiss["Issue_Number"])
                issyear = (reiss["IssueDate"] or "")[:4]
                old_status = reiss["Status"]
                reiss["IssueName"]

                if reiss["forced_file"] is not None and bool(reiss["forced_file"]) is True:
                    logger.fdebug(
                        module
                        + "[FORCED-MATCH] Matched...issue: "
                        + rescan["ComicName"]
                        + "#"
                        + reiss["Issue_Number"]
                        + " --- "
                        + str(int_iss)
                    )
                    havefiles += 1
                    haveissue = "yes"
                    isslocation = tmpfc["ComicFilename"]
                    issSize = str(tmpfc["ComicSize"])
                    logger.fdebug(module + " .......filename: " + isslocation)
                    logger.fdebug(module + " .......filesize: " + str(tmpfc["ComicSize"]))
                    issuedupechk.append(
                        {
                            "fcdigit": int_iss,
                            "filename": tmpfc["ComicFilename"],
                            "filesize": tmpfc["ComicSize"],
                            "issueyear": issyear,
                            "issueid": reiss["IssueID"],
                        }
                    )
                    break

                if temploc is not None:
                    fcdigit = configured.issuedigits(temploc)
                elif (
                    any([booktype == "TPB", booktype == "GN", booktype == "HC", booktype == "One-Shot"])
                    and temploc is None
                ):
                    fcdigit = configured.issuedigits("1")

                if int(fcdigit) == int_iss:
                    logger.fdebug(
                        module
                        + " ["
                        + str(reiss["IssueID"])
                        + "] Issue match - fcdigit: "
                        + str(fcdigit)
                        + " ... int_iss: "
                        + str(int_iss)
                    )

                    if "-" in temploc and temploc.find(reiss["Issue_Number"]) > temploc.find("-"):
                        logger.fdebug(module + " I have detected a possible Title in the filename")
                        logger.fdebug(
                            module + " the issue # has occured after the -, so I assume that it is part of the Title"
                        )
                        break

                    multiplechk = False
                    issuedupe = "no"
                    foundchk = False

                    if len(mc_issue) > 1:
                        for mi in mc_issue:
                            if mi["Int_IssueNumber"] == int_iss:
                                if mi["IssueID"] == reiss["IssueID"]:
                                    logger.fdebug(
                                        module
                                        + " IssueID matches to multiple issues : "
                                        + str(mi["IssueID"])
                                        + ". Checking dupe."
                                    )
                                    logger.fdebug(
                                        module
                                        + " miISSUEYEAR: "
                                        + str(mi["IssueYear"])
                                        + " -- issyear : "
                                        + str(issyear)
                                    )
                                    if any(mi["IssueID"] == d["issueid"] for d in issuedupechk):
                                        logger.fdebug(
                                            module + " IssueID already within dupe. Checking next if available."
                                        )
                                        multiplechk = True
                                        break
                                    if (
                                        mi["IssueYear"]
                                        and issyear
                                        and mi["IssueYear"] in tmpfc["ComicFilename"]
                                        and issyear == mi["IssueYear"]
                                    ):
                                        logger.fdebug(module + " Matched to year within filename : " + str(issyear))
                                        multiplechk = False
                                        break
                                    else:
                                        logger.fdebug(
                                            module + " Did not match to year within filename : " + str(issyear)
                                        )
                                        multiplechk = True
                    if multiplechk:
                        n += 1
                        continue

                    for di in issuedupechk:
                        if di["fcdigit"] == fcdigit and di["issueid"] == reiss["IssueID"]:
                            logger.fdebug(
                                "[DUPECHECK] Duplicate issue detected ["
                                + di["filename"]
                                + "] ["
                                + tmpfc["ComicFilename"]
                                + "]"
                            )
                            logger.fdebug(
                                "[DUPECHECK] Based on duplication preferences I will retain based on : "
                                + comicarr.CONFIG.DUPECONSTRAINT
                            )
                            removedupe = False
                            if "cbr" in comicarr.CONFIG.DUPECONSTRAINT or "cbz" in comicarr.CONFIG.DUPECONSTRAINT:
                                if "cbr" in comicarr.CONFIG.DUPECONSTRAINT:
                                    if tmpfc["ComicFilename"].endswith(".cbz"):
                                        logger.fdebug(
                                            "[DUPECHECK-CBR PRIORITY] [#"
                                            + reiss["Issue_Number"]
                                            + "] Retaining currently scanned in file : "
                                            + di["filename"]
                                        )
                                        issuedupe = "yes"
                                        break
                                    else:
                                        logger.fdebug(
                                            "[DUPECHECK-CBR PRIORITY] [#"
                                            + reiss["Issue_Number"]
                                            + "] Retaining newly scanned in file : "
                                            + tmpfc["ComicFilename"]
                                        )
                                        removedupe = True
                                elif "cbz" in comicarr.CONFIG.DUPECONSTRAINT:
                                    if tmpfc["ComicFilename"].endswith(".cbr"):
                                        logger.fdebug(
                                            "[DUPECHECK-CBZ PRIORITY] [#"
                                            + reiss["Issue_Number"]
                                            + "] Retaining currently scanned in filename : "
                                            + di["filename"]
                                        )
                                        issuedupe = "yes"
                                        break
                                    else:
                                        logger.fdebug(
                                            "[DUPECHECK-CBZ PRIORITY] [#"
                                            + reiss["Issue_Number"]
                                            + "] Retaining newly scanned in filename : "
                                            + tmpfc["ComicFilename"]
                                        )
                                        removedupe = True

                            if comicarr.CONFIG.DUPECONSTRAINT == "filesize":
                                if tmpfc["ComicSize"] <= di["filesize"]:
                                    logger.fdebug(
                                        "[DUPECHECK-FILESIZE PRIORITY] [#"
                                        + reiss["Issue_Number"]
                                        + "] Retaining currently scanned in filename : "
                                        + di["filename"]
                                    )
                                    issuedupe = "yes"
                                    break
                                else:
                                    logger.fdebug(
                                        "[DUPECHECK-FILESIZE PRIORITY] [#"
                                        + reiss["Issue_Number"]
                                        + "] Retaining newly scanned in filename : "
                                        + tmpfc["ComicFilename"]
                                    )
                                    removedupe = True

                            if removedupe:
                                issuedupe_temp = []
                                tmphavefiles = 0
                                for x in issuedupechk:
                                    if x["filename"] != di["filename"]:
                                        issuedupe_temp.append(x)
                                        tmphavefiles += 1
                                issuedupechk = issuedupe_temp
                                havefiles = tmphavefiles + len(annualdupechk)
                                foundchk = False
                                break

                    if issuedupe == "no":
                        if not foundchk:
                            logger.fdebug(
                                module
                                + " Matched...issue: "
                                + rescan["ComicName"]
                                + "#"
                                + reiss["Issue_Number"]
                                + " --- "
                                + str(int_iss)
                            )
                            havefiles += 1
                            haveissue = "yes"
                            isslocation = tmpfc["ComicFilename"]
                            issSize = str(tmpfc["ComicSize"])
                            logger.fdebug(module + " .......filename: " + isslocation)
                            logger.fdebug(module + " .......filesize: " + str(tmpfc["ComicSize"]))
                            issuedupechk.append(
                                {
                                    "fcdigit": fcdigit,
                                    "filename": tmpfc["ComicFilename"],
                                    "filesize": tmpfc["ComicSize"],
                                    "issueyear": issyear,
                                    "issueid": reiss["IssueID"],
                                }
                            )
                            break

                if issuedupe == "yes":
                    logger.fdebug(module + " I should break out here because of a dupe.")
                    break

                if haveissue == "yes" or issuedupe == "yes":
                    break
                n += 1
        else:
            if tmpfc["AnnualComicID"]:
                ANNComicID = tmpfc["AnnualComicID"]
                logger.fdebug(
                    module
                    + " Forcing ComicID to "
                    + str(ANNComicID)
                    + " in case of duplicate numbering across volumes."
                )
                reannuals = db.select_all(
                    select(annuals).where(
                        (annuals.c.ComicID == ComicID)
                        & (annuals.c.ReleaseComicID == ANNComicID)
                        & (annuals.c.Deleted != 1)
                    )
                )
            else:
                reannuals = db.select_all(
                    select(annuals).where((annuals.c.ComicID == ComicID) & (annuals.c.Deleted != 1))
                )
                ANNComicID = ComicID

            if len(reannuals) == 0:
                reannuals = db.select_all(select(issues).where(issues.c.ComicID == ComicID))
                ANNComicID = None

            fcnew = shlex.split(str(temploc))
            len(fcnew)
            n = 0
            reann = None
            while True:
                try:
                    reann = reannuals[n]
                except IndexError:
                    break
                int_iss = configured.issuedigits(reann["Issue_Number"])
                issyear = (reann["IssueDate"] or "")[:4]
                old_status = reann["Status"]

                year_check = re.findall(r"(\d{4})(?=[\s]|annual\b|$)", temploc, flags=re.I)
                if year_check:
                    ann_line = "%s annual" % year_check[0]
                    logger.fdebug("ann_line: %s" % ann_line)
                    fcdigit = configured.issuedigits("1")
                else:
                    fcdigit = configured.issuedigits(re.sub("annual", "", temploc.lower()).strip())
                if fcdigit == 999999999999999:
                    fcdigit = configured.issuedigits(re.sub("special", "", temploc.lower()).strip())

                if int(fcdigit) == int_iss and ANNComicID is not None:
                    logger.fdebug(module + " [" + str(ANNComicID) + "] Annual match - issue : " + str(int_iss))

                    multiplechk = False
                    annualdupe = "no"
                    foundchk = False

                    if len(mc_annual) > 1:
                        for ma in mc_annual:
                            if ma["Int_IssueNumber"] == int_iss:
                                if ma["IssueID"] == reann["IssueID"]:
                                    logger.fdebug(
                                        module
                                        + " IssueID matches to multiple issues : "
                                        + str(ma["IssueID"])
                                        + ". Checking dupe."
                                    )
                                    logger.fdebug(
                                        module
                                        + " maISSUEYEAR: "
                                        + str(ma["IssueYear"])
                                        + " -- issyear : "
                                        + str(issyear)
                                    )
                                    if any(ma["IssueID"] == d["issueid"] for d in annualdupechk):
                                        logger.fdebug(
                                            module + " IssueID already within dupe. Checking next if available."
                                        )
                                        multiplechk = True
                                        break
                                    if (
                                        ma["IssueYear"]
                                        and issyear
                                        and ma["IssueYear"] in tmpfc["ComicFilename"]
                                        and issyear == ma["IssueYear"]
                                    ):
                                        vchk = tmpfc["ComicFilename"].find(ma["IssueYear"])
                                        if tmpfc["ComicFilename"][vchk - 1].lower() == "v":
                                            multiplechk = True
                                        else:
                                            logger.fdebug(module + " Matched to year within filename : " + str(issyear))
                                            multiplechk = False
                                            ANNComicID = ack["ReleaseComicID"]
                                            break
                                    else:
                                        logger.fdebug(
                                            module + " Did not match to year within filename : " + str(issyear)
                                        )
                                        multiplechk = True
                    if multiplechk:
                        n += 1
                        continue

                    for di in annualdupechk:
                        if di["fcdigit"] == fcdigit and di["issueid"] == reann["IssueID"]:
                            logger.fdebug(
                                "[DUPECHECK] Duplicate issue detected ["
                                + di["filename"]
                                + "] ["
                                + tmpfc["ComicFilename"]
                                + "]"
                            )
                            logger.fdebug(
                                "[DUPECHECK] Based on duplication preferences I will retain based on : "
                                + comicarr.CONFIG.DUPECONSTRAINT
                            )
                            removedupe = False
                            if "cbr" in comicarr.CONFIG.DUPECONSTRAINT or "cbz" in comicarr.CONFIG.DUPECONSTRAINT:
                                if "cbr" in comicarr.CONFIG.DUPECONSTRAINT:
                                    if tmpfc["ComicFilename"].endswith(".cbz"):
                                        logger.fdebug(
                                            "[DUPECHECK-CBR PRIORITY] [#"
                                            + reann["Issue_Number"]
                                            + "] Retaining currently scanned in file : "
                                            + di["filename"]
                                        )
                                        annualdupe = "yes"
                                        break
                                    else:
                                        logger.fdebug(
                                            "[DUPECHECK-CBR PRIORITY] [#"
                                            + reann["Issue_Number"]
                                            + "] Retaining newly scanned in file : "
                                            + tmpfc["ComicFilename"]
                                        )
                                        removedupe = True
                                elif "cbz" in comicarr.CONFIG.DUPECONSTRAINT:
                                    if tmpfc["ComicFilename"].endswith(".cbr"):
                                        logger.fdebug(
                                            "[DUPECHECK-CBZ PRIORITY] [#"
                                            + reann["Issue_Number"]
                                            + "] Retaining currently scanned in filename : "
                                            + di["filename"]
                                        )
                                        annualdupe = "yes"
                                        break
                                    else:
                                        logger.fdebug(
                                            "[DUPECHECK-CBZ PRIORITY] [#"
                                            + reann["Issue_Number"]
                                            + "] Retaining newly scanned in filename : "
                                            + tmpfc["ComicFilename"]
                                        )
                                        removedupe = True

                            if comicarr.CONFIG.DUPECONSTRAINT == "filesize":
                                if tmpfc["ComicSize"] <= di["filesize"]:
                                    logger.fdebug(
                                        "[DUPECHECK-FILESIZE PRIORITY] [#"
                                        + reann["Issue_Number"]
                                        + "] Retaining currently scanned in filename : "
                                        + di["filename"]
                                    )
                                    annualdupe = "yes"
                                    break
                                else:
                                    logger.fdebug(
                                        "[DUPECHECK-FILESIZE PRIORITY] [#"
                                        + reann["Issue_Number"]
                                        + "] Retaining newly scanned in filename : "
                                        + tmpfc["ComicFilename"]
                                    )
                                    removedupe = True

                            if removedupe:
                                annualdupe_temp = []
                                tmphavefiles = 0
                                for x in annualdupechk:
                                    logger.fdebug("Comparing x: " + x["filename"] + " to di:" + di["filename"])
                                    if x["filename"] != di["filename"]:
                                        annualdupe_temp.append(x)
                                        tmphavefiles += 1
                                annualdupechk = annualdupe_temp
                                havefiles = tmphavefiles + len(issuedupechk)
                                foundchk = False
                                break

                    if annualdupe == "no":
                        if not foundchk:
                            logger.fdebug(
                                module
                                + " Matched...annual issue: "
                                + rescan["ComicName"]
                                + "#"
                                + str(reann["Issue_Number"])
                                + " --- "
                                + str(int_iss)
                            )
                            havefiles += 1
                            haveissue = "yes"
                            isslocation = tmpfc["ComicFilename"]
                            issSize = str(tmpfc["ComicSize"])
                            logger.fdebug(module + " .......filename: " + isslocation)
                            logger.fdebug(module + " .......filesize: " + str(tmpfc["ComicSize"]))
                            annualdupechk.append(
                                {
                                    "fcdigit": int(fcdigit),
                                    "anncomicid": ANNComicID,
                                    "filename": tmpfc["ComicFilename"],
                                    "filesize": tmpfc["ComicSize"],
                                    "issueyear": issyear,
                                    "issueid": reann["IssueID"],
                                }
                            )
                        break

                if annualdupe == "yes":
                    logger.fdebug(module + " I should break out here because of a dupe.")
                    break

                if haveissue == "yes" or annualdupe == "yes":
                    break
                n += 1

        if issuedupe == "yes" or annualdupe == "yes":
            pass
        else:
            writeit = True
            try:
                if comicarr.CONFIG.ANNUALS_ON:
                    if any(["annual" in temploc.lower(), "special" in temploc.lower()]):
                        if reann is None:
                            logger.fdebug(
                                module
                                + " Annual/Special present in location, but series does not have any annuals attached to it - Ignoring"
                            )
                            writeit = False
                        else:
                            iss_id = reann["IssueID"]
                    else:
                        iss_id = reiss["IssueID"]
                else:
                    if any(["annual" in temploc.lower(), "special" in temploc.lower()]):
                        logger.fdebug(
                            module
                            + " Annual support not enabled, but annual/special issue present within directory. Ignoring issue."
                        )
                        writeit = False
                    else:
                        iss_id = reiss["IssueID"]
            except Exception:
                logger.warn(
                    module
                    + " An error occured trying to get the relevant issue data. This is probably due to the series not having proper issue data."
                )
                logger.warn(
                    module
                    + " you should either Refresh the series, and/or submit an issue on github in regards to the series and the error."
                )
                return

            if writeit and haveissue == "yes":
                if archive:
                    issStatus = "Archived"
                else:
                    issStatus = "Downloaded"

                if ANNComicID:
                    d_annuals.append(
                        {"Status": issStatus, "ComicSize": issSize, "Location": isslocation, "IssueID": iss_id}
                    )
                    annID_to_ignore.append(str(iss_id))
                    ANNComicID = None
                else:
                    d_issues.append(
                        {"Status": issStatus, "ComicSize": issSize, "Location": isslocation, "IssueID": iss_id}
                    )
                    issID_to_ignore.append(str(iss_id))
            else:
                ANNComicID = None
        fn += 1
    logger.fdebug("[haves] issue_status_generation took %s" % (datetime.datetime.now() - a_start))

    b_start = datetime.datetime.now()
    _bulk_update_issue_rows(issues, d_issues, ("Status", "ComicSize", "Location"))
    _bulk_update_issue_rows(annuals, d_annuals, ("Status", "ComicSize", "Location"))
    logger.fdebug("[haves] issue_status_writing took %s" % (datetime.datetime.now() - b_start))

    reforce = db.select_all(select(issues).where((issues.c.ComicID == ComicID) & (issues.c.forced_file == 1)))
    if reforce is not None:
        for rfc in reforce:
            logger.fdebug(
                "%s [FORCED-MATCH] Matched...issue: %s #%s --- %s"
                % (module, rfc["ComicName"], rfc["Issue_Number"], rfc["Int_IssueNumber"])
            )
            havefiles += 1
            logger.fdebug("%s .......filename: %s" % (module, rfc["Location"]))
            logger.fdebug("%s .......filesize: %s" % (module, rfc["ComicSize"]))

            controlValueDict = {"IssueID": rfc["IssueID"]}

            if archive:
                issStatus = "Archived"
            else:
                issStatus = "Downloaded"

            issID_to_ignore.append(rfc["IssueID"])

            newValueDict = {"Location": rfc["Location"], "ComicSize": rfc["ComicSize"], "Status": issStatus}

            db.upsert("issues", newValueDict, controlValueDict)

    update_iss = []
    update_ann = []
    retainedfiles = 0
    cnt = 0
    u_start = datetime.datetime.now()
    for genlist in common_utilities.chunker(issID_to_ignore, 200):
        stmt = select(issues).where((issues.c.ComicID == genlist[0]) & (issues.c.IssueID.notin_(genlist[1:])))
        chkthis = db.select_all(stmt)
        if chkthis is None:
            pass
        else:
            for chk in chkthis:
                if chk["IssueID"] in issID_to_ignore:
                    continue

                old_status = chk["Status"]

                if pause_status:
                    issStatus = old_status
                    logger.fdebug(
                        "[PAUSE_ISSUE_CHECK_STATUS_CHECK] series is paused, keeping status of %s for issue #%s"
                        % (issStatus, chk["Issue_Number"])
                    )
                else:
                    if old_status == "Downloaded" and left_behind(chk):
                        retainedfiles += 1
                        continue
                    if old_status == "Downloaded":
                        issStatus = "Archived"
                    else:
                        continue
                update_iss.append({"Status": issStatus, "IssueID": chk["IssueID"]})

    for genlist in common_utilities.chunker(annID_to_ignore, 200):
        stmt = select(annuals).where(
            (annuals.c.ComicID == genlist[0]) & (annuals.c.Deleted != 1) & (annuals.c.IssueID.notin_(genlist[1:]))
        )
        chkthis = db.select_all(stmt)
        if chkthis is None:
            pass
        else:
            for chk in chkthis:
                if chk["IssueID"] in annID_to_ignore:
                    continue

                old_status = chk["Status"]

                if pause_status:
                    issStatus = old_status
                    logger.fdebug(
                        "[PAUSE_ANNUAL_CHECK_STATUS_CHECK] series is paused, keeping status of %s for issue #%s"
                        % (issStatus, chk["Issue_Number"])
                    )
                else:
                    if old_status == "Downloaded" and left_behind(chk):
                        retainedfiles += 1
                        continue
                    if old_status == "Downloaded":
                        issStatus = "Archived"
                    else:
                        continue
                update_ann.append({"Status": issStatus, "IssueID": chk["IssueID"]})

    logger.fdebug("[nothaves] issue_status_generation_time_taken: %s" % (datetime.datetime.now() - u_start))

    if any([len(update_iss) > 0, len(update_ann) > 0]):
        r_start = datetime.datetime.now()
        _bulk_update_issue_rows(issues, update_iss, ("Status",))
        _bulk_update_issue_rows(annuals, update_ann, ("Status",))
        logger.fdebug("[nothaves] issue_status_writing took %s" % (datetime.datetime.now() - r_start))
        logger.info(
            "%s Updated the status of %s issues for %s (%s) that were not found."
            % (module, len(update_iss), rescan["ComicName"], rescan["ComicYear"])
        )
    havefiles += retainedfiles
    logger.info("%s Total files located: %s" % (module, havefiles))

    foundcount = havefiles
    arcfiles = 0
    arcanns = 0
    arcissues_row = db.select_one(
        select(func.count()).select_from(issues).where((issues.c.ComicID == ComicID) & (issues.c.Status == "Archived"))
    )
    arcissues_cnt = list(arcissues_row.values())[0] if arcissues_row else 0
    if int(arcissues_cnt) > 0:
        arcfiles = arcissues_cnt
    arcannuals_row = db.select_one(
        select(func.count())
        .select_from(annuals)
        .where((annuals.c.ComicID == ComicID) & (annuals.c.Status == "Archived") & (annuals.c.Deleted != 1))
    )
    arcannuals_cnt = list(arcannuals_row.values())[0] if arcannuals_row else 0
    if int(arcannuals_cnt) > 0:
        arcanns = arcannuals_cnt

    if havefiles == 0:
        if arcfiles > 0 or arcanns > 0:
            arcfiles = arcfiles + arcanns
            havefiles = havefiles + arcfiles
            logger.fdebug(
                "%s Adjusting have total to %s because of %s files already"
                " in an Archive status" % (module, havefiles, arcfiles)
            )
    else:
        if (arcfiles + arcanns) > 0:
            logger.fdebug(
                "%s %s issue(s) are in an Archive status already."
                " Increasing Have total from %s to include these archives." % (module, arcfiles + arcanns, havefiles)
            )
            havefiles = havefiles + (arcfiles + arcanns)

    ignorecount = 0
    if comicarr.CONFIG.IGNORE_HAVETOTAL:
        ignoresi_row = db.select_one(
            select(func.count())
            .select_from(issues)
            .where((issues.c.ComicID == ComicID) & (issues.c.Status == "Ignored"))
        )
        ignoresa_row = db.select_one(
            select(func.count())
            .select_from(annuals)
            .where((annuals.c.ComicID == ComicID) & (annuals.c.Status == "Ignored") & (annuals.c.Deleted != 1))
        )
        ignoresi = list(ignoresi_row.values())[0] if ignoresi_row else 0
        ignoresa = list(ignoresa_row.values())[0] if ignoresa_row else 0
        ignorecount = int(ignoresi) + int(ignoresa)
        if ignorecount > 0:
            havefiles = havefiles + ignorecount
            logger.fdebug(
                "%s Adjusting have total to %s because of %s Ignored files." % (module, havefiles, ignorecount)
            )

    snatchedcount = 0
    if comicarr.CONFIG.SNATCHED_HAVETOTAL:
        snatches_row = db.select_one(
            select(func.count())
            .select_from(issues)
            .where((issues.c.ComicID == ComicID) & (issues.c.Status == "Snatched"))
        )
        snatches_cnt = list(snatches_row.values())[0] if snatches_row else 0
        if int(snatches_cnt) > 0:
            snatchedcount = snatches_cnt
            havefiles = havefiles + snatchedcount
            logger.fdebug(
                "%s Adjusting have total to %s because of %s Snatched files." % (module, havefiles, snatchedcount)
            )

    cnt = 0
    downchk = None
    for genlist in common_utilities.chunker(issID_to_ignore, 200):
        stmt = select(issues).where(
            (issues.c.Status == "Downloaded")
            & (issues.c.ComicID == genlist[0])
            & (issues.c.IssueID.notin_(genlist[1:]))
        )
        rows = db.select_all(stmt)
        for r in rows:
            r["type"] = 0
        if cnt == 0:
            downchk = rows
        else:
            downchk += rows
        cnt += 1
    cnt = 0
    for genlist in common_utilities.chunker(annID_to_ignore, 200):
        stmt = select(annuals).where(
            (annuals.c.Status == "Downloaded")
            & (annuals.c.ComicID == genlist[0])
            & (annuals.c.Deleted != 1)
            & (annuals.c.IssueID.notin_(genlist[1:]))
        )
        rows = db.select_all(stmt)
        for r in rows:
            r["type"] = 1
        if any([cnt == 0, downchk is None]):
            downchk = rows
        else:
            downchk += rows
        cnt += 1

    if downchk is None:
        pass
    else:
        archivedissues = 0
        dvalues = []

        for down in downchk:
            if left_behind(down):
                continue
            if down["type"] == 1:
                dtable = "annuals"
            else:
                dtable = "issues"

            if down["Location"] is None:
                logger.fdebug(
                    "%s Location does not exist which means file was not downloaded"
                    " successfully, or was moved." % (module)
                )
                controlValue = {"IssueID": down["IssueID"]}
                newValue = {"Status": "Archived"}
                db.upsert(dtable, newValue, controlValue)
                archivedissues += 1
            else:
                tmp_location = [x["ComicLocation"] for x in fc["comiclist"] if x["ComicFilename"] == down["Location"]]
                if not tmp_location:
                    logger.info(
                        "[%s] Changing status of #%s from Downloaded to Archived -"
                        " cannot locate file %s" % (down["Issue_Number"], down["IssueID"], down["Location"])
                    )
                    try:
                        controlValue = {"IssueID": down["IssueID"]}
                        newValue = {"Status": "Archived"}
                        logger.info("[%s] %s : %s" % (dtable, newValue, controlValue))
                        db.upsert(dtable, newValue, controlValue)
                    except Exception as e:
                        logger.error("error: %s" % e)
                    archivedissues += 1

        if archivedissues > 0:
            logger.fdebug(
                "%s I have changed the status of %s issues to a status of Archived,"
                " as I now cannot locate them in the series directory." % (module, len(dvalues))
            )
        havefiles = havefiles + archivedissues

    combined_total = iscnt + anncnt
    if comicarr.CONFIG.IGNORE_TOTAL:
        ignoresa_row = db.select_one(
            select(func.count())
            .select_from(issues)
            .where((issues.c.ComicID == ComicID) & (issues.c.Status == "Ignored"))
        )
        ignoresb_row = db.select_one(
            select(func.count())
            .select_from(annuals)
            .where((annuals.c.ComicID == ComicID) & (annuals.c.Status == "Ignored") & (annuals.c.Deleted != 1))
        )
        ignoresa_cnt = list(ignoresa_row.values())[0] if ignoresa_row else 0
        ignoresb_cnt = list(ignoresb_row.values())[0] if ignoresb_row else 0
        ignorecnt = ignoresa_cnt + ignoresb_cnt

        if ignorecnt > 0:
            combined_total -= ignorecnt
            logger.fdebug(
                "%s Reducing total comics in series from %s to %s because of %s ignored files."
                % (module, (iscnt + anncnt), combined_total, ignorecnt)
            )

    if havefiles > combined_total:
        logger.warn(
            module
            + " It looks like you have physical issues in the series directory, but are forcing these issues to an Archived Status. Adjusting have counts."
        )
        havefiles = havefiles - arcfiles

    totals(ComicID, havefiles, combined_total, module, recheck=recheck)
    totalarc = arcfiles + archivedissues

    if comicarr.CONFIG.ENFORCE_PERMS:
        logger.fdebug(module + " Ensuring permissions/ownership enforced for series: " + rescan["ComicName"])
        directories.setperms(rescan["ComicLocation"])
    logger.info(
        module
        + " I have physically found "
        + str(foundcount)
        + " issues, ignored "
        + str(ignorecount)
        + " issues, snatched "
        + str(snatchedcount)
        + " issues, and accounted for "
        + str(totalarc)
        + " in an Archived state [ Total Issue Count: "
        + str(havefiles)
        + " / "
        + str(combined_total)
        + " ]"
    )


def totals(ComicID, havefiles=None, totalfiles=None, module=None, issueid=None, file=None, recheck=False):
    if module is None:
        module = "[FILE-RESCAN]"
    filetable = "issues"
    if any([havefiles is None, havefiles == "+1"]):
        if havefiles is None:
            hf = db.select_one(select(comics.c.Have, comics.c.Total).where(comics.c.ComicID == ComicID))
            havefiles = int(hf["Have"])
            totalfiles = int(hf["Total"])
        else:
            hf = db.select_one(
                select(comics.c.Have, comics.c.Total, issues.c.Status.label("IssStatus"))
                .select_from(comics.join(issues, comics.c.ComicID == issues.c.ComicID))
                .where(issues.c.IssueID == issueid)
            )
            if hf is None:
                hf = db.select_one(
                    select(comics.c.Have, comics.c.Total, annuals.c.Status.label("IssStatus"))
                    .select_from(comics.join(annuals, comics.c.ComicID == annuals.c.ComicID))
                    .where((annuals.c.IssueID == issueid) & (annuals.c.Deleted != 1))
                )
                filetable = "annuals"
            totalfiles = int(hf["Total"])
            logger.fdebug("totalfiles: %s" % totalfiles)
            logger.fdebug("status: %s" % hf["IssStatus"])
            if hf["IssStatus"] != "Downloaded":
                try:
                    havefiles = int(hf["Have"]) + 1
                    if havefiles > totalfiles and recheck is False:
                        recheck = True
                        return force_rescan(ComicID, recheck=recheck)
                except TypeError:
                    if totalfiles == 1:
                        havefiles = 1
                    else:
                        logger.warn(
                            "Total issues for this series [ComiciD:%s/IssueID:%s] is not 1 when it should be. This is probably a mistake and the series should be refreshed."
                            % (ComicID, issueid)
                        )
                        havefiles = 0
                logger.fdebug("incremented havefiles: %s" % havefiles)
            else:
                havefiles = int(hf["Have"])
                logger.fdebug("untouched havefiles: %s" % havefiles)
    controlValueStat = {"ComicID": ComicID}
    newValueStat = {"Have": havefiles, "Total": totalfiles, "FilesUpdated": common_dates.now()}

    db.upsert("comics", newValueStat, controlValueStat)
    if file is not None:
        controlValueStat = {"IssueID": issueid, "ComicID": ComicID}
        newValueStat = {"ComicSize": os.path.getsize(file)}
        db.upsert(filetable, newValueStat, controlValueStat)
