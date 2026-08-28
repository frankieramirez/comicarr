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


import decimal
import http.client
import math
import platform
import re
import threading
import time
from xml.dom.minidom import parseString
from xml.parsers.expat import ExpatError

import comicarr
from comicarr import cv, logger
from comicarr.helpers import (
    ignored_publisher_check,
    listLibrary,
    listStoryArcs,
)

mb_lock = threading.Lock()


def patch_http_response_read(func):
    def inner(*args):
        try:
            return func(*args)
        except http.client.IncompleteRead as e:
            return e.partial

    return inner


http.client.HTTPResponse.read = patch_http_response_read(http.client.HTTPResponse.read)

if platform.python_version() == "2.7.6":
    http.client.HTTPConnection._http_vsn = 10
    http.client.HTTPConnection._http_vsn_str = "HTTP/1.0"


def pullsearch(comicapi, comicquery, offset, search_type, sort=None, limit=None):

    cnt = 1
    for x in comicquery:
        if cnt == 1:
            filterline = "%s" % x
        else:
            filterline += ",name:%s" % x
        cnt += 1

    sort_param = sort if (sort and sort != "relevance") else None

    limit_param = limit if limit else 100

    sort_segment = "&sort=" + sort_param if sort_param else ""
    PULLURL = (
        comicarr.CVURL
        + str(search_type)
        + "s?api_key="
        + str(comicapi)
        + "&filter=name:"
        + filterline
        + "&field_list=id,name,start_year,site_detail_url,count_of_issues,image,publisher,deck,description,first_issue,last_issue&format=xml&limit="
        + str(limit_param)
        + sort_segment
        + "&offset="
        + str(offset)
    )

    comicarr.CV_RATE_LIMITER.acquire()

    payload = None

    try:
        r = comicarr.CV_SESSION.get(
            PULLURL, params=payload, verify=comicarr.CONFIG.CV_VERIFY, timeout=comicarr.CV_TIMEOUT
        )
    except Exception as e:
        logger.warn("Error fetching data from ComicVine: %s" % e)
        return

    try:
        dom = parseString(r.content)
    except ExpatError:
        if "Abnormal Traffic Detected" in r.content.decode("utf-8"):
            logger.error("ComicVine has banned this server's IP address because it exceeded the API rate limit.")
        else:
            logger.warn(
                "[WARNING] ComicVine is not responding correctly at the moment. This is usually due to some problems on their end. If you re-try things again in a few moments, it might work properly."
            )
            comicarr.BACKENDSTATUS_CV = "down"
        return
    except Exception as e:
        logger.warn("[ERROR] Error returned from CV: %s" % e)
        return
    else:
        return dom


