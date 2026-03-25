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

import comicarr
from comicarr import logger
from comicarr.app.downloads import queries as dl_queries

# ---------------------------------------------------------------------------
# Download history
# ---------------------------------------------------------------------------

def get_history(ctx, limit=None, offset=None):
    """Get download history, optionally paginated."""
    if limit is not None:
        paginated = dl_queries.get_history(limit=limit, offset=offset)
        return {
            "history": paginated["results"],
            "pagination": {
                "total": paginated["total"],
                "limit": paginated["limit"],
                "offset": paginated["offset"],
                "has_more": paginated["has_more"],
            },
        }
    return dl_queries.get_history()


def clear_history(ctx, status_type=None):
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

def force_process(ctx, nzb_name, nzb_folder, failed=False, issueid=None,
                  comicid=None, ddl=False, oneoff=False,
                  apc_version=None, comicrn_version=None):
    """Queue a download for post-processing.

    For standard API calls, queues to PP_QUEUE for background processing.
    For ComicRN/APC compatibility, calls WebInterface.post_process directly.
    """
    if apc_version is not None:
        # ComicRN/APC compatibility mode — direct processing
        logger.info("[API] Api Call from ComicRN detected - initiating script post-processing.")
        from comicarr.webserve import WebInterface
        fp = WebInterface()
        result = fp.post_process(
            nzb_name, nzb_folder,
            failed=failed,
            apc_version=apc_version,
            comicrn_version=comicrn_version,
        )
        return {"success": True, "data": result}

    # Standard mode — queue for background processing
    logger.info(
        "Received API Request for PostProcessing %s [%s]. Queueing..." % (nzb_name, nzb_folder)
    )
    comicarr.PP_QUEUE.put({
        "nzb_name": nzb_name,
        "nzb_folder": nzb_folder,
        "issueid": issueid,
        "failed": failed,
        "oneoff": oneoff,
        "comicid": comicid,
        "apicall": True,
        "ddl": ddl,
    })
    return {"success": True, "message": "Successfully submitted request for post-processing for %s" % nzb_name}


def process_issue(ctx, comicid, folder, issueid=None):
    """Post-process a specific issue."""
    from comicarr import process
    try:
        fp = process.Process(comicid, folder, issueid)
        result = fp.post_process()
        return {"success": True, "data": result}
    except Exception as e:
        logger.error("[DOWNLOADS] Error processing issue: %s" % e)
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# DDL queue management
# ---------------------------------------------------------------------------

def get_ddl_queue(ctx):
    """Get current DDL download queue."""
    return dl_queries.get_ddl_queue()


def delete_ddl_item(ctx, item_id):
    """Remove an item from the DDL queue."""
    dl_queries.delete_ddl_item(item_id)
    logger.info("[DOWNLOADS] Removed DDL item: %s" % item_id)
    return {"success": True}


def requeue_ddl_item(ctx, item_id):
    """Requeue a failed DDL download."""
    item = dl_queries.get_ddl_item(item_id)
    if not item:
        return {"success": False, "error": "DDL item not found: %s" % item_id}

    dl_queries.update_ddl_status(item_id, "Queued")
    logger.info("[DOWNLOADS] Requeued DDL item: %s" % item_id)
    return {"success": True}
