#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Story Arcs domain service — arc CRUD, reading list, upcoming.

Module-level functions (not classes) — matches existing codebase style.
"""

import datetime
import threading

from comicarr import logger
from comicarr.app.storyarcs import queries as arc_queries

ALLOWED_ARC_STATUSES = {"Wanted", "Read", "Skipped"}


def list_arcs(ctx, custom_only=False):
    """List all story arcs with aggregated stats and computed fields."""
    rows = arc_queries.list_arcs(custom_only=custom_only)
    arclist = []
    for row in rows:
        total = row["Total"] or 0
        have = row["Have"] or 0
        try:
            percent = round((have * 100.0) / total, 1) if total > 0 else 0
        except (ZeroDivisionError, TypeError):
            percent = 0

        min_year = row["min_year"]
        max_year = row["max_year"]
        if min_year is None or max_year is None:
            span_years = None
        elif min_year == max_year:
            span_years = str(max_year)
        else:
            span_years = "%s - %s" % (min_year, max_year)

        arclist.append({
            "StoryArcID": row["StoryArcID"],
            "StoryArc": row["StoryArc"],
            "TotalIssues": total,
            "Have": have,
            "Total": total,
            "percent": percent,
            "SpanYears": span_years,
            "CV_ArcID": row["CV_ArcID"],
            "Publisher": row["Publisher"],
            "ArcImage": row["ArcImage"],
        })
    return arclist


def get_arc_detail(ctx, arc_id):
    """Get a single story arc with summary stats and all issues."""
    arc_row = arc_queries.get_arc_stats(arc_id)
    if arc_row is None:
        return None

    total = arc_row["Total"] or 0
    have = arc_row["Have"] or 0
    try:
        percent = round((have * 100.0) / total, 1) if total > 0 else 0
    except (ZeroDivisionError, TypeError):
        percent = 0

    min_year = arc_row["min_year"]
    max_year = arc_row["max_year"]
    if min_year is None or max_year is None:
        span_years = None
    elif min_year == max_year:
        span_years = str(max_year)
    else:
        span_years = "%s - %s" % (min_year, max_year)

    arc_summary = {
        "StoryArcID": arc_row["StoryArcID"],
        "StoryArc": arc_row["StoryArc"],
        "TotalIssues": total,
        "Have": have,
        "Total": total,
        "percent": percent,
        "SpanYears": span_years,
        "CV_ArcID": arc_row["CV_ArcID"],
        "Publisher": arc_row["Publisher"],
        "ArcImage": arc_row["ArcImage"],
    }

    issues = arc_queries.get_arc_issues(arc_id)

    return {"arc": arc_summary, "issues": issues}


def delete_arc(ctx, arc_id, arc_name=None, delete_type=None):
    """Delete an entire story arc."""
    arc_queries.delete_arc(arc_id, arc_name=arc_name, delete_type=delete_type)
    logger.info("[DELETE-ARC] Removed %s from Story Arcs" % arc_id)
    return {"success": True}


def delete_arc_issue(ctx, issue_arc_id, manual=None):
    """Remove a single issue from a story arc (soft-delete by default)."""
    arc_queries.soft_delete_arc_issue(issue_arc_id, manual=manual)
    logger.info("[DELETE-ARC] Removed %s from the Story Arc" % issue_arc_id)
    return {"success": True}


def set_issue_status(ctx, issue_arc_id, status):
    """Update the status of a single arc issue."""
    if status not in ALLOWED_ARC_STATUSES:
        return {"success": False, "error": "Invalid status"}

    arc_queries.set_issue_status(issue_arc_id, status)
    return {"success": True}


def want_all_issues(ctx, arc_id):
    """Mark all eligible arc issues as Wanted and trigger search."""
    queued, skipped = arc_queries.want_all_issues(arc_id)

    # Trigger search in background if any were queued
    if queued > 0:
        from comicarr.webserve import WebInterface
        threading.Thread(target=WebInterface().ReadGetWanted, args=(arc_id,)).start()

    return {"success": True, "data": {"queued": queued, "skipped": skipped}}


def refresh_arc(ctx, arc_id):
    """Refresh a story arc from ComicVine in the background."""
    arc_row = arc_queries.get_arc_for_refresh(arc_id)
    if arc_row is None:
        return {"success": False, "error": "Story arc not found"}

    from comicarr.webserve import WebInterface
    threading.Thread(
        target=WebInterface().addStoryArc_thread,
        kwargs={
            "arcid": arc_row["StoryArcID"],
            "cvarcid": arc_row["CV_ArcID"],
            "storyarcname": arc_row["StoryArc"],
            "storyarcissues": None,
            "arclist": None,
            "arcrefresh": True,
        },
    ).start()

    return {"success": True, "message": "Refreshing %s from ComicVine" % arc_row["StoryArc"]}


# ---------------------------------------------------------------------------
# Reading list
# ---------------------------------------------------------------------------

def get_readlist(ctx):
    """Get all reading list entries."""
    return arc_queries.get_readlist()


def add_to_readlist(ctx, issue_id):
    """Add an issue to the reading list."""
    from comicarr import readinglist
    read = readinglist.Readinglist(IssueID=issue_id)
    result = read.addtoreadlist()
    if result is not None:
        return {"success": result.get("status") == "success", "message": result.get("message", "")}
    return {"success": True}


def remove_from_readlist(ctx, issue_id):
    """Remove an issue from the reading list."""
    arc_queries.remove_readlist_issue(issue_id)
    logger.info("[DELETE-READ-ISSUE] Removed %s from Reading List" % issue_id)
    return {"success": True}


def clear_read_issues(ctx):
    """Remove all issues marked as Read from the reading list."""
    arc_queries.remove_all_read()
    logger.info("[DELETE-ALL-READ] Removed all Read issues from Reading List")
    return {"success": True}


# ---------------------------------------------------------------------------
# Upcoming
# ---------------------------------------------------------------------------

def get_upcoming(ctx, include_downloaded=False):
    """Get upcoming issues for the current week."""
    today = datetime.date.today()
    if today.strftime("%U") == "00":
        weekday = 0 if today.isoweekday() == 7 else today.isoweekday()
        sunday = today - datetime.timedelta(days=weekday)
        week = sunday.strftime("%U")
        year = sunday.strftime("%Y")
    else:
        week = today.strftime("%U")
        year = today.strftime("%Y")

    return arc_queries.get_upcoming(week, year, include_downloaded=include_downloaded)
