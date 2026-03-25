#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Series domain service — comic CRUD, issue management, imports.

Module-level functions (not classes) — matches existing codebase style.
"""

import os
import queue
import re
import shutil
import threading

import comicarr
from comicarr import logger
from comicarr.app.series import queries as series_queries

# ---------------------------------------------------------------------------
# Series CRUD
# ---------------------------------------------------------------------------

def list_comics(ctx, limit=None, offset=None):
    """List all comics, optionally with pagination."""
    if limit is not None:
        paginated = series_queries.list_comics_paginated(limit, offset=offset or 0)
        return {
            "comics": paginated["results"],
            "pagination": {
                "total": paginated["total"],
                "limit": paginated["limit"],
                "offset": paginated["offset"],
                "has_more": paginated["has_more"],
            },
        }
    return series_queries.list_comics()


def get_comic_detail(ctx, comic_id):
    """Get a single comic with its issues and annuals."""
    comic = series_queries.get_comic(comic_id)
    issues = series_queries.get_issues(comic_id)

    annuals_on = getattr(ctx.config, "ANNUALS_ON", False) if ctx.config else False
    annuals_list = series_queries.get_annuals(comic_id) if annuals_on else []

    return {"comic": comic, "issues": issues, "annuals": annuals_list}


def add_comic(ctx, comic_id):
    """Add a comic to the watchlist (background thread via WebInterface)."""
    # Strip CV prefix if present
    if comic_id.startswith("4050-"):
        comic_id = re.sub("4050-", "", comic_id).strip()

    from comicarr.webserve import WebInterface
    try:
        ac = WebInterface()
        ac.addbyid(comic_id, calledby=True, nothread=False)
    except Exception as e:
        logger.error("[SERIES] Error adding comic %s: %s" % (comic_id, e))
        return {"success": False, "error": str(e)}

    return {"success": True, "message": "Successfully queued up adding id: %s" % comic_id}


def delete_comic(ctx, comic_id, delete_directory=False):
    """Delete a comic series with optional directory deletion."""
    # Strip CV prefix if present
    if comic_id.startswith("4050-"):
        comic_id = re.sub("4050-", "", comic_id).strip()

    comic = series_queries.get_comic_for_delete(comic_id)
    if not comic:
        return {"success": False, "error": "ComicID %s not found in watchlist" % comic_id}

    logger.fdebug(
        "Deletion request received for %s (%s) [%s]" % (comic["ComicName"], comic["ComicYear"], comic_id)
    )

    try:
        series_queries.delete_comic(comic_id)

        if delete_directory and comic.get("ComicLocation"):
            if os.path.exists(comic["ComicLocation"]):
                shutil.rmtree(comic["ComicLocation"])
                logger.fdebug("[SERIES-DELETE] Comic Location (%s) successfully deleted" % comic["ComicLocation"])
            else:
                logger.fdebug("[SERIES-DELETE] Comic Location (%s) does not exist" % comic["ComicLocation"])

    except Exception as e:
        logger.error("Unable to delete ComicID: %s. Error: %s" % (comic_id, e))
        return {"success": False, "error": "Unable to delete ComicID: %s" % comic_id}

    logger.fdebug(
        "[SERIES-DELETE] Successfully deleted %s (%s) [%s]" % (comic["ComicName"], comic["ComicYear"], comic_id)
    )
    return {
        "success": True,
        "message": "Successfully deleted %s (%s) [%s]" % (comic["ComicName"], comic["ComicYear"], comic_id),
    }


def pause_comic(ctx, comic_id):
    """Set comic status to Paused."""
    series_queries.pause_comic(comic_id)
    return {"success": True}


def resume_comic(ctx, comic_id):
    """Set comic status to Active."""
    series_queries.resume_comic(comic_id)
    return {"success": True}


def refresh_comic(ctx, comic_id):
    """Refresh comic metadata in the background."""
    from comicarr import importer

    # Support comma-separated list of IDs
    id_list = [cid.strip() for cid in comic_id.split(",") if cid.strip()]

    watch = []
    already_added = []
    notfound = []

    for cid in id_list:
        if cid.startswith("4050-"):
            cid = re.sub("4050-", "", cid).strip()

        chkdb = series_queries.get_comic_for_refresh(cid)
        if not chkdb:
            notfound.append({"comicid": cid})
        elif cid in comicarr.REFRESH_QUEUE.queue:
            already_added.append({"comicid": cid, "comicname": chkdb["ComicName"]})
        else:
            watch.append({"comicid": cid, "comicname": chkdb["ComicName"]})

    if notfound:
        return {"success": False, "error": "Unable to locate IDs for Refreshing: %s" % notfound}

    if not watch:
        if already_added:
            return {"success": True, "message": "Already queued for refresh"}
        return {"success": False, "error": "No comics to refresh"}

    try:
        importer.refresh_thread(watch)
    except Exception as e:
        logger.warn("[SERIES-REFRESH] Unable to refresh: %s" % e)
        return {"success": False, "error": "Unable to refresh: %s" % str(e)}

    return {"success": True, "message": "Refresh submitted for %s" % comic_id}


# ---------------------------------------------------------------------------
# Issue management
# ---------------------------------------------------------------------------

def queue_issue(ctx, issue_id):
    """Mark an issue as Wanted and trigger search."""
    from comicarr import search
    series_queries.queue_issue(issue_id)
    search.searchforissue(issue_id)
    return {"success": True}


def unqueue_issue(ctx, issue_id):
    """Mark an issue as Skipped."""
    series_queries.unqueue_issue(issue_id)
    return {"success": True}


def get_wanted(ctx, limit=None, offset=None, include_story_arcs=False):
    """Get all wanted issues, optionally with story arcs and annuals."""
    # Issues
    if limit is not None:
        paginated = series_queries.get_wanted_issues(limit=limit, offset=offset)
        result = {
            "issues": paginated["results"],
            "pagination": {
                "total": paginated["total"],
                "limit": paginated["limit"],
                "offset": paginated["offset"],
                "has_more": paginated["has_more"],
            },
        }
    else:
        result = {"issues": series_queries.get_wanted_issues()}

    # Story arcs
    if include_story_arcs:
        upcoming_storyarcs = getattr(ctx.config, "UPCOMING_STORYARCS", False) if ctx.config else False
        if upcoming_storyarcs:
            result["story_arcs"] = series_queries.get_wanted_storyarc_issues()

    # Annuals
    annuals_on = getattr(ctx.config, "ANNUALS_ON", False) if ctx.config else False
    if annuals_on:
        result["annuals"] = series_queries.get_wanted_annuals()

    return result


# ---------------------------------------------------------------------------
# Import management
# ---------------------------------------------------------------------------

def get_import_pending(ctx, limit=50, offset=0, include_ignored=False):
    """Get pending import files grouped by DynamicName/Volume."""
    return series_queries.get_import_pending(limit=limit, offset=offset, include_ignored=include_ignored)


def match_import(ctx, imp_ids, comic_id, issue_id=None):
    """Manually match import files to a comic series."""
    comic_name = series_queries.get_comic_name(comic_id) or "Unknown"

    matched = 0
    for imp_id in imp_ids:
        imp_id = imp_id.strip()
        if not imp_id:
            continue
        series_queries.match_import(imp_id, comic_id, comic_name, issue_id=issue_id)
        matched += 1

    return {"matched": matched, "comic_id": comic_id, "comic_name": comic_name}


def ignore_import(ctx, imp_ids, ignore=True):
    """Mark import files as ignored or unignored."""
    updated = 0
    for imp_id in imp_ids:
        imp_id = imp_id.strip()
        if not imp_id:
            continue
        series_queries.ignore_import(imp_id, ignore=ignore)
        updated += 1

    return {"updated": updated, "ignored": ignore}


def delete_import(ctx, imp_ids):
    """Delete import records."""
    deleted = 0
    for imp_id in imp_ids:
        imp_id = imp_id.strip()
        if not imp_id:
            continue
        series_queries.delete_import(imp_id)
        deleted += 1

    return {"deleted": deleted}


def refresh_import(ctx):
    """Trigger an import directory scan in the background."""
    from comicarr import librarysync

    import_dir = getattr(comicarr.CONFIG, "IMPORT_DIR", None) if comicarr.CONFIG else None
    if not import_dir:
        return {"success": False, "error": "Import directory not configured"}

    try:
        logger.info("[SERIES-IMPORT] Starting import directory scan for: %s" % import_dir)
        import_queue = queue.Queue()
        threading.Thread(
            target=librarysync.scanLibrary, name="API-ImportScan", args=[import_dir, import_queue]
        ).start()
        return {"success": True, "message": "Import scan started for: %s" % import_dir}
    except Exception as e:
        logger.error("[SERIES-IMPORT] Error: %s" % e)
        return {"success": False, "error": "Failed to start import scan: %s" % str(e)}
