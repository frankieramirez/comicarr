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
from comicarr.app.storyarcs import service as storyarcs_service

RECENT_ACTIVITY_DAYS = 30

RECENT_ACTIVITY_PREVIEW_LIMIT = 5
UPCOMING_PREVIEW_LIMIT = 6


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


def get_activity_panel():
    """Return the bounded narrative activity preview and the window it covers.

    Source is the narrative stream (``activity_events``), not ``t_snatched`` —
    so a failed attempt that never reached the snatched table still appears.
    """
    cutoff = recent_activity_cutoff().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "events": dashboard_queries.get_recent_activity(cutoff, limit=RECENT_ACTIVITY_PREVIEW_LIMIT) or [],
        "days": RECENT_ACTIVITY_DAYS,
    }


def get_upcoming_panel():
    """Return this week's releases for series already in the library."""
    releases = storyarcs_service.get_upcoming(include_downloaded=True) or []
    return {"releases": releases[:UPCOMING_PREVIEW_LIMIT]}


def _is_configured_path(value):
    """Return whether a configured library directory is a usable, non-empty path."""
    return isinstance(value, str) and bool(value.strip())


def get_scan_targets():
    """Return which libraries the dashboard's scan action can start."""
    return {
        "comic": _is_configured_path(comicarr.CONFIG.COMIC_DIR),
        "manga": _is_configured_path(comicarr.CONFIG.MANGA_DIR),
    }
