#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Week-by-week pull list for the Releases page (#1080).

Weeks use the same Sunday-based ``%U`` numbering as the stored ``weekly``
rows and :func:`comicarr.app.storyarcs.service.get_current_week`. A week that
has never been stored is fetched on demand from the pull-list sources the
scheduled job uses (Walksoftly, then ComicVine), but only its rows are saved:
the watchlist pass that can mark issues Wanted stays with the scheduled job,
so browsing an old week never changes the library.
"""

import datetime
import threading
import time

from comicarr import logger
from comicarr.app.storyarcs import service as storyarcs_service
from comicarr.app.weekly import queries as weekly_queries

WEEKS_AHEAD = 4
WEEKS_BEHIND = 52
FETCH_RETRY_SECONDS = 15 * 60

_FETCH_LOCK = threading.Lock()
_FETCH_ATTEMPTS: dict[tuple[str, str], float] = {}


WEEK_RANGE_MESSAGE = "Pick a week and year from %s weeks back to %s weeks ahead." % (WEEKS_BEHIND, WEEKS_AHEAD)


class WeekError(ValueError):
    """A requested week is malformed or outside the browsable window."""


def week_sunday(week, year):
    """Return the Sunday that starts ``%U`` week ``week`` of ``year``."""
    jan1 = datetime.date(int(year), 1, 1)
    first_sunday = jan1 + datetime.timedelta(days=(6 - jan1.weekday()) % 7)
    return first_sunday + datetime.timedelta(weeks=int(week) - 1)


def _week_key(sunday):
    week, year = storyarcs_service.get_current_week(today=sunday)
    return str(int(week)), str(year)


def _parse(week, year):
    try:
        week_number, year_number = int(week), int(year)
    except (TypeError, ValueError) as e:
        raise WeekError("week and year must be numbers") from e
    if not 0 <= week_number <= 53 or not 1900 <= year_number <= 2999:
        raise WeekError("week must be 0-53 and year a four-digit year")
    return week_number, year_number


def week_window(week=None, year=None, today=None):
    """Describe one browsable week and its neighbours.

    ``prev``/``next`` are ``None`` at the edges of the window, which runs
    ``WEEKS_BEHIND`` weeks back and ``WEEKS_AHEAD`` weeks ahead of the
    current week.
    """
    today = today or datetime.date.today()
    current_sunday = week_sunday(*storyarcs_service.get_current_week(today=today))
    if week is None and year is None:
        sunday = current_sunday
    else:
        sunday = week_sunday(*_parse(week, year))
    offset = (sunday - current_sunday).days // 7
    if offset > WEEKS_AHEAD or offset < -WEEKS_BEHIND:
        raise WeekError(WEEK_RANGE_MESSAGE)
    week_number, week_year = _week_key(sunday)

    def neighbour(delta):
        if not -WEEKS_BEHIND <= offset + delta <= WEEKS_AHEAD:
            return None
        n_week, n_year = _week_key(sunday + datetime.timedelta(weeks=delta))
        return {"week": n_week, "year": n_year}

    return {
        "week": week_number,
        "year": week_year,
        "start": sunday.isoformat(),
        "end": (sunday + datetime.timedelta(days=6)).isoformat(),
        "offset": offset,
        "prev": neighbour(-1),
        "next": neighbour(1),
    }


def _fetch_week(week, year, start):
    """Store one week's rows from Walksoftly, falling back to ComicVine."""
    from comicarr import locg
    from comicarr.app.weekly import cv_source

    try:
        result = locg.locg(weeknumber=week, year=year)
    except Exception as e:
        logger.warn("[PULL-LIST] Walksoftly fetch for week %s, %s failed: %s" % (week, year, e))
        result = {"status": "failure"}
    if result.get("status") in ("success", "up2date"):
        return "walksoftly"
    if not cv_source.is_available():
        return None
    midweek = (datetime.date.fromisoformat(start) + datetime.timedelta(days=3)).isoformat()
    try:
        fallback = cv_source.pull_week(week, year, midweek)
    except Exception as e:
        logger.warn("[PULL-LIST] ComicVine fetch for week %s, %s failed: %s" % (week, year, e))
        return None
    return cv_source.SOURCE if fallback.get("status") == "success" else None


