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

from sqlalchemy import select

import comicarr
from comicarr import db, helpers, logger
from comicarr.tables import annuals, comics, issues, readlist, storyarcs


class Readinglist(object):
    def __init__(self, filelist=None, IssueID=None, IssueArcID=None):

        if IssueID:
            self.IssueID = IssueID
        else:
            self.IssueID = None
        if IssueArcID:
            self.IssueArcID = IssueArcID
        else:
            self.IssueArcID = None
        if filelist:
            self.filelist = filelist
        else:
            self.filelist = None

        self.module = "[READLIST]"

    def addtoreadlist(self):
        annualize = False
        with db.get_engine().connect() as conn:
            stmt = select(issues).where(issues.c.IssueID == self.IssueID)
            result = [dict(row._mapping) for row in conn.execute(stmt)]
            rl = result[0] if result else None

        if rl is None:
            logger.fdebug(self.module + " Checking against annuals..")
            with db.get_engine().connect() as conn:
                stmt = select(annuals).where(annuals.c.IssueID == self.IssueID)
                result = [dict(row._mapping) for row in conn.execute(stmt)]
                rl = result[0] if result else None
            if rl is None:
                logger.error(self.module + " Cannot locate IssueID - aborting..")
                return {"status": "failure", "message": "Unable to locate issue in database. Does it exist?"}
            else:
                logger.fdebug("%s Successfully found annual for %s" % (self.module, rl["ComicID"]))
                annualize = True

        with db.get_engine().connect() as conn:
            stmt = select(comics).where(comics.c.ComicID == rl["ComicID"])
            result = [dict(row._mapping) for row in conn.execute(stmt)]
            comicinfo = result[0] if result else None

        logger.info(self.module + " Attempting to add issueid " + rl["IssueID"])
        if comicinfo is None:
            logger.info(
                self.module
                + " Issue not located on your current watchlist. I should probably check story-arcs but I do not have that capability just yet."
            )
            return {"status": "failure", "message": "Unable to locate issue in your watchlist. Does it exist?"}
        else:
            locpath = None
            if all([comicarr.CONFIG.MULTIPLE_DEST_DIRS is not None, comicarr.CONFIG.MULTIPLE_DEST_DIRS != "None"]):
                if os.path.exists(
                    os.path.join(comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(comicinfo["ComicLocation"]))
                ):
                    secondary_folders = os.path.join(
                        comicarr.CONFIG.MULTIPLE_DEST_DIRS, os.path.basename(comicinfo["ComicLocation"])
                    )
                else:
                    ff = comicarr.filers.FileHandlers(ComicID=rl["ComicID"])
                    secondary_folders = ff.secondary_folders(comicinfo["ComicLocation"])

                if os.path.exists(os.path.join(secondary_folders, rl["Location"])):
                    locpath = os.path.join(secondary_folders, rl["Location"])
                else:
                    if os.path.exists(os.path.join(comicinfo["ComicLocation"], rl["Location"])):
                        locpath = os.path.join(comicinfo["ComicLocation"], rl["Location"])
            else:
                if os.path.exists(os.path.join(comicinfo["ComicLocation"], rl["Location"])):
                    locpath = os.path.join(comicinfo["ComicLocation"], rl["Location"])

            if locpath is not None:
                comicissue = rl["Issue_Number"]
                if annualize is True:
                    comicname = rl["ReleaseComicName"]
                else:
                    comicname = comicinfo["ComicName"]
                dspinfo = comicname + " #" + comicissue
                if annualize is True:
                    if comicarr.CONFIG.ANNUALS_ON is True:
                        dspinfo = comicname + " #" + rl["Issue_Number"]
                        if "annual" in comicname.lower():
                            comicissue = "Annual " + rl["Issue_Number"]
                        elif "special" in comicname.lower():
                            comicissue = "Special " + rl["Issue_Number"]

                ctrlval = {"IssueID": self.IssueID}
                newval = {
                    "DateAdded": helpers.today(),
                    "Status": "Added",
                    "ComicID": rl["ComicID"],
                    "Issue_Number": comicissue,
                    "IssueDate": rl["IssueDate"],
                    "SeriesYear": comicinfo["ComicYear"],
                    "ComicName": comicname,
                    "Location": locpath,
                }

                db.upsert("readlist", newval, ctrlval)
                logger.info(self.module + " Added " + dspinfo + " to the Reading list.")
        return {"status": "success", "message": "Successfully added %s to your reading list" % dspinfo}

    def markasRead(self, IssueID=None, IssueArcID=None):
        if IssueID:
            with db.get_engine().connect() as conn:
                stmt = select(readlist).where(readlist.c.IssueID == IssueID)
                result = [dict(row._mapping) for row in conn.execute(stmt)]
                issue = result[0] if result else None

            if issue["Status"] == "Read":
                NewVal = {"Status": "Added"}
            else:
                NewVal = {"Status": "Read"}

            NewVal["StatusChange"] = helpers.today()

            CtrlVal = {"IssueID": IssueID}
            db.upsert("readlist", NewVal, CtrlVal)
            logger.info(self.module + " Marked " + issue["ComicName"] + " #" + str(issue["Issue_Number"]) + " as Read.")
        elif IssueArcID:
            with db.get_engine().connect() as conn:
                stmt = select(storyarcs).where(storyarcs.c.IssueArcID == IssueArcID)
                result = [dict(row._mapping) for row in conn.execute(stmt)]
                issue = result[0] if result else None

            if issue["Status"] == "Read":
                NewVal = {"Status": "Added"}
            else:
                NewVal = {"Status": "Read"}
            NewVal["StatusChange"] = helpers.today()
            CtrlVal = {"IssueArcID": IssueArcID}
            db.upsert("storyarcs", NewVal, CtrlVal)
            logger.info(self.module + " Marked " + issue["ComicName"] + " #" + str(issue["IssueNumber"]) + " as Read.")
        else:
            logger.info(self.module + "Could not mark anything as read, no IssueID or IssueArcID passed")

        return
