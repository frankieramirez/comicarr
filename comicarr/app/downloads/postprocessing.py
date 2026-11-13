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
from dataclasses import dataclass, replace
from functools import wraps

import comicarr
from comicarr import logger
from comicarr.app.attention import ManualReview, record
from comicarr.app.common.redaction import redacted_traceback
from comicarr.app.downloads import journal
from comicarr.app.downloads.pp_commands import PostProcessCommandError, validate_postprocess_item

__all__ = ["PostProcessResult", "run", "recover"]

_MAX_INLINE_PP_REDRIVE_PER_PASS = 5
_RECOVERY_BUDGET = ContextVar("postprocessing_recovery_budget", default=None)


# What a run did, carried on ``PostProcessResult.outcome``.
COMPLETED = "completed"  # the processor ran to its end
FAILED = "failed"  # the download failed or processing raised; see fail_reason
DEFERRED = "deferred"  # nothing ran yet; the caller retries or defers
NOTHING = "nothing"  # nothing to do: duplicate, ignored, or no message


@dataclass(frozen=True)
class PostProcessResult:
    status: str
    value: object = None
    detail: str | None = None
    action: str | None = None
    outcome: str | None = None
    fail_reason: str | None = None


@dataclass(frozen=True)
class _Execution:
    """What one processing pass did. ``value`` is the processor's last message."""

    outcome: str
    value: object = None
    fail_reason: str | None = None


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


def _mode(message):
    """The ``mode`` of a legacy processor message, or None."""
    if isinstance(message, dict):
        message = [message]
    if not isinstance(message, (list, tuple)) or not message or not isinstance(message[0], dict):
        return None
    return message[0].get("mode")


def _run_processor(item, *, outside=False):
    """Run the folder processor once and return its message, or None.

    ``outside`` is the retry the processor asks for when the download sits
    outside the folder it was given: the folder is processed again as a
    manual run with no issue identity.
    """
    from comicarr import postprocessor
    from comicarr.app.downloads.postprocess_pipeline import PostProcessRequest, process_download

    if outside:
        request = PostProcessRequest(
            "Manual Run", item["nzb_folder"], journal_release_key=item.get("journal_release_key")
        )
    else:
        request = PostProcessRequest(
            item["nzb_name"],
            item["nzb_folder"],
            issue_id=item.get("issueid"),
            comic_id=item.get("comicid"),
            api_call=item.get("apicall", False),
            ddl=item.get("ddl", False),
            journal_release_key=item.get("journal_release_key"),
        )
    return process_download(request, match=postprocessor.match_folder, deps=postprocessor.pipeline_deps())


def _ran(message):
    if message is None:
        return _Execution(NOTHING)
    if _mode(message) == "fail":
        return _Execution(FAILED, value=message)
    return _Execution(COMPLETED, value=message)


def _journal_fail_reason(release_key):
    if not release_key:
        return None
    try:
        row = journal.read_one(release_key)
    except Exception as e:
        logger.warn("[POST-PROCESSING] Could not read fail reason for %s: %s", release_key, type(e).__name__)
        return None
    return (row or {}).get("fail_reason")


def _handle_failed_download(item):
    """Hand a failed download to ``FailedProcessor``, or record it as left alone."""
    # Lazy: the service module imports this one.
    from comicarr.app.downloads import service

    if comicarr.CONFIG.FAILED_DOWNLOAD_HANDLING is not True:
        logger.warn("[POST-PROCESSING] Failed Download Handling is not enabled. Leaving Failed Download as-is.")
        return _Execution(FAILED, fail_reason=service.terminalize_unhandled_failed_download(item))
    logger.info("[POST-PROCESSING] Initiating Failed Download handling for this download.")
    message = service.run_failed_processor(item)
    mode = _mode(message)
    if mode == "retry":
        logger.info("[POST-PROCESSING] Attempting to return to search module with %s" % message[0]["issueid"])
        from comicarr.app.search.commands import enqueue_failed_download_retry

        enqueue_failed_download_retry(message[0])
    elif mode not in (None, "stop"):
        logger.error("[POST-PROCESSING] mode is unsupported: %s" % mode)
    return _Execution(FAILED, value=message, fail_reason=_journal_fail_reason(item.get("journal_release_key")))


