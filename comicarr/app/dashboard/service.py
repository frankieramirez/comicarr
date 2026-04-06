#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Dashboard domain service — aggregates data from existing tables for
the home dashboard view.
"""

from datetime import datetime, timedelta

import comicarr
from comicarr import db, logger


def get_dashboard_data(ctx):
    """Aggregate dashboard data from existing tables.

    Returns a dict with recently_downloaded, upcoming_releases, stats,
    ai_activity, and ai_configured flag.
    """
    result = {
        "recently_downloaded": [],
        "upcoming_releases": [],
        "stats": {},
        "ai_activity": [],
        "ai_configured": False,
    }

    # Recently downloaded: last 10 from snatched, sorted by DateAdded DESC
    try:
        recent = db.DBConnection().select(
            "SELECT s.ComicName, s.Issue_Number, s.DateAdded, s.Status, s.Provider, "
            "s.ComicID, s.IssueID, c.ComicImage "
            "FROM snatched s LEFT JOIN comics c ON s.ComicID = c.ComicID "
            "ORDER BY s.DateAdded DESC LIMIT 10"
        )
        result["recently_downloaded"] = recent or []
    except Exception as e:
        logger.error("[DASHBOARD] Error fetching recent downloads: %s" % e)

    # Upcoming: next 7 days from futureupcoming
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        week_ahead = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        upcoming = db.DBConnection().select(
            "SELECT ComicName, IssueNumber, IssueDate, Publisher, ComicID, Status "
            "FROM futureupcoming WHERE IssueDate >= ? AND IssueDate <= ? "
            "ORDER BY IssueDate ASC LIMIT 20",
            [today, week_ahead],
        )
        result["upcoming_releases"] = upcoming or []
    except Exception as e:
        logger.error("[DASHBOARD] Error fetching upcoming: %s" % e)

    # Stats: aggregate from comics
    try:
        stats = db.DBConnection().selectone(
            "SELECT COUNT(*) as total_series, "
            "COALESCE(SUM(Have), 0) as total_issues, "
            "COALESCE(SUM(Total), 0) as total_expected "
            "FROM comics WHERE Status != 'Paused'"
        )
        if stats:
            total_expected = stats.get("total_expected", 0) or 0
            total_issues = stats.get("total_issues", 0) or 0
            result["stats"] = {
                "total_series": stats.get("total_series", 0),
                "total_issues": total_issues,
                "total_expected": total_expected,
                "completion_pct": round(total_issues / total_expected * 100, 1) if total_expected > 0 else 0,
            }
    except Exception as e:
        logger.error("[DASHBOARD] Error fetching stats: %s" % e)

    # AI activity: last 5 entries (only if AI configured)
    # Check both runtime client and saved config (client requires restart)
    ai_base_url = getattr(comicarr.CONFIG, "AI_BASE_URL", None)
    if comicarr.AI_CLIENT is not None or ai_base_url:
        result["ai_configured"] = True
        try:
            activity = db.DBConnection().select(
                "SELECT timestamp, feature_type, action_description, "
                "prompt_tokens, completion_tokens, success "
                "FROM ai_activity_log ORDER BY timestamp DESC LIMIT 5"
            )
            result["ai_activity"] = activity or []
        except Exception as e:
            logger.error("[DASHBOARD] Error fetching AI activity: %s" % e)

    return result
