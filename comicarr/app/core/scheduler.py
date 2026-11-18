#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The process's APScheduler instance.

One scheduler is built with the bootstrap runtime context and carried over by
the factory, so jobs added during start-up and jobs the API modifies later
live on the same instance.
"""

import copy

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
)
from apscheduler.schedulers.background import BackgroundScheduler

SCHEDULER_SETTINGS = {
    "apscheduler.executors.default": {
        "class": "apscheduler.executors.pool:ThreadPoolExecutor",
        "max_workers": "20",
    },
    "apscheduler.job_defaults.coalesce": "true",
    "apscheduler.job_defaults.max_instances": "3",
    "apscheduler.timezone": "UTC",
}


def _persist_scheduler_health_event(event):
    """Late import avoids a package-initialization cycle while keeping every event durable."""
    from comicarr.app.system.service import persist_scheduler_event

    return persist_scheduler_event(event)


def build_scheduler():
    """Return an unstarted scheduler that records every job outcome."""
    # APScheduler consumes keys from the nested executor dict, so each
    # scheduler gets its own copy of the settings.
    scheduler = BackgroundScheduler(copy.deepcopy(SCHEDULER_SETTINGS))
    scheduler.add_listener(
        _persist_scheduler_health_event,
        EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED | EVENT_JOB_MAX_INSTANCES,
    )
    return scheduler
