"""Weekly scheduler lifecycle regression tests."""

import datetime
import threading
from unittest.mock import MagicMock

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import comicarr
from comicarr import weeklypullit
from comicarr.app.core import runtime
from comicarr.app.core.context import AppContext
from comicarr.app.system import service as system_service


def test_weekly_run_records_success_and_returns_to_waiting(monkeypatch):
    job_management = MagicMock()
    monkeypatch.setattr(weeklypullit.helpers, "job_management", job_management)
    monkeypatch.setattr(weeklypullit.helpers, "utctimestamp", lambda: 123.0)
    monkeypatch.setattr(weeklypullit.weeklypull, "pullit", MagicMock())
    monkeypatch.setattr(weeklypullit.weeklypull, "future_check", MagicMock())
    monkeypatch.setattr(comicarr, "WEEKLY_STATUS", "Queued")

    weeklypullit.Weekly().run()

    assert comicarr.WEEKLY_STATUS == "Waiting"
    assert job_management.call_args_list[-1].kwargs == {
        "write": True,
        "job": "Weekly Pullist",
        "last_run_completed": 123.0,
        "status": "Waiting",
    }


def test_weekly_run_records_failure_and_recovers_status(monkeypatch):
    job_management = MagicMock()
    monkeypatch.setattr(weeklypullit.helpers, "job_management", job_management)
    monkeypatch.setattr(weeklypullit.helpers, "utctimestamp", lambda: 456.0)
    monkeypatch.setattr(weeklypullit.weeklypull, "pullit", MagicMock(side_effect=RuntimeError("upstream down")))
    monkeypatch.setattr(weeklypullit.weeklypull, "future_check", MagicMock())
    monkeypatch.setattr(comicarr, "WEEKLY_STATUS", "Queued")

    with pytest.raises(RuntimeError, match="upstream down"):
        weeklypullit.Weekly().run()

    assert comicarr.WEEKLY_STATUS == "Error"
    failure_call = job_management.call_args_list[-1].kwargs
    assert failure_call["write"] is True
    assert failure_call["job"] == "Weekly Pullist"
    assert failure_call["last_run_completed"] == 456.0
    assert failure_call["status"] == "Error"
    assert failure_call["failure"] is True
    assert str(failure_call["failure_message"]) == "upstream down"


def test_weekly_run_records_origin_outage_cause(monkeypatch):
    job_management = MagicMock()
    monkeypatch.setattr(weeklypullit.helpers, "job_management", job_management)
    monkeypatch.setattr(weeklypullit.helpers, "utctimestamp", lambda: 456.0)
    monkeypatch.setattr(
        weeklypullit.weeklypull,
        "pullit",
        MagicMock(
            return_value={
                "status": "failure",
                "retry_after": 120,
                "origin_error": True,
                "cause": "Walksoftly is unreachable. The pull-list source is down upstream.",
            }
        ),
    )
    future_check = MagicMock()
    monkeypatch.setattr(weeklypullit.weeklypull, "future_check", future_check)

    with pytest.raises(RuntimeError, match="Walksoftly is unreachable"):
        weeklypullit.Weekly().run()

    future_check.assert_not_called()
    failure_message = str(job_management.call_args_list[-1].kwargs["failure_message"])
    assert "Walksoftly" in failure_message
    assert "upstream" in failure_message.lower()
    assert "connection" not in failure_message.lower()


def test_weekly_run_records_returned_pull_failure(monkeypatch):
    job_management = MagicMock()
    monkeypatch.setattr(weeklypullit.helpers, "job_management", job_management)
    monkeypatch.setattr(weeklypullit.helpers, "utctimestamp", lambda: 456.0)
    monkeypatch.setattr(weeklypullit.weeklypull, "pullit", MagicMock(return_value={"status": "failure"}))
    future_check = MagicMock()
    monkeypatch.setattr(weeklypullit.weeklypull, "future_check", future_check)

    with pytest.raises(RuntimeError, match="reported a failure"):
        weeklypullit.Weekly().run()

    future_check.assert_not_called()
    assert job_management.call_args_list[-1].kwargs["status"] == "Error"
    assert job_management.call_args_list[-1].kwargs["failure"] is True


def _origin_outage_failure():
    return {
        "status": "failure",
        "retry_after": 120,
        "origin_error": True,
        "cause": "Walksoftly is unreachable. The pull-list source is down upstream.",
    }


def _scheduler_job(monkeypatch, hours_ahead=4):
    now = datetime.datetime.now(datetime.timezone.utc)
    job = MagicMock()
    job.next_run_time = now + datetime.timedelta(hours=hours_ahead)
    scheduler = MagicMock()
    scheduler.get_job.return_value = job

    def runtime_value(field, _legacy):
        if field == "scheduler":
            return scheduler
        return None

    monkeypatch.setattr(weeklypullit, "_get_weekly_runtime_value", runtime_value)
    monkeypatch.setattr(weeklypullit.helpers, "job_management", MagicMock())
    monkeypatch.setattr(weeklypullit.helpers, "utctimestamp", lambda: 456.0)
    monkeypatch.setattr(weeklypullit.weeklypull, "future_check", MagicMock())
    return job


