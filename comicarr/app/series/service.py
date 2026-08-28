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

import datetime
import os
import re
import shutil
import threading
from collections.abc import Mapping

import sqlalchemy

import comicarr
from comicarr import db, logger, series_kind
from comicarr.app.acquisition.evidence import has_verified_library_file
from comicarr.app.acquisition.models import AcquisitionIntent, Fulfillment
from comicarr.app.acquisition.policy import EligibilityInput, evaluate_eligibility, project_legacy_state
from comicarr.app.common.filesystem import is_path_within_allowed_dirs
from comicarr.app.core.workers import start_background_thread
from comicarr.app.series import queries as series_queries
from comicarr.tables import annuals, comics, issues, oneoffhistory, storyarcs, weekly

_LIBRARY_ROOT_CONFIG_KEYS = (
    "DESTINATION_DIR",
    "MANGA_DESTINATION_DIR",
    "COMIC_DIR",
    "MANGA_DIR",
    "MULTIPLE_DEST_DIRS",
    "NEWCOM_DIR",
)

_COMIC_SCAN_START_LOCK = threading.Lock()
_MANGA_SCAN_START_LOCK = threading.Lock()

_DISPLAY_BY_FULFILLMENT = {
    Fulfillment.RESERVED: "Reserved",
    Fulfillment.SNATCHED: "Snatched",
    Fulfillment.DOWNLOADED: "Downloaded",
    Fulfillment.ARCHIVED: "Archived",
    Fulfillment.FAILED: "Failed",
    Fulfillment.COVERED: "Covered",
}
_DISPLAY_BY_INTENT = {
    AcquisitionIntent.WANTED: "Wanted",
    AcquisitionIntent.SKIPPED: "Skipped",
    AcquisitionIntent.IGNORED: "Ignored",
}
_DATE_SOURCE_NAMES = {
    "release_date": "releaseDate",
    "digital_date": "digitalDate",
    "issue_date": "issueDate",
}


def _row_value(row, *keys):
    for key in keys:
        if key in row:
            return row[key]
    return None


def _optional_text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value and value.lower() != "none" else None


def _display_state(projection, *, eligibility_reason=None):
    if projection.fulfillment in _DISPLAY_BY_FULFILLMENT:
        return _DISPLAY_BY_FULFILLMENT[projection.fulfillment]
    if projection.intent in _DISPLAY_BY_INTENT:
        return _DISPLAY_BY_INTENT[projection.intent]
    if projection.fulfillment is Fulfillment.MISSING:
        if eligibility_reason == "future":
            return "Skipped"
        return "Missing"
    return "Unknown"


def project_issue_state(row, *, series_status, today=None, annual=False, series_location=None):
    """Return one canonical intent, fulfillment, eligibility, and UI projection."""
    values = dict(row)
    legacy_status = _row_value(values, "status", "Status")
    acquisition_intent = _row_value(values, "acquisitionIntent", "AcquisitionIntent")
    projection = project_legacy_state(acquisition_intent, legacy_status)
    location = _optional_text(_row_value(values, "location", "Location"))

    fulfillment = projection.fulfillment
    verified_file = has_verified_library_file(series_location, location)
    if verified_file and fulfillment is not Fulfillment.ARCHIVED:
        fulfillment = Fulfillment.DOWNLOADED
        evidence = "verified_location"
    elif fulfillment is Fulfillment.DOWNLOADED:
        fulfillment = Fulfillment.UNKNOWN
        evidence = "unverified_downloaded"
    elif legacy_status is not None and str(legacy_status).strip():
        evidence = "legacy_status"
    else:
        evidence = "none"

    normalized_series_status = str(series_status or "").strip().lower()
    decision = evaluate_eligibility(
        EligibilityInput(
            series_active=normalized_series_status in {"active", "loading", "paused"},
            paused=normalized_series_status == "paused",
            intent=projection.intent,
            fulfillment=fulfillment,
            release_date=_row_value(values, "releaseDate", "ReleaseDate"),
            digital_date=_row_value(values, "digitalDate", "DigitalDate"),
            issue_date=_row_value(values, "issueDate", "IssueDate"),
        ),
        today=today,
    )
    display_state = _display_state(
        projection.__class__(projection.intent, fulfillment, projection.intent_is_explicit),
        eligibility_reason=decision.reason,
    )
    owned = fulfillment.is_owned
    in_flight = fulfillment.is_in_flight
    covered = fulfillment is Fulfillment.COVERED
    missing = not owned and not in_flight and not covered
    monitored = projection.intent not in {AcquisitionIntent.SKIPPED, AcquisitionIntent.IGNORED}
    selected_date = decision.selected_date.isoformat() if decision.selected_date else None
    date_source = _DATE_SOURCE_NAMES.get(decision.date_source, decision.date_source)

    values.update(
        {
            "legacyStatus": legacy_status,
            "rawAcquisitionIntent": acquisition_intent,
            "acquisitionIntent": projection.intent.value,
            "intentExplicit": projection.intent_is_explicit,
            "fulfillment": fulfillment.value,
            "fulfillmentEvidence": evidence,
            "displayState": display_state,
            "eligible": decision.eligible,
            "eligibilityReason": decision.reason,
            "eligibilityDate": selected_date,
            "eligibilityDateSource": date_source,
            "eligibility": {
                "eligible": decision.eligible,
                "reason": decision.reason,
                "date": selected_date,
                "source": date_source,
            },
            "owned": owned,
            "covered": covered,
            "physicalOwned": bool(verified_file),
            "archived": fulfillment is Fulfillment.ARCHIVED,
            "inFlight": in_flight,
            "missing": missing,
            "monitored": monitored,
            "future": decision.reason == "future",
            "deferred": missing and not decision.eligible,
            "annual": bool(annual),
        }
    )
    return values


def _issue_summary(projected):
    total = len(projected)
    owned = sum(bool(row["owned"]) for row in projected)
    return {
        "total": total,
        "issues": sum(not row["annual"] for row in projected),
        "annuals": sum(bool(row["annual"]) for row in projected),
        "owned": owned,
        "covered": sum(bool(row.get("covered")) for row in projected),
        "physicalOwned": sum(bool(row["physicalOwned"]) for row in projected),
        "archived": sum(bool(row["archived"]) for row in projected),
        "inFlight": sum(bool(row["inFlight"]) for row in projected),
        "missing": sum(bool(row["missing"]) for row in projected),
        "monitored": sum(bool(row["monitored"]) for row in projected),
        "wanted": sum(row["displayState"] == "Wanted" for row in projected),
        "skipped": sum(row["acquisitionIntent"] == AcquisitionIntent.SKIPPED.value for row in projected),
        "ignored": sum(row["acquisitionIntent"] == AcquisitionIntent.IGNORED.value for row in projected),
        "failed": sum(row["fulfillment"] == Fulfillment.FAILED.value for row in projected),
        "unknown": sum(row["fulfillment"] == Fulfillment.UNKNOWN.value for row in projected),
        "future": sum(bool(row["future"]) for row in projected),
        "eligible": sum(bool(row["eligible"]) for row in projected),
        "deferred": sum(bool(row["deferred"]) for row in projected),
        "completionPercent": round((owned / total) * 100) if total else 0,
    }


def project_issue_collection(rows, *, series_status, today=None, annual=False, series_location=None):
    """Project a homogeneous issue collection and its internally consistent summary."""
    projected = [
        project_issue_state(
            row,
            series_status=series_status,
            today=today,
            annual=annual,
            series_location=series_location,
        )
        for row in rows
    ]
    return projected, _issue_summary(projected)


def _start_library_scan(scanner, status_attr, worker, start_lock, scan_label, scan_dir, thread_name, registry):
    """Reserve and launch a scanner without allowing a second hand-off worker."""
    with start_lock:
        if getattr(scanner, status_attr) == "scanning" or scanner._SCAN_LOCK.locked():
            return {"success": False, "error": "A library scan is already in progress"}

        previous_status = getattr(scanner, status_attr)
        setattr(scanner, status_attr, "scanning")
        try:
            logger.info("[%s-SCAN] Starting %s library scan for: %s" % (scan_label.upper(), scan_label, scan_dir))
            start_background_thread(worker, name=thread_name, registry=registry)
            return {"success": True, "message": "%s scan started for: %s" % (scan_label.capitalize(), scan_dir)}
        except Exception as e:
            setattr(scanner, status_attr, previous_status)
            logger.error("[%s-SCAN] Error: %s" % (scan_label.upper(), e))
            return {"success": False, "error": "Failed to start %s scan: %s" % (scan_label, str(e))}


