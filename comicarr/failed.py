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


import os
import re

import feedparser as feedparser
from sqlalchemy import select

import comicarr
from comicarr import db, helpers, logger
from comicarr.tables import annuals, comics, failed, issues, nzblog

FAIL_REASON_RESEARCHING = "download_failed_researching"
FAIL_REASON_NO_AUTO_HANDLING = "download_failed_no_auto_handling"

STATUS_RETRIED = "retried"


def resolve_failed_release_key(
    journal_release_key=None,
    issueid=None,
    provider=None,
    nzbname=None,
    hash=None,
    discriminant=None,
):
    """Prefer a propagated journal_release_key; else derive under existing rules.

    Returns None when no resolvable identity exists so callers skip the journal
    write rather than invent a colliding key.
    """
    if journal_release_key not in (None, ""):
        return str(journal_release_key)

    from comicarr.app.downloads import journal

    if issueid is None and provider in (None, "") and nzbname in (None, "") and hash in (None, ""):
        return None
    return journal.release_key(
        issueid,
        provider,
        nzbname=nzbname,
        hash=hash,
        discriminant=discriminant,
    )


def terminalize_failed_download(
    release_key,
    fail_reason,
    *,
    status=None,
    issueid=None,
    provider=None,
    nzbname=None,
    hash=None,
    payload=None,
    conn=None,
    **fields,
):
    """Record terminal failure through the Needs attention module interface.

    When ``status`` is provided (e.g. STATUS_RETRIED after FAILED_AUTO enqueue),
    it is stamped in the same terminal write so work-queue membership and the
    stage transition stay transactionally honest. Returns the ``won`` signal
    from ``attention.record`` (False when the row was already terminal).
    """
    if release_key in (None, ""):
        return False
    if fail_reason in (None, ""):
        logger.warn("[FAILED-DOWNLOAD] terminalize skipped: empty fail_reason for release_key=%s" % release_key)
        return False

    from comicarr.app.attention import Failure, record

    outcome = record(
        Failure(
            release_key=release_key,
            reason=fail_reason,
            payload=payload,
            issue_id=issueid,
            provider=provider,
            downloader_type=fields.get("downloader_type"),
            nzb_name=nzbname,
            download_hash=hash,
            resolved_as=status,
        ),
        conn=conn,
    )
    if outcome.transition_won:
        logger.fdebug(
            "[FAILED-DOWNLOAD] journal terminalized release_key=%s fail_reason=%s status=%s"
            % (release_key, fail_reason, status)
        )
    return outcome.transition_won


