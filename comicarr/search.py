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


import contextvars
import datetime
import os
import pathlib
import re
import shutil
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from operator import itemgetter
from urllib.parse import unquote, urljoin, urlparse

import feedparser
import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import or_, select
from urllib3.util.retry import Retry

import comicarr
from comicarr import (
    db,
    failed,
    filechecker,
    findcomicfeed,
    getcomics,
    helpers,
    logger,
    notifiers,
    nzbget,
    rsscheck,
    sabnzbd,
    search_filer,
    series_kind,
    updater,
)
from comicarr.app.common.redaction import redact_sensitive_text
from comicarr.app.common.remote_artifacts import (
    resolve_remote_artifact_path,
    safe_remote_filename,
    write_chunks_atomically,
)
from comicarr.app.core.workers import submit_background_future
from comicarr.app.downloads import handoff
from comicarr.app.search.provider_config import provider_enabled, split_newznab_category_field
from comicarr.downloaders import external_server as exs
from comicarr.tables import (
    annuals,
    comics,
    issues,
    provider_searches,
    storyarcs,
    weekly,
)
from comicarr.torrent import monitor as torrent_monitor

# ThreadPoolExecutor for parallel provider searches
# Using a module-level executor allows connection reuse across searches
_search_executor = None


def get_search_executor():
    """
    Get the module-level ThreadPoolExecutor for parallel searches.
    Creates the executor lazily on first use.
    """
    global _search_executor
    if _search_executor is None:
        # Use a reasonable number of workers - not too many to avoid
        # overwhelming providers, but enough to see parallelization benefit
        _search_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="search_worker")
    return _search_executor


def _wanted_candidate_rows(table, statuses, *extra_conditions):
    """Load candidate and series state together for bulk eligibility checks."""
    stmt = (
        select(table, comics.c.Status.label("SeriesStatus"))
        .select_from(table.outerjoin(comics, comics.c.ComicID == table.c.ComicID))
        .where(table.c.Status.in_(statuses), *extra_conditions)
    )
    return db.select_all(stmt)


def parallel_search_providers(scarios_list, timeout=120):
    """
    Search multiple providers in parallel and return the first successful result.

    Args:
        scarios_list: List of scarios dicts, each containing parameters for one provider
        timeout: Maximum time to wait for all searches (seconds)

    Returns:
        The first successful findit result, or {'status': False} if none succeed
    """
    if not scarios_list:
        return {"status": False}

    # If only one provider, skip parallelization overhead
    if len(scarios_list) == 1:
        try:
            return search_the_matrix(scarios_list[0])
        except Exception as e:
            logger.warn("Search error: %s" % redact_sensitive_text(e))
            return {"status": False}

    executor = get_search_executor()
    futures = {}

    # Submit all searches
    for scarios in scarios_list:
        provider_name = list(scarios.get("current_prov", {}).keys())[0] if scarios.get("current_prov") else "unknown"
        future = submit_background_future(
            executor,
            search_the_matrix,
            args=(scarios,),
            name="provider-search:%s" % provider_name,
        )
        futures[future] = provider_name

    logger.fdebug(f"[PARALLEL-SEARCH] Submitted {len(futures)} provider searches in parallel")

    # Wait for results, return first success
    try:
        for future in as_completed(futures, timeout=timeout):
            provider_name = futures[future]
            try:
                result = future.result()
                if result.get("status") is True:
                    logger.info(f"[PARALLEL-SEARCH] Found result from {provider_name}")
                    # Cancel remaining futures
                    for f in futures:
                        if f != future and not f.done():
                            f.cancel()
                    return result
            except Exception as e:
                logger.warn("[PARALLEL-SEARCH] Error from %s: %s" % (provider_name, redact_sensitive_text(e)))
                continue
    except TimeoutError:
        logger.warn("[PARALLEL-SEARCH] Search timeout exceeded")

    # No successful results
    return {"status": False}


# Module-level HTTP session for connection pooling
# This reuses TCP connections across multiple requests, significantly
# improving performance when making many requests to the same hosts
_http_session = None


