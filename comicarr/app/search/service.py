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
import errno
import re
import time
import uuid
from operator import itemgetter
from pathlib import Path
from urllib.parse import urljoin

import requests

import comicarr
from comicarr import db, logger
from comicarr.app.acquisition.models import DispatchState, ItemOutcome, RunState
from comicarr.app.core.workers import start_background_thread
from comicarr.app.search.commands import SearchCommand, SearchCommandError
from comicarr.app.search.routes import classify, route_health
from comicarr.tables import issues, ref32p
from comicarr.torrent import monitor as torrent_monitor


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

    def add_in_library(comic):
        comic["in_library"] = comic.get("haveit") != "No"
        return comic

    if isinstance(searchresults, dict) and "results" in searchresults:
        searchresults["results"] = [add_in_library(c) for c in searchresults["results"]]
        return searchresults
    elif searchresults:
        searchresults = sorted(searchresults, key=itemgetter("comicyear", "issues"), reverse=True)
        searchresults = [add_in_library(c) for c in searchresults]
        return {"results": searchresults}
    else:
        return {"error": "Search returned no results"}


def find_manga(ctx, name, limit=None, offset=None, sort=None):
    """Search for manga via MAL (primary) or MangaDex (fallback)."""
    mal_ok = getattr(ctx.config, "MAL_ENABLED", False) and getattr(ctx.config, "MAL_CLIENT_ID", None)
    mdex_ok = getattr(ctx.config, "MANGADEX_ENABLED", False)
    if not ctx.config or not (mal_ok or mdex_ok):
        return {"error": "Manga integration is not enabled"}

    try:
        parsed_limit = int(limit) if limit else None
        parsed_offset = int(offset) if offset else None
    except (ValueError, TypeError):
        return {"error": "Invalid pagination parameters"}

    def add_in_library(manga):
        manga["in_library"] = manga.get("haveit") != "No"
        return manga

    mal_enabled = getattr(ctx.config, "MAL_ENABLED", False)
    mal_client_id = getattr(ctx.config, "MAL_CLIENT_ID", None)

    if mal_enabled and mal_client_id:
        from comicarr import myanimelist

        try:
            searchresults = myanimelist.search_manga(name, limit=parsed_limit, offset=parsed_offset, sort=sort)
            if isinstance(searchresults, dict) and "results" in searchresults:
                searchresults["results"] = [add_in_library(m) for m in searchresults["results"]]
                return searchresults
        except Exception as e:
            logger.error("[SEARCH] MAL search failed, falling back to MangaDex: %s" % e)

    from comicarr import mangadex

    searchresults = mangadex.search_manga(name, limit=parsed_limit, offset=parsed_offset, sort=sort)

    if isinstance(searchresults, dict) and "results" in searchresults:
        searchresults["results"] = [add_in_library(m) for m in searchresults["results"]]
        return searchresults
    return {"error": "Search returned no results"}


def add_comic(ctx, comic_id):
    """Add a comic to the watchlist via importer."""
    from comicarr import importer, metron

    try:
        if metron.is_metron_id(comic_id):
            cv_comicid = metron.get_cv_id(comic_id)
            if not cv_comicid:
                return {
                    "success": False,
                    "error": "Metron series %s has no ComicVine mapping - cannot add. "
                    "Try disabling Metron search and re-searching via ComicVine."
                    % metron.strip_metron_prefix(comic_id),
                }
            comic_id = cv_comicid
        watch = [{"comicid": comic_id, "comicname": None, "seriesyear": None}]
        importer.importer_thread(watch)
    except Exception as e:
        logger.error("[SEARCH] Error adding comic %s: %s" % (comic_id, e))
        return {"success": False, "error": str(e)}
    return {
        "success": True,
        "message": "Successfully queued adding id: %s" % comic_id,
        "comicid": comic_id,
    }