def _ensure_week(window):
    """Fetch an unstored week once per ``FETCH_RETRY_SECONDS``; return how rows were found."""
    week, year = window["week"], window["year"]
    if weekly_queries.has_week(week, year):
        return "stored"
    key = (week, year)
    with _FETCH_LOCK:
        if weekly_queries.has_week(week, year):
            return "stored"
        last = _FETCH_ATTEMPTS.get(key)
        if last is not None and time.monotonic() - last < FETCH_RETRY_SECONDS:
            return "unavailable"
        _FETCH_ATTEMPTS[key] = time.monotonic()
        logger.info("[PULL-LIST] Fetching the pull list for week %s, %s on demand" % (week, year))
        source = _fetch_week(week, year, window["start"])
    return "fetched" if source else "unavailable"


def library_state(series, issue):
    """Collapse a row's library match into one display state."""
    if series is None:
        return "not_in_library"
    if issue is None:
        return "in_library"
    status = (issue.get("Status") or "").strip().lower()
    if status in ("downloaded", "archived"):
        return "downloaded"
    if status in ("wanted", "snatched", "failed"):
        return "wanted"
    return "in_library"


def _annotate(rows):
    comic_ids = [row.get("ComicID") for row in rows]
    series_by_id = weekly_queries.get_library_series(comic_ids)
    issues_by_id = weekly_queries.get_library_issues(series_by_id.keys())
    issues_by_number = {}
    for issue in issues_by_id.values():
        issues_by_number.setdefault((issue["ComicID"], str(issue["Issue_Number"] or "").strip()), issue)

    annotated = []
    for row in rows:
        row = dict(row)
        series = series_by_id.get(row.get("ComicID"))
        issue = None
        if series is not None:
            issue = issues_by_id.get(row.get("IssueID")) or issues_by_number.get(
                (row["ComicID"], str(row.get("ISSUE") or "").strip())
            )
        row["in_library"] = series is not None
        row["library_issue_id"] = issue["IssueID"] if issue else None
        row["issue_status"] = issue["Status"] if issue else None
        row["state"] = library_state(series, issue)
        annotated.append(row)
    return annotated


def get_week(week=None, year=None, today=None):
    """Return one week's releases with library state and navigation."""
    window = week_window(week, year, today=today)
    source = _ensure_week(window)
    rows = weekly_queries.get_weekly_releases(window["week"], window["year"]) or []
    return {**window, "source": source, "rows": _annotate(rows)}


def add_from_week(ctx, rowid, want=False, folder=None):
    """Add a pull-list row's series to the library, optionally wanting its issue.

    The add runs on the mass-add worker, which drains every queued series
    before it marks queued issues Wanted, so the issue exists by the time its
    status is set.
    """
    from comicarr import importer
    from comicarr.app.search import service as search_service

    row = weekly_queries.get_weekly_row(rowid)
    if row is None:
        return {"success": False, "status": 404, "error": "That release is no longer on the pull list."}
    comic_id = row.get("ComicID")
    if not comic_id:
        return {
            "success": False,
            "status": 422,
            "error": "%s has no ComicVine id on the pull list. Search for it to add it." % row["COMIC"],
        }
    if weekly_queries.get_library_series([comic_id]):
        return {"success": False, "status": 409, "error": "%s is already in your library." % row["COMIC"]}

    result = search_service.add_comic(ctx, comic_id, folder=folder)
    if not result.get("success"):
        return result
    want_queued = bool(want and row.get("IssueID"))
    if want_queued:
        importer.issue_watcher_thread([row["IssueID"]])
    return {**result, "want_queued": want_queued}
