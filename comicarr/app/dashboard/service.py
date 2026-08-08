#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Dashboard domain service — panel-scoped reads for the home dashboard.

Each panel owns its own read. A read that cannot be answered **raises**
rather than returning a default: the client renders that one panel as
unavailable with its own retry, and its neighbours still render. An empty
panel and a broken panel must never look alike — see §5 of
``docs/architecture/dashboard-spec.md``.
"""

from datetime import datetime, timedelta

import comicarr
from comicarr.app.dashboard import queries as dashboard_queries
from comicarr.app.downloads import queries as dl_queries
from comicarr.app.storyarcs import service as storyarcs_service

RECENT_ACTIVITY_DAYS = 30
ACTIVE_QUEUE_PREVIEW_LIMIT = 5


def recent_activity_cutoff(now=None):
    """Return the inclusive cutoff for the dashboard's bounded activity preview."""
    return (now or datetime.now()) - timedelta(days=RECENT_ACTIVITY_DAYS)


def _percentage(part, whole):
    """Return ``part`` of ``whole`` as a one-decimal percentage, or 0 when unknowable."""
    return round(part / whole * 100, 1) if whole > 0 else 0


def get_library_panel():
    """Return the library aggregates behind the dashboard's KPI strip."""
    stats = dashboard_queries.get_library_stats() or {}
    total_issues = stats.get("total_issues", 0) or 0
    total_expected = stats.get("total_expected", 0) or 0
    result = {
        "total_series": stats.get("total_series", 0) or 0,
        "total_issues": total_issues,
        "total_expected": total_expected,
        "completion_pct": _percentage(total_issues, total_expected),
    }

    manga_stats = dashboard_queries.get_library_stats("manga")
    if manga_stats:
        manga_have = manga_stats.get("manga_have", 0) or 0
        manga_total = manga_stats.get("manga_total", 0) or 0
        result["manga_series"] = manga_stats.get("manga_series", 0)
        result["manga_have"] = manga_have
        result["manga_total"] = manga_total
        result["manga_completion_pct"] = _percentage(manga_have, manga_total)

    comic_stats = dashboard_queries.get_library_stats("comic")
    if comic_stats:
        result["comic_series"] = comic_stats.get("comic_series", 0)
        result["comic_have"] = comic_stats.get("comic_have", 0) or 0
        result["comic_total"] = comic_stats.get("comic_total", 0) or 0

    return {"stats": result}


def get_queue_panel():
    """Return the active-download count and its bounded preview.

    Count and preview share the active DDL predicate deliberately, so the
    tile and the list below it can never disagree.
    """
    return {
        "count": dl_queries.count_active_ddl_items(),
        "items": dl_queries.get_active_ddl_preview(limit=ACTIVE_QUEUE_PREVIEW_LIMIT) or [],
    }


def get_activity_panel():
    """Return the bounded recent-activity preview and the window it covers."""
    cutoff = recent_activity_cutoff().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "events": dashboard_queries.get_recent_activity(cutoff) or [],
        "days": RECENT_ACTIVITY_DAYS,
    }


def get_upcoming_panel():
    """Return this week's releases for series already in the library."""
    return {"releases": storyarcs_service.get_upcoming(include_downloaded=True) or []}


def _has_directory(name):
    """Return whether a library directory is configured to a non-empty path."""
    value = getattr(comicarr.CONFIG, name, None)
    return isinstance(value, str) and bool(value)


def get_scan_targets():
    """Return which libraries the dashboard's scan action can start."""
    return {"comic": _has_directory("COMIC_DIR"), "manga": _has_directory("MANGA_DIR")}