class FailedProcessor(object):
    """Handles Failed downloads that are passed from SABnzbd thus far"""

    def __init__(
        self,
        nzb_name=None,
        nzb_folder=None,
        id=None,
        issueid=None,
        comicid=None,
        prov=None,
        queue=None,
        oneoffinfo=None,
        journal_release_key=None,
    ):
        """
        nzb_name : Full name of the nzb file that has returned as a fail.
        nzb_folder: Full path to the folder of the failed download.
        journal_release_key: Canonical pipeline_journal key when already known
            (PP claim / download_info). Preferred over re-derivation.
        """
        self.nzb_name = nzb_name
        self.nzb_folder = nzb_folder

        self.log = ""

        self.id = id
        if issueid:
            self.issueid = issueid
        else:
            self.issueid = None
        if comicid:
            self.comicid = comicid
        else:
            self.comicid = None

        if oneoffinfo:
            self.oneoffinfo = oneoffinfo
        else:
            self.oneoffinfo = None

        self.prov = prov
        if queue:
            self.queue = queue
        self.valreturn = []
        self.journal_release_key = journal_release_key

    def _log(self, message, level=logger):
        """
        A wrapper for the internal logger which also keeps track of messages and saves them to a string

        message: The string to log (unicode)
        level: The log level to use (optional)
        """
        self.log += message + "\n"

    def Process(self):
        module = "[FAILED-DOWNLOAD]"

        if self.nzb_name and self.nzb_folder:
            self._log("Failed download has been detected: " + self.nzb_name + " in " + self.nzb_folder)

            nzbname = self.nzb_name
            extensions = (".cbr", ".cbz")

            if nzbname.lower().endswith(extensions):
                fd, ext = os.path.splitext(nzbname)
                self._log("Removed extension from nzb: " + ext)
                nzbname = re.sub(str(ext), "", str(nzbname))

            nzbname = re.sub(" ", ".", str(nzbname))
            nzbname = re.sub("[\\,\\:\\?'\\(\\)]", "", str(nzbname))
            nzbname = re.sub(r"[\&]", "and", str(nzbname))
            nzbname = re.sub("_", ".", str(nzbname))

            logger.fdebug(module + " After conversions, nzbname is : " + str(nzbname))
            self._log("nzbname: " + str(nzbname))

            with db.get_engine().connect() as conn:
                stmt = select(nzblog).where(nzblog.c.NZBName == nzbname)
                nzbiss = next((dict(row._mapping) for row in conn.execute(stmt)), None)

            if nzbiss is None:
                self._log("Failure - could not initially locate nzbfile in my database to rename.")
                logger.fdebug(module + " Failure - could not locate nzbfile initially")
                nzbname = re.sub("_", ".", str(nzbname))
                self._log("trying again with this nzbname: " + str(nzbname))
                logger.fdebug(module + " Trying to locate nzbfile again with nzbname of : " + str(nzbname))
                with db.get_engine().connect() as conn:
                    stmt = select(nzblog).where(nzblog.c.NZBName == nzbname)
                    nzbiss = next((dict(row._mapping) for row in conn.execute(stmt)), None)
                if nzbiss is None:
                    logger.error(module + " Unable to locate downloaded file to rename. PostProcessing aborted.")
                    self._log("Unable to locate downloaded file to rename. PostProcessing aborted.")
                    self.valreturn.append({"self.log": self.log, "mode": "stop"})

                    return self.queue.put(self.valreturn)
                else:
                    self._log("I corrected and found the nzb as : " + str(nzbname))
                    logger.fdebug(module + " Auto-corrected and found the nzb as : " + str(nzbname))
                    issueid = nzbiss["IssueID"]
            else:
                issueid = nzbiss["IssueID"]
                logger.fdebug(module + " Issueid: " + str(issueid))
                nzbiss["SARC"]

        else:
            issueid = self.issueid
            with db.get_engine().connect() as conn:
                stmt = select(nzblog).where(nzblog.c.IssueID == issueid)
                nzbiss = next((dict(row._mapping) for row in conn.execute(stmt)), None)
            if nzbiss is None:
                logger.info(
                    module + " Cannot locate corresponding record in download history. This will be implemented soon."
                )
                self.valreturn.append({"self.log": self.log, "mode": "stop"})
                return self.queue.put(self.valreturn)

            nzbname = nzbiss["NZBName"]

        if all([self.id == nzbiss["ID"], self.prov == nzbiss["PROVIDER"]]):
            logger.info(
                "ID %s for provider %s already exists as a Failed item. Continuing the search..."
                % (nzbiss["ID"], nzbiss["PROVIDER"])
            )

        if self.prov is None:
            self.prov = nzbiss["PROVIDER"]
        logger.info(module + " Provider: " + self.prov)

        if self.id is None:
            self.id = nzbiss["ID"]
        logger.info(module + " ID: " + self.id)
        annchk = "no"

        if "annual" in nzbname.lower():
            logger.info(module + " Annual detected.")
            annchk = "yes"
            with db.get_engine().connect() as conn:
                stmt = (
                    select(comics.c.ComicYear, annuals)
                    .select_from(comics.join(annuals, comics.c.ComicID == annuals.c.ComicID, isouter=True))
                    .where(annuals.c.IssueID == issueid, annuals.c.ComicName.isnot(None))
                )
                issuenzb = next((dict(row._mapping) for row in conn.execute(stmt)), None)
        else:
            with db.get_engine().connect() as conn:
                stmt = (
                    select(comics.c.ComicYear, issues)
                    .select_from(comics.join(issues, comics.c.ComicID == issues.c.ComicID, isouter=True))
                    .where(issues.c.IssueID == issueid, issues.c.ComicName.isnot(None))
                )
                issuenzb = next((dict(row._mapping) for row in conn.execute(stmt)), None)

        if issuenzb is not None:
            logger.info(module + " issuenzb found.")
            if helpers.is_number(issueid):
                sandwich = int(issuenzb["IssueID"])
        else:
            logger.info(module + " issuenzb not found.")
            if "S" in issueid:
                sandwich = issueid
            elif "G" in issueid or "-" in issueid:
                sandwich = 1
        try:
            if helpers.is_number(sandwich):
                if sandwich < 900000:
                    pass
            else:
                logger.info("Failed download handling for story-arcs and one-off's are not supported yet. Be patient!")
                self._log(" Unable to locate downloaded file to rename. PostProcessing aborted.")
                self.valreturn.append({"self.log": self.log, "mode": "stop"})
                return self.queue.put(self.valreturn)
        except NameError:
            logger.info("sandwich was not defined. Post-processing aborted...")
            self.valreturn.append({"self.log": self.log, "mode": "stop"})

            return self.queue.put(self.valreturn)

        comicid = issuenzb["ComicID"]
        issuenzb["Issue_Number"]
        logger.info(
            module
            + " Successfully detected as : "
            + issuenzb["ComicName"]
            + " issue: "
            + str(issuenzb["Issue_Number"])
            + " that was downloaded using "
            + self.prov
        )
        self._log(
            "Successfully detected as : "
            + issuenzb["ComicName"]
            + " issue: "
            + str(issuenzb["Issue_Number"])
            + " downloaded using "
            + self.prov
        )

        logger.info(module + " Marking as a Failed Download.")
        self._log("Marking as a Failed Download.")

        ctrlVal = {"IssueID": issueid}
        Vals = {"Status": "Failed"}
        db.upsert("issues", Vals, ctrlVal)

        ctrlVal = {"ID": self.id, "Provider": self.prov, "NZBName": nzbname}
        Vals = {
            "Status": "Failed",
            "ComicName": issuenzb["ComicName"],
            "Issue_Number": issuenzb["Issue_Number"],
            "IssueID": issueid,
            "ComicID": comicid,
            "DateFailed": helpers.now(),
        }
        db.upsert("failed", Vals, ctrlVal)

        logger.info(module + " Successfully marked as Failed.")
        self._log("Successfully marked as Failed.")

        self.issueid = issueid
        if comicarr.CONFIG.FAILED_AUTO:
            self._terminalize_journal(
                FAIL_REASON_RESEARCHING,
                status=STATUS_RETRIED,
                issueid=issueid,
                nzbname=nzbname,
            )
            logger.info(module + " Sending back to search to see if we can find something that will not fail.")
            self._log("Sending back to search to see if we can find something better that will not fail.")
            self.valreturn.append(
                {
                    "self.log": self.log,
                    "mode": "retry",
                    "issueid": issueid,
                    "comicid": comicid,
                    "comicname": issuenzb["ComicName"],
                    "issuenumber": issuenzb["Issue_Number"],
                    "annchk": annchk,
                }
            )

            return self.queue.put(self.valreturn)
        else:
            self._terminalize_journal(
                FAIL_REASON_NO_AUTO_HANDLING,
                status=None,
                issueid=issueid,
                nzbname=nzbname,
            )
            logger.info(
                module + " Stopping search here as automatic handling of failed downloads is not enabled *hint*"
            )
            self._log("Stopping search here as automatic handling of failed downloads is not enabled *hint*")
            self.valreturn.append({"self.log": self.log, "mode": "stop"})
            return self.queue.put(self.valreturn)

    def failed_check(self):

        module = "[FAILED_DOWNLOAD_CHECKER]"

        logger.info("prov  : " + str(self.prov) + "[" + str(self.id) + "]")
        if "indexerguid" in self.id:
            st = self.id.find("searchid:")
            end = self.id.find(",", st)
            self.id = "%" + self.id[:st] + "%" + self.id[end + 1 : len(self.id) - 1] + "%"
            with db.get_engine().connect() as conn:
                stmt = select(failed).where(failed.c.ID.like(self.id))
                chk_fail = next((dict(row._mapping) for row in conn.execute(stmt)), None)
        else:
            with db.get_engine().connect() as conn:
                stmt = select(failed).where(failed.c.ID == self.id)
                chk_fail = next((dict(row._mapping) for row in conn.execute(stmt)), None)

        if chk_fail is None:
            logger.info(module + " Successfully marked this download as Good for downloadable content")
            return "Good"
        else:
            if chk_fail["Status"] == "Good":
                logger.info(
                    module
                    + " result has a status of GOOD - which means it does not currently exist in the failed download list."
                )
                return chk_fail["Status"]
            elif chk_fail["Status"] == "Failed":
                logger.info(
                    module + " result has a status of FAIL which indicates it is not a good choice to download."
                )
                logger.info(module + " continuing search for another download.")
                return chk_fail["Status"]
            elif chk_fail["Status"] == "Retry":
                logger.info(
                    module + " result has a status of RETRY which indicates it was a failed download that retried ."
                )
                return chk_fail["Status"]
            elif chk_fail["Status"] == "Retrysame":
                logger.info(
                    module
                    + " result has a status of RETRYSAME which indicates it was a failed download that retried the initial download."
                )
                return chk_fail["Status"]
            else:
                logger.info(
                    module + " result has a status of " + chk_fail["Status"] + ". I am not sure what to do now."
                )
                return "nope"

    def _resolved_release_key(self, issueid=None, nzbname=None):
        return resolve_failed_release_key(
            journal_release_key=self.journal_release_key,
            issueid=issueid if issueid is not None else self.issueid,
            provider=self.prov,
            nzbname=nzbname if nzbname is not None else self.nzb_name,
            hash=self.id if self.prov and str(self.prov).lower() in {"32p", "wwt", "dem"} else None,
        )

    def _terminalize_journal(self, fail_reason, *, status=None, issueid=None, nzbname=None):
        rkey = self._resolved_release_key(issueid=issueid, nzbname=nzbname)
        if rkey is None:
            logger.fdebug(
                "[FAILED-DOWNLOAD] journal terminalize skipped — release_key not resolvable "
                "(issueid=%s provider=%s)" % (issueid or self.issueid, self.prov)
            )
            return False
        return terminalize_failed_download(
            rkey,
            fail_reason,
            status=status,
            issueid=issueid if issueid is not None else self.issueid,
            provider=self.prov,
            nzbname=nzbname if nzbname is not None else self.nzb_name,
            payload={
                "issueid": issueid if issueid is not None else self.issueid,
                "comicid": self.comicid,
                "provider": self.prov,
                "nzbname": nzbname if nzbname is not None else self.nzb_name,
            },
        )

    def markFailed(self):
        module = "[FAILED-DOWNLOAD]"

        logger.info(module + " Marking as a Failed Download.")

        logger.fdebug(module + "nzb_name: " + self.nzb_name)
        logger.fdebug(module + "issueid: " + str(self.issueid))
        logger.fdebug(module + "nzb_id: " + str(self.id))
        logger.fdebug(module + "prov: " + self.prov)

        logger.fdebug("oneoffinfo: " + str(self.oneoffinfo))
        if self.oneoffinfo:
            ComicName = self.oneoffinfo["ComicName"]
            IssueNumber = self.oneoffinfo["IssueNumber"]

        else:
            if "annual" in self.nzb_name.lower():
                logger.info(module + " Annual detected.")
                with db.get_engine().connect() as conn:
                    stmt = select(annuals).where(
                        annuals.c.IssueID == self.issueid,
                        annuals.c.ComicName.isnot(None),
                    )
                    issuenzb = next((dict(row._mapping) for row in conn.execute(stmt)), None)
            else:
                with db.get_engine().connect() as conn:
                    stmt = select(issues).where(
                        issues.c.IssueID == self.issueid,
                        issues.c.ComicName.isnot(None),
                    )
                    issuenzb = next((dict(row._mapping) for row in conn.execute(stmt)), None)

            ctrlVal = {"IssueID": self.issueid}
            Vals = {"Status": "Failed"}
            db.upsert("issues", Vals, ctrlVal)
            ComicName = issuenzb["ComicName"]
            IssueNumber = issuenzb["Issue_Number"]

        ctrlVal = {"ID": self.id, "Provider": self.prov, "NZBName": self.nzb_name}
        Vals = {
            "Status": "Failed",
            "ComicName": ComicName,
            "Issue_Number": IssueNumber,
            "IssueID": self.issueid,
            "ComicID": self.comicid,
            "DateFailed": helpers.now(),
        }
        db.upsert("failed", Vals, ctrlVal)

        self._terminalize_journal(FAIL_REASON_NO_AUTO_HANDLING, status=None)

        logger.info(module + " Successfully marked as Failed.")
