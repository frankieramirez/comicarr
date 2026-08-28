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


# ---------------------------------------------------------------------------
# Download history
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


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
        # ComicRN/APC compatibility mode — direct processing
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

    # Standard mode — queue for background processing
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


# ---------------------------------------------------------------------------
# Needs-attention compatibility adapters
# ---------------------------------------------------------------------------

# Deprecated public alias retained for callers during the route migration.
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
        # Pre-refactor, any post-queue search failure — blocked or not — carried
        # the row identity plus ``stamped: False``, while the precheck block did
        # not. Both surface as ``search_blocked``; ``stamp_written is False`` is
        # what separates "we re-wanted the issue and left it unstamped" from
        # "we stopped before touching the row".
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


# ---------------------------------------------------------------------------
# DDL queue management
# ---------------------------------------------------------------------------


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
                # Already handed to this process's worker/queue — durable row
                # remains Queued/Downloading under the existing owner.
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
    # Only a terminal failure can be manually retried. Queued rows belong to
    # the durable outbox/recovery worker; accepting them here would allow two
    # concurrent requests to enqueue the same external download.
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
            # Durable row is already owned by this process's worker/queue.
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

    # Check secondary destination directories
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


# --- Extracted from helpers.py ---


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
        # A numberless complete-series pack ("Solo Leveling (2021-2026)")
        # carries no range to expand: it claims every row of the series
        # that is not already Downloaded, volume and chapter rows alike —
        # except rows published after the pack's own year span, which the
        # pack cannot contain (span_end from parse_series_pack_title).
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
            write_valids.append({"issueid": xb["IssueID"], "pack_id"