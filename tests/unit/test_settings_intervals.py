#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Scheduling intervals: the settings surface, and applying a change.

Two failures met here. The settings API advertised two keys that no config
definition backs, so saving either raised KeyError inside apply_transaction and
rolled back the entire payload -- every other setting in the same save was
silently discarded. And the reconfiguration path called a function that has
never existed in this repository, so an interval change never reached the
running scheduler even when the save succeeded.

The existing update_config tests use a MagicMock config, so apply_transaction
never runs and neither failure was visible to them.
"""

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from comicarr.app.system import service as system_service
from comicarr.config import _CONFIG_DEFINITIONS, _PROVIDER_EXTRA_FIELDS


def _readable_config_keys():
    """The uppercase config keys get_safe_config reads off the config object."""
    import inspect
    import re

    source = inspect.getsource(system_service.get_safe_config)
    body = source.split("result = {}")[0]
    return set(re.findall(r'"([A-Z][A-Z0-9_]+)"', body))


class TestEveryAdvertisedKeyIsReal:
    """A key on the settings surface with no definition poisons the whole save."""

    def test_writable_keys_are_all_defined(self):
        undefined = sorted(
            key
            for key in system_service.WRITABLE_CONFIG_KEYS
            if key not in _CONFIG_DEFINITIONS and key not in _PROVIDER_EXTRA_FIELDS
        )

        assert undefined == [], "WRITABLE_CONFIG_KEYS advertises keys config cannot define: %s" % undefined

    def test_readable_keys_are_all_defined(self):
        undefined = sorted(
            key
            for key in _readable_config_keys()
            if key not in _CONFIG_DEFINITIONS and key not in _PROVIDER_EXTRA_FIELDS
        )

        assert undefined == [], "get_safe_config reads keys config cannot define: %s" % undefined

    def test_every_scheduled_interval_is_a_real_config_key(self):
        for job_id, config_key in system_service.SCHEDULER_JOB_INTERVALS.items():
            assert config_key in _CONFIG_DEFINITIONS, "%s drives job %s but is not defined" % (config_key, job_id)

    def test_every_writable_key_survives_config_definition_lookup(self):
        """The actual failure mechanism: _define raises KeyError on an unknown key,
        apply_transaction catches BaseException and rolls the whole payload back, and
        update_config reports a persistence failure for settings that were fine."""
        from comicarr.config import Config

        for key in sorted(set(system_service.WRITABLE_CONFIG_KEYS) - set(_PROVIDER_EXTRA_FIELDS)):
            try:
                Config._define(None, key)
            except KeyError:
                pytest.fail("saving %s would roll back the entire settings payload" % key)

    def test_writable_intervals_are_the_ones_the_api_can_change(self):
        """IMPORT_SCAN_INTERVAL drives a job but is deliberately read-only: it is
        exposed by get_safe_config and has no settings field. Reconfiguration still
        reads it, so a change made another way is picked up."""
        writable = {
            config_key
            for config_key in system_service.SCHEDULER_JOB_INTERVALS.values()
            if config_key in system_service.WRITABLE_CONFIG_KEYS
        }

        assert writable == {
            "SEARCH_INTERVAL",
            "RSS_CHECKINTERVAL",
            "DOWNLOAD_SCAN_INTERVAL",
            "DBUPDATE_INTERVAL",
        }


def _scheduler_with_jobs(**next_run_times):
    scheduler = BackgroundScheduler(timezone="UTC")
    for job_id in system_service.SCHEDULER_JOB_INTERVALS:
        scheduler.add_job(
            lambda: None,
            id=job_id,
            trigger=IntervalTrigger(minutes=1440, timezone="UTC"),
            next_run_time=next_run_times.get(job_id),
        )
    return scheduler


def _ctx(scheduler, **intervals):
    defaults = {config_key: 1440 for config_key in system_service.SCHEDULER_JOB_INTERVALS.values()}
    defaults.update(intervals)
    return SimpleNamespace(scheduler=scheduler, config=SimpleNamespace(**defaults))


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class TestReconfigureSchedulers:
    def test_a_changed_interval_reaches_the_job(self):
        scheduler = _scheduler_with_jobs(search=_now() + datetime.timedelta(minutes=1440))
        ctx = _ctx(scheduler, SEARCH_INTERVAL=720)

        rescheduled = system_service._reconfigure_schedulers(ctx)

        assert "search" in rescheduled
        assert scheduler.get_job("search").trigger.interval == datetime.timedelta(minutes=720)

    def test_a_paused_job_stays_paused(self):
        """scheduler.reschedule_job() would resume it; job.modify(trigger=...) does not."""
        scheduler = _scheduler_with_jobs()  # every job added paused
        ctx = _ctx(scheduler, RSS_CHECKINTERVAL=45)

        system_service._reconfigure_schedulers(ctx)

        job = scheduler.get_job("rss")
        assert job.next_run_time is None
        assert job.trigger.interval == datetime.timedelta(minutes=45)

    def test_shortening_an_interval_takes_effect_immediately(self):
        scheduler = _scheduler_with_jobs(monitor=_now() + datetime.timedelta(minutes=1440))
        ctx = _ctx(scheduler, DOWNLOAD_SCAN_INTERVAL=5)

        system_service._reconfigure_schedulers(ctx)

        assert scheduler.get_job("monitor").next_run_time <= _now() + datetime.timedelta(minutes=5, seconds=5)

    def test_a_pending_run_is_never_pushed_later(self):
        pending = _now() + datetime.timedelta(minutes=10)
        scheduler = _scheduler_with_jobs(search=pending)
        ctx = _ctx(scheduler, SEARCH_INTERVAL=10080)

        system_service._reconfigure_schedulers(ctx)

        assert scheduler.get_job("search").next_run_time == pending

    def test_a_non_positive_interval_pauses_rather_than_removes(self):
        scheduler = _scheduler_with_jobs(importinbox=_now() + datetime.timedelta(minutes=30))
        ctx = _ctx(scheduler, IMPORT_SCAN_INTERVAL=0)

        system_service._reconfigure_schedulers(ctx)

        job = scheduler.get_job("importinbox")
        assert job is not None
        assert job.next_run_time is None

    def test_a_missing_job_is_skipped_not_fatal(self):
        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(
            lambda: None,
            id="search",
            trigger=IntervalTrigger(minutes=1440, timezone="UTC"),
            next_run_time=_now() + datetime.timedelta(minutes=1440),
        )

        assert system_service._reconfigure_schedulers(_ctx(scheduler, SEARCH_INTERVAL=720)) == ("search",)

    def test_an_unusable_interval_is_skipped(self):
        scheduler = _scheduler_with_jobs(search=_now() + datetime.timedelta(minutes=1440))
        ctx = _ctx(scheduler)
        ctx.config.SEARCH_INTERVAL = None

        assert "search" not in system_service._reconfigure_schedulers(ctx)

    def test_no_scheduler_is_not_an_error(self):
        assert system_service._reconfigure_schedulers(SimpleNamespace(scheduler=None, config=MagicMock())) == ()

    def test_a_scheduler_failure_never_raises_into_the_request(self):
        """The durable config write already happened; a scheduler fault must not fail the save."""
        scheduler = MagicMock()
        scheduler.get_job.side_effect = RuntimeError("jobstore is wedged")

        assert system_service._reconfigure_schedulers(_ctx(scheduler)) == ()


class TestUpdateConfigTriggersReconfiguration:
    @pytest.mark.parametrize(
        "config_key",
        sorted(set(system_service.SCHEDULER_JOB_INTERVALS.values()) & system_service.WRITABLE_CONFIG_KEYS),
    )
    def test_changing_any_interval_reconfigures(self, config_key, monkeypatch):
        import comicarr

        ctx = SimpleNamespace(config=MagicMock(), scheduler=MagicMock())
        ctx.config.apply_transaction.return_value = True
        monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
        calls = []
        monkeypatch.setattr(system_service, "_reconfigure_schedulers", lambda _ctx: calls.append(_ctx))

        result = system_service.update_config(ctx, {config_key.lower(): 60})

        assert result == {"success": True}
        assert len(calls) == 1
