#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
OPDS domain router -- Atom XML catalog feeds for OPDS-compatible readers.

Replaces the CherryPy-based OPDS class (comicarr/opds.py) with proper
FastAPI endpoints. Each ``_method()`` from the original class becomes a
dedicated route returning ``application/atom+xml`` responses.
"""

import glob
import os
from urllib.parse import quote_plus
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from starlette.responses import FileResponse

import comicarr
from comicarr import db, helpers, logger
from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import require_opds_auth
from comicarr.getimage import comic_pages, open_archive, page_count, scale_image
from comicarr.tables import annuals, comics, issues, readlist, snatched, storyarcs

router = APIRouter(prefix="/opds", tags=["opds"])

OPDS_MEDIA = "application/atom+xml; profile=opds-catalog"


# ---------------------------------------------------------------------------
# Atom XML rendering helpers
# ---------------------------------------------------------------------------


def _opds_root():
    """Return the configured OPDS root path."""
    if comicarr.CONFIG.HTTP_ROOT is None:
        return "/" + comicarr.CONFIG.OPDS_ENDPOINT
    elif comicarr.CONFIG.HTTP_ROOT.endswith("/"):
        return comicarr.CONFIG.HTTP_ROOT + comicarr.CONFIG.OPDS_ENDPOINT
    else:
        if comicarr.CONFIG.HTTP_ROOT != "/":
            return comicarr.CONFIG.HTTP_ROOT + "/" + comicarr.CONFIG.OPDS_ENDPOINT
        else:
            return "/" + comicarr.CONFIG.OPDS_ENDPOINT


def _get_link(href=None, ltype=None, rel=None, title=None):
    parts = []
    if href:
        parts.append("href=%s" % quoteattr(href))
    if ltype:
        parts.append("type=%s" % quoteattr(ltype))
    if rel:
        parts.append("rel=%s" % quoteattr(rel))
    if title:
        parts.append("title=%s" % quoteattr(title))
    return "<link %s/>" % " ".join(parts)


def _entry_xml(entry):
    """Render a single OPDS <entry> element.

    All text content is escaped via xml.sax.saxutils.escape() and all
    href attribute values via quoteattr() to prevent XML injection.
    """
    lines = ["<entry>"]
    lines.append("  <title>%s</title>" % escape(str(entry.get("title", ""))))
    lines.append("  <id>%s</id>" % escape(str(entry.get("id", ""))))
    lines.append("  <updated>%s</updated>" % escape(str(entry.get("updated", ""))))
    if entry.get("author"):
        lines.append("  <author><name>%s</name></author>" % escape(str(entry["author"])))
    if entry.get("content"):
        lines.append('  <content type="text">%s</content>' % escape(str(entry["content"])))
    href = entry.get("href", "")
    kind = entry.get("kind", "navigation")
    rel = entry.get("rel", "subsection")
    if kind == "acquisition":
        link_type = "application/atom+xml; profile=opds-catalog; kind=acquisition"
    else:
        link_type = "application/atom+xml; profile=opds-catalog; kind=navigation"
    if rel == "file":
        # Direct file download link
        ext = os.path.splitext(href.split("file=")[-1] if "file=" in href else href)[1].lower()
        if ext in (".cbr", ".rar"):
            mime = "application/x-cbr"
        elif ext in (".cbz", ".zip"):
            mime = "application/x-cbz"
        elif ext == ".pdf":
            mime = "application/pdf"
        else:
            mime = "application/octet-stream"
        lines.append(
            '  <link href=%s type=%s rel="http://opds-spec.org/acquisition"/>' % (quoteattr(href), quoteattr(mime))
        )
    else:
        lines.append("  <link href=%s type=%s rel=%s/>" % (quoteattr(href), quoteattr(link_type), quoteattr(rel)))
    if entry.get("stream"):
        lines.append(
            '  <link href=%s type="image/jpeg"'
            ' rel="http://vaemendis.net/opds-pse/stream"'
            ' pse:count="%s"/>' % (quoteattr(entry["stream"]), entry.get("pse_count", 0))
        )
    if entry.get("image"):
        lines.append('  <link href=%s type="image/jpeg" rel="http://opds-spec.org/image"/>' % quoteattr(entry["image"]))
    if entry.get("thumbnail"):
        lines.append(
            '  <link href=%s type="image/jpeg" rel="http://opds-spec.org/image/thumbnail"/>'
            % quoteattr(entry["thumbnail"])
        )
    lines.append("</entry>")
    return "\n".join(lines)


def _feed_xml(feed):
    """Render a complete Atom/OPDS feed document from a feed dict.

    Text content is escaped; attribute values use quoteattr().
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom"'
        ' xmlns:opds="http://opds-spec.org/2010/catalog"'
        ' xmlns:pse="http://vaemendis.net/opds-pse/ns">',
        "  <title>%s</title>" % escape(str(feed.get("title", ""))),
        "  <id>%s</id>" % escape(str(feed.get("id", ""))),
        "  <updated>%s</updated>" % escape(str(feed.get("updated", ""))),
    ]
    for link in feed.get("links", []):
        lines.append(
            "  "
            + _get_link(
                href=link.get("href"),
                ltype=link.get("type"),
                rel=link.get("rel"),
                title=link.get("title"),
            )
        )
    for entry in feed.get("entries", []):
        lines.append(_entry_xml(entry))
    lines.append("</feed>")
    return "\n".join(lines)


def _xml_response(feed):
    """Return a Response with the correct OPDS content type."""
    return Response(content=_feed_xml(feed), media_type=OPDS_MEDIA)


def _error_xml(message):
    """Return an XML error response."""
    xml = "<feed><error>%s</error></feed>" % escape(message)
    return Response(content=xml, media_type="text/xml", status_code=400)


