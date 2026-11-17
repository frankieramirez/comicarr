#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The mass-add and refresh worker queues.

Moved from ``comicarr/importer.py`` (#1464). ``queue_series_adds`` was
``importer_thread``, ``queue_issue_wants`` was ``issue_watcher_thread``,
``queue_refreshes`` was ``refresh_thread`` and ``run_mass_add_queue`` was
``addvialist``. The refresh worker itself is
``app/series/watchlist_refresh.run_refresh_queue``.
"""

import re
import threading
import time
import uuid
from collections.abc import Mapping

import comicarr
from comicarr.app.core import logger
from comicarr.app.series import comic_add, watchlist_refresh
from comicarr.app.series.add_activity import emit_add_activity


def _mass_add_runtime_context():
    """Return the active canonical runtime, if the process has one."""
    from comicarr.app.core.runtime import get_runtime_if_initialized

    ctx = get_runtime_if_initialized()
    return ctx if ctx is not None and not ctx.disposed else None


def _set_mass_add_pool(ctx, pool):
    """Publish the same MASS_ADD worker reference to runtime and legacy code."""
    if ctx is None:
        comicarr.MASS_ADD = pool
        return

    from comicarr.app.core.runtime import set_runtime_field

    set_runtime_field(ctx, "mass_add_pool", pool)


def _set_mass_refresh_pool(ctx, pool):
    """Publish the same MASS_REFRESH worker reference to runtime and legacy code."""
    if ctx is None:
        comicarr.MASS_REFRESH = pool
        return

    from comicarr.app.core.runtime import set_runtime_field

    set_runtime_field(ctx, "mass_refresh_pool", pool)


def run_mass_add_queue(seriesQueue, issueWantQueue):
    while True:
        if seriesQueue.qsize() >= 1:
            time.sleep(3)
            item = seriesQueue.get(True)
            if item == "exit":
                break
            seriesyear = item.get("seriesyear")
            if item["comicname"] is not None:
                if seriesyear is not None:
                    logger.info(
                        "[MASS-ADD][1/%s] Now adding %s (%s) [%s] "
                        % (seriesQueue.qsize() + 1, item["comicname"], seriesyear, item["comicid"])
                    )
                else:
                    logger.info(
                        "[MASS-ADD][1/%s] Now adding %s [%s] "
                        % (seriesQueue.qsize() + 1, item["comicname"], item["comicid"])
                    )
            else:
                logger.info("[MASS-ADD][1/%s] Now adding ComicID: %s " % (seriesQueue.qsize() + 1, item["comicid"]))

            try:
                add_kwargs = {}
                if "suppress_addall" in item.keys():
                    add_kwargs["suppress_addall"] = item["suppress_addall"]
                if item.get("location"):
                    add_kwargs["location"] = item["location"]
                comic_add.add_comic(item["comicid"], **add_kwargs)
                if item.get("want"):
                    # Riding on the add item keeps the want behind its add with
                    # no second queue for the worker to retire past.
                    comic_add.mark_series_wanted(re.sub("^4050-", "", str(item["comicid"])))
            except Exception as e:
                logger.error("[MASS-ADD] Failed adding %s: %s" % (item["comicid"], e))
                emit_add_activity("failed", item["comicid"], comicname=item.get("comicname"), reason_detail=str(e))
        elif issueWantQueue.qsize() > 0:
            time.sleep(1)
            issueItem = issueWantQueue.get(True)
            comic_add.mark_issue_wanted(issueItem)
        elif mass_add_worker_should_retire(seriesQueue, issueWantQueue):
            break
    return False


_MASS_ADD_WORKER_LOCK = threading.RLock()


def mass_add_worker_should_retire(series_queue, issue_queue):
    """Atomically decide whether an idle mass-add worker may exit.

    Producers hold the same lock while enqueueing and checking liveness, so an
    add cannot land between the worker's empty check and its retirement and
    then sit on the queue with no worker to run it (#1322).
    """
    with _MASS_ADD_WORKER_LOCK:
        if not series_queue.empty() or not issue_queue.empty():
            return False
        ctx = _mass_add_runtime_context()
        worker = ctx.mass_add_pool if ctx is not None else getattr(comicarr, "MASS_ADD", None)
        if worker is threading.current_thread():
            _set_mass_add_pool(ctx, None)
        return True


def queue_series_adds(serieslist):

    if type(serieslist) != list:
        serieslist = [(serieslist)]

    with _MASS_ADD_WORKER_LOCK:
        ctx = _mass_add_runtime_context()
        add_list = ctx.add_list if ctx is not None else comicarr.ADD_LIST
        issue_watch_list = ctx.issue_watch_list if ctx is not None else comicarr.ISSUE_WATCH_LIST

        for series in serieslist:
            add_list.put(series)

        pool = ctx.mass_add_pool if ctx is not None else getattr(comicarr, "MASS_ADD", None)
        if pool is not None and getattr(pool, "is_alive", lambda: False)():
            logger.info(
                "[MASS-ADD] MASS_ADD thread already running. Adding an additional %s items to existing queue"
                % len(serieslist)
            )
            return

        logger.info("[MASS-ADD] MASS_ADD thread not started. Started & submitting.")
        pool = threading.Thread(target=run_mass_add_queue, args=(add_list, issue_watch_list), name="mass-add")
        _set_mass_add_pool(ctx, pool)
        pool.start()


def queue_issue_wants(issuelist):
    if type(issuelist) != list:
        issuelist = [issuelist]

    with _MASS_ADD_WORKER_LOCK:
        ctx = _mass_add_runtime_context()
        issue_watch_list = ctx.issue_watch_list if ctx is not None else comicarr.ISSUE_WATCH_LIST
        for issue in issuelist:
            issue_watch_list.put(issue)


_REFRESH_WORKER_LOCK = threading.RLock()


def _start_refresh_worker():
    """Start the on-demand worker under the same lock used for retirement."""
    with _REFRESH_WORKER_LOCK:
        ctx = _mass_add_runtime_context()
        worker = ctx.mass_refresh_pool if ctx is not None else getattr(comicarr, "MASS_REFRESH", None)
        if worker is not None and getattr(worker, "is_alive", lambda: False)():
            return False
        logger.info("[MASS-REFRESH] MASS_REFRESH thread not started. Started & submitting.")
        refresh_queue = ctx.refresh_queue if ctx is not None else comicarr.REFRESH_QUEUE
        worker = threading.Thread(
            target=watchlist_refresh.run_refresh_queue, args=(refresh_queue,), name="mass-refresh"
        )
        _set_mass_refresh_pool(ctx, worker)
        worker.start()
        return True


def refresh_worker_should_retire(refresh_queue):
    """Atomically decide whether an idle refresh worker may exit.

    Producers hold the same lock while enqueueing and checking liveness, so a
    command cannot land between the worker's empty check and its retirement.
    """
    with _REFRESH_WORKER_LOCK:
        if not refresh_queue.empty():
            return False
        ctx = _mass_add_runtime_context()
        worker = ctx.mass_refresh_pool if ctx is not None else getattr(comicarr, "MASS_REFRESH", None)
        if worker is threading.current_thread():
            _set_mass_refresh_pool(ctx, None)
        return True


def _handoff_refresh_items(queue_items, *, start_worker, maintenance=None):
    from comicarr.app.acquisition.maintenance import MaintenanceController

    if not queue_items:
        return
    controller = maintenance or MaintenanceController()
    with controller.lease(
        "refresh-producer",
        work_kind="refresh_queue_handoff",
        entity_type="run",
        entity_id=queue_items[0]["run_id"],
    ) as lease:
        controller.assert_lease_current(lease)
        with _REFRESH_WORKER_LOCK:
            ctx = _mass_add_runtime_context()
            refresh_queue = ctx.refresh_queue if ctx is not None else comicarr.REFRESH_QUEUE
            for queue_item in queue_items:
                refresh_queue.put(queue_item)
            if start_worker:
                _start_refresh_worker()


def _refresh_payload(raw_values):
    if not isinstance(raw_values, Mapping):
        raise ValueError("refresh command must be an object")
    values = {str(key).lower(): value for key, value in raw_values.items()}
    comicid = values.get("comicid")
    if comicid in (None, ""):
        raise ValueError("refresh command is missing comicid")
    payload = {
        "comicid": str(comicid),
        "comicname": values.get("comicname"),
        "seriesyear": values.get("seriesyear"),
    }
    for field in ("r_mode", "calledfrom", "serieslast_updated", "manual_comicid"):
        if field in values:
            payload[field] = values[field]
    return payload


def queue_refreshes(
    serieslist,
    *,
    ledger=None,
    run_id=None,
    trigger="refresh_thread",
    start_worker=True,
    maintenance=None,
):
    """Persist refresh obligations before handing them to the worker queue."""
    from comicarr.app.acquisition.models import DispatchState
    from comicarr.app.acquisition.runs import RunLedger

    if not isinstance(serieslist, list):
        serieslist = [serieslist]
    if not serieslist:
        return None

    ledger = ledger or RunLedger()
    effective_run_id = str(run_id or uuid.uuid4())
    ledger.create_run(effective_run_id, command_kind="refresh", trigger=trigger, scope_type="series_batch")
    queued = []
    for raw_item in serieslist:
        payload = _refresh_payload(raw_item)
        ledger.accept_item(
            effective_run_id,
            entity_type="series",
            entity_id=payload["comicid"],
            payload=payload,
        )
        queue_item = {**payload, "run_id": effective_run_id}
        queued.append(queue_item)
    try:
        _handoff_refresh_items(queued, start_worker=start_worker, maintenance=maintenance)
    except Exception:
        ledger.record_dispatch(effective_run_id, DispatchState.ERROR)
        raise
    ledger.record_dispatch(effective_run_id, DispatchState.ACCEPTED)
    return effective_run_id


def replay_refresh_obligations(*, ledger=None, start_worker=True, maintenance=None):
    """Restore accepted/running refresh obligations after a process restart."""
    from comicarr.app.acquisition.models import DispatchState, ItemOutcome
    from comicarr.app.acquisition.runs import RunLedger

    ledger = ledger or RunLedger()
    queue_items = []
    replayed_run_ids = set()
    for item in ledger.list_recoverable_items("refresh"):
        run_id = item["run_id"]
        entity_id = item["entity_id"]
        if not ledger.claim_recovery(item):
            continue
        try:
            payload = _refresh_payload(item["payload"] or {})
        except ValueError as e:
            ledger.record_outcome(run_id, "series", entity_id, ItemOutcome.QUARANTINED, reason=str(e))
            continue
        if item["state"] == ItemOutcome.RUNNING.value:
            ledger.record_requeue(run_id, "series", entity_id, reason="worker restart", replay=True)
        queue_items.append({**payload, "run_id": run_id})
        replayed_run_ids.add(run_id)
    _handoff_refresh_items(queue_items, start_worker=start_worker, maintenance=maintenance)
    for run_id in replayed_run_ids:
        ledger.record_dispatch(run_id, DispatchState.ACCEPTED)
    return len(queue_items)