def add_manga(ctx, manga_id):
    """Queue a manga add on the mass-add thread (same contract as add_comic)."""
    mal_ok = getattr(ctx.config, "MAL_ENABLED", False) and getattr(ctx.config, "MAL_CLIENT_ID", None)
    mdex_ok = getattr(ctx.config, "MANGADEX_ENABLED", False)
    if not ctx.config or not (mal_ok or mdex_ok):
        return {"success": False, "error": "Manga integration is not enabled"}

    from comicarr import importer, series_kind

    try:
        if series_kind.provider_of(manga_id) is series_kind.SeriesProvider.MYANIMELIST:
            comic_id = series_kind.add_prefix(manga_id, series_kind.SeriesProvider.MYANIMELIST)
        else:
            comic_id = series_kind.add_prefix(manga_id, series_kind.SeriesProvider.MANGADEX)
        importer.importer_thread([{"comicid": comic_id, "comicname": None, "seriesyear": None}])
    except Exception as e:
        logger.error("[SEARCH] Error queueing manga %s: %s" % (manga_id, e))
        return {"success": False, "error": "Error adding manga: %s" % str(e)}
    return {
        "success": True,
        "message": "Successfully queued adding id: %s" % comic_id,
        "comicid": comic_id,
        "content_type": "manga",
    }


def search_issue(ctx, issue_id, *, trigger="issue_retry"):
    """Scoped single-issue search with the same route precheck as force_search.

    Used by needs-attention band retry / search-again (#483). Does not rewrite
    journal stage; callers stamp R9 resolution separately.
    """
    from comicarr.app.search.commands import enqueue_search_command

    if issue_id in (None, "") or not str(issue_id).strip():
        return {
            "success": False,
            "status": "failed",
            "error": "Missing issue_id",
            "message": "Missing issue_id",
        }

    precheck = route_health(ctx)
    if not precheck.get("success"):
        return {
            "success": False,
            "status": "blocked",
            "error": precheck.get("error"),
            "message": precheck.get("message"),
        }

    command = enqueue_search_command(
        {"issueid": str(issue_id).strip()},
        trigger=trigger,
        scope_type="issue",
        scope_id=str(issue_id).strip(),
    )
    return {
        "success": True,
        "status": "accepted",
        "run_id": command.run_id,
        "issue_id": str(issue_id).strip(),
        "message": "Search queued for issue %s" % issue_id,
    }


def force_search(ctx):
    """Trigger a full search for all wanted issues with a durable outcome."""
    from comicarr import search
    from comicarr.app.acquisition.runs import RunLedger

    precheck = route_health(ctx)
    if not precheck.get("success"):
        return {
            "success": False,
            "status": "blocked",
            "error": precheck.get("error"),
            "message": precheck.get("message"),
        }

    run_id = str(uuid.uuid4())
    ledger = RunLedger()
    ledger.create_run(
        run_id,
        command_kind="search",
        trigger="manual_wanted_scan",
        scope_type="wanted_backlog",
        scope_id="all",
    )
    try:
        queue_result = search.searchforissue(
            acquisition_run_id=run_id,
            acquisition_trigger="manual_wanted_scan",
        )
    except Exception as e:
        logger.error("[SEARCH] Force search failed: %s" % e)
        ledger.complete_empty_run(
            run_id,
            completion_state=RunState.FAILED,
            dispatch_state=DispatchState.ERROR,
        )
        return {
            "success": False,
            "status": "failed",
            "run_id": run_id,
            "error": "Search failed to start",
            "message": "Search failed to start",
        }

    queue_result = queue_result if isinstance(queue_result, dict) else {}
    if str(queue_result.get("status") or "").strip().upper() == "IN PROGRESS":
        ledger.complete_empty_run(
            run_id,
            completion_state=RunState.BLOCKED,
            dispatch_state=DispatchState.ERROR,
        )
        return {
            "success": False,
            "status": "blocked",
            "run_id": run_id,
            "error": "search_already_in_progress",
            "message": "Search is already running; no new Wanted items were queued",
        }

    try:
        accepted = max(0, int(queue_result.get("queued_count") or 0))
    except (TypeError, ValueError):
        accepted = 0
    try:
        handoff_errors = max(0, int(queue_result.get("error_count") or 0))
    except (TypeError, ValueError):
        handoff_errors = 0
    if accepted == 0:
        if handoff_errors:
            ledger.complete_empty_run(
                run_id,
                completion_state=RunState.FAILED,
                dispatch_state=DispatchState.ERROR,
            )
            return {
                "success": False,
                "status": "failed",
                "run_id": run_id,
                "accepted": 0,
                "error": "Wanted issues could not be queued",
                "message": "Search could not queue eligible Wanted issues",
            }
        ledger.complete_empty_run(run_id)
        return {
            "success": True,
            "status": "no_match",
            "run_id": run_id,
            "accepted": 0,
            "message": "No eligible Wanted issues were queued",
        }

    ledger.record_dispatch(run_id, DispatchState.ERROR if handoff_errors else DispatchState.ACCEPTED)
    run = ledger.get_run(run_id) or {}
    if handoff_errors:
        return {
            "success": True,
            "status": "partial",
            "run_id": run_id,
            "accepted": int(run.get("accepted_count") or accepted),
            "error": "Some Wanted issues could not be queued",
            "message": "Search queued %s Wanted issue%s; %s could not be queued"
            % (accepted, "" if accepted == 1 else "s", handoff_errors),
        }
    return {
        "success": True,
        "status": "accepted",
        "run_id": run_id,
        "accepted": int(run.get("accepted_count") or accepted),
        "message": "Search queued for %s Wanted issue%s" % (accepted, "" if accepted == 1 else "s"),
    }