def _not_enabled():
    return _error_xml("OPDS not enabled")


def _page_size():
    return comicarr.CONFIG.OPDS_PAGESIZE


# ---------------------------------------------------------------------------
# Navigation link helpers
# ---------------------------------------------------------------------------


def _nav_link(ltype="application/atom+xml; profile=opds-catalog; kind=navigation"):
    return ltype


def _start_link(opdsroot):
    return {"href": opdsroot, "type": _nav_link(), "rel": "start", "title": "Home"}


def _self_link(href):
    return {"href": href, "type": _nav_link(), "rel": "self"}


def _next_link(href):
    return {"href": href, "type": _nav_link(), "rel": "next"}


def _prev_link(href):
    return {"href": href, "type": _nav_link(), "rel": "previous"}


# ---------------------------------------------------------------------------
# OPDS endpoints
# ---------------------------------------------------------------------------


@router.get("/", dependencies=[Depends(require_opds_auth)])
def opds_root(request: Request, ctx: AppContext = Depends(get_context)):
    """OPDS catalog root -- navigation feed."""
    if not comicarr.CONFIG.OPDS_ENABLE:
        return _not_enabled()

    opdsroot = _opds_root()
    feed = {}
    feed["title"] = "Comicarr OPDS"
    feed["id"] = str(request.url).replace("/", ":")
    feed["updated"] = helpers.now()
    links = []
    entries = []

    links.append(_start_link(opdsroot))
    links.append(_self_link(opdsroot))
    links.append(
        {
            "href": "%s?cmd=search" % opdsroot,
            "type": "application/opensearchdescription+xml",
            "rel": "search",
            "title": "Search",
        }
    )

    with db.get_engine().connect() as conn:
        from sqlalchemy import select

        stmt = select(comics.c.ComicPublisher).group_by(comics.c.ComicPublisher)
        publishers = [dict(row._mapping) for row in conn.execute(stmt)]

    entries.append(
        {
            "title": "Recent Additions",
            "id": "Recent",
            "updated": helpers.now(),
            "content": "Recently Added Issues",
            "href": "%s?cmd=Recent" % opdsroot,
            "kind": "acquisition",
            "rel": "subsection",
        }
    )

    if len(publishers) > 0:
        entries.append(
            {
                "title": "Publishers (%s)" % len(publishers),
                "id": "Publishers",
                "updated": helpers.now(),
                "content": "List of Comic Publishers",
                "href": "%s?cmd=Publishers" % opdsroot,
                "kind": "navigation",
                "rel": "subsection",
            }
        )

    comics_list = helpers.havetotals()
    count = sum(1 for c in comics_list if c["haveissues"] is not None and c["haveissues"] > 0)
    if count > -1:
        entries.append(
            {
                "title": "All Titles (%s)" % count,
                "id": "AllTitles",
                "updated": helpers.now(),
                "content": "List of All Comics",
                "href": "%s?cmd=AllTitles" % opdsroot,
                "kind": "navigation",
                "rel": "subsection",
            }
        )

    story_arcs = helpers.listStoryArcs()
    if len(story_arcs) > 0:
        entries.append(
            {
                "title": "Story Arcs (%s)" % len(story_arcs),
                "id": "StoryArcs",
                "updated": helpers.now(),
                "content": "List of Story Arcs",
                "href": "%s?cmd=StoryArcs" % opdsroot,
                "kind": "navigation",
                "rel": "subsection",
            }
        )

    with db.get_engine().connect() as conn:
        from sqlalchemy import select

        stmt = select(readlist)
        read_list = [dict(row._mapping) for row in conn.execute(stmt)]
    if len(read_list) > 0:
        entries.append(
            {
                "title": "Read List (%s)" % len(read_list),
                "id": "ReadList",
                "updated": helpers.now(),
                "content": "Current Read List",
                "href": "%s?cmd=ReadList" % opdsroot,
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
                "updated": helpers.now(),
                "content": "OneOffs",
                "href": "%s?cmd=OneOffs" % opdsroot,
                "kind": "navigation",
                "rel": "subsection",
            }
        )

    feed["links"] = links
    feed["entries"] = entries
    return _xml_response(feed)


@router.get("/publishers", dependencies=[Depends(require_opds_auth)])
def opds_publishers(
    index: int = Query(0),
    ctx: AppContext = Depends(get_context),
):
    """OPDS publishers list."""
    if not comicarr.CONFIG.OPDS_ENABLE:
        return _not_enabled()

    opdsroot = _opds_root()
    page_size = _page_size()
    feed = {}
    feed["title"] = "Comicarr OPDS - Publishers"
    feed["id"] = "Publishers"
    feed["updated"] = helpers.now()
    links = [_start_link(opdsroot), _self_link("%s?cmd=Publishers" % opdsroot)]
    entries = []

    with db.get_engine().connect() as conn:
        from sqlalchemy import select

        stmt = select(comics.c.ComicPublisher).group_by(comics.c.ComicPublisher)
        publishers = [dict(row._mapping) for row in conn.execute(stmt)]

    comics_list = helpers.havetotals()
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
                    "title": "%s (%s)" % (publisher["ComicPublisher"], totaltitles),
                    "id": "publisher:%s" % publisher["ComicPublisher"],
                    "updated": lastupdated,
                    "content": "%s (%s)" % (publisher["ComicPublisher"], totaltitles),
                    "href": "%s?cmd=Publisher&amp;pubid=%s" % (opdsroot, quote_plus(publisher["ComicPublisher"])),
                    "kind": "navigation",
                    "rel": "subsection",
                }
            )

    if len(entries) > (index + page_size):
        links.append(_next_link("%s?cmd=Publishers&amp;index=%s" % (opdsroot, index + page_size)))
    if index >= page_size:
        links.append(_prev_link("%s?cmd=Publishers&amp;index=%s" % (opdsroot, index - page_size)))

    feed["links"] = links
    feed["entries"] = entries[index : (index + page_size)]
    return _xml_response(feed)


