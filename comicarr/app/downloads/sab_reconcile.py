#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Re-queue post-processing for SABnzbd jobs that finished but stayed snatched.

The in-memory NZB monitor is the live path. A restart, a category-filtered
history miss, or a journal row reconstructed without ``nzo_id`` leaves the
issue at Snatched even though SABnzbd history says Completed (#1129). This
module is the shared, idempotent way back onto the existing post-process
queue: startup recovery, the periodic sweep, and the In Flight retry all
call it. A second pass does not import twice — the journal claim inside
post-processing accepts the row once.
"""

import comicarr
from comicarr import logger
from comicarr.app.downloads import journal

INTERVAL_MINUTES = 2
JOB_ID = "sab_completed_reconcile"

_SAB_ROUTES = frozenset({"sab", "sabnzbd"})
_OTHER_ROUTES = frozenset(
    {
        "nzbget",
        "ddl",
        "torrent",
        "rtorrent",
        "deluge",
        "qbittorrent",
        "transmission",
        "utorrent",
        "watchdir",
        "blackhole",
    }
)
_RETRYABLE_STAGES = frozenset({journal.SNATCHED, journal.DOWNLOADED})


class RetryPostProcessError(ValueError):
    """The operator retry could not queue post-processing."""

    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


def _route(row, payload):
    payload = payload or {}
    return (
        str(payload.get("route") or payload.get("client") or (row or {}).get("downloader_type") or "").strip().lower()
    )


def row_targets_sab(row, payload=None):
    """True when this open row is a SABnzbd (or generic NZB-on-SAB) obligation."""
    route = _route(row, payload)
    if route in _OTHER_ROUTES:
        return False
    if route in _SAB_ROUTES:
        return True
    if route == "nzb":
        return bool(getattr(comicarr, "USE_SABNZBD", False)) and not bool(getattr(comicarr, "USE_NZBGET", False))
    if route == "" and bool(getattr(comicarr, "USE_SABNZBD", False)):
        return not (row or {}).get("hash")
    return False


def retry_postprocess_eligible(row, payload=None):
    """Whether Activity → In Flight should offer Retry post-processing."""
    if not row or row.get("stage") not in _RETRYABLE_STAGES:
        return False
    payload = payload or {}
    if row.get("stage") == journal.DOWNLOADED and payload.get("nzb_folder"):
        return True
    return row_targets_sab(row, payload)


def _sab_monitoring_enabled():
    config = getattr(comicarr, "CONFIG", None)
    if config is None:
        return False
    return bool(
        getattr(config, "POST_PROCESSING", False)
        and getattr(config, "NZB_DOWNLOADER", None) == 0
        and getattr(config, "SAB_CLIENT_POST_PROCESSING", False)
        and getattr(comicarr, "USE_SABNZBD", False)
    )


def _validated_item(row, payload):
    """The PP queue item, or an unplaced result when the folder is not importable."""
    from comicarr.app.downloads.pp_commands import PostProcessCommandError, configured_roots, validate_postprocess_item
    from comicarr.app.downloads.recovery import _pp_item_from_row

    item = _pp_item_from_row(row, payload)
    try:
        item = validate_postprocess_item(item, roots=configured_roots())
    except PostProcessCommandError as e:
        return None, {"action": "unplaced", "error": str(e), "release_key": row.get("release_key")}
    return item, None


def _put_postprocess(row, item):
    comicarr.PP_QUEUE.put(item)
    logger.info("[SAB-RECONCILE] queued post-processing for %s (%s)." % (row.get("release_key"), item.get("nzb_name")))
    return {"action": "enqueued", "release_key": row.get("release_key")}


def queue_completed_postprocess(row):
    """Queue PP when this row's SABnzbd job is Completed, or the folder is already known.

    Safe to call repeatedly. A row that is already past ``downloaded`` is left
    alone. A snatched row advances to ``downloaded`` only when this call wins
    the journal transition, and only that winner enqueues — so two sweeps
    cannot both queue the same import.
    """
    from comicarr.app.downloads import recovery, recovery_classify

    if not row or not row.get("release_key"):
        return {"action": "missing"}
    current = journal.read_one(row.get("release_key"))
    if current is None:
        return {"action": "missing"}
    rkey = current.get("release_key")
    if journal.is_terminal(current.get("stage")):
        return {"action": "terminal", "release_key": rkey}
    stage = current.get("stage")
    if stage not in _RETRYABLE_STAGES:
        return {"action": "busy", "release_key": rkey, "stage": stage}

    payload = journal.load_payload(current.get("payload_json")) or {}
    if stage == journal.DOWNLOADED:
        item, rejected = _validated_item(current, payload)
        if rejected:
            return rejected
        return _put_postprocess(current, item)

    if not row_targets_sab(current, payload):
        return {"action": "not-sab", "release_key": rkey}

    details = recovery_classify.classify_details(current, payload=payload)
    verdict = details.get("verdict")
    raw_state = details.get("raw_state")
    if verdict != recovery_classify.COMPLETE:
        return {"action": raw_state or "not-complete", "release_key": rkey, "verdict": verdict}

    payload = recovery._merge_completion_evidence(payload, details)
    item, rejected = _validated_item(current, payload)
    if rejected:
        return rejected
    # Advance before enqueue. A second sweep sees ``downloaded`` and does not
    # run this branch; post-processing then claims the row once.
    won = journal.record_transition(
        rkey,
        journal.DOWNLOADED,
        payload=payload,
        issueid=current.get("issueid"),
        provider=current.get("provider"),
        downloader_type=current.get("downloader_type"),
        nzbname=payload.get("nzb_name") or payload.get("nzbname") or current.get("nzbname"),
    )
    if not won:
        latest = journal.read_one(rkey)
        latest_stage = (latest or {}).get("stage")
        if latest_stage != journal.DOWNLOADED:
            logger.warn(
                "[SAB-RECONCILE] %s looked complete but the journal did not advance (stage=%s)." % (rkey, latest_stage)
            )
            return {"action": "not-won", "release_key": rkey, "stage": latest_stage}
    return _put_postprocess(current, item)


def reconcile_completed_sab_downloads():
    """Periodic sweep: Snatched SAB rows whose history is Completed.

    Downloaded rows are skipped. Startup recovery already re-queues those,
    and repeating it here would stack PP items for work the queue already has.
    """
    summary = {"checked": 0, "enqueued": 0, "skipped": 0}
    if not _sab_monitoring_enabled():
        return summary
    try:
        rows = journal.read_open()
    except Exception as e:
        logger.error("[SAB-RECONCILE] could not read open journal rows: %s" % type(e).__name__)
        return summary

    for row in rows:
        if row.get("stage") != journal.SNATCHED:
            continue
        payload = journal.load_payload(row.get("payload_json"))
        if not row_targets_sab(row, payload):
            continue
        summary["checked"] += 1
        try:
            result = queue_completed_postprocess(row)
        except Exception as e:
            logger.error(
                "[SAB-RECONCILE] %s failed; leaving it for the next pass: %s"
                % (row.get("release_key"), type(e).__name__)
            )
            summary["skipped"] += 1
            continue
        if result.get("action") == "enqueued":
            summary["enqueued"] += 1
        else:
            summary["skipped"] += 1
    if summary["checked"]:
        logger.info(
            "[SAB-RECONCILE] checked %d snatched SABnzbd row(s); queued %d for post-processing."
            % (summary["checked"], summary["enqueued"])
        )
    return summary


_RETRY_ERRORS = {
    "missing": (404, "In-flight download not found."),
    "terminal": (409, "This download is no longer in flight."),
    "busy": (409, "Post-processing is already running for this download."),
    "still": (409, "SABnzbd has not finished this download yet."),
    "unprobeable": (409, "No completed SABnzbd history entry matches this download."),
    "unreachable": (503, "SABnzbd could not be reached. Try again once it is up."),
    "unplaced": (409, "SABnzbd finished, but the completed file is not in a folder Comicarr can import."),
    "not-sab": (409, "Retry post-processing is available for SABnzbd downloads."),
    "not-won": (409, "This download changed while post-processing was being queued. Refresh and try again."),
    "not-complete": (409, "SABnzbd has not completed this download."),
    "absent": (409, "SABnzbd history no longer has this download."),
}


def retry_postprocess(release_key):
    """Operator retry from Activity → In Flight. Reuses the reconcile queue."""
    key = str(release_key or "").strip()
    if not key:
        raise RetryPostProcessError("release_key is required", status_code=400)
    row = journal.read_one(key)
    if row is None:
        raise RetryPostProcessError(_RETRY_ERRORS["missing"][1], status_code=404)
    result = queue_completed_postprocess(row)
    action = result.get("action")
    if action == "enqueued":
        return {"success": True, "release_key": key, "action": action}
    status_code, message = _RETRY_ERRORS.get(action, (409, "Could not retry post-processing."))
    if action == "unplaced" and result.get("error"):
        message = result["error"]
    raise RetryPostProcessError(message, status_code=status_code)
