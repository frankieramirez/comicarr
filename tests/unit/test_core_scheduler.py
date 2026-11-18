#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The process scheduler is built with the bootstrap runtime context."""

from apscheduler.schedulers.background import BackgroundScheduler

from comicarr.app.core import runtime
from comicarr.app.core.scheduler import build_scheduler


def test_build_scheduler_can_run_more_than_once():
    """APScheduler consumes the executor settings; a second build must still work."""
    first = build_scheduler()
    second = build_scheduler()

    assert first is not second
    assert isinstance(second, BackgroundScheduler)
    assert not second.running


def test_the_bootstrap_context_owns_a_real_unstarted_scheduler():
    bootstrap = runtime.new_bootstrap()

    assert isinstance(bootstrap.scheduler, BackgroundScheduler)
    assert not bootstrap.scheduler.running
    assert runtime.new_bootstrap().scheduler is not bootstrap.scheduler
