#  Copyright (C) 2012–2024 Mylar3 contributors
#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Originally based on Mylar3 (https://github.com/mylar3/mylar3).
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.


import datetime

import comicarr
from comicarr import helpers, logger, weeklypull


def _weekly_runtime_context():
    """Return the canonical context when lifecycle startup has completed."""
    from comicarr.app.core.runtime import get_runtime_if_initialized

    ctx = get_runtime_if_initialized()
    return ctx if ctx is not None and not ctx.disposed else None


def _get_weekly_runtime_value(context_field, legacy_name):
    """Read canonical weekly state, with a pre-factory legacy fallback."""
    ctx = _weekly_runtime_context()
    if ctx is not None:
        return getattr(ctx, context_field)
    return getattr(comicarr, legacy_name)


def _set_weekly_runtime_value(context_field, legacy_name, value):
    """Write weekly state once and project the same value to legacy callers."""
    ctx = _weekly_runtime_context()
    if ctx is not None:
        from comicarr.app.core.runtime import set_runtime_field

        return set_runtime_field(ctx, context_field, value)
    setattr(comicarr, legacy_name, value)
    return value


def _restore_manual_next_run():
    """Restore the recurring schedule displaced by an immediate manual run."""
    scheduled_run = _get_weekly_runtime_value("weekly_manual_next_run", "WEEKLY_MANUAL_NEXT_RUN")
    _set_weekly_runtime_value("weekly_manual_next_run", "WEEKLY_MANUAL_NEXT_RUN", None)
    if not isinstance(scheduled_run, datetime.datetime):
        return

    now = datetime.datetime.now(tz=scheduled_run.tzinfo) if scheduled_run.tzinfo else datetime.datetime.utcnow()
    if scheduled_run <= now:
        return

    try:
        scheduler = _get_weekly_runtime_value("scheduler", "SCHED")
        job = scheduler.get_job("weekly") if scheduler is not None else None
        if job is not None:
            job.modify(next_run_time=scheduled_run)
    except Exception as e:
        logger.error("[WEEKLY] Could not restore scheduled refresh time: %s" % e)


def _honor_upstream_retry(retry_after):
    """Move the weekly job's next run earlier when upstream asked for a sooner retry.

    Only ever pulls the schedule forward - a hint later than the regular next
    run is ignored, as is anything beyond an hour, where the normal interval
    is the better retry anyway.
    """
    try:
        seconds = int(retry_after)
    except (TypeError, ValueError):
        return
    if seconds <= 0 or seconds > 3600:
        return
    seconds = max(seconds, 60)
    try:
        scheduler = _get_weekly_runtime_value("scheduler", "SCHED")
        job = scheduler.get_job("weekly") if scheduler is not None else None
        if job is None:
            return
        next_run = getattr(job, "next_run_time", None)
        if next_run is not None and next_run.tzinfo is not None:
            now = datetime.datetime.now(tz=next_run.tzinfo)
        else:
            now = datetime.datetime.utcnow()
        retry_at = now + datetime.timedelta(seconds=seconds)
        if next_run is not None and next_run <= retry_at:
            return
        job.modify(next_run_time=retry_at)
        logger.info(
            "[WEEKLY] Upstream asked for a retry in %s seconds - next pull-list check moved up to %s."
            % (seconds, retry_at.strftime("%Y-%m-%d %H:%M:%S"))
        )
    except Exception as e:
        logger.error("[WEEKLY] Could not honor upstream retry request: %s" % e)


class Weekly:
    def __init__(self):
        pass

    def run(self):
        from comicarr.app.system.service import get_weekly_refresh_lock

        with get_weekly_refresh_lock():
            logger.info("[WEEKLY] Checking Weekly Pull-list for new releases/updates")
            helpers.job_management(
                write=True, job="Weekly Pullist", current_run=helpers.utctimestamp(), status="Running"
            )
            _set_weekly_runtime_value("weekly_status", "WEEKLY_STATUS", "Running")
            retry_hint = None
            try:
                pull_result = weeklypull.pullit()
                if isinstance(pull_result, dict):
                    retry_hint = pull_result.get("retry_after")
                    if pull_result.get("status") == "failure":
                        raise RuntimeError("Weekly pull source reported a failure")
                weeklypull.future_check()
            except Exception as e:
                logger.error("[WEEKLY] Pull-list refresh failed: %s" % e)
                _restore_manual_next_run()
                _honor_upstream_retry(retry_hint)
                helpers.job_management(
                    write=True,
                    job="Weekly Pullist",
                    last_run_completed=helpers.utctimestamp(),
                    status="Error",
                    failure=True,
                    failure_message=e,
                )
                _set_weekly_runtime_value("weekly_status", "WEEKLY_STATUS", "Error")
                raise

            _restore_manual_next_run()
            _honor_upstream_retry(retry_hint)
            helpers.job_management(
                write=True, job="Weekly Pullist", last_run_completed=helpers.utctimestamp(), status="Waiting"
            )
            _set_weekly_runtime_value("weekly_status", "WEEKLY_STATUS", "Waiting")