def force_rss(ctx):
    """Trigger an RSS feed check."""
    try:
        rss = comicarr.rsscheckit.tehMain()
        start_background_thread(
            rss.run,
            args=(True,),
            name="ManualRSS",
            registry=ctx.background_workers,
        )
        return {"success": True, "message": "RSS check initiated"}
    except Exception as e:
        logger.error("[SEARCH] Error starting RSS check: %s" % e)
        return {"success": False, "error": "Failed to start RSS check: %s" % str(e)}


def get_provider_stats(ctx):
    """Preserve the provider-list response shape while sanitizing its fields."""
    return get_health(ctx)["providers"]


def get_health(ctx):
    """Get provider, route, run, worker, and maintenance health."""
    from comicarr.app.search.health import get_search_health

    return get_search_health(
        ctx.config,
        provider_blocklist=getattr(ctx, "provider_blocklist", None) or comicarr.PROVIDER_BLOCKLIST,
    )


def _attempt_status(state):
    if state == ItemOutcome.ACCEPTED.value:
        return "queued"
    if state == ItemOutcome.RUNNING.value:
        return "searching"
    return state


def get_run(ctx, run_id, include_items=True):
    """Return a durable search run without exposing provider request data."""
    from comicarr.app.acquisition.runs import RunLedger
    from comicarr.app.search.commands import queue_priority_for_trigger

    ledger = RunLedger()
    run = ledger.get_run(run_id)
    if run is None or run["command_kind"] != "search":
        return {"success": False, "error": "search run not found", "status_code": 404}
    items = ledger.list_items(run_id) if include_items else []
    active_priorities = {
        item.get("queue_priority", queue_priority_for_trigger(run["trigger"]))
        for item in items
        if item["state"] in {"accepted", "running"}
    }
    queue_priority = "recovery" if "recovery" in active_priorities else queue_priority_for_trigger(run["trigger"])
    return {
        "success": True,
        "run": {
            key: run[key]
            for key in (
                "run_id",
                "command_kind",
                "trigger",
                "scope_type",
                "scope_id",
                "dispatch_state",
                "completion_state",
                "accepted_count",
                "terminal_count",
                "succeeded_count",
                "no_match_count",
                "blocked_count",
                "failed_count",
                "created_at",
                "updated_at",
                "completed_at",
            )
        }
        | {"queue_priority": queue_priority},
        "items": (
            [
                {
                    "entity_type": item["entity_type"],
                    "entity_id": item["entity_id"],
                    "state": item["state"],
                    "attempt_count": item["attempt_count"],
                    "reason": item["reason"],
                    "updated_at": item["updated_at"],
                    "completed_at": item["completed_at"],
                    "queue_priority": item.get("queue_priority", queue_priority),
                    "attempt_status": _attempt_status(item["state"]),
                }
                for item in items
            ]
            if include_items
            else []
        ),
    }


