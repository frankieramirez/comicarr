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
import inspect
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import comicarr
from comicarr.app.system import service as system_service
from comicarr.config import (
    _CONFIG_DEFINITIONS,
    _PROVIDER_EXTRA_FIELDS,
    SCHEDULER_INTERVAL_MINIMUMS,
    clamp_scheduler_intervals,
)


def _readable_config_keys():
    """The uppercase config keys get_safe_config reads off the config object.

    This used to scrape the `safe_keys` list literal out of the function source.
    That list is now derived from `comicarr/app/config/registry.py`, so there is
    nothing left to scrape and the set is read directly.

    The containment assertions below are consequently structural rather than
    empirical -- `readable_keys()` is built from the same entries that produce
    `_CONFIG_DEFINITIONS`, so it cannot name an undefined key. They are kept as
    a guard against a future change reintroducing a hand-maintained literal.
    """
    keys = set(system_service._READABLE_KEYS)
    # Without this the extraction could silently return nothing after a refactor
    # and every assertion built on it would pass vacuously.
    assert len(keys) > 50, "get_safe_config key extraction found almost nothing: %s" % sorted(keys)
    return keys


def _registered_job_ids():
    """The job ids comicarr.start() actually registers with the scheduler."""
    ids = set(re.findall(r'id="([a-z_]+)"', inspect.getsource(comicarr.start)))
    assert ids, "no job registrations found in comicarr.start()"
    return ids


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

    def test_every_mapped_job_id_is_actually_registered(self):
        """The other half of the mapping. SCHEDULER_JOB_INTERVALS duplicates the
        job ids comicarr.start() registers, and _reconfigure_schedulers skips an
        unknown id in silence -- so a rename there would quietly stop interval
        changes from reaching the scheduler, the exact bug this module exists for."""
        registered = _registered_job_ids()
        unregistered = sorted(set(system_service.SCHEDULER_JOB_INTERVALS) - registered)

        assert unregistered == [], "SCHEDULER_JOB_INTERVALS maps job ids nothing registers: %s" % unregistered

    def test_the_job_tables_cover_the_same_jobs(self):
        assert set(system_service.SCHEDULER_JOB_REQUIRED_CONFIG) <= set(system_service.SCHEDULER_JOB_INTERVALS)
        for job_id, config_key in system_service.SCHEDULER_JOB_REQUIRED_CONFIG.items():
            assert config_key in _CONFIG_DEFINITIONS, "%s gates job %s but is not defined" % (config_key, job_id)

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


class TestSchedulerIntervalClamps:
    """A non-positive interval must not reach IntervalTrigger. Config.configure()
    runs on every save via apply_transaction, so this is where it gets caught."""

    @pytest.mark.parametrize("config_key", sorted(SCHEDULER_INTERVAL_MINIMUMS))
    def test_a_negative_interval_is_raised_to_the_minimum(self, config_key):
        minimum = SCHEDULER_INTERVAL_MINIMUMS[config_key][0]
        cfg = SimpleNamespace(**{key: value[0] for key, value in SCHEDULER_INTERVAL_MINIMUMS.items()})
        setattr(cfg, config_key, -1)

        assert clamp_scheduler_intervals(cfg) == [config_key]
        assert getattr(cfg, config_key) == minimum

    @pytest.mark.parametrize("config_key", sorted(SCHEDULER_INTERVAL_MINIMUMS))
    def test_zero_is_also_clamped(self, config_key):
        cfg = SimpleNamespace(**{key: value[0] for key, value in SCHEDULER_INTERVAL_MINIMUMS.items()})
        setattr(cfg, config_key, 0)

        clamp_scheduler_intervals(cfg)

        assert getattr(cfg, config_key) == SCHEDULER_INTERVAL_MINIMUMS[config_key][0]

    def test_an_acceptable_value_is_left_alone(self):
        cfg = SimpleNamespace(**{key: value[0] * 2 for key, value in SCHEDULER_INTERVAL_MINIMUMS.items()})

        assert clamp_scheduler_intervals(cfg) == []
        assert cfg.DBUPDATE_INTERVAL == SCHEDULER_INTERVAL_MINIMUMS["DBUPDATE_INTERVAL"][0] * 2

    def test_an_uncomparable_value_still_raises(self):
        """Unchanged from the three inline checks this replaced: apply_transaction
        rolls the save back rather than storing an interval nothing can use."""
        cfg = SimpleNamespace(**{key: value[0] for key, value in SCHEDULER_INTERVAL_MINIMUMS.items()})
        cfg.SEARCH_INTERVAL = "not-a-number"

        with pytest.raises(TypeError):
            clamp_scheduler_intervals(cfg)

    def test_the_disable_by_zero_intervals_are_not_clamped(self):
        """DOWNLOAD_SCAN_INTERVAL and IMPORT_SCAN_INTERVAL use 0 to mean 'off',
        and comicarr.start() keeps those jobs paused rather than scheduling them.
        Giving them a positive floor would remove the only way to disable them."""
        assert "DOWNLOAD_SCAN_INTERVAL" not in SCHEDULER_INTERVAL_MINIMUMS
        assert "IMPORT_SCAN_INTERVAL" not in SCHEDULER_INTERVAL_MINIMUMS

    def test_every_clamped_key_is_a_real_config_key(self):
        for config_key in SCHEDULER_INTERVAL_MINIMUMS:
            assert config_key in _CONFIG_DEFINITIONS


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
    # The jobs that carry a "is this even configured" guard are configured by
    # default here, so a test that cares about that guard has to clear it.
    defaults.update({config_key: "/tmp" for config_key in system_service.SCHEDULER_JOB_REQUIRED_CONFIG.values()})
    defaults.update(intervals)
    return SimpleNamespace(
        scheduler=scheduler,
        config=SimpleNamespace(**defaults),
        acquisition_workers_blocked=False,
    )


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


