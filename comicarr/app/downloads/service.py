#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Downloads domain service — history, post-processing, DDL queue.

Module-level functions wrapping postprocessor.py (~5k lines) and
download client interactions.
"""

import datetime
import os
import re
import time
import traceback
import zipfile

import rarfile

import comicarr
from comicarr import db, getcomics, logger, nzbget, process, sabnzbd
from comicarr.app.attention import BATCH_CAP, PROBLEM_STATUS, Failure, ManualReview, record
from comicarr.app.downloads import queries as dl_queries
from comicarr.app.downloads.completed_path import resolve_completed_download_file
from comicarr.app.downloads.ddl_commands import DDLCommand, DDLCommandError
from comicarr.app.downloads.pp_commands import PostProcessCommandError, configured_roots, validate_postprocess_item
from comicarr.downloaders import mediafire, mega, pixeldrain
from comicarr.tables import annuals, comics, ddl_info, issues, storyarcs, weekly


def _maintenance_retry_delay(item):
    """Keep fenced monitor work durable without spinning a queue worker."""

    if not isinstance(item, dict):
        return 5
    try:
        attempt = int(item.get("_maintenance_retry_attempt", 0)) + 1
    except (TypeError, ValueError):
        attempt = 1
    item["_maintenance_retry_attempt"] = attempt
    from comicarr.app.acquisition.maintenance import maintenance_retry_delay

    return maintenance_retry_delay(attempt)


def _paginated_activity_response(key, query, **options):
    paginated = query(**options)
    return {
        key: paginated["results"],
        "pagination": {
            "total": paginated["total"],
            "limit": paginated["limit"],
            "offset": paginated["offset"],
            "has_more": paginated["has_more"],
        },
    }


def get_history(limit=None, offset=None, search=None, status=None, sort=None, order="desc"):
    """Get searchable, sortable download history, optionally paginated."""
    if limit is not None:
        return _paginated_activity_response(
            "history",
            dl_queries.get_history,
            limit=limit,
            offset=offset,
            search=search,
            status=status,
            sort=sort,
            order=order,
        )
    return dl_queries.get_history(
        search=search,
        status=status,
        sort=sort,
        order=order,
    )


def clear_history(status_type=None):
    """Clear download history entries."""
    dl_queries.clear_history(status_type=status_type)
    if status_type:
        logger.info("[DOWNLOADS] Cleared history entries with status: %s" % status_type)
    else:
        logger.info("[DOWNLOADS] Cleared all history entries")
    return {"success": True}


def force_process(
    nzb_name,
    nzb_folder,
    failed=False,
    issueid=None,
    comicid=None,
    ddl=False,
    oneoff=False,
    apc_version=None,
    comicrn_version=None,
):
    """Queue a download for post-processing.

    For standard API calls, queues to PP_QUEUE for background processing.
    ComicRN/APC compatibility runs the post-processor directly.
    """
    if apc_version is not None:
        logger.info("[API] Api Call from ComicRN detected - initiating script post-processing.")
        import queue as queue_mod
        import threading

        from comicarr import postprocessor

        pp_queue = queue_mod.Queue()
        if failed == "0":
            failed = False
        elif failed == "1":
            failed = True

        if not failed:
            pp = postprocessor.PostProcessor(nzb_name, nzb_folder, queue=pp_queue)
            thread_ = threading.Thread(target=pp.Process, name="Post-Processing")
            thread_.start()
            thread_.join()
        return {"success": True}

    logger.info("Received API Request for PostProcessing %s [%s]. Queueing..." % (nzb_name, nzb_folder))
    comicarr.PP_QUEUE.put(
        {
            "nzb_name": nzb_name,
            "nzb_folder": nzb_folder,
            "issueid": issueid,
            "failed": failed,
            "oneoff": oneoff,
            "comicid": comicid,
            "apicall": True,
            "ddl": ddl,
        }
    )
    return {"success": True, "message": "Successfully submitted request for post-processing for %s" % nzb_name}


def process_issue(comicid, folder, issueid=None):
    """Post-process a specific issue."""
    from comicarr import process

    try:
        fp = process.Process(nzb_name=comicid, nzb_folder=folder, issueid=issueid)
        result = fp.post_process()
        return {"success": True, "data": result}
    except Exception as e:
        logger.error("[DOWNLOADS] Error processing issue: %s" % e)
        return {"success": False, "error": str(e)}


BAND_BATCH_CAP = BATCH_CAP


def _legacy_request_error(error, *, single=False):
    message = str(error)
    lowered = message.lower()
    if "actor" in lowered:
        message = "audit identity required"
    elif "action" in lowered:
        message = "Unknown action"
    elif single:
        message = "Missing release_key"
    else:
        message = "No release_keys supplied"
    return {
        "success": False,
        "status": "failed",
        "error": message,
        "status_code": 400,
    }


def _legacy_item(item, action):
    status_code = None if item.ok else PROBLEM_STATUS.get(item.problem, 500)
    if not item.ok:
        error = item.message
        if item.problem == "not_in_attention":
            error = "Row is not on the needs-attention band"
        result = {
            "success": False,
            "status": item.status or "failed",
            "error": error,
            "status_code": status_code,
        }
        if item.problem in {"search_blocked", "search_failed", "invalid_import_source"}:
            result["message"] = item.message
        if item.stamp_written is False:
            result.update(
                {
                    "release_key": item.release_key,
                    "issue_id": item.issue_id,
                    "stamped": False,
                }
            )
        return result

    result = {
        "success": True,
        "status": item.status,
        "action": action,
        "release_key": item.release_key,
        "stamped": item.stamp_written,
        "message": item.message,
    }
    if item.issue_id is not None:
        result["issue_id"] = item.issue_id
    if action in {"retry", "search_again"}:
        result["run_id"] = item.run_id
    return result


def _legacy_batch_report(report):
    results = []
    for item in report.results:
        results.append(
            {
                "release_key": item.release_key,
                "ok": item.ok,
                "status": item.status,
                "error": (
                    None
                    if item.ok
                    else (
                        "Row is not on the needs-attention band" if item.problem == "not_in_attention" else item.message
                    )
                ),
                "status_code": None if item.ok else PROBLEM_STATUS.get(item.problem, 500),
            }
        )
    response = {
        "success": report.success,
        "partial": report.partial,
        "action": report.action,
        "requested": report.requested,
        "processed": report.processed,
        "succeeded": report.succeeded,
        "failed": report.failed,
        "capped": report.capped,
        "skipped_for_cap": report.skipped_for_cap,
        "cap": report.cap,
        "results": results,
    }
    if not report.success:
        response["status_code"] = 409
        response["error"] = "No rows could be resolved"
    return response


def resolve_needs_attention(
    ctx,
    release_key,
    action,
    *,
    audit_identity,
    nzb_name=None,
    nzb_folder=None,
):
    """Deprecated one-row adapter for :func:`comicarr.app.attention.resolve`."""
    from comicarr.app.attention import ImportSource, InvalidAttentionRequest, ResolutionRequest, resolve

    source = None
    if str(action or "").strip().lower() == "import" and (nzb_name is not None or nzb_folder is not None):
        source = ImportSource(nzb_name=nzb_name, nzb_folder=nzb_folder)
    try:
        report = resolve(
            ctx,
            ResolutionRequest(
                action=action,
                release_keys=(release_key,),
                actor=audit_identity,
                import_source=source,
            ),
        )
    except InvalidAttentionRequest as e:
        return _legacy_request_error(e, single=True)
    return _legacy_item(report.results[0], report.action)


def _batch_order(release_keys):
    """Deprecated ordering adapter retained for compatibility tests."""
    from comicarr.app.attention._resolution import _batch_order as attention_batch_order

    return attention_batch_order(release_keys)


def resolve_needs_attention_batch(ctx, action, release_keys, *, audit_identity):
    """Deprecated batch adapter for :func:`comicarr.app.attention.resolve`."""
    from comicarr.app.attention import InvalidAttentionRequest, ResolutionRequest, resolve

    try:
        report = resolve(
            ctx,
            ResolutionRequest(
                action=action,
                release_keys=release_keys,
                actor=audit_identity,
            ),
        )
    except InvalidAttentionRequest as e:
        result = _legacy_request_error(e)
        result.pop("status", None)
        return result
    return _legacy_batch_report(report)


def get_ddl_queue(limit=None, offset=None, search=None, status=None, sort=None, order="desc"):
    """Get the active DDL download queue."""
    if limit is not None:
        return _paginated_activity_response(
            "queue",
            dl_queries.get_ddl_queue,
            limit=limit,
            offset=offset,
            search=search,
            status=status,
            sort=sort,
            order=order,
        )
    return dl_queries.get_ddl_queue(
        search=search,
        status=status,
        sort=sort,
        order=order,
    )


def delete_ddl_item(item_id):
    """Remove an item from the DDL queue."""
    dl_queries.delete_ddl_item(item_id)
    logger.info("[DOWNLOADS] Removed DDL item: %s" % item_id)
    return {"success": True}


def _enqueue_ddl_queue_item(target_queue, item):
    """Hand a DDL command to the in-memory worker queue with process-local dedupe.

    ``DDL_QUEUED`` tracks ids already handed to this process's worker (queued or
    in-flight). Skipping duplicates prevents cold-start Queued recovery from
    racing journal STILL re-enqueue of the same id, and allows live outbox
    sweeps without double-dispatching items already sitting in the queue.
    """
    item_id = None
    if isinstance(item, dict):
        item_id = item.get("id") or item.get("ID")
    if item_id and item_id in comicarr.DDL_QUEUED:
        return False
    target_queue.put(item)
    if item_id:
        comicarr.DDL_QUEUED.add(item_id)
    return True


def recover_queued_ddl_commands(queue=None):
    """Replay the durable Queued outbox before the DDL worker starts.

    Only ``Queued`` rows are eligible: ``Downloading`` rows belong to the
    pipeline journal recovery path and must never be duplicated here.
    """
    target_queue = queue if queue is not None else comicarr.DDL_QUEUE
    result = {"enqueued_ids": [], "failed_ids": [], "handoff_failed_ids": []}

    for row in dl_queries.get_queued_ddl_items():
        item_id = row.get("ID")
        try:
            command = DDLCommand.from_mapping(row)
        except DDLCommandError as e:
            if item_id:
                dl_queries.update_ddl_status(item_id, "Failed")
                result["failed_ids"].append(item_id)
            logger.error("[DOWNLOADS-DDL] Invalid durable Queued item %s marked Failed: %s" % (item_id, e))
            continue

        try:
            if not _enqueue_ddl_queue_item(target_queue, command.to_queue_item()):
                continue
        except Exception as e:
            result["handoff_failed_ids"].append(command.id)
            logger.error(
                "[DOWNLOADS-DDL] Startup handoff failed for Queued item %s; row remains recoverable: %s"
                % (command.id, e)
            )
            continue

        result["enqueued_ids"].append(command.id)

    if result["enqueued_ids"]:
        logger.info("[DOWNLOADS-DDL] Recovered %d durable Queued item(s)." % len(result["enqueued_ids"]))
    return result


def requeue_ddl_item(item_id):
    """Requeue a failed DDL download."""
    try:
        item = dl_queries.get_ddl_item(item_id)
    except Exception as e:
        logger.error("[DOWNLOADS] Unable to read DDL item %s for requeue: %s" % (item_id, e))
        return {
            "success": False,
            "error": "Unable to read the durable DDL item",
            "operational_error": True,
        }
    if not item:
        return {"success": False, "error": "DDL item not found: %s" % item_id, "not_found": True}

    status = str(item.get("status") or item.get("Status") or "").strip()
    if status != "Failed":
        if not status:
            try:
                DDLCommand.from_mapping(item)
            except DDLCommandError as e:
                return {"success": False, "error": str(e), "validation_error": True}
        return {
            "success": False,
            "error": "DDL item status %s cannot be requeued" % status,
            "validation_error": True,
        }

    try:
        command = DDLCommand.from_mapping(item)
    except DDLCommandError as e:
        return {"success": False, "error": str(e), "validation_error": True}

    try:
        claimed = dl_queries.claim_failed_ddl_retry(item_id)
        if not claimed:
            return {
                "success": False,
                "error": "DDL item changed before retry could be claimed",
                "validation_error": True,
            }
    except Exception as e:
        logger.error("[DOWNLOADS] Unable to update DDL item %s for requeue: %s" % (item_id, e))
        return {
            "success": False,
            "error": "Unable to update the durable DDL item",
            "operational_error": True,
        }

    try:
        if not _enqueue_ddl_queue_item(comicarr.DDL_QUEUE, command.to_queue_item()):
            return {
                "success": False,
                "error": "Unable to insert DDL command into the worker queue",
                "handoff_error": True,
            }
    except Exception as e:
        logger.error("[DOWNLOADS] Unable to requeue DDL item %s; durable row remains Queued: %s" % (item_id, e))
        return {
            "success": False,
            "error": "Unable to insert DDL command into the worker queue",
            "handoff_error": True,
        }

    logger.info("[DOWNLOADS] Requeued DDL item: %s" % item_id)
    return {"success": True}


def queue_ddl_download(command_values):
    """Validate, persist, and queue a complete direct-download command.

    The durable row is committed before the in-memory handoff. If the queue
    insertion fails, the row remains Queued so cold-start recovery can replay
    the command without losing it.
    """
    try:
        command = DDLCommand.from_mapping(command_values)
    except DDLCommandError as e:
        return {"success": False, "error": str(e), "validation_error": True}

    try:
        db.upsert("ddl_info", command.to_persisted_values(), {"ID": command.id})
    except Exception as e:
        logger.error("[DOWNLOADS] Unable to persist DDL item %s: %s" % (command.id, e))
        return {
            "success": False,
            "error": "Unable to persist the DDL command",
            "operational_error": True,
        }

    try:
        if not _enqueue_ddl_queue_item(comicarr.DDL_QUEUE, command.to_queue_item()):
            logger.info(
                "[DOWNLOADS] DDL download %s already queued in this process; durable row left unchanged" % command.id
            )
            return {"success": True, "message": "DDL download already queued: %s" % command.id}
    except Exception as e:
        logger.error("[DOWNLOADS] Unable to queue DDL item %s; durable row remains Queued: %s" % (command.id, e))
        return {
            "success": False,
            "error": "Unable to insert DDL command into the worker queue",
            "handoff_error": True,
        }

    logger.info("[DOWNLOADS] Queued DDL download: %s (site=%s)" % (command.id, command.site))
    return {"success": True, "message": "DDL download queued: %s" % command.id}


def get_issue_file_path(issue_id):
    """Resolve the on-disk file path for an issue.

    Returns (path, filename) tuple or (None, None) if not found.
    Checks primary ComicLocation and MULTIPLE_DEST_DIRS secondary.
    """
    issue = dl_queries.get_issue_file_info(issue_id)
    if not issue:
        return None, None

    if not issue.get("Location") or not issue.get("ComicLocation"):
        return None, None

    pathfile = os.path.join(issue["ComicLocation"], issue["Location"])
    if os.path.isfile(pathfile):
        return pathfile, issue["Location"]

    if comicarr.CONFIG.MULTIPLE_DEST_DIRS:
        try:
            secondary = os.path.join(
                comicarr.CONFIG.MULTIPLE_DEST_DIRS,
                os.path.basename(issue["ComicLocation"]),
            )
            alt_path = os.path.join(secondary, issue["Location"])
            if os.path.isfile(alt_path):
                return alt_path, issue["Location"]
        except Exception:
            pass

    return None, None


def rename_param(comicid, comicname, issue, ofilename, comicyear=None, issueid=None, annualize=None, arc=False):
    from sqlalchemy import select

    from comicarr.helpers import filesafe, fullmonth, issuedigits, replace_all

    comicid = str(comicid)

    logger.fdebug(type(comicid))
    logger.fdebug(type(issueid))
    logger.fdebug("comicid: %s" % comicid)
    logger.fdebug("issue# as per cv: %s" % issue)

    if issueid is None:
        logger.fdebug("annualize is " + str(annualize))
        if arc:
            chkissue = db.select_one(
                select(storyarcs).where(storyarcs.c.ComicID == comicid, storyarcs.c.IssueNumber == issue)
            )
        else:
            chkissue = db.select_one(select(issues).where(issues.c.ComicID == comicid, issues.c.Issue_Number == issue))
            if all([chkissue is None, annualize is None, not comicarr.CONFIG.ANNUALS_ON]):
                chkissue = db.select_one(
                    select(annuals).where(
                        annuals.c.ComicID == comicid, annuals.c.Issue_Number == issue, annuals.c.Deleted != 1
                    )
                )

        if chkissue is None:
            if arc:
                chkissue = db.select_one(
                    select(storyarcs).where(
                        storyarcs.c.ComicID == comicid, storyarcs.c.Int_IssueNumber == issuedigits(issue)
                    )
                )
            else:
                chkissue = db.select_one(
                    select(issues).where(issues.c.ComicID == comicid, issues.c.Int_IssueNumber == issuedigits(issue))
                )
                if all([chkissue is None, annualize == "yes", comicarr.CONFIG.ANNUALS_ON]):
                    chkissue = db.select_one(
                        select(annuals).where(
                            annuals.c.ComicID == comicid,
                            annuals.c.Int_IssueNumber == issuedigits(issue),
                            annuals.c.Deleted != 1,
                        )
                    )

            if chkissue is None:
                logger.error("Invalid Issue_Number - please validate.")
                return
            else:
                logger.info("Int Issue_number compare found. continuing...")
                issueid = chkissue["IssueID"]
        else:
            issueid = chkissue["IssueID"]

    logger.fdebug("issueid is now : " + str(issueid))
    if arc:
        issuenzb = db.select_one(
            select(storyarcs).where(
                storyarcs.c.ComicID == comicid, storyarcs.c.IssueID == issueid, storyarcs.c.StoryArc == arc
            )
        )
    else:
        issuenzb = db.select_one(select(issues).where(issues.c.ComicID == comicid, issues.c.IssueID == issueid))
        if issuenzb is None:
            logger.fdebug("not an issue, checking against annuals")
            issuenzb = db.select_one(
                select(annuals).where(
                    annuals.c.ComicID == comicid, annuals.c.IssueID == issueid, annuals.c.Deleted != 1
                )
            )
            if issuenzb is None:
                logger.fdebug("Unable to rename - cannot locate issue id within db")
                return
            else:
                annualize = True

    if issuenzb is None:
        logger.fdebug("Unable to rename - cannot locate issue id within db")
        return

    if arc:
        issuenum = issuenzb["IssueNumber"]
        issuedate = issuenzb["IssueDate"]
        publisher = issuenzb["IssuePublisher"]
        series = issuenzb["ComicName"]
        seriesfilename = series
        seriesyear = issuenzb["SeriesYear"]
        arcdir = filesafe(issuenzb["StoryArc"])
        if comicarr.CONFIG.REPLACE_SPACES:
            arcdir = arcdir.replace(" ", comicarr.CONFIG.REPLACE_CHAR)
        if comicarr.CONFIG.STORYARCDIR:
            if comicarr.CONFIG.STORYARC_LOCATION is None:
                storyarcd = os.path.join(comicarr.CONFIG.DESTINATION_DIR, "StoryArcs", arcdir)
            else:
                storyarcd = os.path.join(comicarr.CONFIG.STORYARC_LOCATION, arcdir)
            logger.fdebug("Story Arc Directory set to : " + storyarcd)
        else:
            logger.fdebug("Story Arc Directory set to : " + comicarr.CONFIG.GRABBAG_DIR)
            storyarcd = os.path.join(comicarr.CONFIG.DESTINATION_DIR, comicarr.CONFIG.GRABBAG_DIR)
        comlocation = storyarcd
        comversion = None
    else:
        issuenum = issuenzb["Issue_Number"]
        issuedate = issuenzb["IssueDate"]
        comicnzb = db.select_one(select(comics).where(comics.c.ComicID == comicid))
        publisher = comicnzb["ComicPublisher"]
        series = comicnzb["ComicName"]
        if any([comicnzb["AlternateFileName"] is None, comicnzb["AlternateFileName"] == "None"]) or all(
            [comicnzb["AlternateFileName"] is not None, comicnzb["AlternateFileName"].strip() == ""]
        ):
            seriesfilename = series
        else:
            seriesfilename = comicnzb["AlternateFileName"]
            logger.fdebug(
                "Alternate File Naming has been enabled for this series. Will rename series title to : "
                + seriesfilename
            )
        seriesyear = comicnzb["ComicYear"]
        comlocation = comicnzb["ComicLocation"]
        comversion = comicnzb["ComicVersion"]

    unicodeissue = issuenum

    if type(issuenum) == str:
        vals = {"\xbd": ".5", "\xbc": ".25", "\xbe": ".75", "\u221e": "9999999999", "\xe2": "9999999999"}
    else:
        vals = {"\xbd": ".5", "\xbc": ".25", "\xbe": ".75", "\\u221e": "9999999999", "\xe2": "9999999999"}
    x = [vals[key] for key in vals if key in issuenum]
    if x:
        issuenum = x[0]
        logger.fdebug("issue number formatted: %s" % issuenum)

    issue_except = "None"
    valid_spaces = (".", "-")
    for issexcept in comicarr.ISSUE_EXCEPTIONS:
        if issexcept.lower() in issuenum.lower():
            logger.fdebug("ALPHANUMERIC EXCEPTION : [" + issexcept + "]")
            v_chk = [v for v in valid_spaces if v in issuenum]
            if v_chk:
                iss_space = v_chk[0]
            else:
                iss_space = ""
            if issexcept == "NOW":
                if "!" in issuenum:
                    issuenum = re.sub(r"\!", "", issuenum)
            issue_except = iss_space + issexcept
            logger.fdebug("issue_except denoted as : %s" % issue_except)
            if issuenum.lower() != issue_except.lower():
                issuenum = re.sub("[^0-9]", "", issuenum)
                if any([issuenum == "", issuenum is None]):
                    issuenum = issue_except
            break

    if "." in issuenum:
        iss_find = issuenum.find(".")
        iss_b4dec = issuenum[:iss_find]
        if iss_find == 0:
            iss_b4dec = "0"
        iss_decval = issuenum[iss_find + 1 :]
        if iss_decval.endswith("."):
            iss_decval = iss_decval[:-1]
        if int(iss_decval) == 0:
            iss = iss_b4dec
            issueno = iss
        else:
            if len(iss_decval) == 1:
                iss = iss_b4dec + "." + iss_decval
            else:
                iss = iss_b4dec + "." + iss_decval.rstrip("0")
            issueno = iss_b4dec
    else:
        iss = issuenum
        issueno = iss

    if comicarr.CONFIG.ZERO_LEVEL is False:
        zeroadd = ""
    else:
        if any([comicarr.CONFIG.ZERO_LEVEL_N == "none", comicarr.CONFIG.ZERO_LEVEL_N is None]):
            zeroadd = ""
        elif comicarr.CONFIG.ZERO_LEVEL_N == "0x":
            zeroadd = "0"
        elif comicarr.CONFIG.ZERO_LEVEL_N == "00x":
            zeroadd = "00"

    prettycomiss = None

    if issueno.isalpha():
        prettycomiss = str(issueno)
    else:
        try:
            x = float(issuenum)
            if x < 0:
                prettycomiss = "-" + str(zeroadd) + str(issueno[1:])
            elif x == 9999999999:
                issuenum = "infinity"
            elif x >= 0:
                pass
            else:
                raise ValueError
        except ValueError:
            logger.warn("Unable to properly determine issue number [ %s]" % issueno)
            return

    if all([prettycomiss is None, len(str(issueno)) > 0]):
        if int(issueno) < 10:
            if "." in iss:
                if int(iss_decval) > 0:
                    issueno = str(iss)
                    prettycomiss = str(zeroadd) + str(iss)
                else:
                    prettycomiss = str(zeroadd) + str(int(issueno))
            else:
                prettycomiss = str(zeroadd) + str(iss)
            if issue_except != "None":
                prettycomiss = str(prettycomiss) + issue_except
        elif int(issueno) >= 10 and int(issueno) < 100:
            if any(
                [
                    comicarr.CONFIG.ZERO_LEVEL_N == "none",
                    comicarr.CONFIG.ZERO_LEVEL_N is None,
                    comicarr.CONFIG.ZERO_LEVEL is False,
                ]
            ):
                zeroadd = ""
            else:
                zeroadd = "0"
            if "." in iss:
                if int(iss_decval) > 0:
                    issueno = str(iss)
                    prettycomiss = str(zeroadd) + str(iss)
                else:
                    prettycomiss = str(zeroadd) + str(int(issueno))
            else:
                prettycomiss = str(zeroadd) + str(iss)
            if issue_except != "None":
                prettycomiss = str(prettycomiss) + issue_except
        else:
            if issuenum == "infinity":
                prettycomiss = "infinity"
            else:
                if "." in iss:
                    if int(iss_decval) > 0:
                        issueno = str(iss)
                prettycomiss = str(issueno)
            if issue_except != "None":
                prettycomiss = str(prettycomiss) + issue_except
    elif len(str(issueno)) == 0:
        prettycomiss = str(issueno)

    if comicarr.CONFIG.UNICODE_ISSUENUMBER:
        prettycomiss = unicodeissue

    issueyear = issuedate[:4]
    month = issuedate[5:7].replace("-", "").strip()
    month_name = fullmonth(month)
    if month_name is None:
        month_name = "None"

    if comversion is None:
        comversion = "None"
    if comversion == "None":
        chunk_f_f = re.sub(r"\$VolumeN", "", comicarr.CONFIG.FILE_FORMAT)
        chunk_f = re.compile(r"\s+")
        chunk_file_format = chunk_f.sub(" ", chunk_f_f)
    else:
        chunk_file_format = comicarr.CONFIG.FILE_FORMAT

    if annualize is None:
        chunk_f_f = re.sub(r"\$Annual", "", chunk_file_format)
        chunk_f = re.compile(r"\s+")
        chunk_file_format = chunk_f.sub(" ", chunk_f_f)
    else:
        if comicarr.CONFIG.ANNUALS_ON:
            if "annual" in series.lower():
                if "$Annual" not in chunk_file_format:
                    pass
                else:
                    chunk_f_f = re.sub(r"\$Annual", "", chunk_file_format)
                    chunk_f = re.compile(r"\s+")
                    chunk_file_format = chunk_f.sub(" ", chunk_f_f)
            else:
                if "$Annual" not in chunk_file_format:
                    prettycomiss = "Annual %s" % prettycomiss
        else:
            if "annual" in series.lower():
                if "$Annual" not in chunk_file_format:
                    pass
                else:
                    chunk_f_f = re.sub(r"\$Annual", "", chunk_file_format)
                    chunk_f = re.compile(r"\s+")
                    chunk_file_format = chunk_f.sub(" ", chunk_f_f)
            else:
                if "$Annual" not in chunk_file_format:
                    prettycomiss = "Annual %s" % prettycomiss

    seriesfilename = seriesfilename
    filebad = [":", ",", "/", "?", "!", "'", '"', r"\*"]
    for dbd in filebad:
        if dbd in seriesfilename:
            if any([dbd == "/", dbd == "*"]):
                repthechar = "-"
            else:
                repthechar = ""
            seriesfilename = seriesfilename.replace(dbd, repthechar)

    publisher = re.sub("!", "", publisher)

    file_values = {
        "$Series": seriesfilename,
        "$Issue": prettycomiss,
        "$Year": issueyear,
        "$series": series.lower(),
        "$Publisher": publisher,
        "$publisher": publisher.lower(),
        "$VolumeY": "V" + str(seriesyear),
        "$VolumeN": comversion,
        "$monthname": month_name,
        "$month": month,
        "$Annual": "Annual",
    }

    extensions = (".cbr", ".cbz", ".cb7")
    if ofilename.lower().endswith(extensions):
        path, ext = os.path.splitext(ofilename)

    if comicarr.CONFIG.FILE_FORMAT == "":
        if ofilename.lower().endswith(extensions):
            nfilename = ofilename[:-4]
        else:
            nfilename = ofilename
    else:
        nfilename = replace_all(chunk_file_format, file_values)
        if comicarr.CONFIG.REPLACE_SPACES:
            nfilename = nfilename.replace(" ", comicarr.CONFIG.REPLACE_CHAR)

    nfilename = re.sub(r"[\,\:]", "", nfilename) + ext.lower()

    if comicarr.CONFIG.LOWERCASE_FILENAMES:
        nfilename = nfilename.lower()
        dst = os.path.join(comlocation, nfilename)
    else:
        dst = os.path.join(comlocation, nfilename)

    rename_this = {"destination_dir": dst, "nfilename": nfilename, "issueid": issueid, "comicid": comicid}
    return rename_this


def renamefile_readingorder(readorder):
    logger.fdebug("readingorder#: " + str(readorder))
    if int(readorder) < 10:
        readord = "00" + str(readorder)
    elif int(readorder) >= 10 and int(readorder) <= 99:
        readord = "0" + str(readorder)
    else:
        readord = str(readorder)
    return readord


def duplicate_filecheck(filename, ComicID=None, IssueID=None, StoryArcID=None, rtnval=None):
    from sqlalchemy import select

    logger.info("[DUPECHECK] Duplicate check for " + filename)
    try:
        filesz = os.path.getsize(filename)
    except OSError:
        logger.warn("[DUPECHECK] File cannot be located in location specified.")
        return {"action": None}

    if IssueID:
        dupchk = db.select_one(select(issues).where(issues.c.IssueID == IssueID))
    if dupchk is None:
        dupchk = db.select_one(select(annuals).where(annuals.c.IssueID == IssueID, annuals.c.Deleted != 1))
        if dupchk is None:
            logger.info("[DUPECHECK] Unable to find corresponding Issue within the DB.")
            return {"action": None}

    series = db.select_one(select(comics).where(comics.c.ComicID == dupchk["ComicID"]))

    if dupchk["Status"] == "Downloaded" or dupchk["Status"] == "Archived":
        try:
            dupsize = dupchk["ComicSize"]
        except Exception:
            rtnval = {"action": "write"}

        if dupsize is None:
            havechk = db.select_one(select(comics).where(comics.c.ComicID == ComicID))
            if havechk:
                if havechk["Have"] > havechk["Total"]:
                    cid = [ComicID]
                    comicarr.updater.dbUpdate(ComicIDList=cid, calledfrom="dupechk")
                    return duplicate_filecheck(filename, ComicID, IssueID, StoryArcID)
                else:
                    if rtnval is not None:
                        return rtnval
                    else:
                        rtnval = {"action": "dont_dupe"}
                        comicarr.updater.forceRescan(ComicID)
                        chk1 = duplicate_filecheck(filename, ComicID, IssueID, StoryArcID, rtnval)
                        rtnval = chk1
            else:
                rtnval = {"action": "dupe_file", "to_dupe": os.path.join(series["ComicLocation"], dupchk["Location"])}
        else:
            fixed = False
            fixed_file = re.findall(r"[(]f\d{1}[)]", filename.lower())
            fixed_db_file = re.findall(r"[(]f\d{1}[)]", dupchk["Location"].lower())
            if all([fixed_file, not fixed_db_file]):
                fixed = True
                rtnval = {"action": "dupe_src", "to_dupe": os.path.join(series["ComicLocation"], dupchk["Location"])}
            elif all([fixed_db_file, not fixed_file]):
                fixed = True
                rtnval = {"action": "dupe_file", "to_dupe": filename}
            elif int(dupsize) == 0:
                if dupchk["Status"] == "Archived":
                    rtnval = {"action": "dupe_file", "to_dupe": filename}
                    return rtnval

            tmp_dupeconstraint = comicarr.CONFIG.DUPECONSTRAINT
            if not fixed and (comicarr.CONFIG.DUPECONSTRAINT == "filesize" or tmp_dupeconstraint == "filesize"):
                if filesz <= int(dupsize) and int(dupsize) != 0:
                    rtnval = {"action": "dupe_file", "to_dupe": filename}
                else:
                    rtnval = {
                        "action": "dupe_src",
                        "to_dupe": os.path.join(series["ComicLocation"], dupchk["Location"]),
                    }
    else:
        rtnval = {"action": "write"}
    return rtnval


def _pack_row_matches(row, int_iss, iss_item, kind):
    """Decide whether one issues-table row belongs to a pack range entry.

    A volume pack (e.g. ``v01-14``) covers rows by their ``VolumeNumber``
    — including manga chapter rows that belong to a covered volume — but
    must never claim a chapter numbered like a volume (a chapter 7 with
    an unknown volume is not volume 7). Rows without volume metadata
    (TPB/GN-tracked series) fall back to the plain issue-number match.
    Issue/chapter packs symmetrically never claim volume rows.
    """
    volume = row.get("VolumeNumber")
    chapter = row.get("ChapterNumber")
    if kind == "volume":
        if volume not in (None, ""):
            try:
                return int(float(volume)) == int(iss_item)
            except (TypeError, ValueError):
                return False
        if chapter not in (None, ""):
            return False
    elif volume not in (None, "") and chapter in (None, ""):
        return False
    return row["Int_IssueNumber"] == int_iss


def _register_pack_claims(write_valids, valid):
    if valid:
        for wv in write_valids:
            comicarr.PACK_ISSUEIDS_DONT_QUEUE[wv["issueid"]] = wv["pack_id"]


def _row_released_after(row, cutoff_year):
    """True when the row's first usable date is later than cutoff_year.

    A pack whose title span ends in ``cutoff_year`` cannot contain anything
    published after it. Rows with no parseable date (or the 0000-00-00
    sentinel) are not excluded — the pack keeps the benefit of the doubt.
    """
    for field in ("ReleaseDate", "IssueDate", "DigitalDate"):
        value = str(row.get(field) or "")
        if len(value) >= 4 and value[:4].isdigit() and int(value[:4]) > 0:
            return int(value[:4]) > cutoff_year
    return False


def issue_find_ids(ComicName, ComicID, pack, IssueNumber, pack_id, kind="issue", span_end=None):
    from sqlalchemy import select

    from comicarr.helpers import issuedigits

    issuelist = db.select_all(select(issues).where(issues.c.ComicID == ComicID))

    if kind == "series":
        try:
            cutoff = int(span_end)
        except (TypeError, ValueError):
            cutoff = None
        Int_IssueNumber = issuedigits(IssueNumber)
        issueinfo = []
        write_valids = []
        valid = False
        for xb in issuelist:
            if xb["Status"] == "Downloaded":
                continue
            if cutoff is not None and _row_released_after(xb, cutoff):
                continue
            if Int_IssueNumber == xb["Int_IssueNumber"]:
                valid = True
            issueinfo.append(
                {
                    "issueid": xb["IssueID"],
                    "int_iss": xb["Int_IssueNumber"],
                    "issuenumber": xb["Issue_Number"],
                }
            )
            write_valids.append({"issueid": xb["IssueID"], "pack_id": pack_id})
        _register_pack_claims(write_valids, valid)
        return {
            "issues": issueinfo,
            "issue_range": [x["issuenumber"] for x in issueinfo],
            "valid": valid,
        }

    if "Annual" not in pack:
        if "," not in pack:
            packlist = pack.split(" ")
            pack = re.sub("#", "", pack).strip()
        else:
            packlist = [x.strip() for x in pack.split(",")]
        plist = []
        pack_issues = []
        for pl in packlist:
            pl = re.sub("#", "", pl).strip()
            if "-" in pl:
                le_range = list(range(int(pack[: pack.find("-")]), int(pack[pack.find("-") + 1 :]) + 1))
                for x in le_range:
                    if not [y for y in plist if y == x]:
                        plist.append(int(x))
            else:
                if not [x for x in plist if x == int(pl)]:
                    plist.append(int(pl))

        for pi in plist:
            if type(pi) == list:
                for x in pi:
                    pack_issues.append(x)
            else:
                pack_issues.append(pi)
        pack_issues.sort()
    else:
        tmp_pack = re.sub("[annual/annuals/+]", "", pack.lower()).strip()
        pack_issues_numbers = re.findall(r"\d+", tmp_pack)
        pack_issues = list(range(int(pack_issues_numbers[0]), int(pack_issues_numbers[1]) + 1))

    iss = {}
    issueinfo = []
    write_valids = []

    Int_IssueNumber = issuedigits(IssueNumber)
    valid = False
    ignores = []
    for iss_item in pack_issues:
        int_iss = issuedigits(str(iss_item))
        for xb in issuelist:
            if xb["Status"] != "Downloaded":
                if _pack_row_matches(xb, int_iss, iss_item, kind):
                    if Int_IssueNumber == xb["Int_IssueNumber"]:
                        valid = True
                    issueinfo.append({"issueid": xb["IssueID"], "int_iss": int_iss, "issuenumber": xb["Issue_Number"]})
                    write_valids.append({"issueid": xb["IssueID"], "pack_id": pack_id})
                    if kind != "volume":
                        break
            else:
                ignores.append(iss_item)

    _register_pack_claims(write_valids, valid)

    iss["issues"] = issueinfo

    if len(iss["issues"]) == len(pack_issues):
        logger.fdebug(
            "Complete issue count of %s issues are available within this pack for %s" % (len(pack_issues), ComicName)
        )

    iss["issue_range"] = pack_issues
    iss["valid"] = valid
    return iss


def reverse_the_pack_snatch(pack_id, comicid):
    logger.info(
        "[REVERSE UNO] Reversal of issues marked as Snatched via pack download reversing due to invalid link retrieval.."
    )
    reverselist = [issueid for issueid, packid in comicarr.PACK_ISSUEIDS_DONT_QUEUE.items() if pack_id == packid]
    for x in reverselist:
        db.upsert("issues", {"Status": "Skipped"}, {"IssueID": x})
    if reverselist:
        logger.info("[REVERSE UNO] Reversal completed for %s issues" % len(reverselist))
        try:
            from comicarr.app.activity.producers import emit_grab_cancelled_series

            emit_grab_cancelled_series(comicid, count=len(reverselist))
        except Exception as e:
            logger.fdebug("[ACTIVITY] grab.cancelled @series emit skipped: %s" % e)


def _finalize_ddl_download(item, ddzstat, release_key):
    """Validate and durably hand a completed DDL artifact to PP.

    Called by handoff.perform_handoff while its maintenance lease is still
    active, so the file validation, downloaded transition and PP enqueue form
    one owned side-effect window. It never re-runs the external download.
    """
    from comicarr.app.downloads import journal
    from comicarr.helpers import check_file_condition

    if ddzstat.get("success") and ddzstat.get("filename") is not None:
        filecondition = check_file_condition(ddzstat.get("path"))
        if not filecondition.get("status"):
            ddzstat["success"] = False
            ddzstat["link_type_failure"] = item.get("link_type")

    if not ddzstat.get("success"):
        fail_payload = {
            "issueid": item.get("issueid"),
            "comicid": item.get("comicid"),
            "provider": "DDL",
            "ddl_id": item.get("id"),
            "filename": item.get("filename"),
            "ddl": True,
        }
        record(
            Failure(
                release_key=release_key,
                reason="ddl_download_or_artifact_validation_failed",
                payload=fail_payload,
                issue_id=item.get("issueid"),
                provider="DDL",
                downloader_type="ddl",
                nzb_name=item.get("filename"),
                release_id=item.get("id"),
                comic_id=item.get("comicid"),
            )
        )
        return False

    nzb_name = ddzstat.get("filename") or os.path.basename(ddzstat["path"])
    payload = {
        "issueid": item.get("issueid"),
        "comicid": item.get("comicid"),
        "provider": "DDL",
        "ddl_id": item.get("id"),
        "id": item.get("id"),
        "series": item.get("series"),
        "filename": item.get("filename"),
        "ddl": True,
        "nzb_folder": ddzstat["path"],
        "nzb_name": nzb_name,
        "download_info": {"provider": "DDL", "id": item.get("id")},
    }
    completed = {"status": "Completed", "updated_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    try:
        with db.get_engine().begin() as conn:
            db.upsert_conn(conn, "ddl_info", completed, {"ID": item["id"]})
            won = journal.record_transition(
                release_key,
                journal.DOWNLOADED,
                payload=payload,
                conn=conn,
                issueid=item.get("issueid"),
                provider="DDL",
                downloader_type="ddl",
                nzbname=item.get("filename"),
            )
            if not won:
                current = journal.read_one(release_key)
                if not current or current.get("stage") != journal.DOWNLOADED:
                    raise RuntimeError("DDL downloaded transition did not advance the accepted obligation")
    except Exception as e:
        try:
            db.upsert("ddl_info", completed, {"ID": item["id"]})
            record(
                ManualReview(
                    release_key=release_key,
                    reason="ddl_artifact_state_persistence_error:%s" % type(e).__name__,
                    payload=payload,
                    issue_id=item.get("issueid"),
                    provider="DDL",
                    downloader_type="ddl",
                    nzb_name=item.get("filename"),
                )
            )
        except Exception as quarantine_error:
            logger.error(
                "[DOWNLOADS-DDL] unable to persist quarantine for id=%s: %s"
                % (item.get("id"), type(quarantine_error).__name__)
            )
        raise

    if comicarr.CONFIG.POST_PROCESSING is True:
        comicarr.PP_QUEUE.put(
            {
                "nzb_name": nzb_name,
                "nzb_folder": ddzstat["path"],
                "failed": False,
                "issueid": item.get("issueid"),
                "comicid": item.get("comicid"),
                "apicall": True,
                "ddl": True,
                "download_info": {"provider": "DDL", "id": item.get("id")},
                "journal_release_key": release_key,
            }
        )
    else:
        journal.mark_done(
            release_key,
            payload=payload,
            issueid=item.get("issueid"),
            provider="DDL",
            downloader_type="ddl",
            nzbname=item.get("filename"),
        )
    return True


def ddl_downloader(queue):
    """Run the DDL worker without allowing one poison item to stop it."""
    active_item = {"value": None}
    link_type_failure = {}
    while True:
        try:
            return _ddl_downloader_loop(queue, link_type_failure, active_item)
        except Exception as e:
            item = active_item["value"]
            item_id = None
            if isinstance(item, dict):
                item_id = item.get("id") or item.get("ID")
            logger.error(
                "[DOWNLOADS-DDL] DDL worker rejected item%s; continuing with the next command: %s"
                % ((" id=%s" % item_id) if item_id else "", e)
            )
            if item_id:
                try:
                    db.upsert(
                        "ddl_info",
                        {
                            "status": "Failed",
                            "updated_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                        },
                        {"ID": item_id},
                    )
                except Exception as status_error:
                    logger.error("[DOWNLOADS-DDL] Unable to mark failed DDL item %s: %s" % (item_id, status_error))
                try:
                    from comicarr.app.downloads import journal

                    issueid = item.get("issueid") if isinstance(item, dict) else None
                    filename = item.get("filename") if isinstance(item, dict) else None
                    rkey = journal.release_key(
                        issueid,
                        "DDL",
                        nzbname=filename,
                        hash=None,
                        discriminant=item_id,
                    )
                    existing = journal.read_one(rkey)
                    if existing and not journal.is_terminal(existing.get("stage")):
                        from comicarr.app.common.redaction import redact_sensitive_text

                        fail_detail = redact_sensitive_text(str(e))[:1000]
                        journal_payload = dict(item) if isinstance(item, dict) else {}
                        journal_payload["fail_detail"] = fail_detail
                        record(
                            Failure(
                                release_key=rkey,
                                reason="ddl-worker-rejected",
                                payload=journal_payload,
                                issue_id=issueid,
                                provider="DDL",
                                downloader_type="ddl",
                                nzb_name=filename,
                                release_id=item_id,
                            )
                        )
                except Exception as journal_error:
                    logger.error(
                        "[DOWNLOADS-DDL] Unable to close journal for rejected DDL item %s: %s"
                        % (item_id, journal_error)
                    )
                comicarr.DDL_QUEUED.discard(item_id)
                comicarr.DDL_STUCK_NOTIFIED.discard(item_id)
                link_type_failure.pop(item_id, None)
                ddl_cleanup(item_id)
            active_item["value"] = None


def _ddl_downloader_loop(queue, link_type_failure, active_item):
    from sqlalchemy import delete

    from comicarr.helpers import check_file_condition

    while True:
        if comicarr.DDL_LOCK.locked():
            time.sleep(5)
        elif not comicarr.DDL_LOCK.locked() and queue.qsize() >= 1:
            item = queue.get(True)
            if item == "exit":
                logger.info("Cleaning up workers for shutdown")
                break
            active_item["value"] = item
            command = DDLCommand.from_mapping(item)
            canonical_item = command.to_queue_item()
            for internal_key in ("_journal_retry", "link_type_failure", "ddl", "journal_release_key"):
                if internal_key in item:
                    canonical_item[internal_key] = item[internal_key]
            item = canonical_item
            active_item["value"] = item
            if item["id"] not in comicarr.DDL_QUEUED:
                comicarr.DDL_QUEUED.add(item["id"])
            try:
                link_type_failure[item["id"]].append(item["link_type_failure"])
            except Exception:
                pass

            logger.info("Now loading request from DDL queue: %s" % item["series"])
            ctrlval = {"ID": item["id"]}
            val = {"status": "Downloading", "updated_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}

            from comicarr.app.acquisition.maintenance import MaintenanceBlocked
            from comicarr.app.downloads import handoff, journal

            ddl_issueid = item.get("issueid")
            ddl_payload = {key: value for key, value in item.items() if not key.startswith("_")}
            ddl_payload.update({"provider": "DDL", "ddl": True})
            ddl_rkey = item.get("journal_release_key") or journal.release_key(
                ddl_issueid,
                "DDL",
                nzbname=item.get("filename"),
                hash=None,
                discriminant=item["id"],
            )
            try:
                db.upsert("ddl_info", val, {"ID": item["id"]})
            except Exception as e:
                logger.error(
                    "[DOWNLOADS-DDL] could not persist Downloading state for id=%s; external side effect NOT started: %s"
                    % (item.get("id"), type(e).__name__)
                )
                comicarr.DDL_QUEUED.discard(item["id"])
                continue

            ddl_result = {}
            ddl_finalization = {"complete": False}

            def _run_ddl_side_effect(item=item, ddl_result=ddl_result):
                if item["site"] == "DDL(GetComics)":
                    try:
                        remote_filesize = item["remote_filesize"]
                    except Exception:
                        try:
                            from comicarr.helpers import human2bytes

                            remote_filesize = human2bytes(re.sub("/s", "", item["size"][:-1]).strip())
                        except Exception:
                            remote_filesize = 0

                    if item["link_type"] in {"GC-Main", "GC-Mirror"}:
                        ddz = getcomics.GC()
                        result = ddz.downloadit(
                            id=item["id"],
                            link=item["link"],
                            mainlink=item["mainlink"],
                            resume=item["resume"],
                            issueid=item["issueid"],
                            remote_filesize=remote_filesize,
                            link_type=item["link_type"],
                        )
                    elif item["link_type"] == "GC-Mega":
                        result = mega.MegaNZ().ddl_download(
                            item["link"], None, item["id"], item["issueid"], item["link_type"]
                        )
                    elif item["link_type"] == "GC-Media":
                        result = mediafire.MediaFire().ddl_download(item["link"], item["id"], item["issueid"])
                    else:
                        result = pixeldrain.PixelDrain().ddl_download(item["link"], item["id"], item["issueid"])
                else:
                    result = mega.MegaNZ().ddl_download(
                        item["link"], item["filename"], item["id"], item["issueid"], item["link_type"]
                    )
                ddl_result["value"] = result
                return {"status": bool(result.get("success")), "ddl_id": item["id"]}

            def _finalize_ddl_handoff(
                _response,
                _acceptance,
                item=item,
                ddl_result=ddl_result,
                ddl_rkey=ddl_rkey,
                ddl_finalization=ddl_finalization,
            ):
                ddl_finalization["complete"] = _finalize_ddl_download(item, ddl_result["value"], ddl_rkey)

            try:
                handoff.perform_handoff(
                    ddl_rkey,
                    "ddl",
                    _run_ddl_side_effect,
                    payload=ddl_payload,
                    owner="ddl-worker",
                    issueid=ddl_issueid,
                    provider="DDL",
                    nzbname=item.get("filename"),
                    finalizer=_finalize_ddl_handoff,
                    resume_accepted=bool(item.get("journal_release_key")),
                )
            except MaintenanceBlocked:
                db.upsert(
                    "ddl_info",
                    {"status": "Queued", "updated_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")},
                    {"ID": item["id"]},
                )
                comicarr.DDL_QUEUED.discard(item["id"])
                logger.info("[DOWNLOADS-DDL] Maintenance fence retained id=%s as durable Queued work." % item["id"])
                continue
            except Exception as e:
                logger.error(
                    "[DOWNLOADS-DDL] external outcome for id=%s requires review; not re-downloading: %s"
                    % (item.get("id"), type(e).__name__)
                )
                try:
                    current = journal.read_one(ddl_rkey)
                    if current and current.get("stage") == journal.MANUAL_REVIEW:
                        status = "Manual Review"
                    elif (ddl_result.get("value") or {}).get("success"):
                        status = "Completed"
                    elif current and journal.stage_rank(current.get("stage")) >= journal.stage_rank(journal.DOWNLOADED):
                        status = "Completed"
                    else:
                        status = "Failed"
                    db.upsert(
                        "ddl_info",
                        {"status": status, "updated_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")},
                        {"ID": item["id"]},
                    )
                except Exception as status_error:
                    logger.error(
                        "[DOWNLOADS-DDL] unable to reconcile durable status for id=%s: %s"
                        % (item.get("id"), type(status_error).__name__)
                    )
                comicarr.DDL_QUEUED.discard(item["id"])
                continue
            ddzstat = ddl_result["value"]

            if ddl_finalization["complete"]:
                comicarr.DDL_QUEUED.discard(item["id"])
                comicarr.DDL_STUCK_NOTIFIED.discard(item["id"])
                link_type_failure.pop(item["id"], None)
                ddl_cleanup(item["id"])
                active_item["value"] = None
                continue

            if ddzstat["success"] and ddzstat["filename"] is not None:
                filecondition = check_file_condition(ddzstat["path"])
                if not filecondition["status"]:
                    ddzstat["success"] = False
                    ddzstat["link_type_failure"] = item["link_type"]

            if ddzstat["success"] is True:
                tdnow = datetime.datetime.now()
                nval = {"status": "Completed", "updated_date": tdnow.strftime("%Y-%m-%d %H:%M")}

                ddlc_issueid = item.get("issueid")
                if ddzstat["filename"] is None:
                    ddlc_nzb_name = os.path.basename(ddzstat["path"])
                else:
                    ddlc_nzb_name = ddzstat["filename"]
                ddlc_payload = {
                    "issueid": ddlc_issueid,
                    "comicid": item.get("comicid"),
                    "provider": "DDL",
                    "id": item["id"],
                    "series": item.get("series"),
                    "filename": item.get("filename"),
                    "ddl": True,
                    "nzb_folder": ddzstat["path"],
                    "nzb_name": ddlc_nzb_name,
                    "download_info": {"provider": "DDL", "id": item["id"]},
                }
                ddlc_rkey = journal.release_key(
                    ddlc_issueid,
                    "DDL",
                    nzbname=item.get("filename"),
                    hash=None,
                    discriminant=item["id"],
                )
                try:
                    with db.get_engine().begin() as conn:
                        db.upsert_conn(conn, "ddl_info", nval, {"ID": item["id"]})
                        journal.record_transition(
                            ddlc_rkey,
                            journal.DOWNLOADED,
                            payload=ddlc_payload,
                            conn=conn,
                            issueid=ddlc_issueid,
                            provider="DDL",
                            downloader_type="ddl",
                            nzbname=item.get("filename"),
                        )
                    logger.fdebug("[DOWNLOADS-DDL] Journaled downloaded for %s" % ddlc_rkey)
                except Exception as e:
                    logger.error(
                        "[DOWNLOADS-DDL] artifact exists for id=%s but downloaded-state persistence failed; "
                        "quarantining without re-downloading: %s" % (item.get("id"), type(e).__name__)
                    )
                    try:
                        db.upsert(
                            "ddl_info",
                            {
                                "status": "Manual Review",
                                "updated_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                            },
                            {"ID": item["id"]},
                        )
                        record(
                            ManualReview(
                                release_key=ddlc_rkey,
                                reason="ddl_artifact_state_persistence_error:%s" % type(e).__name__,
                                payload=ddlc_payload,
                                issue_id=ddlc_issueid,
                                provider="DDL",
                                downloader_type="ddl",
                                nzb_name=item.get("filename"),
                            )
                        )
                    except Exception as quarantine_error:
                        logger.error(
                            "[DOWNLOADS-DDL] unable to persist quarantine for id=%s: %s"
                            % (item.get("id"), type(quarantine_error).__name__)
                        )
                    comicarr.DDL_QUEUED.discard(item["id"])
                    comicarr.DDL_STUCK_NOTIFIED.discard(item["id"])
                    try:
                        link_type_failure.pop(item["id"])
                    except KeyError:
                        pass
                    continue

            if all([ddzstat["success"] is True, comicarr.CONFIG.POST_PROCESSING is True]):
                try:
                    if ddzstat["filename"] is None:
                        comicarr.PP_QUEUE.put(
                            {
                                "nzb_name": os.path.basename(ddzstat["path"]),
                                "nzb_folder": ddzstat["path"],
                                "failed": False,
                                "issueid": None,
                                "comicid": item["comicid"],
                                "apicall": True,
                                "ddl": True,
                                "download_info": {"provider": "DDL", "id": item["id"]},
                                "journal_release_key": ddlc_rkey,
                            }
                        )
                    else:
                        comicarr.PP_QUEUE.put(
                            {
                                "nzb_name": ddzstat["filename"],
                                "nzb_folder": ddzstat["path"],
                                "failed": False,
                                "issueid": item["issueid"],
                                "comicid": item["comicid"],
                                "apicall": True,
                                "ddl": True,
                                "download_info": {"provider": "DDL", "id": item["id"]},
                                "journal_release_key": ddlc_rkey,
                            }
                        )
                except Exception as e:
                    logger.error("process error: %s [%s]" % (e, ddzstat))

                comicarr.DDL_QUEUED.discard(item["id"])
                comicarr.DDL_STUCK_NOTIFIED.discard(item["id"])
                try:
                    link_type_failure.pop(item["id"])
                except KeyError:
                    pass
                try:
                    pck_cnt = 0
                    if item["comicinfo"][0]["pack"] is True:
                        for x, y in dict(comicarr.PACK_ISSUEIDS_DONT_QUEUE).items():
                            if y == item["id"]:
                                pck_cnt += 1
                                del comicarr.PACK_ISSUEIDS_DONT_QUEUE[x]
                except Exception:
                    pass
                ddl_cleanup(item["id"])

            elif all([ddzstat["success"] is True, comicarr.CONFIG.POST_PROCESSING is False]):
                ddl_cleanup(item["id"])
            else:
                if item["site"] == "DDL(GetComics)":
                    try:
                        ddzstat["links_exhausted"]
                    except KeyError:
                        try:
                            link_type_failure[item["id"]].append(item["link_type"])
                        except KeyError:
                            link_type_failure[item["id"]] = [item["link_type"]]
                        comicarr.DDL_QUEUED.discard(item["id"])
                        ggc = getcomics.GC(comicid=item["comicid"], issueid=item["issueid"], oneoff=item["oneoff"])
                        ggc.parse_downloadresults(
                            item["id"],
                            item["mainlink"],
                            item["comicinfo"],
                            item["packinfo"],
                            link_type_failure[item["id"]],
                        )
                    else:
                        nval = {"status": "Failed", "updated_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
                        db.upsert("ddl_info", nval, ctrlval)
                        reverse_the_pack_snatch(item["id"], item["comicid"])
                        comicarr.DDL_QUEUED.discard(item["id"])
                        comicarr.DDL_STUCK_NOTIFIED.discard(item["id"])
                        link_type_failure.pop(item["id"], None)
                        ddl_cleanup(item["id"])
                else:
                    with db.get_engine().begin() as conn:
                        conn.execute(delete(ddl_info).where(ddl_info.c.ID == item["id"]))
                    comicarr.DDL_QUEUED.discard(item["id"])
                    comicarr.DDL_STUCK_NOTIFIED.discard(item["id"])
                    comicarr.search.FailedMark(
                        item["issueid"],
                        item["comicid"],
                        item["id"],
                        ddzstat["filename"],
                        item["site"],
                        journal_release_key=item.get("journal_release_key"),
                    )
            active_item["value"] = None
        else:
            try:
                recover_queued_ddl_commands(queue)
            except Exception as recover_error:
                logger.error("[DOWNLOADS-DDL] Live Queued outbox sweep failed: %s" % recover_error)
            time.sleep(5)


def ddl_cleanup(id):
    tlnk = "getcomics-%s.html" % id
    try:
        os.remove(os.path.join(comicarr.CONFIG.CACHE_DIR, "html_cache", tlnk))
    except Exception:
        logger.fdebug("[HTML-cleanup] Unable to remove html used for item from html_cache folder.")


def ddl_health_check():
    if not comicarr.CONFIG.DDL_STUCK_NOTIFY:
        return
    if not comicarr.CONFIG.ENABLE_DDL:
        return

    from sqlalchemy import select

    from comicarr.app.system.service import notify_ddl_stuck

    stuck_items = db.select_all(select(ddl_info).where(ddl_info.c.status == "Downloading"))
    if not stuck_items:
        return

    threshold_minutes = comicarr.CONFIG.DDL_STUCK_THRESHOLD
    now = datetime.datetime.now()

    for item in stuck_items:
        if item["updated_date"] is None:
            continue
        try:
            updated = datetime.datetime.strptime(item["updated_date"], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        age_minutes = (now - updated).total_seconds() / 60
        if age_minutes > threshold_minutes:
            if item["ID"] in comicarr.DDL_STUCK_NOTIFIED:
                continue
            try:
                from comicarr.app.downloads import journal
                from comicarr.tables import pipeline_journal

                stmt = select(pipeline_journal).where(
                    pipeline_journal.c.stage == journal.FAILED,
                    pipeline_journal.c.issueid == str(item["issueid"]),
                )
                if db.select_one(stmt) is not None:
                    comicarr.DDL_STUCK_NOTIFIED.add(item["ID"])
                    continue
            except Exception as e:
                logger.fdebug("[DDL-HEALTH] journal reconciliation skipped (non-fatal): %s" % e)
            logger.warn(
                "[DDL-HEALTH] Download stuck for %d minutes: %s (%s)" % (int(age_minutes), item["series"], item["ID"])
            )
            notify_ddl_stuck(item, int(age_minutes))
            comicarr.DDL_STUCK_NOTIFIED.add(item["ID"])


def postprocess_main(queue):
    import queue as queue_module

    while True:
        try:
            item = queue.get(timeout=5)
        except queue_module.Empty:
            continue
        if item == "exit":
            logger.info("Cleaning up workers for shutdown")
            break
        if comicarr.APILOCK.locked():
            queue.put(item)
            time.sleep(1)
            continue
        logger.info(
            "Now loading post-processing command name=%s issueid=%s"
            % (
                item.get("nzb_name") if isinstance(item, dict) else "unknown",
                item.get("issueid") if isinstance(item, dict) else None,
            )
        )

        try:
            item = validate_postprocess_item(item, roots=_configured_postprocess_roots())
        except PostProcessCommandError as e:
            _quarantine_postprocess_item(item, "invalid_postprocess_command:%s" % type(e).__name__)
            logger.error("[DOWNLOADS-PP] Rejected unsafe post-processing command: %s" % e)
            continue

        outcome, pp = _run_owned_postprocess(item)
        if outcome == "requeue":
            queue.put(item)
            time.sleep(1)
            continue
        if outcome in {"drop", "failed"}:
            continue
        if pp is not None:
            try:
                if pp["mode"] == "stop" and comicarr.APILOCK.locked():
                    comicarr.APILOCK.release()
            except (KeyError, TypeError):
                pass
        if comicarr.APILOCK.locked():
            logger.info("Another item is post-processing still...")
            time.sleep(15)


def _run_owned_postprocess(item):
    """Acquire the maintenance lease before the CAS and hold it through PP."""
    from comicarr.app.acquisition.maintenance import MaintenanceBlocked, MaintenanceController
    from comicarr.app.downloads import journal

    propagated_key = item.get("journal_release_key")
    claim_ident = {
        "issueid": item.get("issueid"),
        "comicid": item.get("comicid"),
        "nzbname": item.get("nzb_name"),
    }
    intended_key = propagated_key or journal.derive_release_key(claim_ident)
    controller = MaintenanceController()
    try:
        lease = controller.acquire_lease(
            "postprocess-worker",
            "postprocess",
            entity_type="release",
            entity_id=intended_key,
        )
    except MaintenanceBlocked:
        return "requeue", None

    canonical_release_key = intended_key
    try:
        controller.assert_lease_current(lease)
        item = validate_postprocess_item(item, roots=_configured_postprocess_roots())
        try:
            won = journal.record_transition(
                canonical_release_key,
                journal.POST_PROCESSING,
                payload={
                    "nzb_name": item.get("nzb_name"),
                    "nzb_folder": item.get("nzb_folder"),
                    "failed": item.get("failed"),
                    "issueid": item.get("issueid"),
                    "comicid": item.get("comicid"),
                    "apicall": item.get("apicall"),
                },
                issueid=item.get("issueid"),
            )
        except Exception as e:
            if propagated_key:
                logger.error(
                    "[DOWNLOADS-PP] Durable claim failed for journaled item %s; retaining without side effect: %s"
                    % (canonical_release_key, type(e).__name__)
                )
                return "requeue", None
            logger.error(
                "[DOWNLOADS-PP] Journal unavailable for explicit legacy/manual PP; using legacy status guard: %s"
                % type(e).__name__
            )
            canonical_release_key = None
            won = True

        if won is False:
            logger.info("[DOWNLOADS-PP] Idempotency claim lost for %s; dropping duplicate." % canonical_release_key)
            return "drop", None

        try:
            pprocess = process.Process(
                item["nzb_name"],
                item["nzb_folder"],
                item["failed"],
                item["issueid"],
                item["comicid"],
                item["apicall"],
                item["ddl"],
                item["download_info"],
                journal_release_key=canonical_release_key,
            )
        except (KeyError, TypeError):
            pprocess = process.Process(
                item["nzb_name"],
                item["nzb_folder"],
                item.get("failed", False),
                item.get("issueid"),
                item.get("comicid"),
                item.get("apicall", False),
                journal_release_key=canonical_release_key,
            )
        return "processed", pprocess.post_process()
    except PostProcessCommandError as e:
        _quarantine_postprocess_item(
            item,
            "invalid_postprocess_command:%s" % type(e).__name__,
            release_key=canonical_release_key,
        )
        logger.error("[DOWNLOADS-PP] Command changed after validation; quarantined: %s" % e)
        return "failed", None
    except MaintenanceBlocked:
        return "requeue", None
    except Exception as e:
        _quarantine_postprocess_item(
            item,
            "postprocess_error:%s" % type(e).__name__,
            release_key=canonical_release_key,
        )
        if comicarr.APILOCK.locked():
            try:
                comicarr.APILOCK.release()
            except RuntimeError:
                pass
        logger.error(
            "[DOWNLOADS-PP] Owned post-processing failed; item quarantined: %s: %s\n%s"
            % (type(e).__name__, e, traceback.format_exc())
        )
        return "failed", None
    finally:
        controller.release_lease(lease.lease_id)


def _configured_postprocess_roots():
    return configured_roots()


def _quarantine_postprocess_item(item, reason, release_key=None):
    from comicarr.app.downloads import journal

    if not isinstance(item, dict):
        return False
    key = release_key or item.get("journal_release_key")
    if not key:
        key = journal.derive_release_key(item)
    try:
        return record(
            ManualReview(
                release_key=key,
                reason=reason,
                payload=item,
                issue_id=item.get("issueid"),
            )
        ).transition_won
    except Exception as e:
        logger.error("[DOWNLOADS-PP] Unable to persist quarantine for %s: %s" % (key, type(e).__name__))
        return False


def worker_main(queue):
    import queue as queue_module

    from comicarr.app.acquisition.maintenance import MaintenanceBlocked, MaintenanceController
    from comicarr.app.search.service import torrentinfo

    while True:
        try:
            item = queue.get(timeout=15)
        except queue_module.Empty:
            continue
        if item == "exit":
            logger.info("Cleaning up workers for shutdown")
            break
        controller = MaintenanceController()
        try:
            with controller.lease(
                "torrent-monitor",
                "download-monitor",
                entity_type="release",
                entity_id=item.get("journal_release_key") or item.get("hash"),
            ) as lease:
                controller.assert_lease_current(lease)
                item.pop("_maintenance_retry_attempt", None)
                snstat = torrentinfo(torrent_hash=item["hash"], download=True)
                _handle_torrent_monitor_result(item, snstat)
        except MaintenanceBlocked:
            queue.put(item)
            time.sleep(_maintenance_retry_delay(item))


def _handle_torrent_monitor_result(item, snstat):
    from comicarr.app.downloads import journal

    status = snstat.get("snatch_status")
    if status == "IN PROGRESS":
        logger.info("Torrent is still downloading; scheduling another monitor pass.")
        comicarr.SNATCHED_QUEUE.put(item)
        return

    payload = {
        "issueid": item.get("issueid"),
        "comicid": item.get("comicid"),
        "hash": item.get("hash"),
        "provider": item.get("provider"),
        "nzbname": item.get("nzbname"),
        "apicall": True,
        "ddl": False,
    }
    rkey = item.get("journal_release_key") or journal.release_key(
        item.get("issueid"),
        item.get("provider"),
        nzbname=item.get("nzbname"),
        hash=item.get("hash"),
        discriminant=item.get("nzbname") or payload,
    )

    if status == "NOT FOUND":
        logger.error(
            "[DOWNLOADS-WORKER] torrent hash not found in client for issueid=%s; marking failed." % item.get("issueid")
        )
        try:
            record(
                Failure(
                    release_key=rkey,
                    reason="torrent_hash_not_in_client",
                    payload=payload,
                    issue_id=item.get("issueid"),
                    provider=item.get("provider"),
                    downloader_type="torrent",
                    nzb_name=item.get("nzbname"),
                    download_hash=item.get("hash"),
                    comic_id=item.get("comicid"),
                )
            )
        except Exception as e:
            logger.error(
                "[DOWNLOADS-WORKER] Unable to record failure for %s: %s" % (rkey, type(e).__name__),
            )
        return

    if status not in {"MONITOR FAIL", "MONITOR COMPLETE"}:
        logger.warn("[DOWNLOADS-WORKER] Unhandled torrent monitor status=%s; retaining journal state." % status)
        return

    copied_path = snstat.get("copied_filepath")
    payload.update({"nzb_name": os.path.basename(copied_path or ""), "nzb_folder": copied_path})
    try:
        existing = journal.read_one(rkey)
        downloader_type = (existing or {}).get("downloader_type") or item.get("clientmode") or "torrent"
        won = journal.record_transition(
            rkey,
            journal.DOWNLOADED,
            payload=payload,
            issueid=item.get("issueid"),
            provider=item.get("provider"),
            downloader_type=downloader_type,
            nzbname=item.get("nzbname"),
            hash=item.get("hash"),
        )
    except Exception as e:
        try:
            record(
                ManualReview(
                    release_key=rkey,
                    reason="torrent_artifact_state_persistence_error:%s" % type(e).__name__,
                    payload=payload,
                    issue_id=item.get("issueid"),
                    provider=item.get("provider"),
                    download_hash=item.get("hash"),
                )
            )
            logger.error("[DOWNLOADS-WORKER] Copied torrent artifact quarantined; PP not started.")
        except Exception as quarantine_error:
            logger.error(
                "[DOWNLOADS-WORKER] Unable to quarantine %s after %s; PP not started: %s"
                % (rkey, type(e).__name__, type(quarantine_error).__name__),
            )
        return
    if not won:
        return
    comicarr.PP_QUEUE.put(
        {
            "nzb_name": payload["nzb_name"],
            "nzb_folder": copied_path,
            "failed": False,
            "issueid": item.get("issueid"),
            "comicid": item.get("comicid"),
            "apicall": True,
            "ddl": False,
            "download_info": None,
            "journal_release_key": rkey,
        }
    )


def nzb_monitor(queue):
    from comicarr.app.acquisition.maintenance import MaintenanceBlocked, MaintenanceController

    while True:
        if comicarr.RETURN_THE_NZBQUEUE.qsize() >= 1:
            if comicarr.USE_SABNZBD is True:
                sab_params = {
                    "apikey": comicarr.CONFIG.SAB_APIKEY,
                    "mode": "queue",
                    "start": 0,
                    "limit": 5,
                    "search": None,
                    "output": "json",
                }
                s = sabnzbd.SABnzbd(params=sab_params)
                sabresponse = s.sender(chkstatus=True)
                if sabresponse["status"] is False:
                    while True:
                        if comicarr.RETURN_THE_NZBQUEUE.qsize() >= 1:
                            qu_retrieve = comicarr.RETURN_THE_NZBQUEUE.get(True)
                            try:
                                controller = MaintenanceController()
                                with controller.lease(
                                    "nzb-monitor",
                                    "download-monitor",
                                    entity_type="release",
                                    entity_id=qu_retrieve.get("journal_release_key") or qu_retrieve.get("nzo_id"),
                                ) as lease:
                                    controller.assert_lease_current(lease)
                                    nzstat = s.historycheck(qu_retrieve)
                                    cdh_monitor(queue, qu_retrieve, nzstat, readd=True, lease=lease)
                            except MaintenanceBlocked:
                                comicarr.RETURN_THE_NZBQUEUE.put(qu_retrieve)
                            except Exception as e:
                                logger.error(
                                    "Exception occurred while resuming NZB monitor id=%s: %s"
                                    % (
                                        qu_retrieve.get("nzo_id") or qu_retrieve.get("NZBID"),
                                        type(e).__name__,
                                    )
                                )
                            time.sleep(5)
                        else:
                            break
        if queue.qsize() >= 1:
            item = queue.get(True)
            if item == "exit":
                logger.info("Cleaning up workers for shutdown")
                break
            logger.info("Now monitoring NZB client id=%s" % (item.get("nzo_id") or item.get("NZBID")))
            route = item.get("clientmode")
            controller = MaintenanceController()
            try:
                with controller.lease(
                    "nzb-monitor",
                    "download-monitor",
                    entity_type="release",
                    entity_id=item.get("journal_release_key") or item.get("nzo_id") or item.get("NZBID"),
                ) as lease:
                    controller.assert_lease_current(lease)
                    if route == "sabnzbd" or (not route and comicarr.USE_SABNZBD is True):
                        nz = sabnzbd.SABnzbd(item)
                        nzstat = nz.processor()
                    elif route == "nzbget" or (not route and comicarr.USE_NZBGET is True):
                        nz = nzbget.NZBGet()
                        nzstat = nz.processor(item)
                    else:
                        logger.warn("There is no matching NZB completed-download handler for route=%s." % route)
                        continue
                    cdh_monitor(queue, item, nzstat, lease=lease)
            except MaintenanceBlocked:
                queue.put(item)
                time.sleep(_maintenance_retry_delay(item))
        else:
            time.sleep(5)


def cdh_monitor(queue, item, nzstat, readd=False, lease=None):
    if lease is not None:
        return _cdh_monitor_owned(queue, item, nzstat, readd=readd)

    from comicarr.app.acquisition.maintenance import MaintenanceBlocked, MaintenanceController

    controller = MaintenanceController()
    try:
        with controller.lease(
            "nzb-monitor",
            "download-monitor",
            entity_type="release",
            entity_id=item.get("journal_release_key") or item.get("nzo_id") or item.get("NZBID"),
        ) as owned_lease:
            controller.assert_lease_current(owned_lease)
            return _cdh_monitor_owned(queue, item, nzstat, readd=readd)
    except MaintenanceBlocked:
        queue.put(item)
        return


def _cdh_monitor_owned(queue, item, nzstat, readd=False):
    from comicarr.helpers import check_file_condition

    known_nzb_id = item.get("nzo_id") or item.get("NZBID")
    if any([nzstat["status"] == "file not found", nzstat["status"] == "double-pp"]):
        logger.warn("Unable to complete post-processing call due to not finding file. [%s]" % item)
    elif nzstat["status"] == "nzb removed" or "unhandled status" in str(nzstat["status"]).lower():
        if readd is True:
            logger.warn("NZB seems to have been in a staging process. Will requeue: %s." % known_nzb_id)
            comicarr.RETURN_THE_NZBQUEUE.put(item)
        else:
            logger.warn("NZB seems to have been removed from queue: %s" % known_nzb_id)
    elif nzstat["status"] == "failed_in_sab":
        logger.warn("Failure returned from SAB for %s" % known_nzb_id)
    elif nzstat["status"] == "queue_paused":
        if comicarr.USE_SABNZBD is True:
            comicarr.RETURN_THE_NZBQUEUE.put(item)
    elif nzstat["status"] is False:
        logger.info("Download %s failed. Requeue NZB to check later..." % known_nzb_id)
        time.sleep(5)
        if item not in queue.queue:
            comicarr.NZB_QUEUE.put(item)
    elif nzstat["status"] is True:
        if nzstat["failed"] is False:
            resolved = resolve_completed_download_file(nzstat["location"], nzstat.get("name"))
            if resolved is None:
                logger.warn("Unable to locate completed download file under %s" % nzstat.get("location"))
                nzstat["failed"] = True
            else:
                filecondition = check_file_condition(resolved)
                if not filecondition["status"]:
                    nzstat["failed"] = True
        if nzstat["failed"] is False:
            logger.info("File successfully downloaded - now initiating completed downloading handling.")
        else:
            logger.info("File failed - now initiating completed failed downloading handling.")
        di = nzstat.get("download_info") or {}
        cdh_journal_release_key = None
        try:
            from comicarr.app.downloads import journal

            journal_payload = {
                "issueid": nzstat.get("issueid"),
                "comicid": nzstat.get("comicid"),
                "provider": di.get("provider"),
                "hash": di.get("hash"),
                "nzb_name": nzstat["name"],
                "nzb_folder": nzstat["location"],
                "apicall": nzstat.get("apicall"),
                "failed": nzstat.get("failed"),
                "ddl": False,
                "download_info": nzstat.get("download_info"),
            }
            rkey = item.get("journal_release_key") or journal.release_key(
                nzstat.get("issueid"),
                di.get("provider"),
                nzbname=di.get("nzbname") or nzstat.get("name"),
                hash=di.get("hash"),
                discriminant=di.get("nzbname") or di.get("provider") or journal_payload,
            )
            existing = journal.read_one(rkey)
            downloader_type = (existing or {}).get("downloader_type") or item.get("clientmode") or "nzb"
            won = journal.record_transition(
                rkey,
                journal.DOWNLOADED,
                payload=journal_payload,
                issueid=nzstat.get("issueid"),
                provider=di.get("provider"),
                downloader_type=downloader_type,
                nzbname=di.get("nzbname") or nzstat.get("name"),
                hash=di.get("hash"),
            )
            cdh_journal_release_key = rkey
            logger.fdebug("[DOWNLOADS-CDH] Journaled downloaded for %s" % rkey)
        except Exception as e:
            if item.get("journal_release_key"):
                try:
                    record(
                        ManualReview(
                            release_key=item["journal_release_key"],
                            reason="nzb_artifact_state_persistence_error:%s" % type(e).__name__,
                            payload=journal_payload,
                            issue_id=nzstat.get("issueid"),
                            provider=di.get("provider"),
                        )
                    )
                except Exception:
                    pass
                logger.error("[DOWNLOADS-CDH] Artifact state was not durable; PP not started.")
                return
            logger.error("[DOWNLOADS-CDH] Legacy unjournaled downloaded transition failed: %s" % type(e).__name__)

        if item.get("journal_release_key") and not won:
            return

        try:
            comicarr.PP_QUEUE.put(
                {
                    "nzb_name": nzstat["name"],
                    "nzb_folder": nzstat["location"],
                    "failed": nzstat["failed"],
                    "issueid": nzstat["issueid"],
                    "comicid": nzstat["comicid"],
                    "apicall": nzstat["apicall"],
                    "ddl": False,
                    "download_info": nzstat["download_info"],
                    "journal_release_key": cdh_journal_release_key,
                }
            )
        except Exception as e:
            logger.error("process error: %s" % e)
    return


def lookupthebitches(
    filelist,
    folder,
    nzbname,
    nzbid,
    prov,
    hash,
    pulldate,
    journal_release_key=None,
    journal_managed=False,
):
    from sqlalchemy import select

    from comicarr.app.series.service import listLibrary

    watchlist = listLibrary()
    matchlist = []
    dt = datetime.datetime.strptime(pulldate, "%Y-%m-%d")
    weeknumber = dt.strftime("%U")
    year = dt.strftime("%Y")
    for f in filelist:
        file = re.sub(folder, "", f).strip()
        pp = comicarr.filechecker.FileChecker(justparse=True, file=file)
        parsedinfo = pp.listFiles()
        if parsedinfo["parse_status"] == "success":
            dyncheck = re.sub(r"[\|\s]", "", parsedinfo["dynamic_name"].lower()).strip()
            check = db.select_one(
                select(weekly).where(
                    weekly.c.DynamicName == dyncheck,
                    weekly.c.weeknumber == weeknumber,
                    weekly.c.year == year,
                    weekly.c.STATUS != "Downloaded",
                )
            )
            if check is not None:
                matchlist.append(
                    {
                        "comicname": check["COMIC"],
                        "issue": check["ISSUE"],
                        "comicid": check["ComicID"],
                        "issueid": check["IssueID"],
                        "dynamicname": check["DynamicName"],
                    }
                )

    if len(matchlist) > 0:
        for x in matchlist:
            if all([x["comicid"] not in watchlist, comicarr.CONFIG.PACK_0DAY_WATCHLIST_ONLY is False]):
                oneoff = True
                mode = "pullwant"
            elif all([x["comicid"] not in watchlist, comicarr.CONFIG.PACK_0DAY_WATCHLIST_ONLY is True]):
                continue
            else:
                oneoff = False
                mode = "want"
            comicarr.updater.nzblog(x["issueid"], nzbname, x["comicname"], id=nzbid, prov=prov, oneoff=oneoff)
            comicarr.updater.foundsearch(
                x["comicid"],
                x["issueid"],
                mode=mode,
                provider=prov,
                hash=hash,
                journal_release_key=journal_release_key,
                journal_managed=journal_managed,
            )


magic_numbers = {
    "PDF": bytes([0x25, 0x50, 0x44, 0x46]),
    "ZIP": bytes([0x50, 0x4B, 0x03, 0x04]),
    "RAR": bytes([0x52, 0x61, 0x72, 0x21, 0x1A, 0x07]),
    "7Z": bytes([0x37, 0x7A, 0xBC, 0xAF, 0x27, 0x1C]),
}


def check_file_condition(file_path):
    logger.fdebug(f"Checking file condition of {file_path}")
    max_number_length = max(len(m) for m in magic_numbers.values())
    try:
        with open(file_path, "rb") as file:
            header = file.read(max_number_length)
    except Exception as e:
        logger.error(f"Could not open {file_path} to check for file type")
        return {"status": False, "type": "unknown", "quality": f"Failed to open file to check quality {e}."}

    if header.startswith(magic_numbers["ZIP"]):
        try:
            with zipfile.ZipFile(file_path, mode="r") as zf:
                test_result = zf.testzip()
                if test_result is not None:
                    return {"status": False, "type": "ZIP", "quality": f"CRC error in file {test_result}."}
        except Exception as e:
            return {"status": False, "type": "ZIP", "quality": f"Error processing zip compressed file: {e}."}
        return {"status": True, "type": "ZIP", "quality": "Good condition."}
    elif header.startswith(magic_numbers["RAR"]):
        try:
            with rarfile.RarFile(file_path, mode="r") as rarf:
                test_result = rarf.testrar()
                if test_result is not None:
                    return {"status": False, "type": "RAR", "quality": f"CRC error in file {test_result}."}
        except Exception as e:
            return {"status": False, "type": "RAR", "quality": f"Error processing rar compressed file: {e}."}
        return {"status": True, "type": "RAR", "quality": "Good condition."}
    elif header.startswith(magic_numbers["7Z"]):
        return {"status": True, "type": "7Z", "quality": "File is using 7zip compression."}
    elif header.startswith(magic_numbers["PDF"]):
        return {"status": True, "type": "PDF", "quality": "PDF file.  No quality checks performed."}
    else:
        return {"status": False, "type": "unknown", "quality": "Unknown file type, unknown condition"}
