#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Own post-processing execution, restart continuation, and completion."""

from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps

import comicarr
from comicarr import logger
from comicarr.app.attention import ManualReview, record
from comicarr.app.downloads import journal
from comicarr.app.downloads.pp_commands import PostProcessCommandError, validate_postprocess_item

__all__ = ["PostProcessResult", "run", "recover"]

_MAX_INLINE_PP_REDRIVE_PER_PASS = 5
_RECOVERY_BUDGET = ContextVar("postprocessing_recovery_budget", default=None)


@dataclass(frozen=True)
class PostProcessResult:
    status: str
    value: object = None
    detail: str | None = None
    action: str | None = None
    redriven: bool = False


def _recovery_pass(function):
    """Private replay adapter: bound expensive work for one startup pass."""

    @wraps(function)
    def replay(*args, **kwargs):
        token = _RECOVERY_BUDGET.set({"count": 0})
        try:
            return function(*args, **kwargs)
        finally:
            _RECOVERY_BUDGET.reset(token)

    return replay


def _execute(item, ownership):
    from comicarr import postprocessor, process

    if item.get("source") in {"compat", "monitor"}:
        import queue

        if item.get("failed"):
            return None
        result_queue = queue.Queue()
        processor = postprocessor.PostProcessor(
            item["nzb_name"],
            item["nzb_folder"],
            item.get("issueid"),
            queue=result_queue,
            comicid=item.get("comicid"),
            apicall=item.get("apicall", False),
            ddl=item.get("ddl", False),
            journal_release_key=item.get("journal_release_key"),
            ownership=ownership,
        )
        processor.Process()
        return None if result_queue.empty() else result_queue.get_nowait()
    processor = process.Process(
        item["nzb_name"],
        item["nzb_folder"],
        item.get("failed", False),
        item.get("issueid"),
        item.get("comicid"),
        item.get("apicall", False),
        item.get("ddl", False),
        item.get("download_info"),
        journal_release_key=item.get("journal_release_key"),
        ownership=ownership,
    )
    return processor.post_process()


def _quarantine(item, reason, release_key=None):
    if not isinstance(item, dict):
        return
    key = release_key or item.get("journal_release_key")
    try:
        key = key or journal.derive_release_key(item)
        record(
            ManualReview(
                release_key=key,
                reason=reason,
                payload=item,
                issue_id=item.get("issueid"),
                provider=item.get("provider"),
            )
        )
    except Exception as e:
        logger.error("[POST-PROCESSING] Unable to record failure for %s: %s", key, type(e).__name__)


def _command(row, payload):
    payload = payload or {}
    return {
        "nzb_name": payload.get("nzb_name") or payload.get("nzbname") or row.get("nzbname"),
        "nzb_folder": payload.get("nzb_folder"),
        "failed": payload.get("failed", False),
        "issueid": payload.get("issueid") or row.get("issueid"),
        "comicid": payload.get("comicid"),
        "provider": row.get("provider"),
        "apicall": payload.get("apicall", True),
        "ddl": payload.get("ddl", False),
        "download_info": payload.get("download_info"),
        "journal_release_key": row["release_key"],
    }


