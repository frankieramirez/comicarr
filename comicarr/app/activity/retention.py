#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Daily age-based purge of narrative activity_events (#489 / ADR §10).

Age only: DELETE WHERE created_at < now - 90 days.
No count ceiling, no severity tier, no config key, no narrative of the sweep.
"""

from __future__ import annotations

import datetime

from sqlalchemy import delete

from comicarr.app.common.dates import normalize_utc_datetime
from comicarr.app.core import logger
from comicarr.db import get_engine
from comicarr.tables import activity_events

RETENTION_DAYS = 90
JOB_ID = "activity_retention"
JOB_NAME = "Activity Event Retention"


def _cutoff_iso(now: datetime.datetime | None = None) -> str:
    """Return the exclusive ISO cutoff matching how created_at is written (UTC isoformat)."""
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    else:
        now = normalize_utc_datetime(now)
    return (now - datetime.timedelta(days=RETENTION_DAYS)).isoformat()


def purge_expired_activity_events(now: datetime.datetime | None = None, engine=None) -> int:
    """Delete activity_events older than RETENTION_DAYS.

    ``created_at`` is stored as a UTC ISO-8601 string (same shape as other modern
    ledgers). Lexicographic comparison is timezone-safe for that format.

    Returns the number of deleted rows.
    """
    engine = engine or get_engine()
    cutoff = _cutoff_iso(now)
    stmt = delete(activity_events).where(activity_events.c.created_at < cutoff)
    with engine.begin() as conn:
        result = conn.execute(stmt)
        return int(result.rowcount or 0)


def run() -> int:
    """APScheduler entry point for the daily retention job."""
    try:
        deleted = purge_expired_activity_events()
    except Exception as e:
        logger.error("[ACTIVITY-RETENTION] Purge failed: %s" % e)
        raise
    if deleted:
        logger.info("[ACTIVITY-RETENTION] Deleted %s activity_events older than %s days" % (deleted, RETENTION_DAYS))
    else:
        logger.fdebug("[ACTIVITY-RETENTION] No activity_events older than %s days" % RETENTION_DAYS)
    return deleted