def retry_run(ctx, run_id):
    """Redrive only search items whose durable queue handoff is still pending."""
    from comicarr.app.acquisition.runs import RunLedger
    from comicarr.app.search.commands import dispatch_pending_search_commands

    ledger = RunLedger()
    run = ledger.get_run(run_id)
    if run is None or run["command_kind"] != "search":
        return {"success": False, "error": "search run not found", "status_code": 404}
    if run["completion_state"] in {"completed", "partial", "blocked", "failed"}:
        return {
            "success": False,
            "error": "terminal search runs cannot be retried",
            "status_code": 409,
        }
    try:
        result = dispatch_pending_search_commands(run_id, ledger=ledger)
    except Exception as e:
        logger.error("[SEARCH] Search run retry failed: %s", e)
        return {"success": False, "error": "search queue handoff retry failed", "status_code": 503}
    refreshed = ledger.get_run(run_id) or run
    if result["errors"]:
        status = "partial" if result["dispatched"] else "failed"
        message = "Some search items still need queue handoff retry"
    elif result["dispatched"]:
        status = "accepted"
        message = "Search queue handoff retry accepted"
    else:
        status = "accepted"
        message = "No pending search queue handoffs remain"
    return {
        "success": not bool(result["errors"]),
        "status": status,
        "run_id": run_id,
        "dispatched": result["dispatched"],
        "errors": result["errors"],
        "message": message,
        "run": refreshed,
    }


def LoadAlternateSearchNames(seriesname_alt, comicid):
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
            return {"snatch_status": "MONITOR ERROR"}

        if cinfo["Status"] != "Snatched" or cinfo["Hash"] is None:
            logger.warn(
                cinfo["ComicName"] + " #" + cinfo["Issue_Number"] + " is currently in a " + cinfo["Status"] + " Status."
            )
            return {"snatch_status": "MONITOR ERROR"}

        torrent_hash = cinfo["Hash"]

    logger.fdebug("Working on torrent: " + torrent_hash)
    if len(torrent_hash) == 32:
        torrent_hash = b16encode(b32decode(torrent_hash))

    if not len(torrent_hash) == 40:
        logger.error("Torrent hash is missing, or an invalid hash value has been passed")
        return {"snatch_status": "MONITOR ERROR"}

    snapshot = torrent_monitor.probe(torrent_hash)
    logger.info("torrent_info: %s" % snapshot)

    if not snapshot.get("reachable"):
        logger.warn("torrent client unreachable for hash %s: %s" % (torrent_hash, snapshot.get("reason")))
        return {"snatch_status": "MONITOR ERROR", "error": snapshot.get("reason")}

    if not snapshot.get("found"):
        logger.warn("torrent not present in client for hash %s (explicit NOT FOUND)." % torrent_hash)
        return {"snatch_status": "NOT FOUND", "hash": torrent_hash}
    else:
        torrent_info = dict(snapshot)
        torrent_status = bool(snapshot.get("completed"))
        torrent_files = snapshot.get("files") or []
        torrent_folder = snapshot.get("folder")

        def resolve_torrent_path():
            if len(torrent_files) == 1:
                return torrent_files[0]
            return torrent_folder

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
            downlocation = resolve_torrent_path()

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
                torrent_info["snatch_status"] = "MONITOR ERROR"
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
            snatch_status = "IN PROGRESS"
            if monitor is True:
                if snapshot.get("client") in torrent_monitor.PAUSABLE_ROUTES:
                    pauseit = torrent_monitor.pause(torrent_hash)
                    if pauseit is False:
                        logger.warn("Unable to pause torrent - cannot run post-process on item at this time.")
                        snatch_status = "MONITOR FAIL"
                    else:
                        torrent_path = torrent_folder
                        try:
                            torrent_path = resolve_torrent_path()
                            new_filepath = torrent_path + ".copy"
                            logger.fdebug("New_Filepath: %s" % new_filepath)
                            shutil.copy(torrent_path, new_filepath)
                            torrent_info["copied_filepath"] = new_filepath
                        except Exception:
                            logger.warn("Unexpected Error: %s" % sys.exc_info()[0])
                            logger.warn(
                                "Unable to create temporary directory to perform meta-tagging. Processing cannot continue with given item at this time."
                            )
                            torrent_info["copied_filepath"] = torrent_path
                        finally:
                            if torrent_monitor.resume(torrent_hash) is False:
                                logger.warn(
                                    "Unable to resume torrent %s after the local copy - it may still be paused in the client."
                                    % torrent_hash
                                )
                else:
                    logger.fdebug(
                        "%s has no pause API; skipping the local copy and leaving the torrent running."
                        % snapshot.get("client")
                    )
            torrent_info["snatch_status"] = snatch_status

    return torrent_info


def block_provider_check(site, simple=True, force=False):
    timenow = int(time.time())
    for prov in comicarr.PROVIDER_BLOCKLIST:
        if prov["site"] == site:
            if force is True:
                comicarr.PROVIDER_BLOCKLIST.remove(prov)
                try:
                    from comicarr.app.search.health import clear_route_block

                    clear_route_block(classify(site))
                except Exception as e:
                    logger.fdebug("[SEARCH] Unable to clear durable route block: %s" % e)
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