def _post_process(item):
    """Process a download: the folder, then failed handling or the outside retry."""
    failed = item.get("failed", False)
    if failed == "0":
        failed = False
    elif failed == "1":
        failed = True

    execution = _Execution(NOTHING)
    outside = False
    if failed is False:
        message = _run_processor(item)
        execution = _ran(message)
        mode = _mode(message)
        if mode == "fail":
            logger.info("[POST-PROCESSING] Initiating Failed Download handling")
            failed = True
        elif mode == "outside":
            outside = True
        elif mode not in (None, "stop"):
            logger.error("[POST-PROCESSING] mode is unsupported: %s" % mode)

    if failed is True:
        handled = _handle_failed_download(item)
        # Handling that posts no message of its own keeps the processor's.
        execution = handled if handled.value is not None else replace(handled, value=execution.value)

    if outside:
        message = _run_processor(item, outside=True)
        execution = _ran(message)
        if _mode(message) not in (None, "stop", "fail"):
            logger.error("[POST-PROCESSING] mode is unsupported: %s" % _mode(message))
    return execution


def _execute(item):
    """Run one request; None means nothing ran."""
    if item.get("source") in {"compat", "monitor"}:
        if item.get("failed"):
            return None
        return _ran(_run_processor(item))
    return _post_process(item)


def _processed(execution, action=None):
    if execution is None:
        execution = _Execution(NOTHING)
    return PostProcessResult(
        "processed",
        value=execution.value,
        action=action,
        outcome=execution.outcome,
        fail_reason=execution.fail_reason,
    )


def _is_unjournaled(item):
    return (
        isinstance(item, dict)
        and item.get("source") in {"manual", "compat", "monitor"}
        and not item.get("journal_release_key")
    )


def _stamp_attention_import(item, *, succeeded=False):
    if not isinstance(item, dict):
        return
    band_key = item.get("attention_release_key")
    if not band_key:
        return
    attempt_key = item.get("journal_release_key")
    if not succeeded and attempt_key and str(band_key) == str(attempt_key):
        return
    try:
        journal.stamp_resolution(band_key, journal.STATUS_IMPORTED)
    except Exception as e:
        logger.warn("[POST-PROCESSING] Could not stamp attention import %s: %s", band_key, e)


def _failed_import_redrive(item, key):
    """True when Import is retrying the same attempt row after a failed claim."""
    if not key or not isinstance(item, dict):
        return False
    if "|import:" not in str(key) or not item.get("attention_release_key"):
        return False
    row = journal.read_one(key)
    if not row or row.get("status") in journal.RESOLVED_STATUSES:
        return False
    return row.get("stage") == journal.MANUAL_REVIEW


def _quarantine(item, reason, release_key=None):
    if not isinstance(item, dict):
        return
    if _is_unjournaled(item) and not release_key:
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


def _log_failure(key, step, item, error):
    logger.error(
        "[POST-PROCESSING] Execution failed for %s during %s (nzb_name=%s, nzb_folder=%s)\n%s",
        key,
        step,
        item.get("nzb_name"),
        item.get("nzb_folder"),
        redacted_traceback(error),
    )


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


def _recovery_count(payload):
    try:
        return int((payload or {}).get("recovery_count") or 0)
    except (TypeError, ValueError):
        return 0


def _legacy_stop_result(value):
    entries = value
    if isinstance(value, dict):
        entries = [value]
    if not isinstance(entries, (list, tuple)) or not entries:
        return False
    first = entries[0]
    return isinstance(first, dict) and first.get("mode") == "stop"


def _claim_recovery(release_key, item, payload):
    """Count one restart re-drive, or quarantine once the bound is spent."""
    # Lazy: helpers -> downloads.service -> this module, so a module-level
    # import of runs would cycle at startup.
    from comicarr.app.acquisition.runs import MAX_RECOVERY_ATTEMPTS

    recovered = _recovery_count(payload)
    if recovered >= MAX_RECOVERY_ATTEMPTS:
        _quarantine(item, "recovery_attempts_exhausted:post_processing", release_key)
        return False
    next_payload = dict(payload or {})
    next_payload["recovery_count"] = recovered + 1
    journal.record_transition(release_key, journal.POST_PROCESSING, payload=next_payload)
    return True


