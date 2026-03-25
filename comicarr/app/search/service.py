#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Search domain service — provider search, RSS monitoring.

Module-level functions wrapping existing search.py (~4300 lines) and
rsscheck.py. Preserves ThreadPoolExecutor for parallel provider queries.
"""

import datetime
import re
import time
from operator import itemgetter
from pathlib import Path
from urllib.parse import urljoin

import requests

import comicarr
from comicarr import db, logger
from comicarr.tables import issues, ref32p


def find_comic(
    ctx, name, issue=None, type_="comic", mode="series", limit=None, offset=None, sort=None, content_type=None
):
    """Search for comics across configured providers.

    Delegates to MangaDex for manga, or mb.findComic for comics/story arcs.
    Returns results with in_library boolean added.
    """
    from comicarr import mb

    if not name:
        return {"error": "Missing a Comic name"}

    try:
        parsed_limit = int(limit) if limit else None
        parsed_offset = int(offset) if offset else None
    except (ValueError, TypeError):
        return {"error": "Invalid pagination parameters"}

    # Route to appropriate provider
    if content_type == "manga":
        if not ctx.config or not getattr(ctx.config, "MANGADEX_ENABLED", False):
            return {"error": "MangaDex integration is not enabled"}
        from comicarr import mangadex

        searchresults = mangadex.search_manga(name, limit=parsed_limit, offset=parsed_offset, sort=sort)
    elif type_ == "story_arc":
        searchresults = mb.findComic(
            name,
            mode,
            issue=None,
            search_type="story_arc",
            limit=parsed_limit,
            offset=parsed_offset,
            sort=sort,
        )
    else:
        searchresults = mb.findComic(
            name,
            mode,
            issue=issue,
            limit=parsed_limit,
            offset=parsed_offset,
            sort=sort,
            content_type=content_type,
        )

    # Add in_library flag
    def add_in_library(comic):
        comic["in_library"] = comic.get("haveit") != "No"
        return comic

    if isinstance(searchresults, dict) and "results" in searchresults:
        searchresults["results"] = [add_in_library(c) for c in searchresults["results"]]
        return searchresults
    else:
        searchresults = sorted(searchresults, key=itemgetter("comicyear", "issues"), reverse=True)
        searchresults = [add_in_library(c) for c in searchresults]
        return {"results": searchresults}


def find_manga(ctx, name, limit=None, offset=None, sort=None):
    """Search for manga via MangaDex API."""
    if not ctx.config or not getattr(ctx.config, "MANGADEX_ENABLED", False):
        return {"error": "MangaDex integration is not enabled"}

    from comicarr import mangadex

    try:
        parsed_limit = int(limit) if limit else None
        parsed_offset = int(offset) if offset else None
    except (ValueError, TypeError):
        return {"error": "Invalid pagination parameters"}

    searchresults = mangadex.search_manga(name, limit=parsed_limit, offset=parsed_offset, sort=sort)

    def add_in_library(manga):
        manga["in_library"] = manga.get("haveit") != "No"
        return manga

    if isinstance(searchresults, dict) and "results" in searchresults:
        searchresults["results"] = [add_in_library(m) for m in searchresults["results"]]
        return searchresults
    return {"error": "Search returned no results"}


def add_comic(ctx, comic_id):
    """Add a comic to the watchlist via importer."""
    from comicarr import importer

    try:
        watch = [{"comicid": comic_id, "comicname": None}]
        importer.importer_thread(watch)
    except Exception as e:
        logger.error("[SEARCH] Error adding comic %s: %s" % (comic_id, e))
        return {"success": False, "error": str(e)}
    return {"success": True, "message": "Successfully queued adding id: %s" % comic_id}


def add_manga(ctx, manga_id):
    """Add a manga by MangaDex ID."""
    if not str(manga_id).startswith("md-"):
        manga_id = "md-" + manga_id

    if not ctx.config or not getattr(ctx.config, "MANGADEX_ENABLED", False):
        return {"success": False, "error": "MangaDex integration is not enabled"}

    try:
        from comicarr import importer

        result = importer.addMangaToDB(manga_id)

        if result and result.get("status") == "complete":
            return {
                "success": True,
                "message": "Successfully added manga: %s" % result.get("comicname", manga_id),
                "comicid": manga_id,
                "content_type": "manga",
            }
        return {"success": False, "error": "Failed to add manga: %s" % manga_id}
    except Exception as e:
        logger.error("[SEARCH] Error adding manga %s: %s" % (manga_id, e))
        return {"success": False, "error": "Error adding manga: %s" % str(e)}


def force_search(ctx):
    """Trigger a full search for all wanted issues."""
    from comicarr import search

    search.searchforissue()
    return {"success": True, "message": "Search initiated"}


def force_rss(ctx):
    """Trigger an RSS feed check."""
    import threading

    try:
        rss = comicarr.rsscheckit.tehMain()
        threading.Thread(target=rss.run, args=(True,)).start()
        return {"success": True, "message": "RSS check initiated"}
    except Exception as e:
        logger.error("[SEARCH] Error starting RSS check: %s" % e)
        return {"success": False, "error": "Failed to start RSS check: %s" % str(e)}


def get_provider_stats(ctx):
    """Get provider search statistics."""
    from comicarr.app.search import queries as search_queries

    return search_queries.get_provider_stats()


# --- Extracted from helpers.py ---


def LoadAlternateSearchNames(seriesname_alt, comicid):
    # seriesname_alt = db.comics['AlternateSearch']
    AS_Alt = []
    Alternate_Names = {}
    alt_count = 0

    if seriesname_alt is None or seriesname_alt == "None":
        return "no results"
    else:
        chkthealt = seriesname_alt.split("##")
        if chkthealt == 0:
            AS_Alt.append(seriesname_alt)
        for calt in chkthealt:
            AS_Alter = re.sub("##", "", calt)
            u_altsearchcomic = AS_Alter
            AS_formatrem_seriesname = re.sub(r"\s+", " ", u_altsearchcomic)
            if AS_formatrem_seriesname[:1] == " ":
                AS_formatrem_seriesname = AS_formatrem_seriesname[1:]

            AS_Alt.append({"AlternateName": AS_formatrem_seriesname})
            alt_count += 1

        Alternate_Names["AlternateName"] = AS_Alt
        Alternate_Names["ComicID"] = comicid
        Alternate_Names["Count"] = alt_count
        logger.info("AlternateNames returned:" + str(Alternate_Names))

        return Alternate_Names


def torrent_create(site, linkid, alt=None):
    if any([site == "32P", site == "TOR"]):
        pass
    elif site == "DEM":
        url = comicarr.DEMURL + "files/download/" + str(linkid) + "/"
    elif site == "WWT":
        url = comicarr.WWTURL + "download.php"

    return url


def parse_32pfeed(rssfeedline):
    KEYS_32P = {}
    if comicarr.CONFIG.ENABLE_32P and len(rssfeedline) > 1:
        userid_st = rssfeedline.find("&user")
        userid_en = rssfeedline.find("&", userid_st + 1)
        if userid_en == -1:
            USERID_32P = rssfeedline[userid_st + 6 :]
        else:
            USERID_32P = rssfeedline[userid_st + 6 : userid_en]

        auth_st = rssfeedline.find("&auth")
        auth_en = rssfeedline.find("&", auth_st + 1)
        if auth_en == -1:
            AUTH_32P = rssfeedline[auth_st + 6 :]
        else:
            AUTH_32P = rssfeedline[auth_st + 6 : auth_en]

        authkey_st = rssfeedline.find("&authkey")
        authkey_en = rssfeedline.find("&", authkey_st + 1)
        if authkey_en == -1:
            AUTHKEY_32P = rssfeedline[authkey_st + 9 :]
        else:
            AUTHKEY_32P = rssfeedline[authkey_st + 9 : authkey_en]

        KEYS_32P = {
            "user": USERID_32P,
            "auth": AUTH_32P,
            "authkey": AUTHKEY_32P,
            "passkey": comicarr.CONFIG.PASSKEY_32P,
        }

    return KEYS_32P


def checkthe_id(comicid=None, up_vals=None):
    from sqlalchemy import select

    from comicarr.helpers import now

    if not up_vals:
        chk = db.select_one(select(ref32p).where(ref32p.c.ComicID == comicid))
        if chk is None:
            return None
        else:
            if chk["Updated"] is None:
                logger.fdebug(
                    "Reference found for 32p - but the id has never been verified after populating. Verifying it is still the right id before proceeding."
                )
                return None
            else:
                c_obj_date = datetime.datetime.strptime(chk["Updated"], "%Y-%m-%d %H:%M:%S")
                n_date = datetime.datetime.now()
                absdiff = abs(n_date - c_obj_date)
                hours = (absdiff.days * 24 * 60 * 60 + absdiff.seconds) / 3600.0
                if hours >= 24:
                    logger.fdebug(
                        "Reference found for 32p - but older than 24hours since last checked. Verifying it is still the right id before proceeding."
                    )
                    return None
                else:
                    return {"id": chk["ID"], "series": chk["Series"]}

    else:
        ctrlVal = {"ComicID": comicid}
        newVal = {"Series": up_vals[0]["series"], "ID": up_vals[0]["id"], "Updated": now()}
        db.upsert("ref32p", newVal, ctrlVal)


def torrentinfo(issueid=None, torrent_hash=None, download=False, monitor=False):
    import os
    import shlex
    import shutil
    import subprocess
    import sys
    from base64 import b16encode, b32decode

    from sqlalchemy import select

    from comicarr.tables import snatched

    if issueid:
        stmt = (
            select(
                issues.c.Issue_Number,
                issues.c.ComicName,
                issues.c.Status,
                snatched.c.Hash,
            )
            .select_from(issues.join(snatched, issues.c.IssueID == snatched.c.IssueID))
            .where(issues.c.IssueID == issueid)
        )
        cinfo = db.select_one(stmt)
        if cinfo is None:
            logger.warn("Unable to locate IssueID of : " + issueid)
            snatch_status = "MONITOR ERROR"

        if cinfo["Status"] != "Snatched" or cinfo["Hash"] is None:
            logger.warn(
                cinfo["ComicName"] + " #" + cinfo["Issue_Number"] + " is currently in a " + cinfo["Status"] + " Status."
            )
            snatch_status = "MONITOR ERROR"

        torrent_hash = cinfo["Hash"]

    logger.fdebug("Working on torrent: " + torrent_hash)
    if len(torrent_hash) == 32:
        torrent_hash = b16encode(b32decode(torrent_hash))

    if not len(torrent_hash) == 40:
        logger.error("Torrent hash is missing, or an invalid hash value has been passed")
        snatch_status = "MONITOR ERROR"
    else:
        if comicarr.USE_RTORRENT:
            from . import rtorrent_test_client

            rp = rtorrent_test_client.RTorrent()
            torrent_info = rp.main(torrent_hash, check=True)
        elif comicarr.USE_DELUGE:
            from comicarr.torrent.clients import deluge as delu

            dp = delu.TorrentClient()
            if not dp.connect(
                comicarr.CONFIG.DELUGE_HOST, comicarr.CONFIG.DELUGE_USERNAME, comicarr.CONFIG.DELUGE_PASSWORD
            ):
                logger.warn("Not connected to Deluge!")

            torrent_info = dp.get_torrent(torrent_hash)
        else:
            snatch_status = "MONITOR ERROR"
            return

    logger.info("torrent_info: %s" % torrent_info)

    if torrent_info is False or len(torrent_info) == 0:
        logger.warn("torrent returned no information. Check logs - aborting auto-snatch at this time.")
        snatch_status = "MONITOR ERROR"
    else:
        if comicarr.USE_DELUGE:
            torrent_status = torrent_info["is_finished"]
            torrent_files = torrent_info["num_files"]
            torrent_folder = torrent_info["save_path"]
            torrent_info["total_filesize"] = torrent_info["total_size"]
            torrent_info["upload_total"] = torrent_info["total_uploaded"]
            torrent_info["download_total"] = torrent_info["total_payload_download"]
            torrent_info["time_started"] = torrent_info["time_added"]

        elif comicarr.USE_RTORRENT:
            torrent_status = torrent_info["completed"]
            torrent_files = len(torrent_info["files"])
            torrent_folder = torrent_info["folder"]

        if all([torrent_status is True, download is True]):
            if not issueid:
                torrent_info["snatch_status"] = "MONITOR STARTING"

            logger.info("Torrent is completed and status is currently Snatched. Attempting to auto-retrieve.")
            with open(comicarr.CONFIG.AUTO_SNATCH_SCRIPT, "r") as f:
                first_line = f.readline()

            if comicarr.CONFIG.AUTO_SNATCH_SCRIPT.endswith(".sh"):
                shell_cmd = re.sub("#!", "", first_line)
                if shell_cmd == "" or shell_cmd is None:
                    shell_cmd = "/bin/bash"
            else:
                shell_cmd = sys.executable

            curScriptName = shell_cmd + " " + str(comicarr.CONFIG.AUTO_SNATCH_SCRIPT)
            if torrent_files > 1:
                downlocation = torrent_folder
            else:
                if comicarr.USE_DELUGE:
                    downlocation = os.path.join(torrent_folder, torrent_info["files"][0]["path"])
                else:
                    downlocation = torrent_info["files"][0]

            autosnatch_env = os.environ.copy()
            autosnatch_env["downlocation"] = downlocation.replace("'", "\\'")

            autosnatch_env["host"] = comicarr.CONFIG.PP_SSHHOST
            autosnatch_env["port"] = comicarr.CONFIG.PP_SSHPORT
            autosnatch_env["user"] = comicarr.CONFIG.PP_SSHUSER
            autosnatch_env["localcd"] = comicarr.CONFIG.PP_SSHLOCALCD
            if comicarr.CONFIG.PP_SSHKEYFILE is not None:
                autosnatch_env["keyfile"] = comicarr.CONFIG.PP_SSHKEYFILE
            else:
                autosnatch_env["keyfile"] = ""
            if comicarr.CONFIG.PP_SSHPASSWD is not None:
                autosnatch_env["passwd"] = comicarr.CONFIG.PP_SSHPASSWD
            else:
                autosnatch_env["passwd"] = ""

            script_cmd = shlex.split(curScriptName, posix=False)
            logger.fdebug("Executing command %s" % script_cmd)
            try:
                p = subprocess.Popen(
                    script_cmd,
                    env=dict(autosnatch_env),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=comicarr.PROG_DIR,
                )
                out, err = p.communicate()
                logger.fdebug("Script result: %s" % out)
            except OSError as e:
                logger.warn("Unable to run extra_script: %s" % e)
                snatch_status = "MONITOR ERROR"
            else:
                if "Access failed: No such file" in str(out):
                    logger.fdebug(
                        "Not located in location it is supposed to be in - probably has been moved by some script and I got the wrong location due to timing. Trying again..."
                    )
                    snatch_status = "IN PROGRESS"
                else:
                    snatch_status = "MONITOR COMPLETE"
                torrent_info["completed"] = torrent_status
                torrent_info["files"] = torrent_files
                torrent_info["folder"] = torrent_folder
                torrent_info["copied_filepath"] = os.path.join(comicarr.CONFIG.PP_SSHLOCALCD, torrent_info["name"])
                torrent_info["snatch_status"] = snatch_status
        else:
            if download is True:
                snatch_status = "IN PROGRESS"
            elif monitor is True:
                if comicarr.USE_DELUGE:
                    pauseit = dp.stop_torrent(torrent_hash)
                    if pauseit is False:
                        logger.warn("Unable to pause torrent - cannot run post-process on item at this time.")
                        snatch_status = "MONITOR FAIL"
                    else:
                        try:
                            new_filepath = os.path.join(torrent_path, ".copy")
                            logger.fdebug("New_Filepath: %s" % new_filepath)
                            shutil.copy(torrent_path, new_filepath)
                            torrent_info["copied_filepath"] = new_filepath
                        except:
                            logger.warn("Unexpected Error: %s" % sys.exc_info()[0])
                            logger.warn(
                                "Unable to create temporary directory to perform meta-tagging. Processing cannot continue with given item at this time."
                            )
                            torrent_info["copied_filepath"] = torrent_path
                        else:
                            dp.start_torrent(torrent_hash)
            else:
                snatch_status = "NOT SNATCHED"

    return torrent_info


def block_provider_check(site, simple=True, force=False):
    timenow = int(time.time())
    for prov in comicarr.PROVIDER_BLOCKLIST:
        if prov["site"] == site:
            if force is True:
                comicarr.PROVIDER_BLOCKLIST.remove(prov)
                if simple is True:
                    return False
                else:
                    return {"blocked": False, "remain": (int(prov["resume"]) - timenow) / 60}
            else:
                if timenow < int(prov["resume"]):
                    if simple is True:
                        return True
                    else:
                        return {"blocked": True, "remain": (int(prov["resume"]) - timenow) / 60}
                else:
                    comicarr.PROVIDER_BLOCKLIST.remove(prov)
    if simple is True:
        return False
    else:
        return {"blocked": False, "remain": 0}


def disable_provider(site, reason=None, delay=0):
    if not delay:
        if comicarr.CONFIG.BLOCKLIST_TIMER > 0:
            delay = int(comicarr.CONFIG.BLOCKLIST_TIMER)
        else:
            delay = 3600
    mins = int(delay / 60) + (delay % 60 > 0)
    logger.info("Temporarily blocking provider %s for %s minutes..." % (site, mins))
    for entry in comicarr.PROVIDER_BLOCKLIST:
        if entry["site"] == site:
            comicarr.PROVIDER_BLOCKLIST.remove(entry)
    newentry = {"site": site, "resume": int(time.time()) + delay, "reason": reason}
    comicarr.PROVIDER_BLOCKLIST.append(newentry)
    logger.info("provider_blocklist: %s" % comicarr.PROVIDER_BLOCKLIST)


def newznab_test(name, host, ssl, apikey):
    from xml.dom.minidom import parseString

    params = {"t": "search", "apikey": apikey, "o": "xml"}

    if not host.endswith("api"):
        if not host.endswith("/"):
            host += "/"
        host = urljoin(host, "api")
        logger.fdebug("[TEST-NEWZNAB] Appending `api` to end of host: %s" % host)
    headers = {"User-Agent": str(comicarr.USER_AGENT)}
    logger.info("host: %s" % host)
    try:
        r = requests.get(host, params=params, headers=headers, verify=bool(ssl))
    except Exception as e:
        logger.warn("Unable to connect: %s" % e)
        return
    else:
        try:
            data = parseString(r.content)
        except Exception as e:
            logger.warn("[WARNING] Error attempting to test: %s" % e)

        try:
            error_code = data.getElementsByTagName("error")[0].attributes["code"].value
        except Exception:
            logger.info("Connected - Status code returned: %s" % r.status_code)
            if r.status_code == 200:
                return True
            else:
                logger.warn("Received response - Status code returned: %s" % r.status_code)
                return False

        code = error_code
        description = data.getElementsByTagName("error")[0].attributes["description"].value
        logger.info("[ERROR:%s] - %s" % (code, description))
        return False


def torznab_test(name, host, ssl, apikey):
    from xml.dom.minidom import parseString

    params = {"t": "search", "apikey": apikey, "o": "xml"}

    if host[-1:] == "/":
        host = host[:-1]
    headers = {"User-Agent": str(comicarr.USER_AGENT)}
    logger.info("host: %s" % host)
    try:
        r = requests.get(host, params=params, headers=headers, verify=bool(ssl))
    except Exception as e:
        logger.warn("Unable to connect: %s" % e)
        return
    else:
        try:
            data = parseString(r.content)
        except Exception as e:
            logger.warn("[WARNING] Error attempting to test: %s" % e)

        try:
            error_code = data.getElementsByTagName("error")[0].attributes["code"].value
        except Exception:
            logger.info("Connected - Status code returned: %s" % r.status_code)
            if r.status_code == 200:
                return True
            else:
                logger.warn("Received response - Status code returned: %s" % r.status_code)
                return False

        code = error_code
        description = data.getElementsByTagName("error")[0].attributes["description"].value
        logger.info("[ERROR:%s] - %s" % (code, description))
        return False


def ignored_publisher_check(publisher):
    if publisher is not None:
        if comicarr.CONFIG.IGNORED_PUBLISHERS is not None and any(
            x
            for x in comicarr.CONFIG.IGNORED_PUBLISHERS
            if any(
                [
                    x.lower() == publisher.lower(),
                    ("*" in x and re.sub(r"\*", "", x.lower()).strip() in publisher.lower()),
                ]
            )
        ):
            logger.fdebug("Ignored publisher [%s]. Ignoring this result." % publisher)
            return True
    return False


def search_queue(queue):
    import queue as queue_module

    while True:
        try:
            item = queue.get(timeout=5)
        except queue_module.Empty:
            continue

        if item == "exit":
            logger.info("[SEARCH-QUEUE] Cleaning up workers for shutdown")
            break

        if comicarr.SEARCHLOCK.locked():
            queue.put(item)  # re-enqueue
            time.sleep(1)
            continue

            gumbo_line = True
            if item["issueid"] in comicarr.PACK_ISSUEIDS_DONT_QUEUE:
                if comicarr.PACK_ISSUEIDS_DONT_QUEUE[item["issueid"]] in comicarr.DDL_QUEUED:
                    logger.fdebug(
                        "[SEARCH-QUEUE-PACK-DETECTION] %s already queued to download via pack...Ignoring"
                        % item["issueid"]
                    )
                    gumbo_line = False

            if gumbo_line:
                logger.fdebug("[SEARCH-QUEUE] Now loading item from search queue: %s" % item)
                if not comicarr.SEARCHLOCK.locked():
                    arcid = None
                    comicid = item["comicid"]
                    issueid = item["issueid"]
                    if issueid is not None:
                        if "_" in issueid:
                            arcid = issueid
                            comicid = None  # required for storyarcs to work
                            issueid = None  # required for storyarcs to work
                    mofo = comicarr.filers.FileHandlers(ComicID=comicid, IssueID=issueid, arcID=arcid)
                    local_check = mofo.walk_the_walk()

                    if local_check["status"]:
                        from comicarr.helpers import check_file_condition

                        fullpath = Path(local_check["filepath"]) / local_check["filename"]
                        filecondition = check_file_condition(fullpath)
                        if not filecondition["status"]:
                            logger.warn(
                                f"CRC Check: File {fullpath} failed condition check ({filecondition['quality']}).  Ignoring."
                            )
                            local_check["status"] = False

                    if local_check["status"] is True:
                        comicarr.PP_QUEUE.put(
                            {
                                "nzb_name": local_check["filename"],
                                "nzb_folder": local_check["filepath"],
                                "failed": False,
                                "issueid": item["issueid"],
                                "comicid": item["comicid"],
                                "apicall": True,
                                "ddl": False,
                                "download_info": None,
                            }
                        )
                    else:
                        try:
                            manual = item["manual"]
                        except Exception:
                            manual = False
                        comicarr.search.searchforissue(item["issueid"], manual=manual)
                    time.sleep(5)

            if comicarr.SEARCHLOCK.locked():
                logger.fdebug("[SEARCH-QUEUE] Another item is currently being searched....")
                time.sleep(15)