def _rss_result_log_summary(result):
    """Return useful RSS metadata without retaining provider-signed links."""
    return "rss result: site=%s title=%s" % (
        redact_sensitive_text(result.get("site", "unknown")),
        redact_sensitive_text(result.get("title", "unknown")),
    )


def get_http_session():
    """
    Get the module-level HTTP session with connection pooling.
    Creates the session lazily on first use.
    """
    global _http_session
    if unfiltered_pass_active():
        return _get_no_retry_http_session()
    if _http_session is None:
        _http_session = requests.Session()

        # Configure retry strategy for resilience
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )

        # Mount adapters with connection pool settings
        # pool_connections: number of connection pools to cache
        # pool_maxsize: max connections per pool
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
        _http_session.mount("http://", adapter)
        _http_session.mount("https://", adapter)

    return _http_session


_no_retry_http_session = None

_UNFILTERED_SERIES_PASS = contextvars.ContextVar("unfiltered_series_pass", default=False)


def unfiltered_pass_active():
    return bool(_UNFILTERED_SERIES_PASS.get())


@contextmanager
def unfiltered_series_pass():
    """Scope an unfiltered series search: one bare-title query per indexer.

    While active (#767): the bare-title pass runs on newznab as well as
    torznab, the pack-shaped pre-filter is skipped so every result reaches
    evaluation, RSS and alternate-name query variants are skipped so each
    indexer is queried exactly once, and HTTP transport retries are disabled
    so a failing indexer surfaces its error instead of being retried.
    """

    token = _UNFILTERED_SERIES_PASS.set(True)
    try:
        yield
    finally:
        _UNFILTERED_SERIES_PASS.reset(token)


def _get_no_retry_http_session():
    global _no_retry_http_session
    if _no_retry_http_session is None:
        _no_retry_http_session = requests.Session()
        adapter = HTTPAdapter(max_retries=Retry(total=0), pool_connections=10, pool_maxsize=20)
        _no_retry_http_session.mount("http://", adapter)
        _no_retry_http_session.mount("https://", adapter)
    return _no_retry_http_session


def _allow_packs_enabled(allow_packs):
    """Per-series AllowPacks arrives as 1, '1', or True depending on source."""
    return any([allow_packs == 1, allow_packs == "1", allow_packs is True])


def _bare_pack_pass_allowed(provider_stat):
    """The cmloopit-0 bare-title pack pass targets word-AND torrent indexers.

    Usenet (newznab) and experimental providers get nothing from a bare
    query that pack matching needs, so they keep the numbered passes only.
    The unfiltered series pass widens this to newznab: there the operator
    asked for every indexer's bare-title results, packs or not (#767).
    """
    if not isinstance(provider_stat, dict):
        return False
    if unfiltered_pass_active():
        return provider_stat.get("type") in ("torznab", "newznab")
    return provider_stat.get("type") == "torznab"