def findComic(
    name,
    mode,
    issue,
    limityear=None,
    search_type=None,
    annual_check=False,
    limit=None,
    offset=None,
    sort=None,
    content_type=None,
):
    search_start_time = time.time()
    logger.info(
        "[SEARCH PERFORMANCE] Starting search for: %s (limit=%s, offset=%s, sort=%s, content_type=%s)"
        % (name, limit, offset, sort, content_type)
    )

    if content_type == "manga" and comicarr.CONFIG.MANGADEX_ENABLED:
        logger.info("[MANGADEX] Using MangaDex API for manga search")
        from comicarr import mangadex

        return mangadex.search_manga(name, limit=limit, offset=offset, sort=sort)

    if search_type != "story_arc" and not annual_check and comicarr.CONFIG.USE_METRON_SEARCH and comicarr.METRON_API:
        logger.info("[METRON] Using Metron API for search")
        from comicarr import metron

        return metron.search_series(
            name, mode=mode, issue=issue, limityear=limityear, limit=limit, offset=offset, sort=sort
        )

    comicResults = None
    comicLibrary = listLibrary()
    comiclist = []
    arcinfolist = []

    commons = ["and", "the", "&", "-"]
    for x in commons:
        cnt = 0
        for m in re.finditer(x, name.lower()):
            cnt += 1
            tehstart = m.start()
            tehend = m.end()
            if any([x == "the", x == "and"]):
                if len(name) == tehend:
                    tehend = -1
                if not all([tehstart == 0, name[tehend] == " "]) or not all(
                    [tehstart != 0, name[tehstart - 1] == " ", name[tehend] == " "]
                ):
                    continue
            else:
                name = name.replace(x, " ", cnt)

    originalname = name
    if "+" in name:
        name = re.sub(r"\+", "PLUS", name)

    pattern = re.compile(r"\w+", re.UNICODE)
    name = pattern.findall(name)

    if "+" in originalname:
        y = []
        for x in name:
            y.append(re.sub("PLUS", "%2B", x))
        name = y

    if limityear is None:
        limityear = "None"

    comicquery = name

    if comicarr.CONFIG.COMICVINE_API == "None" or comicarr.CONFIG.COMICVINE_API is None:
        logger.warn(
            "You have not specified your own ComicVine API key - this is a requirement. Get your own @ http://api.comicvine.com."
        )
        return
    else:
        comicapi = comicarr.CONFIG.COMICVINE_API

    if search_type is None:
        search_type = "volume"

    if limit is not None:
        page_offset = offset if offset is not None else 0
        page_limit = min(limit, 100)

        logger.info("[PAGINATION] Fetching single page: limit=%d, offset=%d" % (page_limit, page_offset))
        searched = pullsearch(comicapi, comicquery, page_offset, search_type, sort=sort, limit=page_limit)
        if searched is None:
            return {
                "results": [],
                "pagination": {"total": 0, "limit": page_limit, "offset": page_offset, "returned": 0},
            }

        totalResults = searched.getElementsByTagName("number_of_total_results")[0].firstChild.wholeText
        logger.fdebug("there are " + str(totalResults) + " total search results")

        if not totalResults:
            return {
                "results": [],
                "pagination": {"total": 0, "limit": page_limit, "offset": page_offset, "returned": 0},
            }

        all_pages = [(0, searched)]
        totalResults_int = int(totalResults)

    else:
        logger.info("[LEGACY] Fetching all results (no pagination parameters)")
        searched = pullsearch(comicapi, comicquery, 0, search_type, sort=sort)
        if searched is None:
            return False

        totalResults = searched.getElementsByTagName("number_of_total_results")[0].firstChild.wholeText
        logger.fdebug("there are " + str(totalResults) + " search results...")
        if not totalResults:
            return False
        if int(totalResults) > 1000:
            logger.warn(
                "Search returned more than 1000 hits ["
                + str(totalResults)
                + "]. Only displaying first 1000 results - use more specifics or the exact ComicID if required."
            )
            totalResults = 1000

        totalResults_int = int(totalResults)

        pages_needed = (totalResults_int + 99) // 100

        all_pages = []
        if comicarr.CONFIG.CV_PARALLEL_PAGINATION and pages_needed > 1:
            parallel_start = time.time()
            logger.info(
                "[PARALLEL] Fetching %d pages in parallel (max %d workers)"
                % (pages_needed, comicarr.CONFIG.CV_MAX_PARALLEL_REQUESTS)
            )
            from concurrent.futures import ThreadPoolExecutor, as_completed

            all_pages = [(0, searched)]

            with ThreadPoolExecutor(
                max_workers=min(comicarr.CONFIG.CV_MAX_PARALLEL_REQUESTS, pages_needed - 1)
            ) as executor:
                futures = {
                    executor.submit(
                        pullsearch, comicapi, comicquery, offset_val * 100, search_type, sort=sort
                    ): offset_val
                    for offset_val in range(1, pages_needed)
                }

                for future in as_completed(futures):
                    offset_val = futures[future]
                    try:
                        result = future.result()
                        if result:
                            all_pages.append((offset_val, result))
                    except Exception as e:
                        logger.error("[PARALLEL] Error fetching page %d: %s" % (offset_val, e))

            all_pages.sort(key=lambda x: x[0])
            parallel_duration = time.time() - parallel_start
            logger.info(
                "[PARALLEL] Fetched %d/%d pages successfully in %.2f seconds"
                % (len(all_pages), pages_needed, parallel_duration)
            )
        else:
            countResults = 0
            while countResults < totalResults_int:
                if countResults > 0:
                    searched = pullsearch(comicapi, comicquery, countResults, search_type, sort=sort)
                if searched:
                    all_pages.append((countResults // 100, searched))
                countResults = countResults + 100

    for offset, searched in all_pages:
        comicResults = searched.getElementsByTagName(search_type)
        n = 0
        if not comicResults:
            break
        for result in comicResults:
            arclist = []
            if search_type == "story_arc":
                try:
                    logger.fdebug("story_arc ascension")
                    names = len(result.getElementsByTagName("name"))
                    n = 0
                    logger.fdebug("length: " + str(names))
                    xmlpub = None
                    while n < names:
                        logger.fdebug(result.getElementsByTagName("name")[n].parentNode.nodeName)
                        if result.getElementsByTagName("name")[n].parentNode.nodeName == "story_arc":
                            logger.fdebug("yes")
                            try:
                                xmlTag = result.getElementsByTagName("name")[n].firstChild.wholeText
                                xmlTag = xmlTag.strip()
                                logger.fdebug("name: " + xmlTag)
                            except:
                                logger.error(
                                    "There was a problem retrieving the given data from ComicVine. Ensure that www.comicvine.com is accessible."
                                )
                                return

                        elif result.getElementsByTagName("name")[n].parentNode.nodeName == "publisher":
                            logger.fdebug("publisher check.")
                            xmlpub = result.getElementsByTagName("name")[n].firstChild.wholeText

                        n += 1
                except:
                    logger.warn("error retrieving story arc search results.")
                    return

                siteurl = len(result.getElementsByTagName("site_detail_url"))
                s = 0
                logger.fdebug("length: " + str(names))
                xmlurl = None
                while s < siteurl:
                    logger.fdebug(result.getElementsByTagName("site_detail_url")[s].parentNode.nodeName)
                    if result.getElementsByTagName("site_detail_url")[s].parentNode.nodeName == "story_arc":
                        try:
                            xmlurl = result.getElementsByTagName("site_detail_url")[s].firstChild.wholeText
                        except:
                            logger.error(
                                "There was a problem retrieving the given data from ComicVine. Ensure that www.comicvine.com is accessible."
                            )
                            return
                    s += 1

                xmlid = result.getElementsByTagName("id")[0].firstChild.wholeText

                if xmlid is not None:
                    arcinfolist = {
                        "comicyear": None,
                        "issues": "?",
                        "arclist": None,
                        "comicimage": "",
                        "comicthumb": "",
                        "description": "Story Arc - Click to load details",
                        "deck": None,
                        "haveit": "No",
                    }
                    logger.info("[LAZY LOAD] Story arc %s - details deferred" % xmlid)
                    comiclist.append(
                        {
                            "name": xmlTag,
                            "comicyear": arcinfolist["comicyear"],
                            "comicid": xmlid,
                            "cvarcid": xmlid,
                            "url": xmlurl,
                            "issues": arcinfolist["issues"],
                            "comicimage": arcinfolist["comicimage"],
                            "comicthumb": arcinfolist["comicthumb"],
                            "publisher": xmlpub,
                            "description": arcinfolist["description"],
                            "deck": arcinfolist["deck"],
                            "arclist": arcinfolist["arclist"],
                            "haveit": arcinfolist["haveit"],
                        }
                    )
                else:
                    comiclist.append(
                        {
                            "name": xmlTag,
                            "comicyear": arcyear,
                            "comicid": xmlid,
                            "url": xmlurl,
                            "issues": issuecount,
                            "comicimage": xmlimage,
                            "comicthumb": xmlthumb,
                            "publisher": xmlpub,
                            "description": xmldesc,
                            "deck": xmldeck,
                            "arclist": arclist,
                            "haveit": haveit,
                        }
                    )

                    logger.fdebug("IssueID's that are a part of " + xmlTag + " : " + str(arclist))
            else:
                xmlcnt = result.getElementsByTagName("count_of_issues")[0].firstChild.wholeText
                if issue is not None and str(issue).isdigit():
                    limiter = int(issue) - 1
                else:
                    limiter = 0

                iss_len = len(result.getElementsByTagName("name"))
                i = 0
                xmlfirst = "1"
                xmllast = None
                try:
                    while i < iss_len:
                        if result.getElementsByTagName("name")[i].parentNode.nodeName == "first_issue":
                            xmlfirst = result.getElementsByTagName("issue_number")[i].firstChild.wholeText
                            if "\xbd" in xmlfirst:
                                xmlfirst = "1"
                        elif result.getElementsByTagName("name")[i].parentNode.nodeName == "last_issue":
                            xmllast = result.getElementsByTagName("issue_number")[i].firstChild.wholeText
                        if all([xmllast is not None, xmlfirst is not None]):
                            break
                        i += 1
                except:
                    xmlfirst = "1"

                if all([xmlfirst == xmllast, xmlfirst.isdigit(), xmlcnt == "0"]):
                    xmlcnt = "1"

                try:
                    d = decimal.Decimal(xmlfirst)
                except Exception:
                    d = 1
                if d < 1:
                    cnt_numerical = int(xmlcnt) + 1
                else:
                    cnt_numerical = int(xmlcnt) + int(math.ceil(d))

                if cnt_numerical >= limiter:
                    cnl = len(result.getElementsByTagName("name"))
                    cl = 0
                    xmlTag = "None"
                    xml_lastissueid = "None"
                    xml_firstissueid = "None"
                    while cl < cnl:
                        if result.getElementsByTagName("name")[cl].parentNode.nodeName == "volume":
                            xmlTag = result.getElementsByTagName("name")[cl].firstChild.wholeText
                            xmlTag = xmlTag.strip()

                        if result.getElementsByTagName("name")[cl].parentNode.nodeName == "last_issue":
                            xml_lastissueid = result.getElementsByTagName("id")[cl].firstChild.wholeText
                        if result.getElementsByTagName("name")[cl].parentNode.nodeName == "first_issue":
                            xml_firstissueid = result.getElementsByTagName("id")[cl].firstChild.wholeText
                        cl += 1

                    try:
                        xmlimage = result.getElementsByTagName("super_url")[0].firstChild.wholeText
                    except Exception:
                        try:
                            xmlimage = result.getElementsByTagName("small_url")[0].firstChild.wholeText
                        except Exception:
                            xmlimage = None

                    try:
                        xmlthumb = result.getElementsByTagName("thumb_url")[0].firstChild.wholeText
                    except Exception:
                        xmlthumb = None

                    if (result.getElementsByTagName("start_year")[0].firstChild) is not None:
                        xmlYr = result.getElementsByTagName("start_year")[0].firstChild.wholeText
                    else:
                        xmlYr = "0000"

                    yearRange = []
                    tmpYr = re.sub(r"\?", "", xmlYr)

                    if tmpYr.isdigit():
                        yearRange.append(tmpYr)
                        tmpyearRange = int(xmlcnt) / 12
                        if float(tmpyearRange):
                            tmpyearRange + 1
                        possible_years = int(tmpYr) + tmpyearRange

                        for i in range(int(tmpYr), int(possible_years), 1):
                            if not any(int(x) == int(i) for x in yearRange):
                                yearRange.append(str(i))

                    logger.fdebug(
                        "[RESULT]["
                        + str(limityear)
                        + "] ComicName:"
                        + xmlTag
                        + " -- "
                        + str(xmlYr)
                        + " [Series years: "
                        + str(yearRange)
                        + "]"
                    )
                    if tmpYr != xmlYr:
                        xmlYr = tmpYr

                    if any(v in limityear for v in yearRange) or limityear == "None":
                        xmlurl = result.getElementsByTagName("site_detail_url")[0].firstChild.wholeText
                        idl = len(result.getElementsByTagName("id"))
                        idt = 0
                        xmlid = None
                        while idt < idl:
                            if result.getElementsByTagName("id")[idt].parentNode.nodeName == "volume":
                                xmlid = result.getElementsByTagName("id")[idt].firstChild.wholeText
                                break
                            idt += 1

                        if xmlid is None:
                            logger.error("Unable to figure out the comicid - skipping this : " + str(xmlurl))
                            continue

                        publishers = result.getElementsByTagName("publisher")
                        if len(publishers) > 0:
                            pubnames = publishers[0].getElementsByTagName("name")
                            if len(pubnames) > 0:
                                xmlpub = pubnames[0].firstChild.wholeText
                            else:
                                xmlpub = "Unknown"
                        else:
                            xmlpub = "Unknown"

                        if ignored_publisher_check(xmlpub):
                            continue

                        try:
                            xmldesc = result.getElementsByTagName("description")[0].firstChild.wholeText
                        except:
                            xmldesc = "None"

                        try:
                            xmldeck = result.getElementsByTagName("deck")[0].firstChild.wholeText
                        except:
                            xmldeck = "None"

                        IMPRINT_PUBLISHERS = ["Marvel", "DC Comics", "Image Comics"]
                        if not comicarr.CONFIG.CV_SKIP_IMPRINT_VALIDATION and xmlpub in IMPRINT_PUBLISHERS:
                            givb = cv.get_imprint_volume_and_booktype(
                                True, xmlYr, xmlpub, xml_firstissueid, xmldesc, xmldeck, annual_check
                            )
                            logger.fdebug("givb: %s" % (givb,))
                        else:
                            givb = None
                            logger.fdebug("[SKIP IMPRINT] Skipping imprint validation for publisher: %s" % xmlpub)

                        if givb:
                            if givb["Type"] == "None":
                                xmltype = None
                            else:
                                xmltype = givb["Type"]
                            if givb["ComicDescription"] == "None":
                                pass
                            else:
                                xmldesc = givb["ComicDescription"]
                            if givb["ComicVersion"] == "None":
                                xmlvol = None
                            else:
                                xmlvol = givb["ComicVersion"]
                            if givb["ComicPublisher"] == "None":
                                xmlpub = None
                            else:
                                xmlpub = givb["ComicPublisher"]
                            if givb["PublisherImprint"] == "None":
                                xmlimprint = None
                            else:
                                xmlimprint = givb["PublisherImprint"]
                        else:
                            xmltype = None
                            xmlvol = None
                            xmlimprint = None

                        if xmlid in comicLibrary:
                            haveit = comicLibrary[xmlid]
                        else:
                            name_key = "name:" + xmlTag.lower().strip() + ":" + str(xmlYr).strip()
                            if name_key in comicLibrary:
                                haveit = comicLibrary[name_key]
                            else:
                                haveit = "No"
                        comiclist.append(
                            {
                                "name": xmlTag,
                                "comicyear": xmlYr,
                                "comicid": xmlid,
                                "url": xmlurl,
                                "issues": xmlcnt,
                                "comicimage": xmlimage,
                                "comicthumb": xmlthumb,
                                "publisher": xmlpub,
                                "description": xmldesc,
                                "deck": xmldeck,
                                "type": xmltype,
                                "haveit": haveit,
                                "lastissueid": xml_lastissueid,
                                "firstissueid": xml_firstissueid,
                                "volume": xmlvol,
                                "imprint": xmlimprint,
                                "seriesrange": yearRange,
                                "metadata_source": "comicvine",
                            }
                        )
                    else:
                        pass
            n += 1

    search_duration = time.time() - search_start_time
    logger.info(
        "[SEARCH PERFORMANCE] Search completed in %.2f seconds (%d results)" % (search_duration, len(comiclist))
    )

    if limit is not None:
        return {
            "results": comiclist,
            "pagination": {
                "total": totalResults_int,
                "limit": limit,
                "offset": page_offset,
                "returned": len(comiclist),
            },
        }
    else:
        return comiclist


def storyarcinfo(xmlid):

    comicLibrary = listStoryArcs()

    arcinfo = {}

    if comicarr.CONFIG.COMICVINE_API == "None" or comicarr.CONFIG.COMICVINE_API is None:
        logger.warn(
            "You have not specified your own ComicVine API key - this is a requirement. Get your own @ http://api.comicvine.com."
        )
        return
    else:
        comicapi = comicarr.CONFIG.COMICVINE_API

    ARCPULL_URL = (
        comicarr.CVURL
        + "story_arc/4045-"
        + str(xmlid)
        + "/?api_key="
        + str(comicapi)
        + "&field_list=issues,publisher,name,first_appeared_in_issue,deck,image&format=xml&offset=0"
    )

    comicarr.CV_RATE_LIMITER.acquire()

    payload = None

    try:
        r = comicarr.CV_SESSION.get(
            ARCPULL_URL, params=payload, verify=comicarr.CONFIG.CV_VERIFY, timeout=comicarr.CV_TIMEOUT
        )
    except Exception as e:
        logger.warn("While parsing data from ComicVine, got exception: %s" % e)
        return

    try:
        arcdom = parseString(r.content)
    except ExpatError:
        if "<title>Abnormal Traffic Detected" in r.content:
            logger.error("ComicVine has banned this server's IP address because it exceeded the API rate limit.")
        else:
            logger.warn("While parsing data from ComicVine, got exception: %s for data: %s" % (e, r.content))
        return
    except Exception as e:
        logger.warn("While parsing data from ComicVine, got exception: %s for data: %s" % (e, r.content))
        return

    try:
        logger.fdebug("story_arc ascension")
        issuedom = arcdom.getElementsByTagName("issue")
        issuecount = len(issuedom)
        isc = 0
        arclist = ""
        ordernum = 1
        for isd in issuedom:
            zeline = isd.getElementsByTagName("id")
            isdlen = len(zeline)
            isb = 0
            while isb < isdlen:
                if isc == 0:
                    arclist = str(zeline[isb].firstChild.wholeText).strip() + "," + str(ordernum)
                else:
                    arclist += "|" + str(zeline[isb].firstChild.wholeText).strip() + "," + str(ordernum)
                ordernum += 1
                isb += 1

            isc += 1

    except:
        logger.fdebug("unable to retrive issue count - nullifying value.")
        issuecount = 0

    try:
        firstid = None
        arcyear = None
        fid = len(arcdom.getElementsByTagName("id"))
        fi = 0
        while fi < fid:
            if arcdom.getElementsByTagName("id")[fi].parentNode.nodeName == "first_appeared_in_issue":
                if not arcdom.getElementsByTagName("id")[fi].firstChild.wholeText == xmlid:
                    logger.fdebug("hit it.")
                    firstid = arcdom.getElementsByTagName("id")[fi].firstChild.wholeText
                    break
            fi += 1
        logger.fdebug("firstid: " + str(firstid))
        if firstid is not None:
            firstdom = cv.pulldetails(comicid=None, rtype="firstissue", issueid=firstid)
            logger.fdebug("success")
            arcyear = cv.Getissue(firstid, firstdom, "firstissue")
    except:
        logger.fdebug("Unable to retrieve first issue details. Not caclulating at this time.")

    try:
        xmlimage = arcdom.getElementsByTagName("super_url")[0].firstChild.wholeText
    except:
        xmlimage = None

    try:
        xmlimage = result.getElementsByTagName("super_url")[0].firstChild.wholeText
    except Exception:
        try:
            xmlimage = result.getElementsByTagName("small_url")[0].firstChild.wholeText
        except Exception:
            xmlimage = None

    try:
        xmlthumb = result.getElementsByTagName("thumb_url")[0].firstChild.wholeText
    except Exception:
        xmlthumb = None

    try:
        xmldesc = arcdom.getElementsByTagName("desc")[0].firstChild.wholeText
    except:
        xmldesc = "None"

    try:
        xmlpub = arcdom.getElementsByTagName("publisher")[0].firstChild.wholeText
    except:
        xmlpub = "None"

    try:
        xmldeck = arcdom.getElementsByTagName("deck")[0].firstChild.wholeText
    except:
        xmldeck = "None"

    if xmlid in comicLibrary:
        haveit = comicLibrary[xmlid]
    else:
        haveit = "No"

    arcinfo = {
        "comicyear": arcyear,
        "comicid": xmlid,
        "issues": issuecount,
        "comicimage": xmlimage,
        "comicthumb": xmlthumb,
        "description": xmldesc,
        "deck": xmldeck,
        "arclist": arclist,
        "haveit": haveit,
        "publisher": xmlpub,
    }

    return arcinfo
