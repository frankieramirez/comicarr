# -*- coding: utf-8 -*-

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

import glob
import os
import re
from io import BytesIO
from operator import itemgetter
from urllib.parse import quote_plus
from xml.sax.saxutils import escape

import cherrypy
import simplejson as simplejson
from cherrypy.lib.static import serve_download, serve_file, serve_fileobj
from PIL import Image
from sqlalchemy import select

import comicarr
from comicarr import db, helpers, logger, readinglist
from comicarr.getimage import comic_pages, open_archive, page_count, scale_image
from comicarr.tables import annuals, comics, issues, readlist, snatched, storyarcs
from comicarr.webserve import serve_template

cmd_list = [
    "root",
    "Publishers",
    "AllTitles",
    "StoryArcs",
    "ReadList",
    "OneOffs",
    "Comic",
    "Publisher",
    "Issue",
    "Stream",
    "StoryArc",
    "Recent",
    "deliverFile",
]


class OPDS(object):
    def __init__(self):
        self.cmd = None
        self.PAGE_SIZE = comicarr.CONFIG.OPDS_PAGESIZE
        self.img = None
        self.issue_id = None
        self.file = None
        self.filename = None
        self.kwargs = None
        self.data = None
        if comicarr.CONFIG.HTTP_ROOT is None:
            self.opdsroot = "/" + comicarr.CONFIG.OPDS_ENDPOINT
        elif comicarr.CONFIG.HTTP_ROOT.endswith("/"):
            self.opdsroot = comicarr.CONFIG.HTTP_ROOT + comicarr.CONFIG.OPDS_ENDPOINT
        else:
            if comicarr.CONFIG.HTTP_ROOT != "/":
                self.opdsroot = comicarr.CONFIG.HTTP_ROOT + "/" + comicarr.CONFIG.OPDS_ENDPOINT
            else:
                self.opdsroot = "/" + comicarr.CONFIG.OPDS_ENDPOINT

    def checkParams(self, *args, **kwargs):

        if "cmd" not in kwargs:
            self.cmd = "root"

        if not comicarr.CONFIG.OPDS_ENABLE:
            self.data = self._error_with_message("OPDS not enabled")
            return

        if not self.cmd:
            if kwargs["cmd"] not in cmd_list:
                self.data = self._error_with_message("Unknown command: %s" % kwargs["cmd"])
                return
            else:
                self.cmd = kwargs.pop("cmd")

        self.kwargs = kwargs
        self.data = "OK"

    def fetchData(self):
        if self.data == "OK":
            logger.fdebug("Recieved OPDS command: " + self.cmd)
            methodToCall = getattr(self, "_" + self.cmd)
            methodToCall(**self.kwargs)
            if self.img:
                if type(self.img) == tuple:
                    iformat, idata = self.img
                    return serve_fileobj(BytesIO(idata), content_type="image/" + iformat)
                else:
                    return serve_file(path=self.img, content_type="image/jpeg")
            if self.file and self.filename:
                if self.issue_id:
                    try:
                        logger.fdebug(
                            "OPDS is attempting to markasRead filename %s aka issue_id %s"
                            % (self.filename, self.issue_id)
                        )
                        readinglist.Readinglist().markasRead(IssueID=self.issue_id)
                    except:
                        logger.fdebug("No reading list found to update.")
                return serve_download(path=self.file, name=self.filename)
            if isinstance(self.data, str):
                return self.data
            else:
                cherrypy.response.headers["Content-Type"] = "text/xml"
                return serve_template(templatename="opds.html", title=self.data["title"], opds=self.data)
        else:
            return self.data

    def _error_with_message(self, message):
        error = "<feed><error>%s</error></feed>" % message
        cherrypy.response.headers["Content-Type"] = "text/xml"
        return error

    def _root(self, **kwargs):
        feed = {}
        feed["title"] = "Comicarr OPDS"
        currenturi = cherrypy.url()
        feed["id"] = re.sub("/", ":", currenturi)
        feed["updated"] = comicarr.helpers.now()
        links = []
        entries = []
        links.append(
            getLink(
                href=self.opdsroot,
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="start",
                title="Home",
            )
        )
        links.append(
            getLink(href=self.opdsroot, type="application/atom+xml; profile=opds-catalog; kind=navigation", rel="self")
        )
        links.append(
            getLink(
                href="%s?cmd=search" % self.opdsroot,
                type="application/opensearchdescription+xml",
                rel="search",
                title="Search",
            )
        )
        with db.get_engine().connect() as conn:
            stmt = select(comics.c.ComicPublisher).group_by(comics.c.ComicPublisher)
            publishers = [dict(row._mapping) for row in conn.execute(stmt)]
        entries.append(
            {
                "title": "Recent Additions",
                "id": "Recent",
                "updated": comicarr.helpers.now(),
                "content": "Recently Added Issues",
                "href": "%s?cmd=Recent" % self.opdsroot,
                "kind": "acquisition",
                "rel": "subsection",
            }
        )
        if len(publishers) > 0:
            count = len(publishers)
            entries.append(
                {
                    "title": "Publishers (%s)" % count,
                    "id": "Publishers",
                    "updated": comicarr.helpers.now(),
                    "content": "List of Comic Publishers",
                    "href": "%s?cmd=Publishers" % self.opdsroot,
                    "kind": "navigation",
                    "rel": "subsection",
                }
            )
        comics_list = comicarr.helpers.havetotals()
        count = 0
        for comic in comics_list:
            if comic["haveissues"] is not None and comic["haveissues"] > 0:
                count += 1
        if count > -1:
            entries.append(
                {
                    "title": "All Titles (%s)" % count,
                    "id": "AllTitles",
                    "updated": comicarr.helpers.now(),
                    "content": "List of All Comics",
                    "href": "%s?cmd=AllTitles" % self.opdsroot,
                    "kind": "navigation",
                    "rel": "subsection",
                }
            )
        storyArcs = comicarr.helpers.listStoryArcs()
        logger.debug(storyArcs)
        if len(storyArcs) > 0:
            entries.append(
                {
                    "title": "Story Arcs (%s)" % len(storyArcs),
                    "id": "StoryArcs",
                    "updated": comicarr.helpers.now(),
                    "content": "List of Story Arcs",
                    "href": "%s?cmd=StoryArcs" % self.opdsroot,
                    "kind": "navigation",
                    "rel": "subsection",
                }
            )
        with db.get_engine().connect() as conn:
            stmt = select(readlist)
            readList = [dict(row._mapping) for row in conn.execute(stmt)]
        if len(readList) > 0:
            entries.append(
                {
                    "title": "Read List (%s)" % len(readList),
                    "id": "ReadList",
                    "updated": comicarr.helpers.now(),
                    "content": "Current Read List",
                    "href": "%s?cmd=ReadList" % self.opdsroot,
                    "kind": "navigation",
                    "rel": "subsection",
                }
            )
        gbd = comicarr.CONFIG.GRABBAG_DIR + "/*"
        oneofflist = glob.glob(gbd)
        if len(oneofflist) > 0:
            entries.append(
                {
                    "title": "One-Offs (%s)" % len(oneofflist),
                    "id": "OneOffs",
                    "updated": comicarr.helpers.now(),
                    "content": "OneOffs",
                    "href": "%s?cmd=OneOffs" % self.opdsroot,
                    "kind": "navigation",
                    "rel": "subsection",
                }
            )
        feed["links"] = links
        feed["entries"] = entries
        self.data = feed
        return

    def _Publishers(self, **kwargs):
        index = 0
        if "index" in kwargs:
            index = int(kwargs["index"])
        feed = {}
        feed["title"] = "Comicarr OPDS - Publishers"
        feed["id"] = "Publishers"
        feed["updated"] = comicarr.helpers.now()
        links = []
        entries = []
        links.append(
            getLink(
                href=self.opdsroot,
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="start",
                title="Home",
            )
        )
        links.append(
            getLink(
                href="%s?cmd=Publishers" % self.opdsroot,
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="self",
            )
        )
        with db.get_engine().connect() as conn:
            stmt = select(comics.c.ComicPublisher).group_by(comics.c.ComicPublisher)
            publishers = [dict(row._mapping) for row in conn.execute(stmt)]
        comics_list = comicarr.helpers.havetotals()
        for publisher in publishers:
            lastupdated = "0000-00-00"
            totaltitles = 0
            for comic in comics_list:
                if comic["ComicPublisher"] == publisher["ComicPublisher"] and comic["haveissues"] > 0:
                    totaltitles += 1
                    if comic["DateAdded"] > lastupdated:
                        lastupdated = comic["DateAdded"]
            if totaltitles > 0:
                entries.append(
                    {
                        "title": escape("%s (%s)" % (publisher["ComicPublisher"], totaltitles)),
                        "id": escape("publisher:%s" % publisher["ComicPublisher"]),
                        "updated": lastupdated,
                        "content": escape("%s (%s)" % (publisher["ComicPublisher"], totaltitles)),
                        "href": "%s?cmd=Publisher&amp;pubid=%s"
                        % (self.opdsroot, quote_plus(publisher["ComicPublisher"])),
                        "kind": "navigation",
                        "rel": "subsection",
                    }
                )
        if len(entries) > (index + self.PAGE_SIZE):
            links.append(
                getLink(
                    href="%s?cmd=AllTitles&amp;index=%s" % (self.opdsroot, index + self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="next",
                )
            )
        if index >= self.PAGE_SIZE:
            links.append(
                getLink(
                    href="%s?cmd=AllTitles&amp;index=%s" % (self.opdsroot, index - self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="previous",
                )
            )

        feed["links"] = links
        feed["entries"] = entries[index : (index + self.PAGE_SIZE)]
        self.data = feed
        return

    def _AllTitles(self, **kwargs):
        index = 0
        if "index" in kwargs:
            index = int(kwargs["index"])
        feed = {}
        feed["title"] = "Comicarr OPDS - All Titles"
        feed["id"] = "AllTitles"
        feed["updated"] = comicarr.helpers.now()
        links = []
        entries = []
        links.append(
            getLink(
                href=self.opdsroot,
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="start",
                title="Home",
            )
        )
        links.append(
            getLink(
                href="%s?cmd=AllTitles" % self.opdsroot,
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="self",
            )
        )
        comics_list = comicarr.helpers.havetotals()
        for comic in comics_list:
            if comic["haveissues"] > 0:
                entries.append(
                    {
                        "title": escape(
                            "%s (%s) (comicID: %s)" % (comic["ComicName"], comic["ComicYear"], comic["ComicID"])
                        ),
                        "id": escape("comic:%s (%s) [%s]" % (comic["ComicName"], comic["ComicYear"], comic["ComicID"])),
                        "updated": comic["DateAdded"],
                        "content": escape("%s (%s)" % (comic["ComicName"], comic["ComicYear"])),
                        "href": "%s?cmd=Comic&amp;comicid=%s" % (self.opdsroot, quote_plus(comic["ComicID"])),
                        "kind": "acquisition",
                        "rel": "subsection",
                    }
                )
        if len(entries) > (index + self.PAGE_SIZE):
            links.append(
                getLink(
                    href="%s?cmd=AllTitles&amp;index=%s" % (self.opdsroot, index + self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="next",
                )
            )
        if index >= self.PAGE_SIZE:
            links.append(
                getLink(
                    href="%s?cmd=AllTitles&amp;index=%s" % (self.opdsroot, index - self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="previous",
                )
            )

        feed["links"] = links
        feed["entries"] = entries[index : (index + self.PAGE_SIZE)]
        self.data = feed
        return

    def _Publisher(self, **kwargs):
        index = 0
        if "index" in kwargs:
            index = int(kwargs["index"])
        if "pubid" not in kwargs:
            self.data = self._error_with_message("No Publisher Provided")
            return
        links = []
        entries = []
        allcomics = comicarr.helpers.havetotals()
        for comic in allcomics:
            if comic["ComicPublisher"] == kwargs["pubid"] and comic["haveissues"] > 0:
                entries.append(
                    {
                        "title": escape("%s (%s)" % (comic["ComicName"], comic["ComicYear"])),
                        "id": escape("comic:%s (%s)" % (comic["ComicName"], comic["ComicYear"])),
                        "updated": comic["DateAdded"],
                        "content": escape("%s (%s)" % (comic["ComicName"], comic["ComicYear"])),
                        "href": "%s?cmd=Comic&amp;comicid=%s" % (self.opdsroot, quote_plus(comic["ComicID"])),
                        "kind": "acquisition",
                        "rel": "subsection",
                    }
                )
        feed = {}
        pubname = "%s (%s)" % (escape(kwargs["pubid"]), len(entries))
        feed["title"] = "Comicarr OPDS - %s" % (pubname)
        feed["id"] = "publisher:%s" % escape(kwargs["pubid"])
        feed["updated"] = comicarr.helpers.now()
        links.append(
            getLink(
                href=self.opdsroot,
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="start",
                title="Home",
            )
        )
        links.append(
            getLink(
                href="%s?cmd=Publishers" % self.opdsroot,
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="self",
            )
        )
        if len(entries) > (index + self.PAGE_SIZE):
            links.append(
                getLink(
                    href="%s?cmd=Publisher&amp;pubid=%s&amp;index=%s"
                    % (self.opdsroot, quote_plus(kwargs["pubid"]), index + self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="next",
                )
            )
        if index >= self.PAGE_SIZE:
            links.append(
                getLink(
                    href="%s?cmd=Publisher&amp;pubid=%s&amp;index=%s"
                    % (self.opdsroot, quote_plus(kwargs["pubid"]), index - self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="previous",
                )
            )

        feed["links"] = links
        feed["entries"] = entries[index : (index + self.PAGE_SIZE)]
        self.data = feed
        return

    def _Comic(self, **kwargs):
        index = 0
        if "index" in kwargs:
            index = int(kwargs["index"])
        if "comicid" not in kwargs:
            self.data = self._error_with_message("No ComicID Provided")
            return
        links = []
        entries = []
        with db.get_engine().connect() as conn:
            stmt = select(comics).where(comics.c.ComicID == kwargs["comicid"])
            result = [dict(row._mapping) for row in conn.execute(stmt)]
            comic = result[0] if result else None
        if not comic:
            self.data = self._error_with_message("Comic Not Found")
            return
        with db.get_engine().connect() as conn:
            stmt = select(issues).where(issues.c.ComicID == kwargs["comicid"]).order_by(issues.c.Int_IssueNumber.desc())
            issues_list = [dict(row._mapping) for row in conn.execute(stmt)]
        if comicarr.CONFIG.ANNUALS_ON:
            with db.get_engine().connect() as conn:
                stmt = select(annuals).where(annuals.c.ComicID == kwargs["comicid"])
                annuals_list = [dict(row._mapping) for row in conn.execute(stmt)]
        else:
            annuals_list = []
        for annual in annuals_list:
            issues_list.append(annual)
        issues_list = [x for x in issues_list if x["Location"]]
        if index <= len(issues_list):
            subset = issues_list[index : (index + self.PAGE_SIZE)]
            for issue in subset:
                if "DateAdded" in issue and issue["DateAdded"]:
                    updated = issue["DateAdded"]
                else:
                    updated = issue["ReleaseDate"]
                image = None
                thumbnail = None
                if "ReleaseComicID" not in issue:
                    title = escape(
                        "%s (%s) #%s - %s"
                        % (issue["ComicName"], comic["ComicYear"], issue["Issue_Number"], issue["IssueName"])
                    )
                    image = issue["ImageURL_ALT"]
                    thumbnail = issue["ImageURL"]
                else:
                    title = escape("Annual %s - %s" % (issue["Issue_Number"], issue["IssueName"]))

                fileloc = os.path.join(comic["ComicLocation"], issue["Location"])
                if not os.path.isfile(fileloc):
                    logger.debug("Missing File: %s" % (fileloc))
                    continue
                metainfo = None
                if comicarr.CONFIG.OPDS_METAINFO:
                    issuedetails = comicarr.helpers.IssueDetails(fileloc).get("metadata", None)
                    if issuedetails is not None:
                        metainfo = issuedetails.get("metadata", None)
                if not metainfo:
                    metainfo = [{"writer": None, "summary": ""}]
                cb, _ = open_archive(fileloc)
                if cb is None:
                    self.data = self._error_with_message("Can't open archive")
                    pse_count = 0  # Or just skip the issue?
                else:
                    pse_count = page_count(cb)
                entries.append(
                    {
                        "title": escape(title),
                        "id": escape(
                            "comic:%s (%s) [%s] - %s"
                            % (issue["ComicName"], comic["ComicYear"], comic["ComicID"], issue["Issue_Number"])
                        ),
                        "updated": updated,
                        "content": escape("%s" % (metainfo[0]["summary"])),
                        "href": "%s?cmd=Issue&amp;issueid=%s&amp;file=%s"
                        % (self.opdsroot, quote_plus(issue["IssueID"]), quote_plus(issue["Location"])),
                        "stream": "%s?cmd=Stream&amp;issueid=%s&amp;file=%s"
                        % (self.opdsroot, quote_plus(issue["IssueID"]), quote_plus(issue["Location"])),
                        "pse_count": pse_count,
                        "kind": "acquisition",
                        "rel": "file",
                        "author": metainfo[0]["writer"],
                        "image": image,
                        "thumbnail": thumbnail,
                    }
                )

        feed = {}
        comicname = "%s" % (escape(comic["ComicName"]))
        feed["title"] = "Comicarr OPDS - %s" % (comicname)
        feed["id"] = escape("comic:%s (%s)" % (comic["ComicName"], comic["ComicYear"]))
        feed["updated"] = comic["DateAdded"]
        links.append(
            getLink(
                href=self.opdsroot,
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="start",
                title="Home",
            )
        )
        links.append(
            getLink(
                href="%s?cmd=Comic&amp;comicid=%s" % (self.opdsroot, quote_plus(kwargs["comicid"])),
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="self",
            )
        )
        if len(issues_list) > (index + self.PAGE_SIZE):
            links.append(
                getLink(
                    href="%s?cmd=Comic&amp;comicid=%s&amp;index=%s"
                    % (self.opdsroot, quote_plus(kwargs["comicid"]), index + self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="next",
                )
            )
        if index >= self.PAGE_SIZE:
            links.append(
                getLink(
                    href="%s?cmd=Comic&amp;comicid=%s&amp;index=%s"
                    % (self.opdsroot, quote_plus(kwargs["comicid"]), index - self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="previous",
                )
            )

        feed["links"] = links
        feed["entries"] = entries
        self.data = feed
        return

    def _Recent(self, **kwargs):
        index = 0
        if "index" in kwargs:
            index = int(kwargs["index"])
        links = []
        entries = []
        with db.get_engine().connect() as conn:
            stmt = (
                select(snatched)
                .where(snatched.c.Status.in_(["Post-Processed", "Downloaded"]))
                .order_by(snatched.c.DateAdded.desc())
                .limit(120)
            )
            recents = [dict(row._mapping) for row in conn.execute(stmt)]
        if index <= len(recents):
            number = 1
            subset = recents[index : (index + self.PAGE_SIZE)]
            for issue in subset:
                with db.get_engine().connect() as conn:
                    stmt = select(issues).where(issues.c.IssueID == issue["IssueID"])
                    result = [dict(row._mapping) for row in conn.execute(stmt)]
                    issuebook = result[0] if result else None
                if not issuebook:
                    with db.get_engine().connect() as conn:
                        stmt = select(annuals).where(annuals.c.IssueID == issue["IssueID"])
                        result = [dict(row._mapping) for row in conn.execute(stmt)]
                        issuebook = result[0] if result else None
                with db.get_engine().connect() as conn:
                    stmt = select(comics).where(comics.c.ComicID == issue["ComicID"])
                    result = [dict(row._mapping) for row in conn.execute(stmt)]
                    comic = result[0] if result else None
                updated = issue["DateAdded"]
                image = None
                thumbnail = None
                if issuebook:
                    if "ReleaseComicID" not in list(issuebook.keys()):
                        if issuebook["DateAdded"] is None:
                            title = escape(
                                "%03d: %s #%s - %s (In stores %s)"
                                % (
                                    index + number,
                                    issuebook["ComicName"],
                                    issuebook["Issue_Number"],
                                    issuebook["IssueName"],
                                    issuebook["ReleaseDate"],
                                )
                            )
                            image = issuebook["ImageURL_ALT"]
                            thumbnail = issuebook["ImageURL"]
                        else:
                            title = escape(
                                "%03d: %s #%s - %s (Added to Comicarr %s, in stores %s)"
                                % (
                                    index + number,
                                    issuebook["ComicName"],
                                    issuebook["Issue_Number"],
                                    issuebook["IssueName"],
                                    issuebook["DateAdded"],
                                    issuebook["ReleaseDate"],
                                )
                            )
                            image = issuebook["ImageURL_ALT"]
                            thumbnail = issuebook["ImageURL"]
                    else:
                        title = escape(
                            "%03d: %s Annual %s - %s (In stores %s)"
                            % (
                                index + number,
                                issuebook["ComicName"],
                                issuebook["Issue_Number"],
                                issuebook["IssueName"],
                                issuebook["ReleaseDate"],
                            )
                        )
                    # logger.info("%s - %s" % (comic['ComicLocation'], issuebook['Location']))
                    number += 1
                    if not issuebook["Location"]:
                        continue
                    location = issuebook["Location"]
                    fileloc = os.path.join(comic["ComicLocation"], issuebook["Location"])
                    metainfo = None
                    if comicarr.CONFIG.OPDS_METAINFO:
                        issuedetails = comicarr.helpers.IssueDetails(fileloc).get("metadata", None)
                        if issuedetails is not None:
                            metainfo = issuedetails.get("metadata", None)
                    if not metainfo:
                        metainfo = {}
                        metainfo[0] = {"writer": None, "summary": ""}
                    cb, _ = open_archive(fileloc)
                    if cb is None:
                        self.data = self._error_with_message("Can't open archive")
                        pse_count = 0  # Or just skip the issue?
                    else:
                        pse_count = page_count(cb)
                    entries.append(
                        {
                            "title": title,
                            "id": escape(
                                "comic:%s (%s) - %s"
                                % (issuebook["ComicName"], comic["ComicYear"], issuebook["Issue_Number"])
                            ),
                            "updated": updated,
                            "content": escape("%s" % (metainfo[0]["summary"])),
                            "href": "%s?cmd=Issue&amp;issueid=%s&amp;file=%s"
                            % (self.opdsroot, quote_plus(issuebook["IssueID"]), quote_plus(location)),
                            "stream": "%s?cmd=Stream&amp;issueid=%s&amp;file=%s"
                            % (self.opdsroot, quote_plus(issuebook["IssueID"]), quote_plus(location)),
                            "pse_count": pse_count,
                            "kind": "acquisition",
                            "rel": "file",
                            "author": metainfo[0]["writer"],
                            "image": image,
                            "thumbnail": thumbnail,
                        }
                    )
        feed = {}
        feed["title"] = "Comicarr OPDS - New Arrivals"
        feed["id"] = escape("New Arrivals")
        feed["updated"] = comicarr.helpers.now()
        links.append(
            getLink(
                href=self.opdsroot,
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="start",
                title="Home",
            )
        )
        links.append(
            getLink(
                href="%s?cmd=Recent" % (self.opdsroot),
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="self",
            )
        )
        if len(recents) > (index + self.PAGE_SIZE):
            links.append(
                getLink(
                    href="%s?cmd=Recent&amp;index=%s" % (self.opdsroot, index + self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="next",
                )
            )
        if index >= self.PAGE_SIZE:
            links.append(
                getLink(
                    href="%s?cmd=Recent&amp;index=%s" % (self.opdsroot, index - self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="previous",
                )
            )

        feed["links"] = links
        feed["entries"] = entries
        self.data = feed
        return

    def _deliverFile(self, **kwargs):
        logger.fdebug("_deliverFile: kwargs: %s" % kwargs)
        if "file" not in kwargs:
            self.data = self._error_with_message("No file provided")
        elif "filename" not in kwargs:
            self.data = self._error_with_message("No filename provided")
        else:
            # logger.fdebug("file name: %s" % str(kwargs['file'])
            self.filename = os.path.split(str(kwargs["file"]))[1]
            self.file = str(kwargs["file"])
        return

    def _Stream(self, **kwargs):
        # Implements the OPDS Page Streaming Extension 1.0 ref. https://vaemendis.net/opds-pse/
        self._Issue(**kwargs)

        if "page" not in kwargs:
            self.data = self._error_with_message("No page number specified")
            self.file = None
            self.filename = None
            return
        try:
            page = int(kwargs["page"])
        except ValueError:
            self.data = self._error_with_message("Invalid page format")
            self.file = None
            self.filename = None
            return

        cb, _ = open_archive(self.file)
        if cb is None:
            self.data = self._error_with_message("Can't open archive")
            self.file = None
            self.filename = None
            return

        page_names = comic_pages(cb)
        if page < 0 or page >= len(page_names):
            self.data = self._error_with_message("Page out of range")
            self.file = None
            self.filename = None
            return

        page_name = page_names[page]
        with cb.open(page_name) as ifile:
            if "width" in kwargs:
                # Support for this is actually optional. I'm not sure if many clients use it at all?
                width = int(kwargs["width"])

                img = Image.open(ifile)
                max_width = int(kwargs["width"])
                width, height = img.size
                if max_width < width or True:
                    iformat = "jpeg"
                    self.img = (iformat, scale_image(img, iformat, max_width))
                else:
                    ifile.seek(0)
                    self.img = (img.format.lower(), ifile.read())

            else:
                self.img = (os.path.splitext(page_name)[1][1:], ifile.read())

    def _Issue(self, **kwargs):
        if "issueid" not in kwargs:
            self.data = self._error_with_message("No ComicID Provided")
            return
        with db.get_engine().connect() as conn:
            stmt = select(storyarcs).where(
                storyarcs.c.IssueID == kwargs["issueid"],
                storyarcs.c.Location.isnot(None),
            )
            result = [dict(row._mapping) for row in conn.execute(stmt)]
            issue = result[0] if result else None
        if not issue:
            with db.get_engine().connect() as conn:
                stmt = select(issues).where(issues.c.IssueID == kwargs["issueid"])
                result = [dict(row._mapping) for row in conn.execute(stmt)]
                issue = result[0] if result else None
            if not issue:
                with db.get_engine().connect() as conn:
                    stmt = select(annuals).where(annuals.c.IssueID == kwargs["issueid"])
                    result = [dict(row._mapping) for row in conn.execute(stmt)]
                    issue = result[0] if result else None
                if not issue:
                    self.data = self._error_with_message("Issue Not Found")
                    return
            with db.get_engine().connect() as conn:
                stmt = select(comics).where(comics.c.ComicID == issue["ComicID"])
                result = [dict(row._mapping) for row in conn.execute(stmt)]
                comic = result[0] if result else None
            if not comic:
                self.data = self._error_with_message("Comic Not Found in Watchlist")
                return
            self.issue_id = issue["IssueID"]
            self.file = os.path.join(comic["ComicLocation"], issue["Location"])
            self.filename = issue["Location"]
        else:
            self.issue_id = issue["IssueID"]
            self.file = issue["Location"]
            self.filename = os.path.split(issue["Location"])[1]
        return

    def _StoryArcs(self, **kwargs):
        index = 0
        if "index" in kwargs:
            index = int(kwargs["index"])
        links = []
        entries = []
        arcs = []
        storyArcIds = comicarr.helpers.listStoryArcs()
        for arc in storyArcIds:
            issuecount = 0
            arcname = ""
            updated = "0000-00-00"
            with db.get_engine().connect() as conn:
                stmt = select(storyarcs).where(storyarcs.c.StoryArcID == arc)
                arclist = [dict(row._mapping) for row in conn.execute(stmt)]
            for issue in arclist:
                if issue["Status"] == "Downloaded":
                    issuecount += 1
                    arcname = issue["StoryArc"]
                    if issue["IssueDate"] > updated:
                        updated = issue["IssueDate"]
            if issuecount > 0:
                arcs.append({"StoryArcName": arcname, "StoryArcID": arc, "IssueCount": issuecount, "updated": updated})
        newlist = sorted(arcs, key=itemgetter("StoryArcName"))
        subset = newlist[index : (index + self.PAGE_SIZE)]
        for arc in subset:
            entries.append(
                {
                    "title": "%s (%s)" % (arc["StoryArcName"], arc["IssueCount"]),
                    "id": escape("storyarc:%s" % (arc["StoryArcID"])),
                    "updated": arc["updated"],
                    "content": "%s (%s)" % (arc["StoryArcName"], arc["IssueCount"]),
                    "href": "%s?cmd=StoryArc&amp;arcid=%s" % (self.opdsroot, quote_plus(arc["StoryArcID"])),
                    "kind": "acquisition",
                    "rel": "subsection",
                }
            )
        feed = {}
        feed["title"] = "Comicarr OPDS - Story Arcs"
        feed["id"] = "StoryArcs"
        feed["updated"] = comicarr.helpers.now()
        links.append(
            getLink(
                href=self.opdsroot,
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="start",
                title="Home",
            )
        )
        links.append(
            getLink(
                href="%s?cmd=StoryArcs" % self.opdsroot,
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="self",
            )
        )
        if len(arcs) > (index + self.PAGE_SIZE):
            links.append(
                getLink(
                    href="%s?cmd=StoryArcs&amp;index=%s" % (self.opdsroot, index + self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="next",
                )
            )
        if index >= self.PAGE_SIZE:
            links.append(
                getLink(
                    href="%s?cmd=StoryArcs&amp;index=%s" % (self.opdsroot, index - self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="previous",
                )
            )

        feed["links"] = links
        feed["entries"] = entries
        self.data = feed
        return

    def _OneOffs(self, **kwargs):
        index = 0
        if "index" in kwargs:
            index = int(kwargs["index"])
        links = []
        entries = []
        flist = []
        book = ""
        gbd = str(comicarr.CONFIG.GRABBAG_DIR + "/*")
        flist = glob.glob(gbd)
        readlist_items = []
        for book in flist:
            issue = {}
            fileexists = True
            book = book
            issue["Title"] = book
            issue["IssueID"] = book
            issue["fileloc"] = book
            issue["filename"] = book
            issue["image"] = None
            issue["thumbnail"] = None
            issue["updated"] = helpers.now()
            if not os.path.isfile(issue["fileloc"]):
                fileexists = False
            if fileexists:
                readlist_items.append(issue)
        if len(readlist_items) > 0:
            if index <= len(readlist_items):
                subset = readlist_items[index : (index + self.PAGE_SIZE)]
                for issue in subset:
                    metainfo = None
                    metainfo = [{"writer": None, "summary": ""}]
                    entries.append(
                        {
                            "title": escape(issue["Title"]),
                            "id": escape("comic:%s" % issue["IssueID"]),
                            "updated": issue["updated"],
                            "content": escape("%s" % (metainfo[0]["summary"])),
                            "href": "%s?cmd=deliverFile&amp;file=%s&amp;filename=%s"
                            % (self.opdsroot, quote_plus(issue["fileloc"]), quote_plus(issue["filename"])),
                            "kind": "acquisition",
                            "rel": "file",
                            "author": metainfo[0]["writer"],
                            "image": issue["image"],
                            "thumbnail": issue["thumbnail"],
                        }
                    )

            feed = {}
            feed["title"] = "Comicarr OPDS - One-Offs"
            feed["id"] = escape("OneOffs")
            feed["updated"] = comicarr.helpers.now()
            links.append(
                getLink(
                    href=self.opdsroot,
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="start",
                    title="Home",
                )
            )
            links.append(
                getLink(
                    href="%s?cmd=OneOffs" % self.opdsroot,
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="self",
                )
            )
            if len(readlist_items) > (index + self.PAGE_SIZE):
                links.append(
                    getLink(
                        href="%s?cmd=OneOffs&amp;index=%s" % (self.opdsroot, index + self.PAGE_SIZE),
                        type="application/atom+xml; profile=opds-catalog; kind=navigation",
                        rel="next",
                    )
                )
            if index >= self.PAGE_SIZE:
                links.append(
                    getLink(
                        href="%s?cmd=Read&amp;index=%s" % (self.opdsroot, index - self.PAGE_SIZE),
                        type="application/atom+xml; profile=opds-catalog; kind=navigation",
                        rel="previous",
                    )
                )

            feed["links"] = links
            feed["entries"] = entries
            self.data = feed
            return

    def _ReadList(self, **kwargs):
        index = 0
        if "index" in kwargs:
            index = int(kwargs["index"])
        links = []
        entries = []
        with db.get_engine().connect() as conn:
            stmt = select(readlist).where(readlist.c.Status != "Read")
            rlist = [dict(row._mapping) for row in conn.execute(stmt)]
        readlist_items = []
        for book in rlist:
            fileexists = False
            issue = {}
            issue["Title"] = "%s #%s" % (book["ComicName"], book["Issue_Number"])
            issue["IssueID"] = book["IssueID"]
            with db.get_engine().connect() as conn:
                stmt = select(comics).where(comics.c.ComicID == book["ComicID"])
                result = [dict(row._mapping) for row in conn.execute(stmt)]
                comic = result[0] if result else None
            with db.get_engine().connect() as conn:
                stmt = select(issues).where(issues.c.IssueID == book["IssueID"])
                result = [dict(row._mapping) for row in conn.execute(stmt)]
                bookentry = result[0] if result else None
            if bookentry:
                if bookentry["Location"]:
                    fileexists = True
                    issue["fileloc"] = os.path.join(comic["ComicLocation"], bookentry["Location"])
                    issue["filename"] = bookentry["Location"]
                    issue["image"] = bookentry["ImageURL_ALT"]
                    issue["thumbnail"] = bookentry["ImageURL"]
                if bookentry["DateAdded"]:
                    issue["updated"] = bookentry["DateAdded"]
                else:
                    issue["updated"] = bookentry["IssueDate"]
            else:
                with db.get_engine().connect() as conn:
                    stmt = select(annuals).where(annuals.c.IssueID == book["IssueID"])
                    result = [dict(row._mapping) for row in conn.execute(stmt)]
                    annualentry = result[0] if result else None
                if annualentry:
                    if annualentry["Location"]:
                        fileexists = True
                        issue["fileloc"] = os.path.join(comic["ComicLocation"], annualentry["Location"])
                        issue["filename"] = annualentry["Location"]
                        issue["image"] = None
                        issue["thumbnail"] = None
                        issue["updated"] = annualentry["IssueDate"]
            if not os.path.isfile(issue["fileloc"]):
                fileexists = False
            if fileexists:
                readlist_items.append(issue)
        if len(readlist_items) > 0:
            if index <= len(readlist_items):
                subset = readlist_items[index : (index + self.PAGE_SIZE)]
                for issue in subset:
                    metainfo = None
                    if comicarr.CONFIG.OPDS_METAINFO:
                        issuedetails = comicarr.helpers.IssueDetails(issue["fileloc"]).get("metadata", None)
                        if issuedetails is not None:
                            metainfo = issuedetails.get("metadata", None)
                    if not metainfo:
                        metainfo = [{"writer": None, "summary": ""}]
                    fileloc = issue["fileloc"]
                    if not os.path.isfile(fileloc):
                        logger.debug("Missing File: %s" % (fileloc))
                        continue
                    cb, _ = open_archive(fileloc)
                    if cb is None:
                        self.data = self._error_with_message("Can't open archive")
                        pse_count = 0  # Or just skip the issue?
                    else:
                        pse_count = page_count(cb)
                    entries.append(
                        {
                            "title": escape(issue["Title"]),
                            "id": escape("comic:%s" % issue["IssueID"]),
                            "updated": issue["updated"],
                            "content": escape("%s" % (metainfo[0]["summary"])),
                            "href": "%s?cmd=Issue&amp;issueid=%s&amp;file=%s"
                            % (self.opdsroot, quote_plus(issue["IssueID"]), quote_plus(issue["filename"])),
                            "stream": "%s?cmd=Stream&amp;issueid=%s&amp;file=%s"
                            % (self.opdsroot, quote_plus(issue["IssueID"]), quote_plus(issue["filename"])),
                            "pse_count": pse_count,
                            "kind": "acquisition",
                            "rel": "file",
                            "author": metainfo[0]["writer"],
                            "image": issue["image"],
                            "thumbnail": issue["thumbnail"],
                        }
                    )

            feed = {}
            feed["title"] = "Comicarr OPDS - ReadList"
            feed["id"] = escape("ReadList")
            feed["updated"] = comicarr.helpers.now()
            links.append(
                getLink(
                    href=self.opdsroot,
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="start",
                    title="Home",
                )
            )
            links.append(
                getLink(
                    href="%s?cmd=ReadList" % self.opdsroot,
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="self",
                )
            )
            if len(readlist_items) > (index + self.PAGE_SIZE):
                links.append(
                    getLink(
                        href="%s?cmd=ReadList&amp;index=%s" % (self.opdsroot, index + self.PAGE_SIZE),
                        type="application/atom+xml; profile=opds-catalog; kind=navigation",
                        rel="next",
                    )
                )
            if index >= self.PAGE_SIZE:
                links.append(
                    getLink(
                        href="%s?cmd=Read&amp;index=%s" % (self.opdsroot, index - self.PAGE_SIZE),
                        type="application/atom+xml; profile=opds-catalog; kind=navigation",
                        rel="previous",
                    )
                )

            feed["links"] = links
            feed["entries"] = entries
            self.data = feed
            return

    def _StoryArc(self, **kwargs):
        index = 0
        if "index" in kwargs:
            index = int(kwargs["index"])
        if "arcid" not in kwargs:
            self.data = self._error_with_message("No ArcID Provided")
            return
        links = []
        entries = []
        with db.get_engine().connect() as conn:
            stmt = select(storyarcs).where(storyarcs.c.StoryArcID == kwargs["arcid"]).order_by(storyarcs.c.ReadingOrder)
            arclist = [dict(row._mapping) for row in conn.execute(stmt)]
        newarclist = []
        arcname = ""
        for book in arclist:
            arcname = book["StoryArc"]
            fileexists = False
            issue = {}
            issue["ReadingOrder"] = book["ReadingOrder"]
            issue["Title"] = "%s #%s" % (book["ComicName"], book["IssueNumber"])
            issue["IssueID"] = book["IssueID"]
            issue["fileloc"] = ""
            if book["Location"]:
                issue["fileloc"] = book["Location"]
                fileexists = True
                issue["filename"] = os.path.split(book["Location"])[1]
                issue["image"] = None
                issue["thumbnail"] = None
                issue["updated"] = book["IssueDate"]
            else:
                with db.get_engine().connect() as conn:
                    stmt = select(issues).where(issues.c.IssueID == book["IssueID"])
                    result = [dict(row._mapping) for row in conn.execute(stmt)]
                    bookentry = result[0] if result else None
                if bookentry:
                    if bookentry["Location"]:
                        with db.get_engine().connect() as conn:
                            stmt = select(comics).where(comics.c.ComicID == bookentry["ComicID"])
                            result = [dict(row._mapping) for row in conn.execute(stmt)]
                            comic = result[0] if result else None
                        fileexists = True
                        issue["fileloc"] = os.path.join(comic["ComicLocation"], bookentry["Location"])
                        issue["filename"] = bookentry["Location"]
                        issue["image"] = bookentry["ImageURL_ALT"]
                        issue["thumbnail"] = bookentry["ImageURL"]
                    if bookentry["DateAdded"]:
                        issue["updated"] = bookentry["DateAdded"]
                    else:
                        issue["updated"] = bookentry["IssueDate"]
                else:
                    with db.get_engine().connect() as conn:
                        stmt = select(annuals).where(annuals.c.IssueID == book["IssueID"])
                        result = [dict(row._mapping) for row in conn.execute(stmt)]
                        annualentry = result[0] if result else None
                    if annualentry:
                        if annualentry["Location"]:
                            with db.get_engine().connect() as conn:
                                stmt = select(comics).where(comics.c.ComicID == annualentry["ComicID"])
                                result = [dict(row._mapping) for row in conn.execute(stmt)]
                                comic = result[0] if result else None
                            fileexists = True
                            issue["fileloc"] = os.path.join(comic["ComicLocation"], annualentry["Location"])
                            issue["filename"] = annualentry["Location"]
                            issue["image"] = None
                            issue["thumbnail"] = None
                            issue["updated"] = annualentry["IssueDate"]
                        else:
                            if book["Location"]:
                                fileexists = True
                                issue["fileloc"] = book["Location"]
                                issue["filename"] = os.path.split(book["Location"])[1]
                                issue["image"] = None
                                issue["thumbnail"] = None
                                issue["updated"] = book["IssueDate"]
            if not os.path.isfile(issue["fileloc"]):
                fileexists = False
            if fileexists:
                newarclist.append(issue)
        if len(newarclist) > 0:
            if index <= len(newarclist):
                subset = newarclist[index : (index + self.PAGE_SIZE)]
                for issue in subset:
                    metainfo = None
                    if comicarr.CONFIG.OPDS_METAINFO:
                        issuedetails = comicarr.helpers.IssueDetails(issue["fileloc"]).get("metadata", None)
                        if issuedetails is not None:
                            metainfo = issuedetails.get("metadata", None)
                    if not metainfo:
                        metainfo = [{"writer": None, "summary": ""}]
                    fileloc = issue["fileloc"]
                    cb, _ = open_archive(fileloc)
                    if cb is None:
                        self.data = self._error_with_message("Can't open archive")
                        pse_count = 0  # Or just skip the issue?
                    else:
                        pse_count = page_count(cb)
                    entries.append(
                        {
                            "title": escape("%s - %s" % (issue["ReadingOrder"], issue["Title"])),
                            "id": escape("comic:%s" % issue["IssueID"]),
                            "updated": issue["updated"],
                            "content": escape("%s" % (metainfo[0]["summary"])),
                            "href": "%s?cmd=Issue&amp;issueid=%s&amp;file=%s"
                            % (self.opdsroot, quote_plus(issue["IssueID"]), quote_plus(issue["filename"])),
                            "stream": "%s?cmd=Stream&amp;issueid=%s&amp;file=%s"
                            % (self.opdsroot, quote_plus(issue["IssueID"]), quote_plus(issue["filename"])),
                            "pse_count": pse_count,
                            "kind": "acquisition",
                            "rel": "file",
                            "author": metainfo[0]["writer"],
                            "image": issue["image"],
                            "thumbnail": issue["thumbnail"],
                        }
                    )

        feed = {}
        feed["title"] = "Comicarr OPDS - %s" % escape(arcname)
        feed["id"] = escape("storyarc:%s" % kwargs["arcid"])
        feed["updated"] = comicarr.helpers.now()
        links.append(
            getLink(
                href=self.opdsroot,
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="start",
                title="Home",
            )
        )
        links.append(
            getLink(
                href="%s?cmd=StoryArc&amp;arcid=%s" % (self.opdsroot, quote_plus(kwargs["arcid"])),
                type="application/atom+xml; profile=opds-catalog; kind=navigation",
                rel="self",
            )
        )
        if len(newarclist) > (index + self.PAGE_SIZE):
            links.append(
                getLink(
                    href="%s?cmd=StoryArc&amp;arcid=%s&amp;index=%s"
                    % (self.opdsroot, quote_plus(kwargs["arcid"]), index + self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="next",
                )
            )
        if index >= self.PAGE_SIZE:
            links.append(
                getLink(
                    href="%s?cmd=StoryArc&amp;arcid=%s&amp;index=%s"
                    % (self.opdsroot, quote_plus(kwargs["arcid"]), index - self.PAGE_SIZE),
                    type="application/atom+xml; profile=opds-catalog; kind=navigation",
                    rel="previous",
                )
            )

        feed["links"] = links
        feed["entries"] = entries
        self.data = feed
        return


def getLink(href=None, type=None, rel=None, title=None):
    link = {}
    if href:
        link["href"] = href
    if type:
        link["type"] = type
    if rel:
        link["rel"] = rel
    if title:
        link["title"] = title
    return link