def search_init(
    ComicName,
    IssueNumber,
    ComicYear,
    SeriesYear,
    Publisher,
    IssueDate,
    StoreDate,
    IssueID,
    AlternateSearch=None,
    UseFuzzy=None,
    ComicVersion=None,
    SARC=None,
    IssueArcID=None,
    smode=None,
    rsschecker=None,
    ComicID=None,
    manualsearch=None,
    filesafe=None,
    allow_packs=None,
    oneoff=False,
    manual=False,
    torrentid_32p=None,
    digitaldate=None,
    booktype=None,
    ignore_booktype=False,
    _ai_expanded=False,
    content_type=None,
    chapter_number=None,
    volume_number=None,
):

    comicarr.COMICINFO = []
    # unaltered_ComicName = None
    # if filesafe:
    #    if filesafe != ComicName and smode != 'want_ann':
    #        logger.info(
    #            '[SEARCH] Special Characters exist within Series Title. Enabling'
    #            ' search-safe Name : %s' % filesafe
    #        )
    #        if AlternateSearch is None or AlternateSearch == 'None':
    #            AlternateSearch = filesafe
    #        else:
    #            AlternateSearch += '##' + filesafe
    #        unaltered_ComicName = ComicName

    if ComicYear is None:
        ComicYear = str(datetime.datetime.now().year)
    else:
        ComicYear = str(ComicYear)[:4]
    if Publisher:
        if Publisher == "IDW Publishing":
            Publisher = "IDW"
        logger.fdebug("Publisher is : %s" % Publisher)

    if IssueArcID and not IssueID:
        issuetitle = helpers.get_issue_title(IssueArcID)
    else:
        issuetitle = helpers.get_issue_title(IssueID)

    if issuetitle:
        logger.fdebug("Issue Title given as : %s" % issuetitle)
    else:
        logger.fdebug("Issue Title not found. Setting to None.")

    if smode == "pullwant" or IssueID is None:
        # one-off the download.
        logger.fdebug("One-Off Search parameters:")
        logger.fdebug("ComicName: %s" % ComicName)
        logger.fdebug("Issue: %s" % IssueNumber)
        logger.fdebug("Year: %s" % ComicYear)
        logger.fdebug("IssueDate: %s" % IssueDate)
        oneoff = True
    if SARC:
        logger.fdebug("Story-ARC Search parameters:")
        logger.fdebug("Story-ARC: %s" % SARC)
        logger.fdebug("IssueArcID: %s" % IssueArcID)

    # --- Manga content-type branch ---
    # When searching for manga chapters, construct manga-specific query terms
    # and inject them as AlternateSearch patterns. The rest of the search pipeline
    # (providers, matching, snatching) works unchanged.
    if content_type == "manga":
        logger.fdebug("[SEARCH-MANGA] Manga content detected for %s" % ComicName)
        manga_terms = _build_manga_search_terms(ComicName, chapter_number, volume_number)
        if manga_terms:
            manga_alt_str = "##".join(manga_terms)
            logger.fdebug("[SEARCH-MANGA] Generated %d search variations: %s" % (len(manga_terms), manga_terms))
            if AlternateSearch and AlternateSearch != "None":
                AlternateSearch = manga_alt_str + "##" + AlternateSearch
            else:
                AlternateSearch = manga_alt_str

    provider_list = provider_order(initial_run=True)
    if content_type == "manga":
        provider_list = _providers_without_ddl(provider_list)
    findit = {}
    findit["status"] = False

    if provider_list["totalproviders"] == 0:
        logger.error(
            "[WARNING] You have %s search providers enabled. I need at least ONE"
            " provider to work. Aborting search." % provider_list["totalproviders"]
        )
        findit["status"] = False
        nzbprov = None
        return findit, nzbprov

    logger.fdebug("search provider order is %s" % provider_list["prov_order"])

    # fix for issue dates between Nov-Dec/(Jan-Feb-Mar)
    IssDateFix = "no"
    if StoreDate is not None:
        StDt = str(StoreDate)[5:7]
        if any(
            [
                StDt == "10",
                StDt == "12",
                StDt == "11",
                StDt == "01",
                StDt == "02",
                StDt == "03",
            ]
        ):
            IssDateFix = StDt
    else:
        IssDt = str(IssueDate)[5:7]
        if any([IssDt == "12", IssDt == "11", IssDt == "01", IssDt == "02", IssDt == "03"]):
            IssDateFix = IssDt

    searchcnt = 0
    srchloop = 1

    # Interactive review: the operator is watching, so the retry layers built
    # for unattended search only delay the result sheet (#768). Skip the RSS
    # cache pass and (below) run one numbered query per provider.
    interactive = search_filer.interactive_collection_active()

    if rsschecker:
        if comicarr.CONFIG.ENABLE_RSS:
            searchcnt = 1  # rss-only
        else:
            searchcnt = 1  # if it's not enabled, don't even bother.
    elif interactive:
        searchcnt = 2
        srchloop = 2  # straight to API, no RSS pass
    else:
        if comicarr.CONFIG.ENABLE_RSS:
            searchcnt = 2  # rss first, then api on non-matches
        else:
            searchcnt = 2  # set the searchcnt to 2 (api)
            srchloop = 2  # start the counter at API, so itll exit without running RSS

    if unfiltered_pass_active():
        # One live query per indexer: the RSS pass would only replay cached
        # feed entries against the same session.
        searchcnt = 2
        srchloop = 2

    findcomiciss, c_number = get_findcomiciss(IssueNumber)

    while srchloop <= searchcnt:
        """searchmodes:
        rss - will run through the built-cached db of entries
        api - will run through the providers via api (or non-api in the case of
              Experimental) the trick is if the search is done during an rss compare,
              it needs to exit when done. Ootherwise, the order of operations is rss
              feed check first, followed by api on non-results.
        """

        if srchloop == 1:
            searchmode = "rss"  # order of ops - this will be used first.
        elif srchloop == 2:
            searchmode = "api"

        if "0-Day" in ComicName:
            cmloopit = 1
        else:
            cmloopit = None
            if any([booktype == "One-Shot", "annual" in ComicName.lower()]):
                cmloopit = 4
                if "annual" in ComicName.lower():
                    if IssueNumber is not None:
                        if helpers.issuedigits(IssueNumber) != 1000:
                            cmloopit = None
            if cmloopit is None:
                if len(c_number) == 1:
                    cmloopit = 3
                elif len(c_number) == 2:
                    cmloopit = 2
                else:
                    cmloopit = 1
        logger.info("cmloopit: %s" % cmloopit)
        chktpb = 0
        from comicarr.app.manga.acquisition import booktype_bypasses_format_gates

        if any([booktype == "TPB", booktype == "HC", booktype == "GN"]) and not booktype_bypasses_format_gates(
            booktype
        ):
            chktpb = 1

        # A pack title ("v01-14", "(2021-2026)") rarely contains the single
        # issue number being searched, so the numbered query variants never
        # retrieve packs from word-AND indexers (Nyaa et al) — the 0.34.0 pack
        # matcher starves (#744). When packs are allowed, one extra bare-title
        # pass (cmloopit 0) runs after the numbered variants. TPB/HC/GN
        # already get a bare pass through chktpb; RSS mode queries a cached
        # feed where the bare pass would only repeat the same lookup.
        pack_title_pass = all(
            [
                _allow_packs_enabled(allow_packs),
                comicarr.CONFIG.ENABLE_TORRENT_SEARCH,
                chktpb == 0,
                IssueNumber is not None,
                searchmode != "rss",
            ]
        )

        if unfiltered_pass_active():
            # Unfiltered series search (#767): exactly one bare-title query
            # per indexer — no numbered variants, regardless of Allow Packs.
            cmloopit = 0
            pack_title_pass = True

        if findit["status"] is True:
            logger.fdebug("Found result on first run, exiting search module now.")
            break

        logger.fdebug("Initiating Search via : %s" % searchmode)

        if len(provider_list["prov_order"]) == 1:
            tmp_prov_count = 1
        else:
            tmp_prov_count = len(provider_list["prov_order"])

        checked_once = []
        prov_count = 0

        while tmp_prov_count > prov_count:
            logger.info("tmp_prov_count: %s / prov_count: %s" % (tmp_prov_count, prov_count))
            tmp_cmloopit = cmloopit
            progress_provider = provider_list["prov_order"][prov_count]
            while tmp_cmloopit >= (0 if pack_title_pass else 1):
                if tmp_cmloopit == 4:
                    tmp_IssueNumber = None
                else:
                    tmp_IssueNumber = IssueNumber

                prov_order = provider_list["prov_order"]
                logger.info("checked_once: %s" % (checked_once,))
                if checked_once:
                    if prov_order[prov_count] in checked_once:
                        break
                provider_blocked = helpers.block_provider_check(prov_order[prov_count])
                if provider_blocked:
                    logger.warn("provider blocked. Ignoring search on this provider.")
                    break
                send_prov_count = tmp_prov_count - prov_count
                newznab_host = None
                torznab_host = None
                logger.info("prov_order[prov_count]: %s" % (prov_order[prov_count],))

                # this loads the previous runs from the db to ensure we're always persistant
                searchprov = last_run_check(check=True)
                # logger.fdebug('searchprov: %s' % (searchprov,))

                # should be DDL(GetComics)
                if (
                    prov_order[prov_count] == "DDL(GetComics)"
                    and not provider_blocked
                    and "DDL(GetComics)" not in checked_once
                ):
                    if "DDL(GetComics)" not in searchprov.keys():
                        searchprov["DDL(GetComics)"] = {
                            "id": 200,
                            "type": "DDL",
                            "lastrun": 0,
                            "active": True,
                            "hits": 0,
                        }
                    else:
                        searchprov["DDL(GetComics)"]["active"] = True
                elif (
                    prov_order[prov_count] == "DDL(External)"
                    and not provider_blocked
                    and "DDL(External)" not in checked_once
                ):
                    if "DDL(External)" not in searchprov.keys():
                        searchprov["DDL(External)"] = {
                            "id": 201,
                            "type": "DDL(External)",
                            "lastrun": 0,
                            "active": True,
                            "hits": 0,
                        }
                    else:
                        searchprov["DDL(External)"]["active"] = True
                elif prov_order[prov_count] == "32p" and not provider_blocked:
                    searchprov["32P"] = {"type": "torrent", "lastrun": 0, "active": True, "hits": 0}
                elif (
                    prov_order[prov_count].lower() == "experimental"
                    and not provider_blocked
                    and "experimental" not in checked_once
                ):
                    if all(["experimental" not in searchprov.keys(), "Experimental" not in searchprov.keys()]):
                        prov_order[prov_count] = "experimental"  # cause it's Experimental for display
                        logger.info("resetting searchprov - last run here..")
                        searchprov["experimental"] = {
                            "id": 101,
                            "type": "experimental",
                            "lastrun": 0,
                            "active": True,
                            "hits": 0,
                        }
                    else:
                        searchprov["experimental"]["active"] = True
                elif prov_order[prov_count] == "public torrents" and not provider_blocked:
                    if "Public Torrents" not in searchprov.keys():
                        searchprov["Public Torrents"] = {
                            "id": comicarr.PROVIDER_START_ID + 1,
                            "type": "torrent",
                            "lastrun": 0,
                            "active": True,
                            "hits": 0,
                        }
                    else:
                        searchprov["Public Torrents"]["active"] = True
                elif "torznab" in prov_order[prov_count]:
                    fnd = False
                    for nninfo in provider_list["torznab_info"]:
                        torznab_host = nninfo["info"]
                        if torznab_host is None:
                            logger.fdebug("there was an error - torznab information was blank and it should not be.")
                            break
                        if all(
                            [
                                nninfo["provider"] == prov_order[prov_count],
                                not provider_blocked,
                                torznab_host[0] not in searchprov.keys(),
                            ]
                        ):
                            searchprov[torznab_host[0]] = {
                                "id": comicarr.PROVIDER_START_ID + 1,
                                "type": "torznab",
                                "lastrun": 0,
                                "active": True,
                                "hits": 0,
                            }
                            fnd = True
                        elif all(
                            [
                                nninfo["provider"] == prov_order[prov_count],
                                not provider_blocked,
                                torznab_host[0] in searchprov.keys(),
                            ]
                        ):
                            searchprov[torznab_host[0]]["active"] = True
                            fnd = True
                        if fnd is True:
                            break
                elif "newznab" in prov_order[prov_count]:
                    fnd = False
                    for nninfo in provider_list["newznab_info"]:
                        newznab_host = nninfo["info"]
                        if newznab_host is None:
                            logger.fdebug("there was an error - newznab information was blank and it should not be.")
                            break
                        if all(
                            [
                                nninfo["provider"] == prov_order[prov_count],
                                not provider_blocked,
                                newznab_host[0] not in searchprov.keys(),
                            ]
                        ):
                            searchprov[newznab_host[0]] = {
                                "id": comicarr.PROVIDER_START_ID + 1,
                                "type": "newznab",
                                "lastrun": 0,
                                "active": True,
                                "hits": 0,
                            }
                            fnd = True
                        elif all(
                            [
                                nninfo["provider"] == prov_order[prov_count],
                                not provider_blocked,
                                newznab_host[0] in searchprov.keys(),
                            ]
                        ):
                            searchprov[newznab_host[0]]["active"] = True
                            fnd = True
                        if fnd is True:
                            break
                else:
                    logger.info("why here? resetting searchprov - last run here..")
                    newznab_host = None
                    torznab_host = None
                    if prov_order[prov_count].lower() not in searchprov.keys():
                        searchprov[prov_order[prov_count].lower()] = {
                            "id": comicarr.PROVIDER_START_ID + 1,
                            "type": prov_order[prov_count].lower(),
                            "lastrun": 0,
                            "active": True,
                            "hits": 0,
                        }
                    else:
                        searchprov[prov_order[prov_count].lower()]["active"] = True

                # logger.fdebug('searchprov: %s' % (searchprov,))
                # mark the currently active provider here.
                current_prov = get_current_prov(searchprov)
                logger.info("current_prov: %s" % (current_prov))

                if all(
                    [
                        not provider_blocked,
                        "".join(current_prov.keys()) in checked_once,
                    ]
                ):
                    break

                logger.info("tmp_cmloopit: %s [Issue #:%s]" % (tmp_cmloopit, tmp_IssueNumber))

                scarios = {
                    "tmp_IssueNumber": tmp_IssueNumber,
                    "ComicYear": ComicYear,
                    "SeriesYear": SeriesYear,
                    "Publisher": Publisher,
                    "IssueDate": IssueDate,
                    "StoreDate": StoreDate,
                    "current_prov": current_prov,
                    "send_prov_count": send_prov_count,
                    "IssDateFix": IssDateFix,
                    "IssueID": IssueID,
                    "UseFuzzy": UseFuzzy,
                    "newznab_host": newznab_host,
                    "ComicVersion": ComicVersion,
                    "SARC": SARC,
                    "IssueArcID": IssueArcID,
                    "ComicID": ComicID,
                    "issuetitle": issuetitle,
                    "oneoff": oneoff,
                    "cmloopit": tmp_cmloopit,
                    "manual": manual,
                    "torznab_host": torznab_host,
                    "digitaldate": digitaldate,
                    "booktype": booktype,
                    "chktpb": chktpb,
                    "ignore_booktype": ignore_booktype,
                    "smode": smode,
                    "allow_packs": allow_packs,
                    "findit": findit,
                }

                if searchmode == "rss":
                    logger.info("RSS searchmode enabled for %s" % ComicName)
                    scarios["RSS"] = "yes"
                    for xx in gen_altnames(ComicName, AlternateSearch, filesafe, smode):
                        logger.info("comicname searched for: %s" % ComicName)
                        if all([findit["status"] is False, not provider_blocked]):
                            scarios["ComicName"] = xx["ComicName"]
                            scarios["unaltered_ComicName"] = xx["unaltered_ComicName"]
                            findit = search_the_matrix(scarios)
                            if findit["status"] is True:
                                logger.fdebug("findit = found!")
                                break

                else:
                    logger.info("API searchmode enabled for %s" % ComicName)
                    scarios["RSS"] = "no"
                    if unfiltered_pass_active():
                        # One query per indexer: alternate-name variants would
                        # each add another query against the same provider, and
                        # the query must be the bare series title even when an
                        # alternate name carries `!!` priority.
                        altnames = [
                            {
                                "ComicName": ComicName,
                                "unaltered_ComicName": ComicName,
                            }
                        ]
                    else:
                        altnames = gen_altnames(ComicName, AlternateSearch, filesafe, smode)
                    for xx in altnames:
                        logger.info("comicname searched for: %s" % ComicName)
                        if all([findit["status"] is False, not provider_blocked]):
                            scarios["ComicName"] = xx["ComicName"]
                            scarios["unaltered_ComicName"] = xx["unaltered_ComicName"]
                            findit = search_the_matrix(scarios)
                            logger.info("findit: %s" % (findit,))
                            if findit["status"] is True:
             