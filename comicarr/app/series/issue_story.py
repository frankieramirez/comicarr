#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The facts beside an issue's story: attempts, candidates and log lines.

The issue page tells "what happened" from the activity log. This module adds
what the activity log cannot: how many times each step ran, the releases the
last search weighed, and the log lines that mention this issue.
"""

from __future__ import annotations

import datetime
import os
import re

from sqlalchemy import func, select

from comicarr import db, logger
from comicarr.app.search import search_history
from comicarr.tables import activity_events, annuals, issues, pipeline_journal

LOG_LINES = 8
_LOG_STAMP = re.compile(r"^(\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2})")
_ARCHIVE_EXT = re.compile(r"\.(cb[zr7t]|zip|rar|pdf|epub|nzb|torrent)$", re.IGNORECASE)


def _attempts(issue_id):
    rows = db.select_all(
        select(activity_events.c.activity, func.count().label("n"))
        .where(activity_events.c.subject_id == str(issue_id))
        .where(activity_events.c.status != "started")
        .group_by(activity_events.c.activity)
    )
    counts = {row["activity"]: int(row["n"] or 0) for row in rows or []}
    return {key: counts.get(key, 0) for key in ("search", "grab", "download", "import")}


def _latest_journal(issue_id):
    return db.select_one(
        select(
            pipeline_journal.c.nzbname,
        )
        .where(pipeline_journal.c.issueid == str(issue_id))
        .order_by(pipeline_journal.c.updated_date.desc())
        .limit(1)
    )


def _normalize_title(value):
    return re.sub(r"[^a-z0-9]", "", _ARCHIVE_EXT.sub("", str(value or "")).lower())


def _mark_chosen(search, chosen_name):
    if not search or not chosen_name:
        return search
    wanted = _normalize_title(chosen_name)
    for row in search.get("accepted") or []:
        row["chosen"] = bool(wanted) and _normalize_title(row.get("title")) == wanted
    return search


def _issue_label(issue_id):
    for table in (issues, annuals):
        row = db.select_one(
            select(table.c.ComicName, table.c.Issue_Number).where(table.c.IssueID == str(issue_id)).limit(1)
        )
        if row and row.get("ComicName"):
            return "%s #%s" % (row["ComicName"], row.get("Issue_Number") or "")
    return None


def _log_queries(issue_id, chosen_name):
    queries = []
    stem = _ARCHIVE_EXT.sub("", os.path.basename(str(chosen_name or ""))).strip()
    if len(stem) >= 6:
        queries.append(stem)
    label = _issue_label(issue_id)
    if label:
        queries.append(label)
    queries.append("IssueID: %s" % issue_id)
    return queries


def _stamp(line):
    match = _LOG_STAMP.match(line)
    if not match:
        return None
    try:
        return datetime.datetime.strptime(match.group(1), "%d-%b-%Y %H:%M:%S")
    except ValueError:
        return None


def _log_lines(ctx, issue_id, chosen_name):
    from comicarr.app.system import service as system_service
    from comicarr.app.system.log_files import LogFileError

    queries = _log_queries(issue_id, chosen_name)
    found = {}
    for query in queries:
        try:
            result = system_service.search_logs(ctx, "current", query, limit=LOG_LINES)
        except LogFileError:
            break
        except Exception as e:
            logger.fdebug("[ISSUE-STORY] Log search failed for %s: %s" % (issue_id, e))
            break
        for line in result.get("logs") or []:
            text = line.rstrip("\n")
            if text and _stamp(text) is not None:
                found.setdefault(text, _stamp(text))
    lines = sorted(found, key=lambda text: found[text])[-LOG_LINES:]
    return {"query": queries[0], "lines": lines}


def story_details(ctx, issue_id):
    """Everything the issue page shows beside "What happened"."""
    issue_id = str(issue_id)
    latest = _latest_journal(issue_id)
    chosen_name = (latest or {}).get("nzbname")
    return {
        "issue_id": issue_id,
        "attempts": _attempts(issue_id),
        "search": _mark_chosen(search_history.read(issue_id), chosen_name),
        "chosen": chosen_name,
        "log": _log_lines(ctx, issue_id, chosen_name),
    }