@router.get("/titles", dependencies=[Depends(require_opds_auth)])
def opds_all_titles(
    index: int = Query(0),
    ctx: AppContext = Depends(get_context),
):
    """OPDS all titles list."""
    if not comicarr.CONFIG.OPDS_ENABLE:
        return _not_enabled()

    opdsroot = _opds_root()
    page_size = _page_size()
    feed = {}
    feed["title"] = "Comicarr OPDS - All Titles"
    feed["id"] = "AllTitles"
    feed["updated"] = helpers.now()
    links = [_start_link(opdsroot), _self_link("%s?cmd=AllTitles" % opdsroot)]
    entries = []

    comics_list = helpers.havetotals()
    for comic in comics_list:
        if comic["haveissues"] > 0:
            entries.append(
                {
                    "title": "%s (%s) (comicID: %s)" % (comic["ComicName"], comic["ComicYear"], comic["ComicID"]),
                    "id": "comic:%s (%s) [%s]" % (comic["ComicName"], comic["ComicYear"], comic["ComicID"]),
                    "updated": comic["DateAdded"],
                    "content": "%s (%s)" % (comic["ComicName"], comic["ComicYear"]),
                    "href": "%s?cmd=Comic&amp;comicid=%s" % (opdsroot, quote_plus(comic["ComicID"])),
                    "kind": "acquisition",
                    "rel": "subsection",
                }
            )

    if len(entries) > (index + page_size):
        links.append(_next_link("%s?cmd=AllTitles&amp;index=%s" % (opdsroot, index + page_size)))
    if index >= page_size:
        links.append(_prev_link("%s?cmd=AllTitles&amp;index=%s" % (opdsroot, index - page_size)))

    feed["links"] = links
    feed["entries"] = entries[index : (index + page_size)]
    return _xml_response(feed)


@router.get("/publishers/{publisher}", dependencies=[Depends(require_opds_auth)])
def opds_publisher(
    publisher: str,
    index: int = Query(0),
    ctx: AppContext = Depends(get_context),
):
    """OPDS publisher detail -- comics from a specific publisher."""
    if not comicarr.CONFIG.OPDS_ENABLE:
        return _not_enabled()

    opdsroot = _opds_root()
    page_size = _page_size()
    links = [_start_link(opdsroot), _self_link("%s?cmd=Publishers" % opdsroot)]
    entries = []

    allcomics = helpers.havetotals()
    for comic in allcomics:
        if comic["ComicPublisher"] == publisher and comic["haveissues"] > 0:
            entries.append(
                {
                    "title": "%s (%s)" % (comic["ComicName"], comic["ComicYear"]),
                    "id": "comic:%s (%s)" % (comic["ComicName"], comic["ComicYear"]),
                    "updated": comic["DateAdded"],
                    "content": "%s (%s)" % (comic["ComicName"], comic["ComicYear"]),
                    "href": "%s?cmd=Comic&amp;comicid=%s" % (opdsroot, quote_plus(comic["ComicID"])),
                    "kind": "acquisition",
                    "rel": "subsection",
                }
            )

    feed = {}
    pubname = "%s (%s)" % (publisher, len(entries))
    feed["title"] = "Comicarr OPDS - %s" % pubname
    feed["id"] = "publisher:%s" % publisher
    feed["updated"] = helpers.now()

    if len(entries) > (index + page_size):
        links.append(
            _next_link(
                "%s?cmd=Publisher&amp;pubid=%s&amp;index=%s" % (opdsroot, quote_plus(publisher), index + page_size)
            )
        )
    if index >= page_size:
        links.append(
            _prev_link(
                "%s?cmd=Publisher&amp;pubid=%s&amp;index=%s" % (opdsroot, quote_plus(publisher), index - page_size)
            )
        )

    feed["links"] = links
    feed["entries"] = entries[index : (index + page_size)]
    return _xml_response(feed)