def _configured_library_roots(config):
    """Return explicit, non-empty roots that can contain series directories."""
    if config is None:
        return []

    roots = []
    for key in _LIBRARY_ROOT_CONFIG_KEYS:
        root = getattr(config, key, None)
        if not isinstance(root, str):
            continue
        root = root.strip()
        if root and root.lower() != "none":
            roots.append(root)
    return roots


def _is_strict_library_descendant(path, config):
    """Require path to resolve below, but never equal, a configured root."""
    if not isinstance(path, (str, os.PathLike)):
        return False

    roots = _configured_library_roots(config)
    if not roots:
        return False

    try:
        return is_path_within_allowed_dirs(path, roots, strict=True)
    except (OSError, TypeError, ValueError):
        return False


def _remove_comic_location(comic_location):
    """Remove a validated ComicLocation without following directory symlinks.

    Symlinks and regular files are unlinked in place. Real directories use
    rmtree. Other special nodes are skipped so DB cleanup can still proceed.
    """
    if os.path.islink(comic_location) or os.path.isfile(comic_location):
        os.unlink(comic_location)
        return "unlinked"
    if os.path.isdir(comic_location):
        shutil.rmtree(comic_location)
        return "removed"
    return "skipped"


def list_comics(ctx, limit=None, offset=None):
    """List all comics, optionally with pagination."""
    if limit is not None:
        paginated = series_queries.list_comics_paginated(limit, offset=offset or 0)
        return {
            "comics": [series_queries.with_library_cover_src(row) for row in paginated["results"]],
            "pagination": {
                "total": paginated["total"],
                "limit": paginated["limit"],
                "offset": paginated["offset"],
                "has_more": paginated["has_more"],
            },
        }
    return [series_queries.with_library_cover_src(row) for row in series_queries.list_comics()]


def get_comic_detail(ctx, comic_id):
    """Get a single comic with its issues and annuals."""
    comic = [series_queries.with_library_cover_src(row) for row in series_queries.get_comic(comic_id)]
    issue_rows = series_queries.get_issues(comic_id)

    annuals_on = getattr(ctx.config, "ANNUALS_ON", False) if ctx.config else False
    annual_rows = series_queries.get_annuals(comic_id) if annuals_on else []
    series_status = comic[0].get("Status") if comic else None
    series_location = comic[0].get("ComicLocation") if comic else None
    projected_issues, _ = project_issue_collection(
        issue_rows,
        series_status=series_status,
        series_location=series_location,
    )
    projected_annuals, _ = project_issue_collection(
        annual_rows,
        series_status=series_status,
        annual=True,
        series_location=series_location,
    )
    summary = _issue_summary(projected_issues + projected_annuals)
    comic_row = comic[0] if comic else None

    return {
        "comic": comic,
        "issues": projected_issues,
        "annuals": projected_annuals,
        "summary": summary,
        "providerLinks": series_kind.provider_page_links(comic_row) if comic_row else [],
    }


def add_comic(ctx, comic_id):
    """Add a comic to the watchlist (background thread via importer)."""
    if comic_id.startswith("4050-"):
        comic_id = re.sub("4050-", "", comic_id).strip()

    from comicarr import importer

    try:
        watch = [{"comicid": comic_id, "comicname": None, "seriesyear": None}]
        importer.importer_thread(watch)
    except Exception as e:
        logger.error("[SERIES] Error adding comic %s: %s" % (comic_id, e))
        return {"success": False, "error": str(e)}

    return {"success": True, "message": "Successfully queued up adding id: %s" % comic_id}


def delete_comic(ctx, comic_id, delete_directory=False):
    """Delete a comic series with optional directory deletion."""
    if comic_id.startswith("4050-"):
        comic_id = re.sub("4050-", "", comic_id).strip()

    comic = series_queries.get_comic_for_delete(comic_id)
    if not comic:
        return {"success": False, "error": "ComicID %s not found in watchlist" % comic_id}

    logger.fdebug("Deletion request received for %s (%s) [%s]" % (comic["ComicName"], comic["ComicYear"], comic_id))

    try:
        if delete_directory and comic.get("ComicLocation"):
            comic_location = comic["ComicLocation"]
            if not _is_strict_library_descendant(comic_location, ctx.config):
                logger.error(
                    "[SERIES-DELETE] Refusing to delete Comic Location (%s): "
                    "not a strict descendant of a configured library root" % comic_location
                )
                return {
                    "success": False,
                    "error": "Unable to safely delete the directory for ComicID: %s" % comic_id,
                }

            if os.path.lexists(comic_location):
                action = _remove_comic_location(comic_location)
                if action == "skipped":
                    logger.fdebug(
                        "[SERIES-DELETE] Comic Location (%s) is not a regular file, "
                        "symlink, or directory; skipping filesystem removal" % comic_location
                    )
                else:
                    logger.fdebug("[SERIES-DELETE] Comic Location (%s) successfully %s" % (comic_location, action))
            else:
                logger.fdebug("[SERIES-DELETE] Comic Location (%s) does not exist" % comic_location)

        series_queries.delete_comic(comic_id)

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


def update_search_settings(
    ctx,
    comic_id,
    allow_packs=None,
    ignore_type=None,
    bare_number_mode=None,
    monitor_mode=None,
):
    """Update the per-series search flags (#633, #689, #691).

    ``allow_packs`` gates pack/bundle release matching; ``ignore_type`` lets
    results through the booktype-mismatch check in search_filer.
    ``bare_number_mode`` is volumes/chapters/auto; ``monitor_mode`` is
    blended/volumes/chapters. Omitted fields are left untouched.
    """
    from comicarr.app.manga.acquisition import MONITOR_MODES, normalize_monitor_mode
    from comicarr.app.manga.bare_numbers import MODES as BARE_MODES
    from comicarr.app.manga.bare_numbers import normalize_mode

    existing = series_queries.get_comic_search_settings(comic_id)
    if not existing:
        return {"success": False, "error": "ComicID %s not found in watchlist" % comic_id}

    values = {}
    if allow_packs is not None:
        values["AllowPacks"] = "1" if allow_packs else "0"
    if ignore_type is not None:
        values["IgnoreType"] = 1 if ignore_type else 0
    if bare_number_mode is not None:
        if str(bare_number_mode).strip().lower() not in BARE_MODES:
            return {"success": False, "error": "bare_number_mode must be auto, volumes, or chapters"}
        values["BareNumberMode"] = normalize_mode(bare_number_mode)
    if monitor_mode is not None:
        if str(monitor_mode).strip().lower() not in MONITOR_MODES:
            return {"success": False, "error": "monitor_mode must be blended, volumes, or chapters"}
        values["MonitorMode"] = normalize_monitor_mode(monitor_mode)

    if not values:
        return {"success": False, "error": "No search settings provided"}

    series_queries.update_comic_search_settings(comic_id, values)
    logger.fdebug("[SERIES] Updated search settings for %s: %s" % (comic_id, values))
    updated = series_queries.get_comic_search_settings(comic_id)
    return {
        "success": True,
        "settings": {
            "allow_packs": updated["AllowPacks"] in (1, "1"),
            "ignore_type": bool(updated["IgnoreType"]),
            "bare_number_mode": normalize_mode(updated.get("BareNumberMode")),
            "monitor_mode": normalize_monitor_mode(updated.get("MonitorMode")),
        },
    }


def update_content_kind(ctx, comic_id, content_type):
    """Persist an operator-controlled comic-or-manga classification.

    Content kind is deliberately independent of provider identity and legacy
    publication ``Type``. This write therefore touches only ``ContentType``;
    provider metadata and issue/annual rows remain unchanged.
    """
    if content_type not in ("comic", "manga"):
        return {"success": False, "error": "Content kind must be comic or manga"}

    existing = series_queries.get_comic_content_kind(comic_id)
    if not existing:
        return {"success": False, "error": "ComicID %s not found in watchlist" % comic_id}

    series_queries.update_comic_content_kind(comic_id, content_type)
    updated = series_queries.get_comic_content_kind(comic_id)
    canonical = updated["ContentType"] if updated else content_type
    logger.fdebug("[SERIES] Updated content kind for %s: %s" % (comic_id, canonical))
    return {"success": True, "content_type": canonical}


