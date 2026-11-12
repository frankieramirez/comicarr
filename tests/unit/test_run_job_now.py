#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Activity > Health: run a scheduled job now."""

import datetime
from types import SimpleNamespace

from comicarr.app.system import router as system_router
from comicarr.app.system import service as system_service


class FakeJob:
    def __init__(self, name, next_run_time):
        self.name = name
        self.next_run_time = next_run_time
        self.modified = None

    def modify(self, next_run_time):
        self.modified = next_run_time
        self.next_run_time = next_run_time


class FakeScheduler:
    def __init__(self, jobs):
        self.jobs = jobs

    def get_job(self, job_id):
        return self.jobs.get(job_id)


def _ctx(**jobs):
    return SimpleNamespace(scheduler=FakeScheduler(jobs))


def test_moves_a_runnable_job_to_now():
    later = datetime.datetime(2099, 1, 1, tzinfo=datetime.timezone.utc)
    rss = FakeJob("RSS Feeds", later)

    result = system_service.request_job_run(_ctx(rss=rss), "rss")

    assert result["accepted"] is True
    assert result["state"] == "queued"
    assert rss.modified is not None and rss.modified < later


def test_refuses_a_paused_job():
    rss = FakeJob("RSS Feeds", None)
    result = system_service.request_job_run(_ctx(rss=rss), "rss")
    assert result == {"accepted": False, "state": "paused", "error": "That job is paused"}
    assert rss.modified is None


def test_unscheduled_job_is_unavailable():
    result = system_service.request_job_run(_ctx(), "search")
    assert result["accepted"] is False
    assert result["state"] == "unavailable"


def test_weekly_goes_through_the_weekly_refresh(monkeypatch):
    seen = []
    monkeypatch.setattr(
        system_service, "request_weekly_refresh", lambda ctx: seen.append(ctx) or {"accepted": True, "state": "queued"}
    )
    ctx = _ctx()
    assert system_service.request_job_run(ctx, "weekly") == {"accepted": True, "state": "queued"}
    assert seen == [ctx]


def test_router_404s_jobs_that_are_not_runnable():
    retention = FakeJob("Ledger Retention", datetime.datetime(2099, 1, 1, tzinfo=datetime.timezone.utc))
    response = system_router.run_job("ledger_retention", ctx=_ctx(ledger_retention=retention))
    assert response.status_code == 404
    assert retention.modified is None
