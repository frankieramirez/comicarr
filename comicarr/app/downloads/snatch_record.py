#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Snatch bookkeeping seam (ADR-0005, Foundations plan section 2).

``record_release_link`` writes the ``nzblog`` row that ties a release to an
issue for post-processing. ``record_snatch`` marks the issue Snatched, writes
the ``snatched`` history row and the journal ``snatched`` transition.

The bodies, ``nzblog``, ``foundsearch`` and ``no_searchresults``, moved here
from ``comicarr/updater.py`` (#1460) and keep their legacy signatures for the
search and post-processing callers.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

import comicarr
from comicarr import db, helpers, logger
from comicarr.app.manga import volumes as manga_volumes
from comicarr.app.manga.ledger import volume_number_from_id
from comicarr.tables import annuals, comics, issues, storyarcs, weekly
from comicarr.tables import nzblog as nzblog_tbl


def record_release_link(
    issue_id: str | None,
    nzb_name: str,
    comic_name: str,
    *,
    provider: str,
    nzb_id: str | None = None,
    one_off: bool = False,
) -> dict[str, Any]:
    """Record the release-to-issue link (``nzblog``)."""
    return nzblog(issue_id, nzb_name, comic_name, id=nzb_id, prov=provider, oneoff=one_off)


def record_snatch(
    comic_id: str,
    issue_id: str,
    *,
    mode: str,
    provider: str,
    hash: str | None = None,
    journal_release_key: str | None = None,
    journal_managed: bool = False,
) -> None:
    """Record that a release was snatched (``foundsearch``)."""
    foundsearch(
        comic_id,
        issue_id,
        mode=mode,
        provider=provider,
        hash=hash,
        journal_release_key=journal_release_key,
        journal_managed=journal_managed,
    )


def no_searchresults(ComicID):
    controlValue = {"ComicID": ComicID}
    newValue = {"Status": "Error", "LatestDate": "Error", "LatestIssue": "Error"}
    db.upsert("comics", newValue, controlValue)


def nzblog(IssueID, NZBName, ComicName, SARC=None, IssueArcID=None, id=None, prov=None, alt_nzbname=None, oneoff=False):
    newValue = {"NZBName": NZBName}

    if SARC:
        logger.fdebug("Story Arc (SARC) detected as: " + str(SARC))
        IssueID = "S" + str(IssueArcID)
        newValue["SARC"] = SARC

    if oneoff is True:
        logger.fdebug(
            "One-Off download detected when updating - crossing the t's and dotting the i's so things work..."
        )
        newValue["OneOff"] = True

    if IssueID is None or IssueID == "None":
        if any([comicarr.CONFIG.HIGHCOUNT == 0, comicarr.CONFIG.HIGHCOUNT is None]):
            comicarr.CONFIG.HIGHCOUNT = 900000
        else:
            comicarr.CONFIG.HIGHCOUNT += 1

        IssueID = comicarr.CONFIG.HIGHCOUNT

    controlValue = {"IssueID": IssueID, "PROVIDER": prov}

    if id:
        logger.info("setting the nzbid for this download grabbed by " + prov + " in the nzblog to : " + str(id))
        newValue["ID"] = id

    if alt_nzbname:
        logger.info(
            "setting the alternate nzbname for this download grabbed by " + prov + " in the nzblog to : " + alt_nzbname
        )
        newValue["AltNZBName"] = alt_nzbname

    chkd = db.select_one(select(nzblog_tbl).where((nzblog_tbl.c.IssueID == IssueID) & (nzblog_tbl.c.PROVIDER == prov)))
    if chkd is None:
        pass
    else:
        altnames = chkd["AltNZBName"]
        if any([altnames is None, altnames == ""]):
            with db.get_engine().begin() as conn:
                conn.execute(
                    nzblog_tbl.delete().where((nzblog_tbl.c.IssueID == IssueID) & (nzblog_tbl.c.PROVIDER == prov))
                )
            logger.fdebug("Deleted stale entry from nzblog for IssueID: " + str(IssueID) + " [" + prov + "]")
    db.upsert("nzblog", newValue, controlValue)

    return {"IssueID": IssueID, "NZBName": NZBName, "PROVIDER": prov}


def foundsearch(
    ComicID,
    IssueID,
    mode=None,
    down=None,
    provider=None,
    SARC=None,
    IssueArcID=None,
    module=None,
    hash=None,
    crc=None,
    comicname=None,
    issuenumber=None,
    pullinfo=None,
    nzbname=None,
    journal_release_key=None,
    journal_managed=False,
):

    if module is None:
        module = ""
    module += "[UPDATER]"

    modcomicname = False

    logger.fdebug(module + " comicid: " + str(ComicID))
    logger.fdebug(module + " issueid: " + str(IssueID))
    # A manga volume grab carries a volume id ("{comicId}-v{n}"). Volumes are
    # not issues (ADR-0004), so there is no issue row to read or mark (#1279).
    manga_volume = volume_number_from_id(ComicID, IssueID) if mode not in ("pullwant", "story_arc") else None
    if mode != "pullwant":
        if manga_volume is not None:
            comic = db.select_one(select(comics).where(comics.c.ComicID == ComicID))
            ComicName = comic["ComicName"]
            IssueNum = "Volume %s" % manga_volume
        elif mode != "story_arc":
            comic = db.select_one(select(comics).where(comics.c.ComicID == ComicID))
            ComicName = comic["ComicName"]
            if mode == "want_ann":
                issue = db.select_one(select(annuals).where(annuals.c.IssueID == IssueID))
                if ComicName != issue["ReleaseComicName"] + " Annual":
                    ComicName = issue["ReleaseComicName"]
                    modcomicname = True
            else:
                issue = db.select_one(select(issues).where(issues.c.IssueID == IssueID))
            issue["IssueDate"][:4]
            IssueNum = issue["Issue_Number"]

        else:
            issue = db.select_one(select(storyarcs).where(storyarcs.c.IssueArcID == IssueArcID))
            ComicName = issue["ComicName"]
            issue["IssueYEAR"]
            IssueNum = issue["IssueNumber"]
    else:
        oneinfo = db.select_one(select(weekly).where(weekly.c.IssueID == IssueID))
        if oneinfo is None:
            ComicName = comicname
            IssueNum = issuenumber
        else:
            ComicName = oneinfo["COMIC"]
            IssueNum = oneinfo["ISSUE"]

    if down is None:
        logger.info(module + " Updating status to snatched")
        logger.fdebug(module + " Provider is " + provider)
        if hash:
            logger.fdebug(module + " Hash set to : " + hash)
        newValue = {"Status": "Snatched"}
        if mode == "story_arc":
            cValue = {"IssueArcID": IssueArcID}
            snatchedupdate = {"IssueArcID": IssueArcID}
            db.upsert("storyarcs", newValue, cValue)
            snatchedupdate = {"IssueID": IssueArcID, "Status": "Snatched", "Provider": provider}

        else:
            if manga_volume is not None:
                manga_volumes.record_volume(ComicID, manga_volume, manga_volumes.SNATCHED)
            elif mode == "want_ann":
                controlValue = {"IssueID": IssueID}
                db.upsert("annuals", newValue, controlValue)
            else:
                controlValue = {"IssueID": IssueID}
                if mode != "pullwant":
                    db.upsert("issues", newValue, controlValue)

            snatchedupdate = {"IssueID": IssueID, "Status": "Snatched", "Provider": provider}

        if mode == "story_arc":
            IssueNum = issue["IssueNumber"]
            newsnatchValues = {
                "ComicName": ComicName,
                "ComicID": ComicID,
                "Issue_Number": IssueNum,
                "DateAdded": helpers.now(),
                "Status": "Snatched",
                "Hash": hash,
            }

            db.upsert("snatched", newsnatchValues, snatchedupdate)

        elif manga_volume is not None:
            newsnatchValues = {
                "ComicName": ComicName,
                "ComicID": ComicID,
                "Issue_Number": IssueNum,
                "DateAdded": helpers.now(),
                "Status": "Snatched",
                "Hash": hash,
            }

            db.upsert("snatched", newsnatchValues, snatchedupdate)

        elif mode != "pullwant":
            if modcomicname:
                IssueNum = issue["Issue_Number"]
            else:
                if mode == "want_ann":
                    IssueNum = "Annual " + issue["Issue_Number"]
                else:
                    IssueNum = issue["Issue_Number"]

            newsnatchValues = {
                "ComicName": ComicName,
                "ComicID": ComicID,
                "Issue_Number": IssueNum,
                "DateAdded": helpers.now(),
                "Status": "Snatched",
                "Hash": hash,
            }

            db.upsert("snatched", newsnatchValues, snatchedupdate)

        else:
            newsnatchValues = {
                "ComicName": ComicName,
                "ComicID": ComicID,
                "IssueID": IssueID,
                "Issue_Number": IssueNum,
                "DateAdded": helpers.now(),
                "Status": "Snatched",
                "Hash": hash,
            }

            db.upsert("snatched", newsnatchValues, snatchedupdate)

        chkit = db.select_one(select(weekly).where((weekly.c.ComicID == ComicID) & (weekly.c.IssueID == IssueID)))

        if chkit is not None:
            comicname = chkit["COMIC"]
            issue = chkit["ISSUE"]

            ctlVal = {"ComicID": ComicID, "IssueID": IssueID}
            db.upsert("weekly", {"STATUS": "Snatched"}, ctlVal)

            newValue["IssueNumber"] = issue
            newValue["ComicName"] = comicname
            newValue["Status"] = "Snatched"
            if pullinfo is not None:
                newValue["weeknumber"] = pullinfo["weeknumber"]
                newValue["year"] = pullinfo["year"]
            else:
                try:
                    newValue["weeknumber"] = chkit["weeknumber"]
                    newValue["year"] = chkit["year"]
                except Exception:
                    pass

            db.upsert("oneoffhistory", newValue, ctlVal)

        logger.info("%s Updated the status (Snatched) complete for %s Issue: %s" % (module, ComicName, IssueNum))

        try:
            from comicarr.app.downloads import journal

            if journal_managed:
                logger.fdebug(
                    "%s Pipeline journal is already owned by the accepted handoff; skipping generic snatched row."
                    % module
                )
                return
            journal_issueid = snatchedupdate.get("IssueID")
            payload = {
                "issueid": journal_issueid,
                "comicid": ComicID,
                "provider": provider,
                "hash": hash,
                "nzbname": nzbname,
                "mode": mode,
                "comicname": ComicName,
                "issuenumber": IssueNum,
            }
            rkey = journal_release_key or journal.release_key(
                journal_issueid,
                provider,
                nzbname=nzbname,
                hash=hash,
                discriminant=nzbname or payload,
            )
            journal.record_transition(
                rkey,
                journal.SNATCHED,
                payload=payload,
                issueid=journal_issueid,
                provider=provider,
                nzbname=nzbname,
                hash=hash,
            )
        except Exception as e:
            logger.error(
                "%s Journal snatched transition failed for %s (IssueID=%s "
                "provider=%s) — durable snatch is intact, recoverable at "
                "startup: %s" % (module, ComicName, snatchedupdate.get("IssueID"), provider, e)
            )
    else:
        if down == "PP":
            logger.info(module + " Setting status to Post-Processed in history.")
            downstatus = "Post-Processed"
        else:
            logger.info(module + " Setting status to Downloaded in history.")
            downstatus = "Downloaded"
        if mode == "want_ann":
            if not modcomicname:
                IssueNum = "Annual " + IssueNum
        elif mode == "story_arc":
            IssueID = IssueArcID

        snatchedupdate = {"IssueID": IssueID, "Status": downstatus, "Provider": provider}
        newsnatchValues = {
            "ComicName": ComicName,
            "ComicID": ComicID,
            "Issue_Number": IssueNum,
            "DateAdded": helpers.now(),
            "Status": downstatus,
            "crc": crc,
        }
        db.upsert("snatched", newsnatchValues, snatchedupdate)

        if mode == "story_arc":
            cValue = {"IssueArcID": IssueArcID}
            nValue = {"Status": "Downloaded"}
            db.upsert("storyarcs", nValue, cValue)

        elif mode != "pullwant" and manga_volume is None:
            controlValue = {"IssueID": IssueID}
            newValue = {"Status": "Downloaded"}
            if mode == "want_ann":
                db.upsert("annuals", newValue, controlValue)
            else:
                db.upsert("issues", newValue, controlValue)

        chkit = db.select_one(
            select(weekly).where(
                (weekly.c.ComicID == ComicID) & (weekly.c.IssueID == IssueID) & (weekly.c.STATUS == "Snatched")
            )
        )

        if chkit is not None:
            comicname = chkit["COMIC"]
            issue = chkit["ISSUE"]

            ctlVal = {"ComicID": ComicID, "IssueID": IssueID}
            newVal = {"Status": "Downloaded"}
            db.upsert("weekly", {"STATUS": "Downloaded"}, ctlVal)

            newVal["IssueNumber"] = issue
            newVal["ComicName"] = comicname
            newVal["Status"] = "Downloaded"
            if pullinfo is not None:
                newVal["weeknumber"] = pullinfo["weeknumber"]
                newVal["year"] = pullinfo["year"]
            db.upsert("oneoffhistory", newVal, ctlVal)

        logger.info(
            "%s Updating Status (%s) now completed for %s issue: %s" % (module, downstatus, ComicName, IssueNum)
        )
    return