def _note_unfinished_claim(release_key, value):
    """Rotate an expected stop (or other unfinished claim) out of oldest-first order."""
    if not release_key:
        return
    row = journal.read_one(release_key)
    if not row or row.get("stage") != journal.POST_PROCESSING:
        return
    payload = journal.load_payload(row.get("payload_json")) or {}
    if _legacy_stop_result(value):
        payload["fail_detail"] = "postprocess_stopped"
    else:
        payload.setdefault("fail_detail", "postprocess_unfinished")
    journal.record_transition(release_key, journal.POST_PROCESSING, payload=payload)


def _try_note_unfinished_claim(release_key, value):
    """Rotation bookkeeping must not change a completed run's outcome."""
    try:
        _note_unfinished_claim(release_key, value)
    except Exception as e:
        logger.warn(
            "[POST-PROCESSING] Unable to rotate unfinished claim for %s: %s",
            release_key,
            type(e).__name__,
        )


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
        return PostProcessResult("failed", detail=str(e), outcome=FAILED, fail_reason="invalid_postprocess_command")

    unjournaled = _is_unjournaled(item)
    key = None
    if not unjournaled:
        key = item.get("journal_release_key") or journal.derive_release_key(
            {
                "issueid": item.get("issueid"),
                "comicid": item.get("comicid"),
                "nzbname": item["nzb_name"],
            }
        )
    lock = comicarr.APILOCK
    if not lock.acquire(blocking=False):
        return PostProcessResult(
            "busy", detail="Post-processing is busy; retry later", action="retry", outcome=DEFERRED
        )
    controller = None
    lease = None
    step = "maintenance lease"
    try:
        controller = MaintenanceController()
        lease = controller.acquire_lease("postprocess-worker", "postprocess", entity_type="release", entity_id=key)
        controller.assert_lease_current(lease)
        item = validate_postprocess_item(item)
        if unjournaled:
            # A manual folder can discover many releases on successive runs.
            # Claiming its display name would suppress every subsequent scan.
            item["journal_release_key"] = None
            step = "process"
            return _processed(_execute(item))
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
                        "provider",
                        "apicall",
                        "ddl",
                        "download_info",
                        "attention_release_key",
                    )
                },
                issueid=item.get("issueid"),
                provider=item.get("provider"),
            )
        except Exception as e:
            if item.get("journal_release_key"):
                logger.error("[POST-PROCESSING] Claim unavailable for %s: %s", key, type(e).__name__)
                return PostProcessResult(
                    "busy", detail="Processing journal unavailable; retry later", action="retry", outcome=DEFERRED
                )
            logger.warn(
                "[POST-PROCESSING] Manual journal unavailable; using existing status checks: %s", type(e).__name__
            )
            key = None
            won = True
        if not won and not _failed_import_redrive(item, key):
            return PostProcessResult("duplicate", outcome=NOTHING)
        item["journal_release_key"] = key
        step = "process"
        execution = _execute(item)
        _try_note_unfinished_claim(key, execution.value if execution else None)
        _stamp_attention_import(item, succeeded=True)
        return _processed(execution)
    except MaintenanceBlocked:
        return PostProcessResult(
            "busy",
            detail="Post-processing is paused for maintenance; retry later",
            action="retry",
            outcome=DEFERRED,
        )
    except PostProcessCommandError as e:
        _quarantine(item, "invalid_postprocess_command:%s" % type(e).__name__, key)
        _stamp_attention_import(item)
        return PostProcessResult("failed", detail=str(e), outcome=FAILED, fail_reason="invalid_postprocess_command")
    except Exception as e:
        _quarantine(item, "postprocess_error:%s" % type(e).__name__, key)
        _stamp_attention_import(item)
        _log_failure(key, step, item, e)
        return PostProcessResult("failed", detail=str(e), outcome=FAILED, fail_reason="postprocess_error")
    finally:
        try:
            if lease is not None:
                controller.release_lease(lease.lease_id)
        finally:
            lock.release()