PROVIDER_DOWN_ERRNOS = frozenset(
    {
        errno.ETIMEDOUT,
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.EHOSTDOWN,
        errno.EHOSTUNREACH,
        errno.ENETDOWN,
        errno.ENETUNREACH,
    }
)


def _nested_errno(exc, depth=0):
    """Dig the OS-level errno out of a requests exception.

    requests wraps urllib3 which wraps the original OSError, so the errno is
    never on the exception we catch — it sits a few layers down in `args`,
    `__cause__` or `__context__`.
    """
    if exc is None or depth > 6:
        return None
    code = getattr(exc, "errno", None)
    if isinstance(code, int) and code:
        return code
    for nested in list(getattr(exc, "args", ()) or ()) + [exc.__cause__, exc.__context__]:
        if isinstance(nested, BaseException):
            code = _nested_errno(nested, depth + 1)
            if code is not None:
                return code
    return None


def provider_unreachable(exc):
    """True when a requests exception means the provider is down, not just unhappy.

    A rate-limit (429), an auth failure or any other HTTP error means the
    provider answered — blocklisting it for an hour is the wrong response.
    """
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None):
        return False
    code = _nested_errno(exc)
    if code is not None:
        return code in PROVIDER_DOWN_ERRNOS
    return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


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
    try:
        from comicarr.app.search.health import record_route_outcome

        record_route_outcome(
            classify(site),
            success=False,
            error=reason or "Provider temporarily blocked",
            blocked_until=newentry["resume"],
        )
    except Exception as e:
        logger.fdebug("[SEARCH] Unable to persist provider route failure: %s" % e)
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


def _process_search_command(command):
    """Process one validated command or raise to the queue owner."""
    if command.issueid in comicarr.PACK_ISSUEIDS_DONT_QUEUE:
        if comicarr.PACK_ISSUEIDS_DONT_QUEUE[command.issueid] in comicarr.DDL_QUEUED:
            logger.fdebug(
                "[SEARCH-QUEUE-PACK-DETECTION] %s already queued to download via pack...Ignoring" % command.issueid
            )
            return {"status": "BLOCKED", "reason": "already queued by pack"}

    logger.fdebug("[SEARCH-QUEUE] Now loading item from search queue: %s" % command.to_mapping())
    arcid = None
    comicid = command.comicid
    issueid = command.issueid
    if "_" in issueid:
        arcid = issueid
        comicid = None
        issueid = None

    mofo = comicarr.filers.FileHandlers(
        ComicID=comicid,
        IssueID=issueid,
        arcID=arcid,
        entity_type=command.entity_type,
    )
    local_check = mofo.walk_the_walk()

    if local_check["status"]:
        from comicarr.helpers import check_file_condition

        fullpath = Path(local_check["filepath"]) / local_check["filename"]
        filecondition = check_file_condition(fullpath)
        if not filecondition["status"]:
            logger.warn(f"CRC Check: File {fullpath} failed condition check ({filecondition['quality']}).  Ignoring.")
            local_check["status"] = False

    if local_check["status"] is True:
        comicarr.PP_QUEUE.put(
            {
                "nzb_name": local_check["filename"],
                "nzb_folder": local_check["filepath"],
                "failed": False,
                "issueid": command.issueid,
                "comicid": command.comicid,
                "apicall": True,
                "ddl": False,
                "download_info": None,
            }
        )
        return {"status": True, "source": "local"}
    return comicarr.search.searchforissue(
        command.issueid,
        manual=command.manual,
        entity_type=command.entity_type,
    )


def _search_outcome(result):
    if isinstance(result, dict):
        status = result.get("status")
        if isinstance(status, str) and status.strip().upper() == "IN PROGRESS":
            return None, "search already in progress"
        if isinstance(status, str) and status.strip().upper() == "BLOCKED":
            return ItemOutcome.BLOCKED, str(result.get("reason") or "search blocked")
        if status is True:
            return ItemOutcome.SUCCEEDED, None
        if status is False:
            return ItemOutcome.NO_MATCH, str(result.get("reason") or "provider returned no match")
    return ItemOutcome.FAILED, "search returned no explicit outcome"


def _safe_task_done(queue):
    try:
        queue.task_done()
    except (AttributeError, ValueError):
        pass