def test_first_origin_error_may_pull_schedule_forward(monkeypatch):
    job = _scheduler_job(monkeypatch)
    weeklypullit.origin_error_streak = 0
    monkeypatch.setattr(weeklypullit.weeklypull, "pullit", MagicMock(return_value=_origin_outage_failure()))

    with pytest.raises(RuntimeError, match="Walksoftly is unreachable"):
        weeklypullit.Weekly().run()

    job.modify.assert_called_once()
    new_time = job.modify.call_args.kwargs["next_run_time"]
    assert new_time < datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)


def test_second_consecutive_origin_error_does_not_pull_schedule_forward(monkeypatch):
    job = _scheduler_job(monkeypatch)
    weeklypullit.origin_error_streak = 0
    monkeypatch.setattr(weeklypullit.weeklypull, "pullit", MagicMock(return_value=_origin_outage_failure()))

    with pytest.raises(RuntimeError):
        weeklypullit.Weekly().run()
    job.modify.reset_mock()
    with pytest.raises(RuntimeError):
        weeklypullit.Weekly().run()

    job.modify.assert_not_called()


def test_cache_fallback_origin_error_stops_pulling_forward_once_streak_is_active(monkeypatch):
    job = _scheduler_job(monkeypatch)
    weeklypullit.origin_error_streak = 1
    monkeypatch.setattr(
        weeklypullit.weeklypull,
        "pullit",
        MagicMock(
            return_value={
                "status": "success",
                "retry_after": 120,
                "origin_error": True,
                "cause": "Walksoftly is unreachable. The pull-list source is down upstream.",
            }
        ),
    )

    weeklypullit.Weekly().run()

    job.modify.assert_not_called()


def test_live_success_resets_origin_error_streak_so_retry_after_can_be_honored_again(monkeypatch):
    job = _scheduler_job(monkeypatch)
    weeklypullit.origin_error_streak = 3
    monkeypatch.setattr(weeklypullit.weeklypull, "pullit", MagicMock(return_value={"status": "success"}))

    weeklypullit.Weekly().run()

    assert weeklypullit.origin_error_streak == 0
    monkeypatch.setattr(weeklypullit.weeklypull, "pullit", MagicMock(return_value=_origin_outage_failure()))
    with pytest.raises(RuntimeError):
        weeklypullit.Weekly().run()

    job.modify.assert_called_once()


def test_weekly_run_projects_running_state_before_refresh_cannot_enqueue_again(monkeypatch):
    """A manual refresh must observe the canonical Running state, not stale Queued state."""
    scheduler = MagicMock()
    scheduler.get_job.return_value = MagicMock(next_run_time=datetime.datetime.utcnow())
    ctx = AppContext(scheduler=scheduler, weekly_status="Queued")
    monkeypatch.setattr(runtime, "_runtime", ctx)
    monkeypatch.setattr(system_service, "_fallback_weekly_refresh_lock", threading.RLock())
    monkeypatch.setattr(weeklypullit.helpers, "job_management", MagicMock())
    monkeypatch.setattr(weeklypullit.helpers, "utctimestamp", lambda: 123.0)
    monkeypatch.setattr(weeklypullit.weeklypull, "future_check", MagicMock())

    observed = []

    def pullit_while_running():
        observed.append(system_service.request_weekly_refresh(ctx))
        return None

    monkeypatch.setattr(weeklypullit.weeklypull, "pullit", pullit_while_running)

    weeklypullit.Weekly().run()

    assert observed == [
        {
            "accepted": False,
            "state": "running",
            "next_run_time": str(scheduler.get_job.return_value.next_run_time),
        }
    ]


def test_manual_run_restores_the_original_future_schedule(monkeypatch):
    scheduled_run = datetime.datetime.utcnow() + datetime.timedelta(hours=4)
    job = MagicMock()
    scheduler = MagicMock()
    scheduler.get_job.return_value = job
    monkeypatch.setattr(comicarr, "SCHED", scheduler)
    monkeypatch.setattr(comicarr, "WEEKLY_MANUAL_NEXT_RUN", scheduled_run)

    weeklypullit._restore_manual_next_run()

    job.modify.assert_called_once_with(next_run_time=scheduled_run)
    assert comicarr.WEEKLY_MANUAL_NEXT_RUN is None


def test_manual_refresh_restores_a_real_interval_trigger_schedule(monkeypatch):
    timezone = datetime.timezone.utc
    original_next_run = datetime.datetime.now(timezone) + datetime.timedelta(hours=4)
    scheduler = BackgroundScheduler(timezone=timezone)
    scheduler.add_job(
        lambda: None,
        trigger=IntervalTrigger(hours=4, timezone=timezone),
        id="weekly",
        next_run_time=original_next_run,
    )
    ctx = AppContext(scheduler=scheduler, weekly_status="Waiting")
    monkeypatch.setattr(comicarr, "WEEKLY_STATUS", "Waiting")
    monkeypatch.setattr(comicarr, "WEEKLY_MANUAL_NEXT_RUN", None)
    monkeypatch.setattr(system_service.db, "upsert", MagicMock())
    monkeypatch.setattr(comicarr, "SCHED", scheduler)

    result = system_service.request_weekly_refresh(ctx)
    weeklypullit._restore_manual_next_run()

    assert result["accepted"] is True
    assert scheduler.get_job("weekly").next_run_time == original_next_run
