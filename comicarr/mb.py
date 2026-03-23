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

    # Build sort parameter - omit for relevance (API natural order is best proxy)
    sort_param = sort if (sort and sort != "relevance") else None

    # Build limit parameter - use provided limit or default to 100
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
    )  # 2012/22/02 - CVAPI flipped back to offset instead of page

    # all these imports are standard on most modern python implementations
    # logger.info('MB.PULLURL:' + PULLURL)

    # new CV API restriction - one api request / second.
    # Use intelligent rate limiter instead of fixed sleep
    comicarr.CV_RATE_LIMITER.acquire()

    # download the file:
    payload = None

    try:
        r = comicarr.CV_SESSION.get(
            PULLURL, params=payload, verify=comicarr.CONFIG.CV_VERIFY, timeout=comicarr.CV_TIMEOUT
        )
    except Exception as e:
        logger.warn("Error fetching data from ComicVine: %s" % e)
        return

    try:
        dom = parseString(r.content)  # (data)
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

    # Check if manga search is requested and MangaDex is enabled
    if content_type == "manga" and comicarr.CONFIG.MANGADEX_ENABLED:
        logger.info("[MANGADEX] Using MangaDex API for manga search")
        from comicarr import mangadex

        return mangadex.search_manga(name, limit=limit, offset=offset, sort=sort)

    # Check if Metron search is enabled and configured (only for volume/series search, not story arcs)
    if search_type != "story_arc" and comicarr.CONFIG.USE_METRON_SEARCH and comicarr.METRON_API:
        logger.info("[METRON] Using Metron API for search")
        from comicarr import metron

        return metron.search_series(
            name, mode=mode, issue=issue, limityear=limityear, limit=limit, offset=offset, sort=sort
        )

    # with mb_lock:
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

    # Determine pagination strategy based on whether limit/offset are provided
    if limit is not None:
        # Server-side pagination mode: fetch only the requested page
        page_offset = offset if offset is not None else 0
        page_limit = min(limit, 100)  # ComicVine API max is 100 per request

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

        # For pagination mode, we only fetch the single requested page
        all_pages = [(0, searched)]  # Use 0 as page index since we're only fetching one page
        totalResults_int = int(totalResults)

    else:
        # Legacy mode: fetch all results up to 1000 (backward compatibility)
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

        # Calculate pages needed (100 results per page)
        pages_needed = (totalResults_int + 99) // 100

        # Fetch all pages - either in parallel or sequentially
        all_pages = []
        if comicarr.CONFIG.CV_PARALLEL_PAGINATION and pages_needed > 1:
            parallel_start = time.time()
            logger.info(
                "[PARALLEL] Fetching %d pages in parallel (max %d workers)"
                % (pages_needed, comicarr.CONFIG.CV_MAX_PARALLEL_REQUESTS)
            )
            from concurrent.futures import ThreadPoolExecutor, as_completed

            # Start with first page already fetched
            all_pages = [(0, searched)]

            # Fetch remaining pages in parallel
            with ThreadPoolExecutor(
                max_workers=min(comicarr.CONFIG.CV_MAX_PARALLEL_REQUESTS, pages_needed - 1)
            ) as executor:
                # Submit remaining pages
                futures = {
                    executor.submit(
                        pullsearch, comicapi, comicquery, offset_val * 100, search_type, sort=sort
                    ): offset_val
                    for offset_val in range(1, pages_needed)
                }

                # Collect results as they complete
                for future in as_completed(futures):
                    offset_val = futures[future]
                    try:
                        result = future.result()
                        if result:
                            all_pages.append((offset_val, result))
                    except Exception as e:
                        logger.error("[PARALLEL] Error fetching page %d: %s" % (offset_val, e))

            # Sort pages by offset to maintain order
            all_pages.sort(key=lambda x: x[0])
            parallel_duration = time.time() - parallel_start
            logger.info(
                "[PARALLEL] Fetched %d/%d pages successfully in %.2f seconds"
                % (len(all_pages), pages_needed, parallel_duration)
            )
        else:
            # Sequential fetching (original behavior)
            countResults = 0
            while countResults < totalResults_int:
                if countResults > 0:
                    searched = pullsearch(comicapi, comicquery, countResults, search_type, sort=sort)
                if searched:
                    all_pages.append((countResults // 100, searched))
                countResults = countResults + 100

    # Process all pages
    for offset, searched in all_pages:
        comicResults = searched.getElementsByTagName(search_type)
        n = 0
        if not comicResults:
            break
        for result in comicResults:
            # retrieve the first xml tag (<tag>data</tag>)
            # that the parser finds with name tagName:
            arclist = []
            if search_type == "story_arc":
                # call cv.py here to find out issue count in story arc
                try:
                    logger.fdebug("story_arc ascension")
                    names = len(result.getElementsByTagName("name"))
                    n = 0
                    logger.fdebug("length: " + str(names))
                    xmlpub = None  # set this incase the publisher field isn't populated in the xml
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
                    # Lazy load story arc details - don't call storyarcinfo during search
                    # Arc details will be loaded on-demand when user views/clicks the arc
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
                # here we can determine what called us, and either start gathering all issues or just limited ones.
                if issue is not None and str(issue).isdigit():
                    # this gets buggered up with NEW/ONGOING series because the db hasn't been updated
                    # to reflect the proper count. Drop it by 1 to make sure.
                    limiter = int(issue) - 1
                else:
                    limiter = 0
                # get the first issue # (for auto-magick calcs)

                iss_len = len(result.getElementsByTagName("name"))
                i = 0
                xmlfirst = "1"
                xmllast = None
                try:
                    while i < iss_len:
                        if result.getElementsByTagName("name")[i].parentNode.nodeName == "first_issue":
                            xmlfirst = result.getElementsByTagName("issue_number")[i].firstChild.wholeText
                            if "\xbd" in xmlfirst:
                                xmlfirst = "1"  # if the first issue is 1/2, just assume 1 for logistics
                        elif result.getElementsByTagName("name")[i].parentNode.nodeName == "last_issue":
                            xmllast = result.getElementsByTagName("issue_number")[i].firstChild.wholeText
                        if all([xmllast is not None, xmlfirst is not None]):
                            break
                        i += 1
                except:
                    xmlfirst = "1"

                if all([xmlfirst == xmllast, xmlfirst.isdigit(), xmlcnt == "0"]):
                    xmlcnt = "1"

                # logger.info('There are : ' + str(xmlcnt) + ' issues in this series.')
                # logger.info('The first issue started at # ' + str(xmlfirst))
                try:
                    d = decimal.Decimal(xmlfirst)
                except Exception:
                    d = 1  # assume 1st issue as #1 if it can't be parsed.
                if d < 1:
                    cnt_numerical = int(xmlcnt) + 1
                else:
                    cnt_numerical = int(xmlcnt) + int(
                        math.ceil(d)
                    )  # (of issues + start of first issue = numerical range)

                # logger.info('The maximum issue number should be roughly # ' + str(cnt_numerical))
                # logger.info('The limiter (issue max that we know of) is # ' + str(limiter))
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
                            # break

                        # if result.getElementsByTagName('name')[cl].parentNode.nodeName == 'image':
                        #    xmlimage = result.getElementsByTagName('super_url')[0].firstChild.wholeText

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

                        # ignore specific publishers on a global scale here.
                        if ignored_publisher_check(xmlpub):
                            continue

                        try:
                            xmldesc = result.getElementsByTagName("description")[0].firstChild.wholeText
                            # xmldesc = cv.drophtml(xmldesc)
                        except:
                            xmldesc = "None"

                        # this is needed to display brief synopsis for each series on search results page.
                        try:
                            xmldeck = result.getElementsByTagName("deck")[0].firstChild.wholeText
                        except:
                            xmldeck = "None"

                        # Conditional imprint validation - only for known imprint publishers
                        IMPRINT_PUBLISHERS = ["Marvel", "DC Comics", "Image Comics"]
                        if not comicarr.CONFIG.CV_SKIP_IMPRINT_VALIDATION and xmlpub in IMPRINT_PUBLISHERS:
                            givb = cv.get_imprint_volume_and_booktype(
                                True, xmlYr, xmlpub, xml_firstissueid, xmldesc, xmldeck, annual_check
                            )
                            logger.fdebug("givb: %s" % (givb,))
                        else:
                            # Skip imprint validation - use existing values
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
                            # When skipping imprint validation, use defaults
                            xmltype = None
                            xmlvol = None
                            xmlimprint = None
                            # xmlpub and xmldesc already set above

                        # xmltype = None
                        # if xmldeck != 'None':
                        #    if any(['print' in xmldeck.lower(), 'digital' in xmldeck.lower(), 'paperback' in xmldeck.lower(), 'one shot' in re.sub('-', '', xmldeck.lower()).strip(), 'hardcover' in xmldeck.lower()]):
                        #        if all(['print' in xmldeck.lower(), 'reprint' not in xmldeck.lower()]):
                        #            xmltype = 'Print'
                        #        elif 'digital' in xmldeck.lower():
                        #            xmltype = 'Digital'
                        #        elif 'paperback' in xmldeck.lower():
                        #            xmltype = 'TPB'
                        #        elif 'graphic novel' in xmldeck.lower():
                        #            xmltype = 'GN'
                        #        elif 'hardcover' in xmldeck.lower():
                        #            xmltype = 'HC'
                        #        elif 'oneshot' in re.sub('-', '', xmldeck.lower()).strip():
                        #            xmltype = 'One-Shot'
                        #        else:
                        #            xmltype = 'Print'

                        # if xmldesc != 'None' and xmltype is None:
                        #    if 'print' in xmldesc[:60].lower() and all(['print edition can be found' not in xmldesc.lower(), 'reprints' not in xmldesc.lower()]):
                        #        xmltype = 'Print'
                        #    elif 'digital' in xmldesc[:60].lower() and 'digital edition can be found' not in xmldesc.lower():
                        #        xmltype = 'Digital'
                        #    elif all(['paperback' in xmldesc[:60].lower(), 'paperback can be found' not in xmldesc.lower()]) or all(['hardcover' not in xmldesc[:60].lower(), 'collects' in xmldesc[:60].lower()]):
                        #        xmltype = 'TPB'
                        #    elif all(['graphic novel' in xmldesc[:60].lower(), 'graphic novel can be found' not in xmldesc.lower()]):
                        #        xmltype = 'GN'
                        #    elif 'hardcover' in xmldesc[:60].lower() and 'hardcover can be found' not in xmldesc.lower():
                        #        xmltype = 'HC'
                        #    elif any(['one-shot' in xmldesc[:60].lower(), 'one shot' in xmldesc[:60].lower()]) and any(['can be found' not in xmldesc.lower(), 'following the' not in xmldesc.lower()]):
                        #        i = 0
                        #        xmltype = 'One-Shot'
                        #        avoidwords = ['preceding', 'after the special', 'following the']
                        #        while i < 2:
                        #            if i == 0:
                        #                cbd = 'one-shot'
                        #            elif i == 1:
                        #                cbd = 'one shot'
                        #            tmp1 = xmldesc[:60].lower().find(cbd)
                        #            if tmp1 != -1:
                        #                for x in avoidwords:
                        #                    tmp2 = xmldesc[:tmp1].lower().find(x)
                        #                    if tmp2 != -1:
                        #                        xmltype = 'Print'
                        #                        i = 3
                        #                        break
                        #            i+=1
                        #    else:
                        #        xmltype = 'Print'

                        if xmlid in comicLibrary:
                            haveit = comicLibrary[xmlid]
                        else:
                            # Fallback: check by name and year for cross-provider matching
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
                                "seriesrange": yearRange,  # returning additional information about series run polled from CV
                                "metadata_source": "comicvine",
                            }
                        )
                        # logger.fdebug('year: %s - constraint met: %s [%s] --- 4050-%s' % (xmlYr,xmlTag,xmlYr,xmlid))
                    else:
                        # logger.fdebug('year: ' + str(xmlYr) + ' -  contraint not met. Has to be within ' + str(limityear))
                        pass
            n += 1

    search_duration = time.time() - search_start_time
    logger.info(
        "[SEARCH PERFORMANCE] Search completed in %.2f seconds (%d results)" % (search_duration, len(comiclist))
    )

    # Return with pagination metadata if limit was provided, otherwise return legacy format
    if limit is not None:
        return {
            "results": comiclist,
            "pagination": {
                "total": totalResults_int,
                "limit": limit,
                "offset": page_offset,  # Use page_offset instead of offset
                "returned": len(comiclist),
            },
        }
    else:
        # Legacy format: just return the list
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

    # respawn to the exact id for the story arc and count the # of issues present.
    ARCPULL_URL = (
        comicarr.CVURL
        + "story_arc/4045-"
        + str(xmlid)
        + "/?api_key="
        + str(comicapi)
        + "&field_list=issues,publisher,name,first_appeared_in_issue,deck,image&format=xml&offset=0"
    )
    # logger.fdebug('arcpull_url:' + str(ARCPULL_URL))

    # new CV API restriction - one api request / second.
    # Use intelligent rate limiter instead of fixed sleep
    comicarr.CV_RATE_LIMITER.acquire()

    # download the file:
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
        issuecount = len(issuedom)  # arcdom.getElementsByTagName('issue') )
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
                    break  # - dont' break out here as we want to gather ALL the issue ID's since it's here
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
        #'name':                 xmlTag,    #theese four are passed into it only when it's a new add
        #'url':                  xmlurl,    #needs to be modified for refreshing to work completely.
        #'publisher':            xmlpub,
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