@router.get("/comics/{comic_id}", dependencies=[Depends(require_opds_auth)])
def opds_comic(
    comic_id: str,
    index: int = Query(0),
    ctx: AppContext = Depends(get_context),
):
    """OPDS comic detail -- issues for a specific comic."""
    if not comicarr.CONFIG.OPDS_ENABLE:
        return _not_enabled()

    opdsroot = _opds_root()
    page_size = _page_size()
    links = []
    entries = []

    with db.get_engine().connect() as conn:
        from sqlalchemy import select

        stmt = select(comics).where(comics.c.ComicID == comic_id)
        result = [dict(row._mapping) for row in conn.execute(stmt)]
        comic = result[0] if result else None
    if not comic:
        return _error_xml("Comic Not Found")

    with db.get_engine().connect() as conn:
        from sqlalchemy import select

        stmt = select(issues).where(issues.c.ComicID == comic_id).order_by(issues.c.Int_IssueNumber.desc())
        issues_list = [dict(row._mapping) for row in conn.execute(stmt)]

    if comicarr.CONFIG.ANNUALS_ON:
        with db.get_engine().connect() as conn:
            from sqlalchemy import select

            stmt = select(annuals).where(annuals.c.ComicID == comic_id)
            annuals_list = [dict(row._mapping) for row in conn.execute(stmt)]
    else:
        annuals_list = []

    for annual in annuals_list:
        issues_list.append(annual)

    issues_list = [x for x in issues_list if x["Location"]]

    if index <= len(issues_list):
        subset = issues_list[index : (index + page_size)]
        for issue in subset:
            if "DateAdded" in issue and issue["DateAdded"]:
                updated = issue["DateAdded"]
            else:
                updated = issue["ReleaseDate"]
            image = None
            thumbnail = None
            if "ReleaseComicID" not in issue:
                title = "%s (%s) #%s - %s" % (
                    issue["ComicName"],
                    comic["ComicYear"],
                    issue["Issue_Number"],
                    issue["IssueName"],
                )
                image = issue["ImageURL_ALT"]
                thumbnail = issue["ImageURL"]
            else:
                title = "Annual %s - %s" % (issue["Issue_Number"], issue["IssueName"])

            fileloc = os.path.join(comic["ComicLocation"], issue["Location"])
            if not os.path.isfile(fileloc):
                logger.debug("Missing File: %s" % fileloc)
                continue

            metainfo = None
            if comicarr.CONFIG.OPDS_METAINFO:
                issuedetails = helpers.IssueDetails(fileloc).get("metadata", None)
                if issuedetails is not None:
                    metainfo = issuedetails.get("metadata", None)
            if not metainfo:
                metainfo = [{"writer": None, "summary": ""}]

            cb, _ = open_archive(fileloc)
            if cb is None:
                pse_count = 0
            else:
                pse_count = page_count(cb)

            entries.append(
                {
                    "title": title,
                    "id": "comic:%s (%s) [%s] - %s"
                    % (issue["ComicName"], comic["ComicYear"], comic["ComicID"], issue["Issue_Number"]),
                    "updated": updated,
                    "content": "%s" % metainfo[0]["summary"],
                    "href": "%s?cmd=Issue&amp;issueid=%s&amp;file=%s"
                    % (opdsroot, quote_plus(issue["IssueID"]), quote_plus(issue["Location"])),
                    "stream": "%s?cmd=Stream&amp;issueid=%s&amp;file=%s"
                    % (opdsroot, quote_plus(issue["IssueID"]), quote_plus(issue["Location"])),
                    "pse_count": pse_count,
                    "kind": "acquisition",
                    "rel": "file",
                    "author": metainfo[0]["writer"],
                    "image": image,
                    "thumbnail": thumbnail,
                }
            )

    feed = {}
    comicname = "%s" % comic["ComicName"]
    feed["title"] = "Comicarr OPDS - %s" % comicname
    feed["id"] = "comic:%s (%s)" % (comic["ComicName"], comic["ComicYear"])
    feed["updated"] = comic["DateAdded"]
    links.append(_start_link(opdsroot))
    links.append(_self_link("%s?cmd=Comic&amp;comicid=%s" % (opdsroot, quote_plus(comic_id))))

    if len(issues_list) > (index + page_size):
        links.append(
            _next_link("%s?cmd=Comic&amp;comicid=%s&amp;index=%s" % (opdsroot, quote_plus(comic_id), index + page_size))
        )
    if index >= page_size:
        links.append(
            _prev_link("%s?cmd=Comic&amp;comicid=%s&amp;index=%s" % (opdsroot, quote_plus(comic_id), index - page_size))
        )

    feed["links"] = links
    feed["entries"] = entries
    return _xml_response(feed)