def _recover_arc_copy(release_key, row, payload):
    """Finish an owed story-arc copy from the placed library file.

    The library issue completed before the restart, so the download is never
    re-processed: the copy is made (or recorded) from the journal row alone.
    A failed copy leaves the row owed for the next pass.
    """
    from comicarr.app.downloads.postprocess_pipeline import recover_arc_copy
    from comicarr.app.storyarcs import ArcCopyError

    try:
        recover_arc_copy(release_key, row, payload)
    except ArcCopyError as e:
        logger.warn("[POST-PROCESSING] Story-arc copy for %s is still owed: %s", release_key, e)
        return PostProcessResult("failed", detail=str(e), action="arc-copy-owed", outcome=DEFERRED)
    return PostProcessResult("processed", action="arc-copy-finished", outcome=COMPLETED)


def recover(release_key):
    """Continue authoritative journal state without repeating a fresh claim."""
    from comicarr.app.acquisition.maintenance import MaintenanceBlocked, MaintenanceController
    from comicarr.app.downloads._postprocess_completion import finish_obligation, obligation_already_fulfilled

    lock = comicarr.APILOCK
    if not lock.acquire(blocking=False):
        return PostProcessResult(
            "busy", detail="Post-processing is busy; retry later", action="post_processing-busy", outcome=DEFERRED
        )
    controller = None
    lease = None
    item = None
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
            return PostProcessResult("ignored", action="ignored", outcome=NOTHING)
        payload = journal.load_payload(row.get("payload_json"))
        if isinstance(payload, dict) and payload.get("arc_copy"):
            return _recover_arc_copy(release_key, row, payload)
        if row["stage"] == journal.MOVED or obligation_already_fulfilled(row):
            finish_obligation(release_key, row, payload)
            action = "moved-finish-dbfacts" if row["stage"] == journal.MOVED else "post_processing-already-fulfilled"
            return PostProcessResult("processed", action=action, outcome=COMPLETED)
        budget = _RECOVERY_BUDGET.get()
        if budget is not None and budget["count"] >= _MAX_INLINE_PP_REDRIVE_PER_PASS:
            return PostProcessResult(
                "busy", action="skip-pp-cap-deferred", detail="Startup processing budget reached", outcome=DEFERRED
            )
        item = _command(row, payload)
        try:
            item = validate_postprocess_item(item)
        except PostProcessCommandError as e:
            _quarantine(item, "invalid_recovered_postprocess_command:%s" % type(e).__name__, release_key)
            return PostProcessResult(
                "failed",
                detail=str(e),
                action="post_processing-manual-review",
                outcome=FAILED,
                fail_reason="invalid_recovered_postprocess_command",
            )
        if not _claim_recovery(release_key, item, payload):
            return PostProcessResult(
                "failed",
                detail="recovery_attempts_exhausted:post_processing",
                action="post_processing-manual-review",
                outcome=FAILED,
                fail_reason="recovery_attempts_exhausted",
            )
        if budget is not None:
            budget["count"] += 1
        execution = _execute(item)
        _try_note_unfinished_claim(release_key, execution.value if execution else None)
        return _processed(execution, action="post_processing-redrive")
    except MaintenanceBlocked:
        return PostProcessResult(
            "busy", detail="Post-processing is paused for maintenance", action="post_processing-busy", outcome=DEFERRED
        )
    except Exception as e:
        if item is None:
            raise
        _quarantine(item, "recovered_postprocess_error:%s" % type(e).__name__, release_key)
        _log_failure(release_key, "process", item, e)
        return PostProcessResult(
            "failed",
            detail=str(e),
            action="post_processing-manual-review",
            outcome=FAILED,
            fail_reason="recovered_postprocess_error",
        )
    finally:
        try:
            if lease is not None:
                controller.release_lease(lease.lease_id)
        finally:
            lock.release()