@pytest.fixture(autouse=True)
def _clean_parked_jobs():
    """_INTERVAL_PARKED_JOBS is process state; do not leak it between tests."""
    system_service._INTERVAL_PARKED_JOBS.clear()
    yield
    system_service._INTERVAL_PARKED_JOBS.clear()


class TestReconfigureSchedulers:
    def test_a_changed_interval_reaches_the_job(self):
        scheduler = _scheduler_with_jobs(search=_now() + datetime.timedelta(minutes=1440))
        ctx = _ctx(scheduler, SEARCH_INTERVAL=720)

        rescheduled = system_service._reconfigure_schedulers(ctx)

        assert "search" in rescheduled
        assert scheduler.get_job("search").trigger.interval == datetime.timedelta(minutes=720)

    def test_a_job_paused_by_someone_else_stays_paused(self):
        """A job paused from the jobs UI, or by turning ENABLE_RSS off, keeps its
        new interval but must not be resumed. scheduler.reschedule_job() would
        resume it; job.modify(trigger=...) does not."""
        scheduler = _scheduler_with_jobs()  # every job added paused, by nobody here
        ctx = _ctx(scheduler, RSS_CHECKINTERVAL=45)

        system_service._reconfigure_schedulers(ctx)

        job = scheduler.get_job("rss")
        assert job.next_run_time is None
        assert job.trigger.interval == datetime.timedelta(minutes=45)

    def test_a_job_parked_by_a_zero_interval_comes_back(self):
        """The inverse of the pause below. Without it, setting an interval to 0 and
        then correcting it left the job dark until the process restarted -- and the
        pause is replayed from jobhistory, so a restart did not fix it either."""
        scheduler = _scheduler_with_jobs(monitor=_now() + datetime.timedelta(minutes=30))

        system_service._reconfigure_schedulers(_ctx(scheduler, DOWNLOAD_SCAN_INTERVAL=0))
        assert scheduler.get_job("monitor").next_run_time is None

        rescheduled = system_service._reconfigure_schedulers(_ctx(scheduler, DOWNLOAD_SCAN_INTERVAL=15))

        job = scheduler.get_job("monitor")
        assert "monitor" in rescheduled
        assert job.next_run_time is not None
        assert job.trigger.interval == datetime.timedelta(minutes=15)

    def test_a_parked_job_comes_back_even_after_its_status_reads_paused(self, monkeypatch):
        """job_management() derives comicarr.<JOB>_STATUS from the live scheduler, so
        once it runs, a job we parked is indistinguishable from an operator-paused one
        by status alone. Remembering who parked it is what makes the recovery work."""
        monkeypatch.setattr(comicarr, "MONITOR_STATUS", "Paused")
        scheduler = _scheduler_with_jobs(monitor=_now() + datetime.timedelta(minutes=30))

        system_service._reconfigure_schedulers(_ctx(scheduler, DOWNLOAD_SCAN_INTERVAL=0))
        system_service._reconfigure_schedulers(_ctx(scheduler, DOWNLOAD_SCAN_INTERVAL=15))

        assert scheduler.get_job("monitor").next_run_time is not None

    def test_a_job_missing_its_required_config_is_not_resumed(self):
        """comicarr.start() refuses to run the folder monitor without CHECK_FOLDER;
        a positive interval alone must not talk it into running here either."""
        scheduler = _scheduler_with_jobs(monitor=_now() + datetime.timedelta(minutes=30))

        system_service._reconfigure_schedulers(_ctx(scheduler, DOWNLOAD_SCAN_INTERVAL=0))
        system_service._reconfigure_schedulers(_ctx(scheduler, DOWNLOAD_SCAN_INTERVAL=15, CHECK_FOLDER=None))

        assert scheduler.get_job("monitor").next_run_time is None

    def test_a_blocked_acquisition_gate_resumes_nothing(self):
        scheduler = _scheduler_with_jobs(search=_now() + datetime.timedelta(minutes=30))

        system_service._reconfigure_schedulers(_ctx(scheduler, SEARCH_INTERVAL=0))
        ctx = _ctx(scheduler, SEARCH_INTERVAL=720)
        ctx.acquisition_workers_blocked = True
        system_service._reconfigure_schedulers(ctx)

        assert scheduler.get_job("search").next_run_time is None

    def test_a_job_that_was_never_parked_is_not_tracked(self):
        scheduler = _scheduler_with_jobs(search=_now() + datetime.timedelta(minutes=30))

        system_service._reconfigure_schedulers(_ctx(scheduler, SEARCH_INTERVAL=720))

        assert "search" not in system_service._INTERVAL_PARKED_JOBS

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

    def test_an_unusable_interval_is_skipped_and_logged(self, monkeypatch):
        """A non-digit string survives Config.process_kwargs unchanged, so this is
        reachable from the API. Skipping is right; skipping in silence is not --
        every other failure in this loop says why."""
        errors = []
        monkeypatch.setattr(
            system_service,
            "logger",
            SimpleNamespace(error=errors.append, fdebug=lambda _msg: None),
        )
        scheduler = _scheduler_with_jobs(search=_now() + datetime.timedelta(minutes=1440))
        ctx = _ctx(scheduler)
        ctx.config.SEARCH_INTERVAL = "not-a-number"

        assert "search" not in system_service._reconfigure_schedulers(ctx)
        assert any("search" in message and "SEARCH_INTERVAL" in message for message in errors), errors

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