def pause_comic(ctx, comic_id):
    """Set comic status to Paused."""
    series_queries.pause_comic(comic_id)
    return {"success": True}


def resume_comic(ctx, comic_id):
    """Set comic status to Active."""
    series_queries.resume_comic(comic_id)
    return {"success": True}


def _refresh_queue_contains(comic_id):
    refresh_queue = comicarr.REFRESH_QUEUE
    mutex = getattr(refresh_queue, "mutex", None)
    if mutex is not None:
        with mutex:
            pending = list(refresh_queue.queue)
    else:
        pending = list(getattr(refresh_queue, "queue", ()))

    expected = str(comic_id)
    for item in pending:
        if isinstance(item, Mapping):
            values = {str(key).lower(): value for key, value in item.items()}
            if str(values.get("comicid")) == expected:
                return True
        elif str(item) == expected:
            return True
    return False


def refresh_comic(ctx, comic_id):
    """Refresh comic metadata in the background."""
    from comicarr import importer

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
        elif _refresh_queue_contains(cid):
            already_added.append({"comicid": cid, "comicname": chkdb["ComicName"]})
        else:
            watch.append(
                {
                    "comicid": cid,
                    "comicname": chkdb["ComicName"],
                    "seriesyear": chkdb["ComicYear"],
                }
            )

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


def queue_issue(ctx, issue_id, audit_identity):
    """Mark an issue as Wanted and trigger search."""
    from comicarr.app.search.commands import enqueue_search_command

    series_queries.queue_issue(issue_id, audit_identity)
    command = enqueue_search_command({"issueid": issue_id}, trigger="issue_wanted")
    return {"success": True, "run_id": command.run_id}


def unqueue_issue(ctx, issue_id, audit_identity):
    """Mark an issue as Skipped."""
    series_queries.unqueue_issue(issue_id, audit_identity)
    return {"success": True}


def _wanted_issue_selection(issue_id):
    row = db.select_one(sqlalchemy.select(issues).where(issues.c.IssueID == issue_id))
    if row is None or row.get("Status") != "Wanted":
        return None, {"success": False, "error": "Wanted issue not found", "status_code": 404}
    return [
        {
            "entity_type": "issue",
            "entity_id": str(row["IssueID"]),
            "issue_number": row.get("Issue_Number"),
            "source": {
                "status": row.get("Status"),
                "intent": row.get("AcquisitionIntent"),
                "location": row.get("Location"),
                "release_date": row.get("ReleaseDate"),
                "digital_date": row.get("DigitalDate"),
                "issue_date": row.get("IssueDate"),
            },
        }
    ], {"success": True, "comicId": str(row["ComicID"]), "issueId": str(row["IssueID"])}


def preview_wanted_issue(issue_id, *, actor, session_id):
    """Mint a session-bound, one-item preview for an already Wanted issue."""
    selection, result = _wanted_issue_selection(issue_id)
    if not result["success"]:
        return result
    from comicarr.app.search.bulk import create_preview

    result.update(
        create_preview(
            db.get_engine(),
            series_id=result["comicId"],
            actor=actor,
            session_id=session_id,
            selection=selection,
        )
    )
    return result


def search_wanted_issue(issue_id, audit_identity, *, preview_token, fingerprint, session_id):
    """Confirm exactly one Wanted item through the durable search ledger."""
    if not preview_token or not fingerprint or not session_id:
        return {"success": False, "error": "a current Wanted issue preview is required", "status_code": 400}

    from comicarr.app.search.bulk import SearchMissingConfirmationError, SearchMissingStalePreview, confirm_preview

    selection, preview = _wanted_issue_selection(issue_id)
    if not preview["success"]:
        return preview
    try:
        result = confirm_preview(
            db.get_engine(),
            series_id=preview["comicId"],
            actor=audit_identity,
            session_id=session_id,
            preview_token=preview_token,
            supplied_fingerprint=fingerprint,
            current_selection=selection,
            trigger="issue_wanted",
            scope_type="issue",
            scope_id=issue_id,
        )
    except SearchMissingStalePreview as e:
        return {"success": False, "status": "stale_preview", "error": str(e), "status_code": 409}
    except SearchMissingConfirmationError as e:
        return {"success": False, "status": "invalid_preview", "error": str(e), "status_code": 409}
    return {
        "success": True,
        "status": "accepted" if not result["dispatch_error"] else "pending_dispatch",
        "accepted": result["accepted"],
        "run_id": result["run_id"],
        "idempotent": result["idempotent"],
        "message": "Queued one Wanted issue for search",
    }


def _search_missing_preview_state(ctx, comic_id):
    """Build the current public preview and private CAS selection once."""
    detail = get_comic_detail(ctx, comic_id)
    comic_rows = detail.get("comic") or []
    comic = comic_rows[0] if isinstance(comic_rows, list) and comic_rows else comic_rows
    if not comic:
        return None, {"success": False, "error": "Series not found", "status_code": 404}

    def _issue_id(row):
        return row.get("id") or row.get("issueId") or row.get("IssueID")

    def _issue_number(row):
        return row.get("number") or row.get("issueNumber") or row.get("Issue_Number")

    rows = list(detail.get("issues") or []) + list(detail.get("annuals") or [])
    eligible = [row for row in rows if row.get("eligible") and not row.get("owned") and not row.get("inFlight")]
    excluded = []
    for row in rows:
        if row in eligible:
            continue
        reason = row.get("eligibilityReason") or ("owned" if row.get("owned") else "excluded")
        if row.get("owned"):
            reason = "owned"
        elif row.get("inFlight"):
            reason = "in_flight"
        elif row.get("acquisitionIntent") == AcquisitionIntent.SKIPPED.value:
            reason = "explicit_skip"
        elif row.get("acquisitionIntent") == AcquisitionIntent.IGNORED.value:
            reason = "explicit_ignore"
        elif row.get("future"):
            reason = "future"
        excluded.append(
            {
                "issueId": _issue_id(row),
                "issueNumber": _issue_number(row),
                "reason": reason,
                "displayState": row.get("displayState"),
            }
        )

    route = {"viable": True, "reason": None}
    try:
        from comicarr.app.search.health import blocking_route_reason, get_search_health

        health = get_search_health(
            ctx.config,
            provider_blocklist=getattr(ctx, "provider_blocklist", None) or comicarr.PROVIDER_BLOCKLIST,
        )
        routes = health.get("routes") or {}
        viable = bool(health.get("viable_route")) or any(
            bool((routes.get(name) or {}).get("ready") or (routes.get(name) or {}).get("viable"))
            for name in ("ddl", "nzb", "torrent")
        )
        if not viable:
            route = {"viable": False, "reason": blocking_route_reason(routes)}
    except Exception as e:
        logger.warn("[SERIES] Route readiness unavailable for bulk search preview: %s" % e)
        route = {"viable": False, "reason": "route_health_unavailable"}

    from comicarr.app.search.bulk import selection_from_detail

    summary = detail.get("summary") or {}
    return selection_from_detail(detail), {
        "success": True,
        "comicId": comic_id,
        "eligibleCount": len(eligible),
        "excludedCount": len(excluded),
        "eligible": [
            {
                "issueId": _issue_id(row),
                "issueNumber": _issue_number(row),
                "entityType": "annual" if row.get("annual") else "issue",
                "displayState": row.get("displayState"),
                "eligibilityReason": row.get("eligibilityReason"),
            }
            for row in eligible
        ],
        "excluded": excluded,
        "route": route,
        "summary": summary,
        "canSearch": bool(eligible) and bool(route.get("viable")),
    }


def preview_search_all_missing(ctx, comic_id, *, actor=None, session_id=None):
    """Preview eligible work and, for browsers, mint a one-shot confirm token."""
    selection, preview = _search_missing_preview_state(ctx, comic_id)
    if not preview.get("success"):
        return preview
    if actor is not None or session_id is not None:
        if not actor or not session_id:
            return {
                "success": False,
                "error": "authenticated session is required for bulk search preview",
                "status_code": 401,
            }
        if selection:
            from comicarr.app.search.bulk import create_preview

            preview.update(
                create_preview(
                    db.get_engine(),
                    series_id=comic_id,
                    actor=actor,
                    session_id=session_id,
                    selection=selection,
                )
            )
    return preview


