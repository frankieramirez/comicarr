#  Copyright (C) 2012–2024 Mylar3 contributors
#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Originally based on Mylar3 (https://github.com/mylar3/mylar3).
# -*- coding: utf-8 -*-
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

import queue

import comicarr

from . import logger


class Process(object):
    def __init__(
        self,
        nzb_name,
        nzb_folder,
        failed=False,
        issueid=None,
        comicid=None,
        apicall=False,
        ddl=False,
        download_info=None,
        journal_release_key=None,
    ):
        self.nzb_name = nzb_name
        self.nzb_folder = nzb_folder
        self.failed = failed
        self.issueid = issueid
        self.comicid = comicid
        self.apicall = apicall
        self.ddl = ddl
        self.download_info = download_info
        self.journal_release_key = journal_release_key

    def _terminalize_handling_disabled(self):
        """Mark the journal failed when failed-download handling is off.

        Prefer the PP claim key; fall back under existing release_key rules
        from download_info / issue identity.
        """
        from comicarr import failed as failed_mod

        info = self.download_info if isinstance(self.download_info, dict) else {}
        issueid = self.issueid or info.get("issueid")
        provider = info.get("provider")
        nzbname = self.nzb_name or info.get("nzbname")
        h = info.get("hash")
        rkey = failed_mod.resolve_failed_release_key(
            journal_release_key=self.journal_release_key,
            issueid=issueid,
            provider=provider,
            nzbname=nzbname,
            hash=h,
            discriminant=info or None,
        )
        if rkey is None:
            logger.fdebug(
                "[PROCESS] journal terminalize skipped — release_key not resolvable "
                "(issueid=%s provider=%s)" % (issueid, provider)
            )
            return False
        return failed_mod.terminalize_failed_download(
            rkey,
            failed_mod.FAIL_REASON_NO_AUTO_HANDLING,
            status=None,
            issueid=issueid,
            provider=provider,
            nzbname=nzbname,
            hash=h,
            payload={
                "issueid": issueid,
                "comicid": self.comicid or info.get("comicid"),
                "provider": provider,
                "nzbname": nzbname,
                "failed": True,
            },
        )

    def post_process(self):
        if self.failed == "0":
            self.failed = False
        elif self.failed == "1":
            self.failed = True

        ppqueue = queue.Queue()
        retry_outside = False

        if self.failed is False:
            PostProcess = comicarr.postprocessor.PostProcessor(
                self.nzb_name,
                self.nzb_folder,
                self.issueid,
                queue=ppqueue,
                comicid=self.comicid,
                apicall=self.apicall,
                ddl=self.ddl,
                journal_release_key=self.journal_release_key,
            )
            PostProcess.Process()
            if not ppqueue.empty():
                chk = ppqueue.get()
                while True:
                    if chk[0]["mode"] == "fail":
                        logger.info("Initiating Failed Download handling")
                        self.failed = True
                        break
                    elif chk[0]["mode"] == "stop":
                        break
                    elif chk[0]["mode"] == "outside":
                        retry_outside = True
                        break
                    else:
                        logger.error("mode is unsupported: " + chk[0]["mode"])
                        break

        if self.failed is True:
            if comicarr.CONFIG.FAILED_DOWNLOAD_HANDLING is True:
                logger.info("Initiating Failed Download handling for this download.")
                nzbid = self.download_info["id"]
                provider = self.download_info["provider"]
                FailProcess = comicarr.failed.FailedProcessor(
                    nzb_name=self.nzb_name,
                    nzb_folder=self.nzb_folder,
                    queue=ppqueue,
                    prov=provider,
                    id=nzbid,
                    issueid=self.issueid,
                    comicid=self.comicid,
                    journal_release_key=self.journal_release_key,
                )
                FailProcess.Process()
                failchk = ppqueue.get()
                if failchk[0]["mode"] == "retry":
                    logger.info("Attempting to return to search module with " + str(failchk[0]["issueid"]))
                    from comicarr.app.search.commands import enqueue_failed_download_retry

                    enqueue_failed_download_retry(failchk[0])
                elif failchk[0]["mode"] == "stop":
                    pass
                else:
                    logger.error("mode is unsupported: " + failchk[0]["mode"])
            else:
                logger.warn("Failed Download Handling is not enabled. Leaving Failed Download as-is.")
                self._terminalize_handling_disabled()

        if retry_outside:
            PostProcess = comicarr.postprocessor.PostProcessor("Manual Run", self.nzb_folder, queue=ppqueue)
            PostProcess.Process()
            chk = ppqueue.get()
            while True:
                if chk[0]["mode"] == "fail":
                    logger.info("Initiating Failed Download handling")
                    self.failed = True
                    break
                elif chk[0]["mode"] == "stop":
                    break
                else:
                    logger.error("mode is unsupported: " + chk[0]["mode"])
                    break
        return
