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
    """Hand a DDL command to the in-memory worker queue with process-local dedupe."""
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
    """Replay the durable Queued outbox before the DDL worker starts."""
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
    """Validate, persist, and queue a complete direct-download command."""
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
    """Resolve the on-disk file path for an issue."""
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


# --- Extracted from helpers.py ---


def rename_param(comicid, comicname, issue, ofilename, comicyear=None, issueid=None, annualize=None, arc=False):
    from sqlalchemy import select

    from comicarr.helpers import filesafe, fullmonth, issuedigits, replace_all

    comicid = str(comicid)

    logger.fdebug(type(comicid))
    lo