def search_all_missing(
    ctx,
    comic_id,
    audit_identity,
    *,
    confirm=False,
    preview_token=None,
    fingerprint=None,
    session_id=None,
):
    """Create one durable, session-bound series search from a fresh preview."""
    if not confirm:
        return {"success": False, "error": "explicit confirmation is required", "status_code": 400}
    if not preview_token or not fingerprint or not session_id:
        return {
            "success": False,
            "error": "a current bulk search preview token is required",
            "status_code": 400,
        }

    from comicarr.app.search.bulk import (
        SearchMissingConfirmationError,
        SearchMissingStalePreview,
        confirm_preview,
        read_preview,
    )

    try:
        stored_preview = read_preview(
            db.get_engine(),
            actor=audit_identity,
            session_id=session_id,
            preview_token=preview_token,
            supplied_fingerprint=fingerprint,
        )
        if stored_preview["series_id"] != str(comic_id):
            raise SearchMissingConfirmationError("bulk search preview belongs to a different series")
    except SearchMissingConfirmationError as e:
        return {
            "success": False,
            "status": "invalid_preview",
            "error": str(e),
            "status_code": 409,
        }

    selection, preview = _search_missing_preview_state(ctx, comic_id)
    if not preview.get("success"):
        return preview

    if stored_preview["state"] == "accepted":
        try:
            result = confirm_preview(
                db.get_engine(),
                series_id=comic_id,
                actor=audit_identity,
                session_id=session_id,
                preview_token=preview_token,
                supplied_fingerprint=fingerprint,
                current_selection=selection,
            )
        except SearchMissingConfirmationError as e:
            return {
                "success": False,
                "status": "invalid_preview",
                "error": str(e),
                "status_code": 409,
            }
        return {
            "success": True,
            "status": "accepted" if not result["dispatch_error"] else "pending_dispatch",
            "accepted": result["accepted"],
            "rejected": preview.get("excludedCount") or 0,
            "run_id": result["run_id"],
            "idempotent": True,
            "message": (
                "Queued %s missing issue(s) for search" % result["accepted"]
                if not result["dispatch_error"]
                else "Search is durable but waiting for queue handoff retry"
            ),
            "preview": preview,
        }

    if not preview.get("route", {}).get("viable"):
        return {
            "success": False,
            "error": preview.get("route", {}).get("reason") or "no_viable_acquisition_route",
            "status": "blocked",
            "status_code": 409,
            "preview": preview,
        }
    if not selection:
        return {
            "success": True,
            "status": "noop",
            "accepted": 0,
            "rejected": preview.get("excludedCount") or 0,
            "run_id": None,
            "message": "No eligible missing issues to search",
            "preview": preview,
        }

    try:
        result = confirm_preview(
            db.get_engine(),
            series_id=comic_id,
            actor=audit_identity,
            session_id=session_id,
            preview_token=preview_token,
            supplied_fingerprint=fingerprint,
            current_selection=selection,
        )
    except SearchMissingStalePreview as e:
        return {
            "success": False,
            "status": "stale_preview",
            "error": str(e),
            "status_code": 409,
            "preview": preview,
        }
    except SearchMissingConfirmationError as e:
        return {
            "success": False,
            "status": "invalid_preview",
            "error": str(e),
            "status_code": 409,
        }

    return {
        "success": True,
        "status": "accepted" if not result["dispatch_error"] else "pending_dispatch",
        "accepted": result["accepted"],
        "rejected": preview.get("excludedCount") or 0,
        "run_id": result["run_id"],
        "idempotent": result["idempotent"],
        "message": "Queued %s missing issue(s) for search" % result["accepted"],
        "preview": preview,
    }


def _attach_wanted_acquisition_annotations(rows):
    """Stamp each Wanted row with its latest search run-item annotation.

    Membership is unchanged (``Status == 'Wanted'``). Annotation is derived
    solely from the latest ``acquisition_run_items`` search row for that
    IssueID so closed runs stay sticky until a newer run supersedes them.
    """
    if not rows:
        return rows
    entity_ids = [row.get("IssueID") for row in rows if row.get("IssueID")]
    latest = series_queries.get_latest_search_items_by_entity_ids(entity_ids)
    for row in rows:
        issue_id = row.get("IssueID")
        item = latest.get(str(issue_id)) if issue_id is not None else None
        if item is None:
            row["acquisition"] = None
            continue
        row["acquisition"] = {
            "state": item["state"],
            "attempt_count": item["attempt_count"],
            "reason": item["reason"],
            "run_id": item["run_id"],
            "entity_type": item["entity_type"],
            "updated_at": item["updated_at"],
            "completed_at": item["completed_at"],
        }
    return rows


def get_wanted(ctx, limit=None, offset=None, include_story_arcs=False, search=None):
    """Get all wanted issues, optionally with story arcs and annuals.

    ``search`` filters ComicName / Issue_Number before pagination so the
    returned rows and pagination metadata describe the same result set.

    Each returned row also carries a live-and-sticky ``acquisition`` annotation
    from the latest search run item for that IssueID (or ``null`` when never
    searched). Membership filtering is unchanged.
    """
    if limit is not None:
        paginated = series_queries.get_wanted_issues(limit=limit, offset=offset, search=search)
        result = {
            "issues": _attach_wanted_acquisition_annotations(paginated["results"]),
            "pagination": {
                "total": paginated["total"],
                "limit": paginated["limit"],
                "offset": paginated["offset"],
                "has_more": paginated["has_more"],
            },
        }
    else:
        result = {
            "issues": _attach_wanted_acquisition_annotations(series_queries.get_wanted_issues(search=search)),
        }

    if include_story_arcs:
        upcoming_storyarcs = getattr(ctx.config, "UPCOMING_STORYARCS", False) if ctx.config else False
        if upcoming_storyarcs:
            result["story_arcs"] = _attach_wanted_acquisition_annotations(series_queries.get_wanted_storyarc_issues())

    annuals_on = getattr(ctx.config, "ANNUALS_ON", False) if ctx.config else False
    if annuals_on:
        result["annuals"] = _attach_wanted_acquisition_annotations(series_queries.get_wanted_annuals())

    return result


def get_import_pending(ctx, limit=50, offset=0, include_ignored=False):
    """Get pending import files grouped by DynamicName/Volume."""
    return series_queries.get_import_pending(limit=limit, offset=offset, include_ignored=include_ignored)


def update_import_metadata(ctx, imp_id, issue_number):
    """Update editable file-level metadata on a pending import row."""
    if imp_id is None or not str(imp_id).strip():
        return {"success": False, "error": "Missing impID"}
    if issue_number is None or not str(issue_number).strip():
        return {"success": False, "error": "Issue number cannot be blank"}

    imp_id = str(imp_id).strip()
    issue_number = str(issue_number).strip()
    row = series_queries.get_import_row(imp_id)
    if not row:
        return {"success": False, "error": "Import record not found: %s" % imp_id, "not_found": True}
    if row.get("Status") == "Imported":
        return {"success": False, "error": "Imported records cannot be edited", "imported": True}

    series_queries.update_import_issue_number(imp_id, issue_number)
    return {"success": True, "imp_id": imp_id, "issue_number": issue_number}


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
    """Trigger an import inbox scan in the background."""
    from comicarr import importinbox

    import_dir = getattr(comicarr.CONFIG, "IMPORT_DIR", None) if comicarr.CONFIG else None
    if not import_dir:
        return {"success": False, "error": "Import directory not configured"}

    try:
        logger.info("[IMPORT-INBOX] Starting import inbox scan for: %s" % import_dir)
        start_background_thread(
            importinbox.inboxScan,
            name="API-InboxScan",
            registry=ctx.background_workers,
        )
        return {"success": True, "message": "Import inbox scan started for: %s" % import_dir}
    except Exception as e:
        logger.error("[IMPORT-INBOX] Error: %s" % e)
        return {"success": False, "error": "Failed to start import scan: %s" % str(e)}


def manga_library_scan(ctx):
    """Trigger a manga library scan in the background."""
    from comicarr import mangasync

    manga_dir = getattr(comicarr.CONFIG, "MANGA_DIR", None) if comicarr.CONFIG else None
    if not manga_dir:
        return {"success": False, "error": "Manga directory not configured"}
    if not os.path.isdir(manga_dir):
        return {"success": False, "error": "Manga directory not found: %s" % manga_dir}

    return _start_library_scan(
        mangasync,
        "MANGA_SCAN_STATUS",
        mangasync.mangaScan,
        _MANGA_SCAN_START_LOCK,
        "manga",
        manga_dir,
        "API-MangaScan",
        ctx.background_workers,
    )


