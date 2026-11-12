#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""One-line answers to "what did this background job do last time?".

Activity > Health shows a result beside each job ("1 grabbed", "Nothing to
import"). The jobs themselves are legacy loops that return nothing useful, so
the answer is read back from what they leave behind: acquisition runs, the
activity log, the weekly table and the import queue. Each summary covers the
window that starts when the job last ran, so a search that grabs an issue in
the queue after its scheduler slot returned still counts toward that run.

A summary is ``None`` when there is nothing honest to say; the UI then falls
back to "Finished without errors".
"""

from __future__ import annotations

import datetime

from sqlalchemy import and_, func, select

import comicarr
from comicarr import db, logger
from comicarr.tables import acquisition_runs, activity_events, comics, importresults, weekly


def _iso(timestamp) -> str | None:
    try:
        return datetime.datetime.fromtimestamp(float(timestamp), tz=datetime.timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _plural(count, noun, plural=None) -> str:
    return "%s %s" % (count, noun if count == 1 else (plural or noun + "s"))


def _run_totals(command_kind, since, triggers=None):
    clauses = [acquisition_runs.c.command_kind == command_kind, acquisition_runs.c.created_at >= since]
    if triggers:
        clauses.append(acquisition_runs.c.trigger.in_(triggers))
    row = db.select_one(
        select(
            func.count().label("runs"),
            func.coalesce(func.sum(acquisition_runs.c.accepted_count), 0).label("accepted"),
            func.coalesce(func.sum(acquisition_runs.c.succeeded_count), 0).label("succeeded"),
            func.coalesce(func.sum(acquisition_runs.c.failed_count), 0).label("failed"),
        ).where(and_(*clauses))
    )
    return row or {"runs": 0, "accepted": 0, "succeeded": 0, "failed": 0}


def _event_count(activity, status, since):
    row = db.select_one(
        select(func.count().label("n")).where(
            and_(
                activity_events.c.activity == activity,
                activity_events.c.status == status,
                activity_events.c.created_at >= since,
            )
        )
    )
    return int((row or {}).get("n") or 0)


def _search(since):
    totals = _run_totals("search", since, triggers=("wanted_scan",))
    searched = int(totals["accepted"] or 0)
    grabbed = int(totals["succeeded"] or 0)
    if searched == 0:
        return "Nothing wanted to search"
    if grabbed:
        return "%s grabbed of %s searched" % (grabbed, searched)
    return "%s searched, nothing grabbed yet" % searched


def _rss(since):
    grabbed = _event_count("grab", "succeeded", since)
    return _plural(grabbed, "grab") if grabbed else "No new matches"


def _monitor(since):
    imported = _event_count("import", "succeeded", since)
    failed = _event_count("import", "failed", since)
    if imported and failed:
        return "%s imported, %s failed" % (imported, failed)
    if failed:
        return "%s failed to import" % failed
    return "%s imported" % imported if imported else "Nothing to import"


def _library_refresh(since):
    totals = _run_totals("refresh", since)
    refreshed = int(totals["succeeded"] or 0)
    failed = int(totals["failed"] or 0)
    if not totals["runs"]:
        return None
    if failed:
        return "%s refreshed, %s failed" % (_plural(refreshed, "series", "series"), failed)
    return "%s up to date" % _plural(refreshed, "series", "series")


def _weekly(_since):
    week = getattr(comicarr, "CURRENT_WEEKNUMBER", None)
    year = getattr(comicarr, "CURRENT_YEAR", None)
    if week in (None, "") or year in (None, ""):
        return None
    row = db.select_one(
        select(func.count().label("n")).where(
            and_(
                weekly.c.weeknumber == str(int(week)),
                weekly.c.year == str(int(year)),
                weekly.c.ComicID.in_(select(comics.c.ComicID)),
            )
        )
    )
    count = int((row or {}).get("n") or 0)
    if not count:
        return "No new issues for your series"
    return "%s for your series" % _plural(count, "new issue")


def _import_inbox(_since):
    row = db.select_one(
        select(func.count().label("n")).where(
            and_(
                importresults.c.Status != "Imported",
                func.coalesce(importresults.c.IgnoreFile, 0) == 0,
            )
        )
    )
    waiting = int((row or {}).get("n") or 0)
    return "%s waiting for a pick" % _plural(waiting, "file") if waiting else "Nothing new to place"


def _version(_since):
    current = getattr(comicarr, "CURRENT_VERSION", None)
    latest = getattr(comicarr, "LATEST_VERSION", None)
    if not latest or not current:
        return None
    if str(latest) == str(current):
        return "Up to date"
    return "Version %s is out" % str(latest).lstrip("v")


def _connection_check(_since):
    from comicarr.app.system import connections

    return connections.summarize(connections.snapshot())


_SUMMARIES = {
    "search": _search,
    "rss": _rss,
    "monitor": _monitor,
    "dbupdater": _library_refresh,
    "weekly": _weekly,
    "importinbox": _import_inbox,
    "version": _version,
    "connection_check": _connection_check,
}


def summarize(job_id, last_attempt) -> str | None:
    """The one-line result for ``job_id`` since ``last_attempt`` (epoch seconds)."""
    summary = _SUMMARIES.get(str(job_id))
    if summary is None or last_attempt in (None, ""):
        return None
    since = _iso(last_attempt)
    if since is None:
        return None
    try:
        return summary(since)
    except Exception as e:
        logger.fdebug("[SCHEDULER] Could not summarize %s: %s" % (job_id, e))
        return None