@router.get("/recent", dependencies=[Depends(require_opds_auth)])
def opds_recent(
    index: int = Query(0),
    ctx: AppContext = Depends(get_context),
):
    """OPDS recent additions feed."""
    if not comicarr.CONFIG.OPDS_ENABLE:
        return _not_enabled()

    opdsroot = _opds_root()
    page_size = _page_size()
    links = []
    entries = []

    from sqlalchemy import select

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
        subset = recents[index : (index + page_size)]

        # Batch-load all IssueIDs and ComicIDs for this page
        issue_ids = [r["IssueID"] for r in subset if r.get("IssueID")]
        comic_ids = [r["ComicID"] for r in subset if r.get("ComicID")]

        issues_lookup = {}
        annuals_lookup = {}
        comics_lookup = {}

        if issue_ids:
            with db.get_engine().connect() as conn:
                rows = [
                    dict(row._mapping) for row in conn.execute(select(issues).where(issues.c.IssueID.in_(issue_ids)))
                ]
                for row in rows:
                    issues_lookup[row["IssueID"]] = row

                # Load annuals for any IssueIDs not found in issues
                missing_ids = [iid for iid in issue_ids if iid not in issues_lookup]
                if missing_ids:
                    rows = [
                        dict(row._mapping)
                        for row in conn.execute(select(annuals).where(annuals.c.IssueID.in_(missing_ids)))
                    ]
                    for row in rows:
                        annuals_lookup[row["IssueID"]] = row

        if comic_ids:
            with db.get_engine().connect() as conn:
                rows = [
                    dict(row._mapping) for row in conn.execute(select(comics).where(comics.c.ComicID.in_(comic_ids)))
                ]
                for row in rows:
                    comics_lookup[row["ComicID"]] = row

        for issue_rec in subset:
            issuebook = issues_lookup.get(issue_rec["IssueID"])
            if not issuebook:
                issuebook = annuals_lookup.get(issue_rec["IssueID"])
            comic = comics_lookup.get(issue_rec["ComicID"])

            updated = issue_rec["DateAdded"]
            image = None
            thumbnail = None

            if issuebook:
                if "ReleaseComicID" not in list(issuebook.keys()):
                    if issuebook["DateAdded"] is None:
                        title = "%03d: %s #%s - %s (In stores %s)" % (
                            index + number,
                            issuebook["ComicName"],
                            issuebook["Issue_Number"],
                            issuebook["IssueName"],
                            issuebook["ReleaseDate"],
                        )
                    else:
                        title = "%03d: %s #%s - %s (Added to Comicarr %s, in stores %s)" % (
                            index + number,
                            issuebook["ComicName"],
                            issuebook["Issue_Number"],
                            issuebook["IssueName"],
                            issuebook["DateAdded"],
                            issuebook["ReleaseDate"],
                        )
                    image = issuebook.get("ImageURL_ALT")
                    thumbnail = issuebook.get("ImageURL")
                else:
                    title = "%03d: %s Annual %s - %s (In stores %s)" % (
                        index + number,
                        issuebook["ComicName"],
                        issuebook["Issue_Number"],
                        issuebook["IssueName"],
                        issuebook["ReleaseDate"],
                    )

                number += 1
                if not issuebook["Location"]:
                    continue
                location = issuebook["Location"]
                fileloc = os.path.join(comic["ComicLocation"], issuebook["Location"])

                metainfo = None
                if comicarr.CONFIG.OPDS_METAINFO:
                    issuedetails = helpers.IssueDetails(fileloc).get("metadata", None)
                    if issuedetails is not None:
                        metainfo = issuedetails.get("metadata", None)
                if not metainfo:
                    metainfo = {}
                    metainfo[0] = {"writer": None, "summary": ""}

                cb, _ = open_archive(fileloc)
                if cb is None:
                    pse_count = 0
                else:
                    pse_count = page_count(cb)

                entries.append(
                    {
                        "title": title,
                        "id": "comic:%s (%s) - %s"
                        % (issuebook["ComicName"], comic["ComicYear"], issuebook["Issue_Number"]),
                        "updated": updated,
                        "content": "%s" % metainfo[0]["summary"],
                        "href": "%s?cmd=Issue&amp;issueid=%s&amp;file=%s"
                        % (opdsroot, quote_plus(issuebook["IssueID"]), quote_plus(location)),
                        "stream": "%s?cmd=Stream&amp;issueid=%s&amp;file=%s"
                        % (opdsroot, quote_plus(issuebook["IssueID"]), quote_plus(location)),
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
    feed["id"] = "New Arrivals"
    feed["updated"] = helpers.now()
    links.append(_start_link(opdsroot))
    links.append(_self_link("%s?cmd=Recent" % opdsroot))

    if len(recents) > (index + page_size):
        links.append(_next_link("%s?cmd=Recent&amp;index=%s" % (opdsroot, index + page_size)))
    if index >= page_size:
        links.append(_prev_link("%s?cmd=Recent&amp;index=%s" % (opdsroot, index - page_size)))

    feed["links"] = links
    feed["entries"] = entries
    return _xml_response(feed)


@router.get("/issues/{issue_id}", dependencies=[Depends(require_opds_auth)])
def opds_issue(
    issue_id: str,
    file: str = Query(None),
    ctx: AppContext = Depends(get_context),
):
    """OPDS issue detail -- resolve file location for download."""
    if not comicarr.CONFIG.OPDS_ENABLE:
        return _not_enabled()

    file_path, filename, resolved_issue_id = _resolve_issue_file(issue_id)
    if file_path is None:
        return _error_xml("Issue Not Found")

    if not _validate_file_path(file_path):
        return Response(status_code=403)

    # Mark as read
    try:
        from comicarr import readinglist

        logger.fdebug("OPDS is attempting to markasRead filename %s aka issue_id %s" % (filename, resolved_issue_id))
        readinglist.Readinglist().markasRead(IssueID=resolved_issue_id)
    except Exception:
        logger.fdebug("No reading list found to update.")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


@router.get("/stream/{issue_id}", dependencies=[Depends(require_opds_auth)])
def opds_stream(
    issue_id: str,
    file: str = Query(None),
    page: int = Query(None),
    width: int = Query(None),
    ctx: AppContext = Depends(get_context),
):
    """OPDS Page Streaming Extension 1.0 endpoint.

    Streams individual pages from a comic archive for compatible readers.
    """
    if not comicarr.CONFIG.OPDS_ENABLE:
        return _not_enabled()

    file_path, filename, resolved_issue_id = _resolve_issue_file(issue_id)
    if file_path is None:
        return _error_xml("Issue Not Found")

    if not _validate_file_path(file_path):
        return Response(status_code=403)

    if page is None:
        return _error_xml("No page number specified")

    cb, _ = open_archive(file_path)
    if cb is None:
        return _error_xml("Can't open archive")

    page_names = comic_pages(cb)
    if page < 0 or page >= len(page_names):
        return _error_xml("Page out of range")

    page_name = page_names[page]
    with cb.open(page_name) as ifile:
        if width is not None:
            from PIL import Image

            img = Image.open(ifile)
            img_width, img_height = img.size
            if width < img_width:
                iformat = "jpeg"
                data = scale_image(img, iformat, width)
            else:
                ifile.seek(0)
                iformat = img.format.lower() if img.format else "jpeg"
                data = ifile.read()
        else:
            ext = os.path.splitext(page_name)[1][1:]
            iformat = ext if ext else "jpeg"
            data = ifile.read()

    return Response(content=data, media_type="image/%s" % iformat)


@router.get("/storyarcs", dependencies=[Depends(require_opds_auth)])
def opds_storyarcs(
    index: int = Query(0),
    ctx: AppContext = Depends(get_context),
):
    """OPDS story arcs listing."""
    if not comicarr.CONFIG.OPDS_ENABLE:
        return _not_enabled()

    from operator import itemgetter

    opdsroot = _opds_root()
    page_size = _page_size()
    links = []
    entries = []
    arcs = []

    storyArcIds = helpers.listStoryArcs()
    for arc in storyArcIds:
        issuecount = 0
        arcname = ""
        updated = "0000-00-00"
        with db.get_engine().connect() as conn:
            from sqlalchemy import select

            stmt = select(storyarcs).where(storyarcs.c.StoryArcID == arc)
            arclist = [dict(row._mapping) for row in conn.execute(stmt)]
        for issue in arclist:
            if issue["Status"] == "Downloaded":
                issuecount += 1
                arcname = issue["StoryArc"]
                if issue["IssueDate"] > updated:
                    updated = issue["IssueDate"]
        if issuecount > 0:
            arcs.append(
                {
                    "StoryArcName": arcname,
                    "StoryArcID": arc,
                    "IssueCount": issuecount,
                    "updated": updated,
                }
            )

    newlist = sorted(arcs, key=itemgetter("StoryArcName"))
    subset = newlist[index : (index + page_size)]
    for arc in subset:
        entries.append(
            {
                "title": "%s (%s)" % (arc["StoryArcName"], arc["IssueCount"]),
                "id": "storyarc:%s" % arc["StoryArcID"],
                "updated": arc["updated"],
                "content": "%s (%s)" % (arc["StoryArcName"], arc["IssueCount"]),
                "href": "%s?cmd=StoryArc&amp;arcid=%s" % (opdsroot, quote_plus(arc["StoryArcID"])),
                "kind": "acquisition",
                "rel": "subsection",
            }
        )

    feed = {}
    feed["title"] = "Comicarr OPDS - Story Arcs"
    feed["id"] = "StoryArcs"
    feed["updated"] = helpers.now()
    links.append(_start_link(opdsroot))
    links.append(_self_link("%s?cmd=StoryArcs" % opdsroot))

    if len(arcs) > (index + page_size):
        links.append(_next_link("%s?cmd=StoryArcs&amp;index=%s" % (opdsroot, index + page_size)))
    if index >= page_size:
        links.append(_prev_link("%s?cmd=StoryArcs&amp;index=%s" % (opdsroot, index - page_size)))

    feed["links"] = links
    feed["entries"] = entries
    return _xml_response(feed)


@router.get("/storyarcs/{arc_id}", dependencies=[Depends(require_opds_auth)])
def opds_storyarc(
    arc_id: str,
    index: int = Query(0),
    ctx: AppContext = Depends(get_context),
):
    """OPDS story arc detail -- issues in reading order."""
    if not comicarr.CONFIG.OPDS_ENABLE:
        return _not_enabled()

    opdsroot = _opds_root()
    page_size = _page_size()
    links = []
    entries = []

    from sqlalchemy import select

    with db.get_engine().connect() as conn:
        stmt = select(storyarcs).where(storyarcs.c.StoryArcID == arc_id).order_by(storyarcs.c.ReadingOrder)
        arclist = [dict(row._mapping) for row in conn.execute(stmt)]

    # Batch-load all referenced IssueIDs and ComicIDs
    all_issue_ids = [b["IssueID"] for b in arclist if b.get("IssueID")]
    issues_lookup = {}
    annuals_lookup = {}
    comics_lookup = {}

    if all_issue_ids:
        with db.get_engine().connect() as conn:
            rows = [
                dict(row._mapping) for row in conn.execute(select(issues).where(issues.c.IssueID.in_(all_issue_ids)))
            ]
            for row in rows:
                issues_lookup[row["IssueID"]] = row

            missing_ids = [iid for iid in all_issue_ids if iid not in issues_lookup]
            if missing_ids:
                rows = [
                    dict(row._mapping)
                    for row in conn.execute(select(annuals).where(annuals.c.IssueID.in_(missing_ids)))
                ]
                for row in rows:
                    annuals_lookup[row["IssueID"]] = row

        # Collect all ComicIDs from issues and annuals lookups
        all_comic_ids = set()
        for row in issues_lookup.values():
            if row.get("ComicID"):
                all_comic_ids.add(row["ComicID"])
        for row in annuals_lookup.values():
            if row.get("ComicID"):
                all_comic_ids.add(row["ComicID"])

        if all_comic_ids:
            with db.get_engine().connect() as conn:
                rows = [
                    dict(row._mapping)
                    for row in conn.execute(select(comics).where(comics.c.ComicID.in_(list(all_comic_ids))))
                ]
                for row in rows:
                    comics_lookup[row["ComicID"]] = row

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
            bookentry = issues_lookup.get(book["IssueID"])
            if bookentry:
                if bookentry["Location"]:
                    comic = comics_lookup.get(bookentry["ComicID"])
                    if comic:
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
                annualentry = annuals_lookup.get(book["IssueID"])
                if annualentry:
                    if annualentry["Location"]:
                        comic = comics_lookup.get(annualentry["ComicID"])
                        if comic:
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

        if issue["fileloc"] and not os.path.isfile(issue["fileloc"]):
            fileexists = False
        if fileexists:
            newarclist.append(issue)

    if len(newarclist) > 0:
        if index <= len(newarclist):
            subset = newarclist[index : (index + page_size)]
            for issue in subset:
                metainfo = None
                if comicarr.CONFIG.OPDS_METAINFO:
                    issuedetails = helpers.IssueDetails(issue["fileloc"]).get("metadata", None)
                    if issuedetails is not None:
                        metainfo = issuedetails.get("metadata", None)
                if not metainfo:
                    metainfo = [{"writer": None, "summary": ""}]
                fileloc = issue["fileloc"]
                cb, _ = open_archive(fileloc)
                if cb is None:
                    pse_count = 0
                else:
                    pse_count = page_count(cb)
                entries.append(
                    {
                        "title": "%s - %s" % (issue["ReadingOrder"], issue["Title"]),
                        "id": "comic:%s" % issue["IssueID"],
                        "updated": issue["updated"],
                        "content": "%s" % metainfo[0]["summary"],
                        "href": "%s?cmd=Issue&amp;issueid=%s&amp;file=%s"
                        % (opdsroot, quote_plus(issue["IssueID"]), quote_plus(issue["filename"])),
                        "stream": "%s?cmd=Stream&amp;issueid=%s&amp;file=%s"
                        % (opdsroot, quote_plus(issue["IssueID"]), quote_plus(issue["filename"])),
                        "pse_count": pse_count,
                        "kind": "acquisition",
                        "rel": "file",
                        "author": metainfo[0]["writer"],
                        "image": issue["image"],
                        "thumbnail": issue["thumbnail"],
                    }
                )

    feed = {}
    feed["title"] = "Comicarr OPDS - %s" % arcname
    feed["id"] = "storyarc:%s" % arc_id
    feed["updated"] = helpers.now()
    links.append(_start_link(opdsroot))
    links.append(_self_link("%s?cmd=StoryArc&amp;arcid=%s" % (opdsroot, quote_plus(arc_id))))

    if len(newarclist) > (index + page_size):
        links.append(
            _next_link("%s?cmd=StoryArc&amp;arcid=%s&amp;index=%s" % (opdsroot, quote_plus(arc_id), index + page_size))
        )
    if index >= page_size:
        links.append(
            _prev_link("%s?cmd=StoryArc&amp;arcid=%s&amp;index=%s" % (opdsroot, quote_plus(arc_id), index - page_size))
        )

    feed["links"] = links
    feed["entries"] = entries
    return _xml_response(feed)


@router.get("/readlist", dependencies=[Depends(require_opds_auth)])
def opds_readlist(
    index: int = Query(0),
    ctx: AppContext = Depends(get_context),
):
    """OPDS reading list feed."""
    if not comicarr.CONFIG.OPDS_ENABLE:
        return _not_enabled()

    opdsroot = _opds_root()
    page_size = _page_size()
    links = []
    entries = []

    from sqlalchemy import select

    with db.get_engine().connect() as conn:
        stmt = select(readlist).where(readlist.c.Status != "Read")
        rlist = [dict(row._mapping) for row in conn.execute(stmt)]

    # Batch-load all referenced IssueIDs and ComicIDs
    rl_issue_ids = [b["IssueID"] for b in rlist if b.get("IssueID")]
    rl_comic_ids = [b["ComicID"] for b in rlist if b.get("ComicID")]

    rl_issues_lookup = {}
    rl_annuals_lookup = {}
    rl_comics_lookup = {}

    if rl_issue_ids:
        with db.get_engine().connect() as conn:
            rows = [
                dict(row._mapping) for row in conn.execute(select(issues).where(issues.c.IssueID.in_(rl_issue_ids)))
            ]
            for row in rows:
                rl_issues_lookup[row["IssueID"]] = row

            missing_ids = [iid for iid in rl_issue_ids if iid not in rl_issues_lookup]
            if missing_ids:
                rows = [
                    dict(row._mapping)
                    for row in conn.execute(select(annuals).where(annuals.c.IssueID.in_(missing_ids)))
                ]
                for row in rows:
                    rl_annuals_lookup[row["IssueID"]] = row

    if rl_comic_ids:
        with db.get_engine().connect() as conn:
            rows = [
                dict(row._mapping) for row in conn.execute(select(comics).where(comics.c.ComicID.in_(rl_comic_ids)))
            ]
            for row in rows:
                rl_comics_lookup[row["ComicID"]] = row

    readlist_items = []
    for book in rlist:
        fileexists = False
        issue = {}
        issue["Title"] = "%s #%s" % (book["ComicName"], book["Issue_Number"])
        issue["IssueID"] = book["IssueID"]
        comic = rl_comics_lookup.get(book["ComicID"])
        bookentry = rl_issues_lookup.get(book["IssueID"])
        if bookentry:
            if bookentry["Location"] and comic:
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
            annualentry = rl_annuals_lookup.get(book["IssueID"])
            if annualentry:
                if annualentry["Location"] and comic:
                    fileexists = True
                    issue["fileloc"] = os.path.join(comic["ComicLocation"], annualentry["Location"])
                    issue["filename"] = annualentry["Location"]
                    issue["image"] = None
                    issue["thumbnail"] = None
                    issue["updated"] = annualentry["IssueDate"]
        if fileexists and not os.path.isfile(issue.get("fileloc", "")):
            fileexists = False
        if fileexists:
            readlist_items.append(issue)

    if len(readlist_items) > 0:
        if index <= len(readlist_items):
            subset = readlist_items[index : (index + page_size)]
            for issue in subset:
                metainfo = None
                if comicarr.CONFIG.OPDS_METAINFO:
                    issuedetails = helpers.IssueDetails(issue["fileloc"]).get("metadata", None)
                    if issuedetails is not None:
                        metainfo = issuedetails.get("metadata", None)
                if not metainfo:
                    metainfo = [{"writer": None, "summary": ""}]
                fileloc = issue["fileloc"]
                if not os.path.isfile(fileloc):
                    logger.debug("Missing File: %s" % fileloc)
                    continue
                cb, _ = open_archive(fileloc)
                if cb is None:
                    pse_count = 0
                else:
                    pse_count = page_count(cb)
                entries.append(
                    {
                        "title": issue["Title"],
                        "id": "comic:%s" % issue["IssueID"],
                        "updated": issue["updated"],
                        "content": "%s" % metainfo[0]["summary"],
                        "href": "%s?cmd=Issue&amp;issueid=%s&amp;file=%s"
                        % (opdsroot, quote_plus(issue["IssueID"]), quote_plus(issue["filename"])),
                        "stream": "%s?cmd=Stream&amp;issueid=%s&amp;file=%s"
                        % (opdsroot, quote_plus(issue["IssueID"]), quote_plus(issue["filename"])),
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
    feed["id"] = "ReadList"
    feed["updated"] = helpers.now()
    links.append(_start_link(opdsroot))
    links.append(_self_link("%s?cmd=ReadList" % opdsroot))

    if len(readlist_items) > (index + page_size):
        links.append(_next_link("%s?cmd=ReadList&amp;index=%s" % (opdsroot, index + page_size)))
    if index >= page_size:
        links.append(_prev_link("%s?cmd=ReadList&amp;index=%s" % (opdsroot, index - page_size)))

    feed["links"] = links
    feed["entries"] = entries
    return _xml_response(feed)


@router.get("/oneoffs", dependencies=[Depends(require_opds_auth)])
def opds_oneoffs(
    index: int = Query(0),
    ctx: AppContext = Depends(get_context),
):
    """OPDS one-offs / grab bag listing."""
    if not comicarr.CONFIG.OPDS_ENABLE:
        return _not_enabled()

    opdsroot = _opds_root()
    page_size = _page_size()
    links = []
    entries = []

    gbd = str(comicarr.CONFIG.GRABBAG_DIR + "/*")
    flist = glob.glob(gbd)
    readlist_items = []
    for book in flist:
        issue = {}
        issue["Title"] = book
        issue["IssueID"] = book
        issue["fileloc"] = book
        issue["filename"] = book
        issue["image"] = None
        issue["thumbnail"] = None
        issue["updated"] = helpers.now()
        if os.path.isfile(issue["fileloc"]):
            readlist_items.append(issue)

    if len(readlist_items) > 0:
        if index <= len(readlist_items):
            subset = readlist_items[index : (index + page_size)]
            for issue in subset:
                metainfo = [{"writer": None, "summary": ""}]
                entries.append(
                    {
                        "title": issue["Title"],
                        "id": "comic:%s" % issue["IssueID"],
                        "updated": issue["updated"],
                        "content": "%s" % metainfo[0]["summary"],
                        "href": "%s?cmd=deliverFile&amp;file=%s&amp;filename=%s"
                        % (opdsroot, quote_plus(issue["fileloc"]), quote_plus(issue["filename"])),
                        "kind": "acquisition",
                        "rel": "file",
                        "author": metainfo[0]["writer"],
                        "image": issue["image"],
                        "thumbnail": issue["thumbnail"],
                    }
                )

    feed = {}
    feed["title"] = "Comicarr OPDS - One-Offs"
    feed["id"] = "OneOffs"
    feed["updated"] = helpers.now()
    links.append(_start_link(opdsroot))
    links.append(_self_link("%s?cmd=OneOffs" % opdsroot))

    if len(readlist_items) > (index + page_size):
        links.append(_next_link("%s?cmd=OneOffs&amp;index=%s" % (opdsroot, index + page_size)))
    if index >= page_size:
        links.append(_prev_link("%s?cmd=OneOffs&amp;index=%s" % (opdsroot, index - page_size)))

    feed["links"] = links
    feed["entries"] = entries
    return _xml_response(feed)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_issue_file(issue_id):
    """Resolve the file path for an issue ID.

    Checks storyarcs, issues, then annuals -- mirroring the original
    _Issue method. Returns (file_path, filename, issue_id) or
    (None, None, None) if not found.
    """
    from sqlalchemy import select

    # Check storyarcs first (they may have absolute Location paths)
    with db.get_engine().connect() as conn:
        stmt = select(storyarcs).where(
            storyarcs.c.IssueID == issue_id,
            storyarcs.c.Location.isnot(None),
        )
        result = [dict(row._mapping) for row in conn.execute(stmt)]
        issue = result[0] if result else None

    if issue:
        return issue["Location"], os.path.split(issue["Location"])[1], issue["IssueID"]

    # Check issues table
    with db.get_engine().connect() as conn:
        stmt = select(issues).where(issues.c.IssueID == issue_id)
        result = [dict(row._mapping) for row in conn.execute(stmt)]
        issue = result[0] if result else None

    if not issue:
        # Check annuals
        with db.get_engine().connect() as conn:
            stmt = select(annuals).where(annuals.c.IssueID == issue_id)
            result = [dict(row._mapping) for row in conn.execute(stmt)]
            issue = result[0] if result else None
        if not issue:
            return None, None, None

    # Look up the comic for the ComicLocation
    with db.get_engine().connect() as conn:
        stmt = select(comics).where(comics.c.ComicID == issue["ComicID"])
        result = [dict(row._mapping) for row in conn.execute(stmt)]
        comic = result[0] if result else None

    if not comic:
        return None, None, None

    file_path = os.path.join(comic["ComicLocation"], issue["Location"])
    return file_path, issue["Location"], issue["IssueID"]


def _validate_file_path(filepath):
    """Check that filepath is inside an allowed comic directory.

    Returns True if the path is within one of the configured directories,
    False otherwise.
    """
    real_path = os.path.realpath(filepath)
    allowed_dirs = [
        os.path.realpath(d)
        for d in [
            getattr(comicarr.CONFIG, "DESTINATION_DIR", ""),
            getattr(comicarr.CONFIG, "COMIC_DIR", ""),
            getattr(comicarr.CONFIG, "STORYARC_LOCATION", ""),
            getattr(comicarr.CONFIG, "GRABBAG_DIR", ""),
        ]
        if d
    ]
    if not allowed_dirs:
        return False
    return any(os.path.commonpath([real_path, d]) == d for d in allowed_dirs)