def manga_scan_confirm(ctx, selected_ids, scan_id):
    """Confirm and import selected manga series from scan results."""
    from comicarr import mangasync

    if not selected_ids:
        return {"success": False, "error": "No series selected"}

    if not scan_id:
        return {"success": False, "error": "Missing scan_id"}

    return mangasync.import_selected_manga(selected_ids, scan_id)


def comic_library_scan(ctx):
    """Trigger a comic library scan in the background."""
    from comicarr import comicsync

    comic_dir = getattr(comicarr.CONFIG, "COMIC_DIR", None) if comicarr.CONFIG else None
    if not comic_dir:
        return {"success": False, "error": "Comic directory not configured"}
    if not os.path.isdir(comic_dir):
        return {"success": False, "error": "Comic directory not found: %s" % comic_dir}

    return _start_library_scan(
        comicsync,
        "COMIC_SCAN_STATUS",
        comicsync.comicScan,
        _COMIC_SCAN_START_LOCK,
        "comic",
        comic_dir,
        "API-ComicScan",
        ctx.background_workers,
    )


def comic_scan_confirm(ctx, selected_ids, scan_id):
    """Confirm and import selected comic series from scan results."""
    from comicarr import comicsync

    if not selected_ids:
        return {"success": False, "error": "No series selected"}

    if not scan_id:
        return {"success": False, "error": "Missing scan_id"}

    return comicsync.import_selected_series(selected_ids, scan_id)


def ComicSort(comicorder=None, sequence=None, imported=None):
    from sqlalchemy import select

    if sequence:
        i = 0
        comicsort = db.select_all(select(comics).order_by(comics.c.ComicSortName))
        comicorderlist = []
        comicorder = {}
        comicidlist = []
        if sequence == "update":
            comicarr.COMICSORT["SortOrder"] = None
            comicarr.COMICSORT["LastOrderNo"] = None
            comicarr.COMICSORT["LastOrderID"] = None
        for csort in comicsort:
            if csort["ComicID"] is None:
                pass
            if csort["ComicID"] not in comicidlist:
                if sequence == "startup":
                    comicorderlist.append({"ComicID": csort["ComicID"], "ComicOrder": i})
                elif sequence == "update":
                    comicorderlist.append(
                        {
                            "ComicID": csort["ComicID"],
                            "ComicOrder": i,
                        }
                    )

                comicidlist.append(csort["ComicID"])
                i += 1
        if sequence == "startup":
            if i == 0:
                comicorder["SortOrder"] = {"ComicID": "99999", "ComicOrder": 1}
                comicorder["LastOrderNo"] = 1
                comicorder["LastOrderID"] = 99999
            else:
                comicorder["SortOrder"] = comicorderlist
                comicorder["LastOrderNo"] = i - 1
                comicorder["LastOrderID"] = comicorder["SortOrder"][i - 1]["ComicID"]
            if i < 0:
                i == 0
            logger.info("Sucessfully ordered " + str(i - 1) + " series in your watchlist.")
            return comicorder
        elif sequence == "update":
            comicarr.COMICSORT["SortOrder"] = comicorderlist
            if i == 0:
                placemnt = 1
            else:
                placemnt = int(i - 1)
            try:
                comicarr.COMICSORT["LastOrderNo"] = placemnt
                comicarr.COMICSORT["LastOrderID"] = comicarr.COMICSORT["SortOrder"][placemnt]["ComicID"]
            except Exception:
                comicorder["SortOrder"] = {"ComicID": "99999", "ComicOrder": 1}
                comicarr.COMICSORT["LastOrderNo"] = 1
                comicarr.COMICSORT["LastOrderID"] = 99999
            return
    else:
        sortedapp = []
        if comicorder["LastOrderNo"] == "999":
            lastorderval = int(comicorder["LastOrderNo"]) + 1
        else:
            lastorderval = 999
        sortedapp.append({"ComicID": imported, "ComicOrder": lastorderval})
        comicarr.COMICSORT["SortOrder"] = sortedapp
        comicarr.COMICSORT["LastOrderNo"] = lastorderval
        comicarr.COMICSORT["LastOrderID"] = imported
        return


def updateComicLocation():
    from sqlalchemy import select

    from comicarr.helpers import filesafe, replace_all

    if comicarr.CONFIG.NEWCOM_DIR is not None:
        logger.info("Performing a one-time mass update to Comic Location")
        checkdirectory = comicarr.filechecker.validateAndCreateDirectory(comicarr.CONFIG.NEWCOM_DIR, create=True)
        if not checkdirectory:
            logger.warn("Error trying to validate/create directory. Aborting this process at this time.")
            return
        dirlist = db.select_all(select(comics))
        comloc = []

        if dirlist is not None:
            for dl in dirlist:
                u_comicnm = dl["ComicName"]
                comicname_folder = filesafe(u_comicnm)

                publisher = re.sub("!", "", dl["ComicPublisher"])
                year = dl["ComicYear"]

                if dl["Corrected_Type"] is not None:
                    booktype = dl["Corrected_Type"]
                else:
                    booktype = dl["Type"]
                if booktype == "Print" or all([booktype != "Print", comicarr.CONFIG.FORMAT_BOOKTYPE is False]):
                    chunk_fb = re.sub(r"\$Type", "", comicarr.CONFIG.FOLDER_FORMAT)
                    chunk_b = re.compile(r"\s+")
                    chunk_folder_format = chunk_b.sub(" ", chunk_fb)
                else:
                    chunk_folder_format = comicarr.CONFIG.FOLDER_FORMAT

                comversion = dl["ComicVersion"]
                if comversion is None:
                    comversion = "None"
                if comversion == "None":
                    chunk_f_f = re.sub(r"\$VolumeN", "", chunk_folder_format)
                    chunk_f = re.compile(r"\s+")
                    chunk_folder = chunk_f.sub(" ", chunk_f_f)
                else:
                    chunk_folder = chunk_folder_format

                imprint = dl["PublisherImprint"]
                if any([imprint is None, imprint == "None"]):
                    chunk_f_f = re.sub(r"\$Imprint", "", chunk_folder)
                    chunk_f = re.compile(r"\s+")
                    folderformat = chunk_f.sub(" ", chunk_f_f)
                else:
                    folderformat = chunk_folder

                values = {
                    "$Series": comicname_folder,
                    "$Publisher": publisher,
                    "$Imprint": imprint,
                    "$Year": year,
                    "$series": comicname_folder.lower(),
                    "$publisher": publisher.lower(),
                    "$VolumeY": "V" + str(year),
                    "$VolumeN": comversion,
                    "$Type": booktype,
                }

                ccdir = re.sub(r"[\\|/]", "%&", comicarr.CONFIG.NEWCOM_DIR)
                ddir = re.sub(r"[\\|/]", "%&", comicarr.CONFIG.DESTINATION_DIR)
                dlc = re.sub(r"[\\|/]", "%&", dl["ComicLocation"])

                if comicarr.CONFIG.FFTONEWCOM_DIR:
                    if comicarr.CONFIG.FOLDER_FORMAT == "":
                        comlocation = re.sub(ddir, ccdir, dlc).strip()
                    else:
                        first = replace_all(folderformat, values)
                        if comicarr.CONFIG.REPLACE_SPACES:
                            first = first.replace(" ", comicarr.CONFIG.REPLACE_CHAR)
                        comlocation = os.path.join(comicarr.CONFIG.NEWCOM_DIR, first).strip()

                else:
                    comlocation = re.sub(ddir, ccdir, dlc).strip()

                try:
                    com_done = re.sub("%&", os.sep.encode().decode("unicode-escape"), comlocation).strip()
                except Exception as e:
                    logger.warn("[%s] error during conversion: %s" % (comlocation, e))
                    com_done = comlocation.replace("%&", os.sep).strip()

                comloc.append({"comlocation": com_done, "origlocation": dl["ComicLocation"], "comicid": dl["ComicID"]})

            if len(comloc) > 0:
                if comicarr.CONFIG.FFTONEWCOM_DIR:
                    logger.info(
                        "FFTONEWCOM_DIR is enabled. Applying the existing folder format to ALL directories regardless of existing location paths"
                    )
                else:
                    logger.info(
                        "FFTONEWCOM_DIR is not enabled. I will keep existing subdirectory paths, and will only change the actual Comic Location in the path."
                    )
                    logger.fdebug(" (ie. /mnt/Comics/Marvel/Hush-(2012) to /mnt/mynewLocation/Marvel/Hush-(2012) ")

                for cl in comloc:
                    ctrlVal = {"ComicID": cl["comicid"]}
                    newVal = {"ComicLocation": cl["comlocation"]}
                    db.upsert("comics", newVal, ctrlVal)
                    logger.fdebug("Updated : " + cl["origlocation"] + " .: TO :. " + cl["comlocation"])
                logger.info(
                    "Updated " + str(len(comloc)) + " series to a new Comic Location as specified in the config.ini"
                )
            else:
                logger.fdebug(
                    "Failed in updating the Comic Locations. Check Folder Format string and/or log the issue."
                )
        else:
            logger.info(
                "There are no series in your watchlist to Update the locations. Not updating anything at this time."
            )
        comicarr.CONFIG.writeconfig(values={"locmove": False})
    else:
        logger.info("No new ComicLocation path specified - not updating. Set NEWCOMD_DIR in config.ini")
    return