def _requeue_search_command(queue, command, ledger, reason):
    requeued = None
    if ledger and command.run_id:
        requeued = ledger.record_requeue(command.run_id, command.entity_type, command.issueid, reason=reason)
    queue.put(command.to_mapping())
    return requeued


def _record_search_worker_health(state, error=None):
    """Keep health telemetry best-effort so diagnostics cannot break queue ownership."""
    try:
        from comicarr.app.search.health import record_worker_heartbeat

        record_worker_heartbeat("search", state=state, error=error)
    except Exception as e:
        logger.fdebug("[SEARCH-QUEUE] Unable to persist worker heartbeat: %s" % e)


def search_queue(queue, ledger=None, maintenance=None):
    import queue as queue_module

    from comicarr.app.acquisition.maintenance import MaintenanceBlocked, MaintenanceController, maintenance_retry_delay

    worker_maintenance = maintenance
    last_heartbeat = 0.0
    _record_search_worker_health("running")

    while True:
        try:
            item = queue.get(timeout=5)
        except queue_module.Empty:
            if time.monotonic() - last_heartbeat >= 30:
                _record_search_worker_health("idle")
                last_heartbeat = time.monotonic()
            continue

        try:
            if item == "exit":
                logger.info("[SEARCH-QUEUE] Cleaning up workers for shutdown")
                _record_search_worker_health("stopped")
                break

            command = SearchCommand.from_mapping(item)
            _record_search_worker_health("running")
            command_ledger = ledger
            if command.run_id:
                from comicarr.app.acquisition.runs import RunLedger

                command_ledger = command_ledger or RunLedger()

            if comicarr.SEARCHLOCK.locked():
                _requeue_search_command(queue, command, command_ledger, "search lock held")
                logger.fdebug("[SEARCH-QUEUE] Search lock held; deliberately requeued %s" % command.issueid)
                time.sleep(1)
                continue

            if command_ledger and command.run_id:
                item_state = command_ledger.get_item(command.run_id, command.entity_type, command.issueid)
                if item_state is None:
                    raise SearchCommandError("Search command references an unknown durable obligation")
                if ItemOutcome(item_state["state"]).terminal:
                    continue
                if item_state["state"] == ItemOutcome.RUNNING.value:
                    continue
                if not command_ledger.claim_item(command.run_id, command.entity_type, command.issueid):
                    continue

            try:
                if worker_maintenance is None:
                    worker_maintenance = MaintenanceController()
                with worker_maintenance.lease(
                    "search-worker",
                    work_kind="provider_search",
                    entity_type=command.entity_type,
                    entity_id=command.issueid,
                ) as lease:
                    worker_maintenance.assert_lease_current(lease)
                    result = _process_search_command(command)
            except Exception as e:
                if not isinstance(e, MaintenanceBlocked):
                    if command_ledger and command.run_id:
                        command_ledger.record_outcome(
                            command.run_id,
                            command.entity_type,
                            command.issueid,
                            ItemOutcome.FAILED,
                            reason=str(e),
                        )
                    logger.error("[SEARCH-QUEUE] Search command %s failed: %s" % (command.issueid, e))
                    _record_search_worker_health("failed", e)
                    continue
                requeued = _requeue_search_command(queue, command, command_ledger, str(e))
                _record_search_worker_health("blocked", e)
                time.sleep(maintenance_retry_delay((requeued or {}).get("attempt_count", 1)))
                continue

            outcome, outcome_reason = _search_outcome(result)
            if outcome is None:
                requeued = _requeue_search_command(queue, command, command_ledger, outcome_reason)
                time.sleep(maintenance_retry_delay((requeued or {}).get("attempt_count", 1)))
                continue
            if command_ledger and command.run_id:
                command_ledger.record_outcome(
                    command.run_id,
                    command.entity_type,
                    command.issueid,
                    outcome,
                    reason=outcome_reason,
                )
            _record_search_worker_health("idle")
            time.sleep(5)
        except SearchCommandError as e:
            logger.error("[SEARCH-QUEUE] Rejected malformed command: %s" % e)
            _record_search_worker_health("failed", e)
        except Exception as e:
            logger.error("[SEARCH-QUEUE] Queue ownership failure; continuing worker: %s" % e)
            _record_search_worker_health("failed", e)
        finally:
            _safe_task_done(queue)