def run(request):
    """Process new work; a busy attempt leaves its journal claim untouched.

    A supplied release key is authoritative. Unjournaled requests retain the
    legacy status fallback if the journal claim cannot be written.
    """
    from comicarr.app.acquisition.maintenance import MaintenanceBlocked, MaintenanceController

    try:
        item = validate_postprocess_item(request)
    except PostProcessCommandError as e:
        _quarantine(request, "invalid_postprocess_command:%s" % type(e).__name__)
        return PostProcessResult("failed", detail=str(e))

    key = item.get("journal_release_key") or journal.derive_release_key(
        {
            "issueid": item.get("issueid"),
            "comicid": item.get("comicid"),
            "nzbname": item["nzb_name"],
        }
    )
    lock = comicarr.APILOCK
    if not lock.acquire(blocking=False):
        return PostProcessResult("busy", detail="Post-processing is busy; retry later", action="retry")
    controller = None
    lease = None
    try:
        controller = MaintenanceController()
        lease = controller.acquire_lease("postprocess-worker", "postprocess", entity_type="release", entity_id=key)
        controller.assert_lease_current(lease)
        item = validate_postprocess_item(item)
        if item.get("source") in {"manual", "compat", "monitor"} and not item.get("journal_release_key"):
            # A manual folder can discover many releases on successive runs.
            # Claiming its display name would suppress every subsequent scan.
            item["journal_release_key"] = None
            return PostProcessResult("processed", value=_execute(item, object()))
        try:
            won = journal.record_transition(
                key,
                journal.POST_PROCESSING,
                payload={
                    k: item.get(k)
                    for k in (
                        "nzb_name",
                        "nzb_folder",
                        "failed",
                        "issueid",
                        "comicid",
                        "apicall",
                        "ddl",
                        "download_info",
                    )
                },
                issueid=item.get("issueid"),
            )
        except Exception as e:
            if item.get("journal_release_key"):
                logger.error("[POST-PROCESSING] Claim unavailable for %s: %s", key, type(e).__name__)
                return PostProcessResult("busy", detail="Processing journal unavailable; retry later", action="retry")
            logger.warn(
                "[POST-PROCESSING] Manual journal unavailable; using existing status checks: %s", type(e).__name__
            )
            key = None
            won = True
        if not won:
            return PostProcessResult("duplicate")
        item["journal_release_key"] = key
        return PostProcessResult("processed", value=_execute(item, object()))
    except MaintenanceBlocked:
        return PostProcessResult(
            "busy", detail="Post-processing is paused for maintenance; retry later", action="retry"
        )
    except PostProcessCommandError as e:
        _quarantine(item, "invalid_postprocess_command:%s" % type(e).__name__, key)
        return PostProcessResult("failed", detail=str(e))
    except Exception as e:
        _quarantine(item, "postprocess_error:%s" % type(e).__name__, key)
        logger.error("[POST-PROCESSING] Execution failed: %s", e)
        return PostProcessResult("failed", detail=str(e))
    finally:
        try:
            if lease is not None:
                controller.release_lease(lease.lease_id)
        finally:
            lock.release()


def recover(release_key):
    """Continue authoritative journal state without repeating a fresh claim."""
    from comicarr.app.acquisition.maintenance import MaintenanceBlocked, MaintenanceController
    from comicarr.app.downloads._postprocess_completion import finish_obligation, obligation_already_fulfilled

    lock = comicarr.APILOCK
    if not lock.acquire(blocking=False):
        return PostProcessResult("busy", detail="Post-processing is busy; retry later", action="post_processing-busy")
    controller = None
    lease = None
    item = None
    redriven = False
    try:
        controller = MaintenanceController()
        lease = controller.acquire_lease(
            "startup-recovery",
            "postprocess-redrive",
            entity_type="release",
            entity_id=release_key,
        )
        controller.assert_lease_current(lease)
        row = journal.read_one(release_key)
        if not row or row.get("stage") not in {journal.MOVED, journal.POST_PROCESSING}:
            return PostProcessResult("ignored", action="ignored")
        payload = journal.load_payload(row.get("payload_json"))
        if row["stage"] == journal.MOVED or obligation_already_fulfilled(row):
            finish_obligation(release_key, row, payload)
            action = "moved-finish-dbfacts" if row["stage"] == journal.MOVED else "post_processing-already-fulfilled"
            return PostProcessResult("processed", action=action)
        budget = _RECOVERY_BUDGET.get()
        if budget is not None and budget["count"] >= _MAX_INLINE_PP_REDRIVE_PER_PASS:
            return PostProcessResult("busy", action="skip-pp-cap-deferred", detail="Startup processing budget reached")
        item = _command(row, payload)
        try:
            item = validate_postprocess_item(item)
        except PostProcessCommandError as e:
            _quarantine(item, "invalid_recovered_postprocess_command:%s" % type(e).__name__, release_key)
            return PostProcessResult("failed", detail=str(e), action="post_processing-manual-review")
        if budget is not None:
            budget["count"] += 1
        redriven = True
        value = _execute(item, object())
        return PostProcessResult("processed", value=value, action="post_processing-redrive", redriven=True)
    except MaintenanceBlocked:
        return PostProcessResult(
            "busy", detail="Post-processing is paused for maintenance", action="post_processing-busy"
        )
    except Exception as e:
        if item is None:
            raise
        _quarantine(item, "recovered_postprocess_error:%s" % type(e).__name__, release_key)
        return PostProcessResult("failed", detail=str(e), action="post_processing-manual-review", redriven=redriven)
    finally:
        try:
            if lease is not None:
                controller.release_lease(lease.lease_id)
        finally:
            lock.release()