def checkthepub(ComicID):
    from sqlalchemy import select

    publishers = ["marvel", "dc", "darkhorse"]
    pubchk = db.select_one(select(comics).where(comics.c.ComicID == ComicID))
    if pubchk is None:
        logger.fdebug(
            "No publisher information found to aid in determining series..defaulting to base check of 55 days."
        )
        return comicarr.CONFIG.BIGGIE_PUB
    else:
        for publish in publishers:
            if publish in pubchk["ComicPublisher"].lower():
                return comicarr.CONFIG.BIGGIE_PUB

        return comicarr.CONFIG.INDIE_PUB


def annual_update():
    from sqlalchemy import select

    annuallist = db.select_all(select(annuals).where(annuals.c.Deleted != 1))
    if annuallist is None:
        logger.info("no annuals to update.")
        return

    cnames = []
    for ann in annuallist:
        coms = db.select_one(select(comics).where(comics.c.ComicID == ann["ComicID"]))
        cnames.append({"ComicID": ann["ComicID"], "ComicName": coms["ComicName"]})

    i = 0
    for cns in cnames:
        ctrlVal = {"ComicID": cns["ComicID"]}
        newVal = {"ComicName": cns["ComicName"]}
        db.upsert("annuals", newVal, ctrlVal)
        i += 1

    logger.info(str(i) + " series have been updated in the annuals table.")
    return


_havetotals_cache = None
_havetotals_cache_time = 0


def havetotals(refreshit=None):
    global _havetotals_cache, _havetotals_cache_time
    import time

    from sqlalchemy import delete, func, select

    from comicarr.helpers import today

    now = time.monotonic()
    if _havetotals_cache is not None and (now - _havetotals_cache_time) < 30 and not refreshit:
        return _havetotals_cache

    comics_list = []

    if refreshit is None:
        if comicarr.CONFIG.ANNUALS_ON:
            stmt = (
                select(comics, func.count(annuals.c.IssueID).label("TotalAnnuals"))
                .outerjoin(annuals, annuals.c.ComicID == comics.c.ComicID)
                .group_by(comics.c.ComicID)
                .order_by(comics.c.ComicSortName)
            )
            comiclist = db.select_all(stmt)
        else:
            stmt = select(comics).group_by(comics.c.ComicID).order_by(comics.c.ComicSortName)
            comiclist = db.select_all(stmt)
    else:
        comiclist = []
        stmt = (
            select(
                comics.c.ComicID,
                comics.c.Have,
                comics.c.Total,
                func.count(annuals.c.IssueID).label("TotalAnnuals"),
            )
            .outerjoin(annuals, annuals.c.ComicID == comics.c.ComicID)
            .where(comics.c.ComicID == refreshit)
            .group_by(comics.c.ComicID)
        )
        comicref = db.select_one(stmt)
        comiclist.append(
            {
                "ComicID": comicref["ComicID"],
                "Have": comicref["Have"],
                "Total": comicref["Total"],
                "TotalAnnuals": comicref["TotalAnnuals"],
            }
        )

    for comic in comiclist:
        try:
            totalissues = comic["Total"]
            haveissues = comic["Have"]
        except TypeError:
            logger.warn(
                "[Warning] ComicID: "
                + str(comic["ComicID"])
                + " is incomplete - Removing from DB. You should try to re-add the series."
            )
            with db.get_engine().begin() as conn:
                conn.execute(
                    delete(comics).where(comics.c.ComicID == comic["ComicID"], comics.c.ComicName.like("Comic ID%"))
                )
                conn.execute(
                    delete(issues).where(issues.c.ComicID == comic["ComicID"], issues.c.ComicName.like("Comic ID%"))
                )
            continue

        if not haveissues:
            haveissues = 0

        if refreshit is not None:
            if haveissues > totalissues:
                return True
            else:
                return False

        if any([haveissues == "None", haveissues is None]):
            haveissues = 0
        if any([totalissues == "None", totalissues is None]):
            totalissues = 0

        try:
            percent = (haveissues * 100.0) / totalissues
            if percent > 100:
                percent = 101
        except (ZeroDivisionError, TypeError):
            percent = 0
            totalissues = "?"

        if comic["LatestDate"] is None:
            logger.warn(
                comic["ComicName"]
                + " has not finished loading. Nulling some values so things display properly until they can populate."
            )
            recentstatus = "Loading"
        elif comic["ComicPublished"] is None or comic["ComicPublished"] == "" or comic["LatestDate"] is None:
            recentstatus = "Unknown"
        elif comic["ForceContinuing"] == 1:
            recentstatus = "Continuing"
        elif "present" in comic["ComicPublished"].lower() or (today()[:4] in comic["LatestDate"]):
            if "Err" in comic["LatestDate"]:
                recentstatus = "Loading"
            else:
                latestdate = comic["LatestDate"]
                if "-" in latestdate[:3]:
                    st_date = latestdate.find("-")
                    st_remainder = latestdate[st_date + 1 :]
                    st_year = latestdate[:st_date]
                    year = "20" + st_year
                    latestdate = str(year) + "-" + str(st_remainder)
                c_date = datetime.date(int(latestdate[:4]), int(latestdate[5:7]), 1)
                n_date = datetime.date.today()
                recentchk = (n_date - c_date).days
                if comic["NewPublish"] is True:
                    recentstatus = "Continuing"
                else:
                    if recentchk < 55:
                        recentstatus = "Continuing"
                    else:
                        recentstatus = "Ended"
        else:
            recentstatus = "Ended"

        if recentstatus == "Loading":
            cpub = comic["ComicPublished"]
        else:
            try:
                cpub = re.sub("(N)", "", comic["ComicPublished"]).strip()
            except Exception as e:
                if comic["cv_removed"] == 0:
                    logger.warn(
                        "[Error: %s] No Publisher found for %s - you probably want to Refresh the series when you get a chance."
                        % (e, comic["ComicName"])
                    )
                cpub = None

        comictype = comic["Type"]
        try:
            if (
                any([comictype == "None", comictype is None, comictype == "Print"])
                and all(
                    [comic["Corrected_Type"] != "TPB", comic["Corrected_Type"] != "GN", comic["Corrected_Type"] != "HC"]
                )
            ) or all([comic["Corrected_Type"] is not None, comic["Corrected_Type"] == "Print"]):
                comictype = None
            else:
                if comic["Corrected_Type"] is not None:
                    comictype = comic["Corrected_Type"]
                else:
                    comictype = comictype
        except Exception:
            comictype = None

        if any([comic["ComicVersion"] is None, comic["ComicVersion"] == "None", comic["ComicVersion"] == ""]):
            cversion = None
        else:
            cversion = comic["ComicVersion"]

        if comic["ComicImage"] is None:
            comicImage = "cache/%s.jpg" % comic["ComicID"]
        else:
            comicImage = comic["ComicImage"]

        comics_list.append(
            {
                "ComicID": comic["ComicID"],
                "ComicName": comic["ComicName"],
                "ComicSortName": comic["ComicSortName"],
                "ComicPublisher": comic["ComicPublisher"],
                "ComicYear": comic["ComicYear"],
                "ComicImage": comicImage,
                "LatestIssue": comic["LatestIssue"],
                "IntLatestIssue": comic["IntLatestIssue"],
                "LatestDate": comic["LatestDate"],
                "ComicVolume": cversion,
                "ComicPublished": cpub,
                "PublisherImprint": comic["PublisherImprint"],
                "Status": comic["Status"],
                "recentstatus": recentstatus,
                "percent": percent,
                "totalissues": totalissues,
                "haveissues": haveissues,
                "DateAdded": comic["LastUpdated"],
                "Type": comic["Type"],
                "Corrected_Type": comic["Corrected_Type"],
                "displaytype": comictype,
                "cv_removed": comic["cv_removed"],
            }
        )

    if not refreshit:
        _havetotals_cache = comics_list
        _havetotals_cache_time = now

    return comics_list


def listPull(weeknumber, year):
    from sqlalchemy import select

    library = {}
    rows = db.select_all(select(weekly.c.ComicID).where(weekly.c.weeknumber == weeknumber, weekly.c.year == year))
    for row in rows:
        library[row["ComicID"]] = row["ComicID"]
    return library


def listLibrary(comicid=None):
    from sqlalchemy import select

    library = {}
    if comicid is None:
        if comicarr.CONFIG.ANNUALS_ON is True:
            stmt = (
                select(
                    comics.c.ComicID,
                    annuals.c.ReleaseComicID,
                    comics.c.Status,
                    comics.c.ComicName,
                    comics.c.ComicYear,
                    comics.c.MalID,
                    comics.c.MangaDexID,
                )
                .outerjoin(annuals, comics.c.ComicID == annuals.c.ComicID)
                .group_by(comics.c.ComicID)
            )
        else:
            stmt = select(
                comics.c.ComicID,
                comics.c.Status,
                comics.c.ComicName,
                comics.c.ComicYear,
                comics.c.MalID,
                comics.c.MangaDexID,
            ).group_by(comics.c.ComicID)
    else:
        cleaned_id = re.sub("4050-", "", comicid).strip()
        if comicarr.CONFIG.ANNUALS_ON is True:
            stmt = (
                select(
                    comics.c.ComicID,
                    annuals.c.ReleaseComicID,
                    comics.c.Status,
                    comics.c.ComicName,
                    comics.c.ComicYear,
                    comics.c.MalID,
                    comics.c.MangaDexID,
                )
                .outerjoin(annuals, comics.c.ComicID == annuals.c.ComicID)
                .where(comics.c.ComicID == cleaned_id)
                .group_by(comics.c.ComicID)
            )
        else:
            stmt = (
                select(
                    comics.c.ComicID,
                    comics.c.Status,
                    comics.c.ComicName,
                    comics.c.ComicYear,
                    comics.c.MalID,
                    comics.c.MangaDexID,
                )
                .where(comics.c.ComicID == cleaned_id)
                .group_by(comics.c.ComicID)
            )

    rows = db.select_all(stmt)
    for row in rows:
        library[row["ComicID"]] = {"comicid": row["ComicID"], "status": row["Status"]}
        try:
            if row["ReleaseComicID"] is not None:
                library[row["ReleaseComicID"]] = {"comicid": row["ComicID"], "status": row["Status"]}
        except Exception:
            pass
        try:
            name = row["ComicName"]
            year = row["ComicYear"]
            if name and year:
                name_key = "name:" + name.lower().strip() + ":" + str(year).strip()
                library[name_key] = {"comicid": row["ComicID"], "status": row["Status"]}
        except Exception:
            pass
        try:
            mal_id = row.get("MalID")
            if mal_id:
                mal_key = series_kind.add_prefix(mal_id, series_kind.SeriesProvider.MYANIMELIST)
                library[mal_key] = {"comicid": row["ComicID"], "status": row["Status"]}
            mangadex_id = row.get("MangaDexID")
            if mangadex_id:
                mangadex_key = series_kind.add_prefix(mangadex_id, series_kind.SeriesProvider.MANGADEX)
                library[mangadex_key] = {"comicid": row["ComicID"], "status": row["Status"]}
        except Exception as e:
            logger.fdebug("[SERIES] Cross-index by MAL/MangaDex ID failed for %s: %s" % (row.get("ComicID"), e))

    return library


def listoneoffs(weeknumber, year):
    from sqlalchemy import select

    library = []
    stmt = (
        select(
            oneoffhistory.c.IssueID,
            oneoffhistory.c.Status,
            oneoffhistory.c.ComicID,
            oneoffhistory.c.ComicName,
            oneoffhistory.c.IssueNumber,
        )
        .distinct()
        .where(
            oneoffhistory.c.weeknumber == weeknumber,
            oneoffhistory.c.year == year,
            oneoffhistory.c.Status.in_(["Downloaded", "Snatched"]),
        )
    )
    rows = db.select_all(stmt)
    for row in rows:
        library.append(
            {
                "IssueID": row["IssueID"],
                "ComicID": row["ComicID"],
                "ComicName": row["ComicName"],
                "IssueNumber": row["IssueNumber"],
                "Status": row["Status"],
                "weeknumber": weeknumber,
                "year": year,
            }
        )
    return library


def listIssues(weeknumber, year):
    from sqlalchemy import select

    library = []
    stmt = (
        select(
            issues.c.Status,
            issues.c.ComicID,
            issues.c.IssueID,
            issues.c.ComicName,
            issues.c.IssueDate,
            issues.c.ReleaseDate,
            weekly.c.PUBLISHER.label("publisher"),
            issues.c.Issue_Number,
        )
        .select_from(weekly.join(issues, weekly.c.IssueID == issues.c.IssueID))
        .where(weekly.c.weeknumber == str(int(weeknumber)), weekly.c.year == str(year))
    )
    rows = db.select_all(stmt)
    for row in rows:
        if row["ReleaseDate"] is None:
            tmpdate = row["IssueDate"]
        else:
            tmpdate = row["ReleaseDate"]
        library.append(
            {
                "ComicID": row["ComicID"],
                "Status": row["Status"],
                "IssueID": row["IssueID"],
                "ComicName": row["ComicName"],
                "Publisher": row["publisher"],
                "Issue_Number": row["Issue_Number"],
                "IssueYear": tmpdate,
            }
        )

    if comicarr.CONFIG.ANNUALS_ON:
        stmt_ann = (
            select(
                annuals.c.Status,
                annuals.c.ComicID,
                annuals.c.ReleaseComicID,
                annuals.c.IssueID,
                annuals.c.ComicName,
                annuals.c.ReleaseDate,
                annuals.c.IssueDate,
                weekly.c.PUBLISHER.label("publisher"),
                annuals.c.Issue_Number,
            )
            .select_from(weekly.join(annuals, weekly.c.IssueID == annuals.c.IssueID))
            .where(weekly.c.weeknumber == str(int(weeknumber)), weekly.c.year == str(year))
        )
        ann_rows = db.select_all(stmt_ann)
        for row in ann_rows:
            if row["ReleaseDate"] is None:
                tmpdate = row["IssueDate"]
            else:
                tmpdate = row["ReleaseDate"]
            library.append(
                {
                    "ComicID": row["ComicID"],
                    "Status": row["Status"],
                    "IssueID": row["IssueID"],
                    "ComicName": row["ComicName"],
                    "Publisher": row["publisher"],
                    "Issue_Number": row["Issue_Number"],
                    "IssueYear": tmpdate,
                }
            )

    return library


def incr_snatched(ComicID):
    from sqlalchemy import select

    incr_count = db.select_one(select(comics.c.Have).where(comics.c.ComicID == ComicID))
    logger.fdebug("Incrementing HAVE count total to : " + str(incr_count["Have"] + 1))
    newCtrl = {"ComicID": ComicID}
    newVal = {"Have": incr_count["Have"] + 1}
    db.upsert("comics", newVal, newCtrl)
    return


def get_issue_title(IssueID=None, ComicID=None, IssueNumber=None, IssueArcID=None):
    from sqlalchemy import select

    from comicarr.helpers import issuedigits

    if IssueID:
        issue = db.select_one(select(issues).where(issues.c.IssueID == IssueID))
        if issue is None:
            issue = db.select_one(select(annuals).where(annuals.c.IssueID == IssueID))
            if issue is None:
                logger.fdebug("Unable to locate given IssueID within the db. Assuming Issue Title is None.")
                return None
    else:
        issue = db.select_one(
            select(issues).where(issues.c.ComicID == ComicID, issues.c.Int_IssueNumber == issuedigits(IssueNumber))
        )
        if issue is None:
            issue = db.select_one(select(annuals).where(annuals.c.IssueID == IssueID))
            if issue is None:
                if IssueArcID:
                    issue = db.select_one(select(storyarcs).where(storyarcs.c.IssueArcID == IssueArcID))
                    if issue is None:
                        logger.fdebug("Unable to locate given IssueID within the db. Assuming Issue Title is None.")
                        return None
                else:
                    logger.fdebug("Unable to locate given IssueID within the db. Assuming Issue Title is None.")
                    return None

    return issue["IssueName"]


def latestdate_fix():
    from sqlalchemy import select

    from comicarr.helpers import filesafe

    datefix = []
    cnupdate = []
    comiclist = db.select_all(select(comics))
    if comiclist is None:
        logger.fdebug("No Series in watchlist to correct latest date")
        return
    for cl in comiclist:
        if cl["ComicName_Filesafe"] is None:
            cnupdate.append({"comicid": cl["ComicID"], "comicname_filesafe": filesafe(cl["ComicName"])})
        latestdate = cl["LatestDate"]
        try:
            if latestdate[8:] == "":
                if len(latestdate) <= 7:
                    finddash = latestdate.find("-")
                    if finddash != 4:
                        lat_month = latestdate[:finddash]
                        lat_year = latestdate[finddash + 1 :]
                    else:
                        lat_month = latestdate[finddash + 1 :]
                        lat_year = latestdate[:finddash]

                    latestdate = (lat_year) + "-" + str(lat_month) + "-01"
                    datefix.append({"comicid": cl["ComicID"], "latestdate": latestdate})
        except Exception:
            datefix.append({"comicid": cl["ComicID"], "latestdate": "0000-00-00"})

    if len(datefix) > 0:
        logger.info(
            "Preparing to correct/fix "
            + str(len(datefix))
            + " series that have incorrect values given for the Latest Date field."
        )
        for df in datefix:
            newCtrl = {"ComicID": df["comicid"]}
            newVal = {"LatestDate": df["latestdate"]}
            db.upsert("comics", newVal, newCtrl)
    if len(cnupdate) > 0:
        logger.info(
            "Preparing to update " + str(len(cnupdate)) + " series on your watchlist for use with non-ascii characters"
        )
        for cn in cnupdate:
            newCtrl = {"ComicID": cn["comicid"]}
            newVal = {"ComicName_Filesafe": cn["comicname_filesafe"]}
            db.upsert("comics", newVal, newCtrl)

    return


def latestdate_update():
    from sqlalchemy import select

    stmt = (
        select(
            comics.c.ComicID,
            issues.c.IssueID,
            comics.c.LatestDate,
            issues.c.ReleaseDate,
            issues.c.Issue_Number,
        )
        .select_from(comics.outerjoin(issues, comics.c.ComicID == issues.c.ComicID))
        .where(
            sqlalchemy.or_(
                comics.c.LatestDate < issues.c.ReleaseDate,
                comics.c.LatestDate.like("%Unknown%"),
            )
        )
        .group_by(comics.c.ComicID)
    )
    ccheck = db.select_all(stmt)
    if ccheck is None or len(ccheck) == 0:
        return
    logger.info(
        "Now preparing to update " + str(len(ccheck)) + " series that have out-of-date latest date information."
    )
    ablist = []
    for cc in ccheck:
        ablist.append({"ComicID": cc["ComicID"], "LatestDate": cc["ReleaseDate"], "LatestIssue": cc["Issue_Number"]})

    for a in ablist:
        logger.info(a)
        newVal = {"LatestDate": a["LatestDate"], "LatestIssue": a["LatestIssue"]}
        ctrlVal = {"ComicID": a["ComicID"]}
        logger.info("updating latest date for : " + a["ComicID"] + " to " + a["LatestDate"] + " #" + a["LatestIssue"])
        db.upsert("comics", newVal, ctrlVal)


def latestissue_update():
    from sqlalchemy import select

    from comicarr.helpers import issuedigits

    cck = db.select_all(select(comics.c.ComicID, comics.c.LatestIssue).where(comics.c.intLatestIssue.is_(None)))

    if cck:
        c_list = []
        for ck in cck:
            c_list.append({"ComicID": ck["ComicID"], "intLatestIssue": issuedigits(ck["LatestIssue"])})

        logger.info("[LATEST_ISSUE_TO_INT] Updating the latestIssue field for %s series" % (len(c_list)))

        for ct in c_list:
            try:
                newVal = {"intLatestIssue": ct["intLatestIssue"]}
                ctrlVal = {"ComicID": ct["ComicID"]}
                db.upsert("comics", newVal, ctrlVal)
            except Exception as e:
                logger.fdebug("exception encountered: %s" % e)
                continue


def DateAddedFix():
    from sqlalchemy import update

    DA_A = datetime.datetime.today()
    DateAdded = DA_A.strftime("%Y-%m-%d")

    with db.get_engine().begin() as conn:
        conn.execute(
            update(issues).where(issues.c.Status == "Wanted", issues.c.DateAdded.is_(None)).values(DateAdded=DateAdded)
        )
        conn.execute(
            update(annuals)
            .where(annuals.c.Status == "Wanted", annuals.c.DateAdded.is_(None), annuals.c.Deleted != 1)
            .values(DateAdded=DateAdded)
        )


def statusChange(status_from, status_to, comicid=None, bulk=False, api=True):
    from sqlalchemy import select

    the_list = []
    if bulk is False:
        sc = db.select_all(select(issues.c.IssueID).where(issues.c.ComicID == comicid, issues.c.Status == status_from))
        for s in sc:
            the_list.append({"table": "issues", "issueid": s["IssueID"]})
        if comicarr.CONFIG.ANNUALS_ON:
            ac = db.select_all(
                select(annuals.c.IssueID).where(annuals.c.ComicID == comicid, annuals.c.Status == status_from)
            )
            for s in ac:
                the_list.append({"table": "annuals", "issueid": s["IssueID"]})
    else:
        if comicid == "All":
            sc = db.select_all(select(issues.c.IssueID).where(issues.c.Status == status_from))
            for s in sc:
                the_list.append({"table": "issues", "issueid": s["IssueID"]})
            if comicarr.CONFIG.ANNUALS_ON:
                ac = db.select_all(select(annuals.c.IssueID).where(annuals.c.Status == status_from))
                for s in ac:
                    the_list.append({"table": "annuals", "issueid": s["IssueID"]})

        else:
            for x in comicid:
                sc = db.select_all(
                    select(issues.c.IssueID).where(issues.c.ComicID == x, issues.c.Status == status_from)
                )
                for s in sc:
                    the_list.append({"table": "issues", "issueid": s["IssueID"]})
                if comicarr.CONFIG.ANNUALS_ON:
                    ac = db.select_all(
                        select(annuals.c.IssueID).where(annuals.c.ComicID == x, annuals.c.Status == status_from)
                    )
                    for s in ac:
                        the_list.append({"table": "annuals", "issueid": s["IssueID"]})

    cnt = 0
    for x in the_list:
        try:
            db.upsert(x["table"], {"Status": status_to}, {"IssueID": x["issueid"], "Status": status_from})
        except Exception:
            pass
        else:
            cnt += 1

    rtnline = "Updated %s Issues from a status of %s to %s" % (cnt, status_from, status_to)
    logger.info(rtnline)

    return rtnline


def issue_status(IssueID):
    from sqlalchemy import select

    IssueID = str(IssueID)

    isschk = db.select_one(select(issues).where(issues.c.IssueID == IssueID))
    if isschk is None:
        isschk = db.select_one(select(annuals).where(annuals.c.IssueID == IssueID, annuals.c.Deleted != 1))
        if isschk is None:
            isschk = db.select_one(select(storyarcs).where(storyarcs.c.IssueArcID == IssueID))
            if isschk is None:
                logger.warn("Unable to retrieve IssueID from db. This is a problem. Aborting.")
                return False

    if any([isschk["Status"] == "Downloaded", isschk["Status"] == "Snatched"]):
        return True
    else:
        return False
