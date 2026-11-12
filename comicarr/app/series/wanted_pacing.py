#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""How fast auto-search is working through Wanted, for the Wanted page.

Two lanes reach a Wanted issue. Issues added in the last
``SEARCH_TIER_CUTOFF`` days get a full indexer search every
``SEARCH_INTERVAL``. Everything older waits for the RSS watchlist pass, which
checks up to ``WANTED_SEARCH_PASS_ITEMS`` issues per ``RSS_CHECKINTERVAL``
against the cached feeds, newest release first, and remembers what it checked
this cycle in ``rss_search_seen`` (see ``app/search/backlog.py``).

This module reads that state back: how far through the cycle the pass is, the
rate it has actually managed lately, when it runs next, and so roughly when
each series' issues come up. It changes nothing.
"""

from __future__ import annotations

import datetime
import math
import time

from sqlalchemy import select

import comicarr
from comicarr import db, logger
from comicarr.app.search.backlog import DEFAULT_ITEM_BUDGET, PASS_RSS_WANTED, _config_int
from comicarr.tables import rss_search_seen

# The measured rate looks back this far, and never over less than one pass.
RATE_WINDOW_HOURS = 6


def _seen():
    try:
        rows = db.select_all(
            select(rss_search_seen.c.issue_id, rss_search_seen.c.checked_at).where(
                rss_search_seen.c.pass_kind == PASS_RSS_WANTED
            )
        )
    except Exception as e:
        logger.fdebug("[WANTED-PACING] Unable to read the RSS pass seen set: %s" % e)
        return {}
    seen = {}
    for row in rows or []:
        try:
            seen[str(row["issue_id"])] = float(row["checked_at"])
        except (TypeError, ValueError):
            seen[str(row["issue_id"])] = 0.0
    return seen


def _job_next_run(job_id):
    scheduler = getattr(comicarr, "SCHED", None)
    if scheduler is None:
        return None
    try:
        job = scheduler.get_job(job_id)
    except Exception as e:
        logger.fdebug("[WANTED-PACING] Unable to read job %s: %s" % (job_id, e))
        return None
    if job is None or job.next_run_time is None:
        return None
    when = job.next_run_time
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return when.astimezone(datetime.timezone.utc).isoformat()


def _indexer_count(config):
    if config is None:
        return 0
    try:
        from comicarr.app.system.connections import _indexer_targets

        return len(_indexer_targets(config))
    except Exception as e:
        logger.fdebug("[WANTED-PACING] Unable to count indexers: %s" % e)
        return 0


def _rss_on(config):
    return bool(getattr(config, "ENABLE_RSS", False)) and str(getattr(comicarr, "RSS_STATUS", "")) != "Paused"


def _order_key(row):
    # The pass walks Wanted newest release first (search.searchforissue).
    return str(row.get("ReleaseDate") or "")


def measured_rate(seen_times, *, now, interval_minutes, configured):
    """Issues checked per hour lately; the configured ceiling when there is no history."""
    window_start = now - RATE_WINDOW_HOURS * 3600
    recent = [at for at in seen_times if at >= window_start]
    if not recent:
        return configured, False
    span = max(now - min(recent), interval_minutes * 60, 1)
    return len(recent) / (span / 3600), True


def pacing(rows, *, config=None, now=None):
    """The pacing banner and per-series ETAs for the Wanted rows given.

    Returns ``(summary, eta_by_comic)`` where ``eta_by_comic`` maps a ComicID
    to hours until the pass reaches that series' last unchecked issue.
    """
    config = config if config is not None else getattr(comicarr, "CONFIG", None)
    now = now if now is not None else time.time()
    interval = max(1, _config_int("RSS_CHECKINTERVAL", 20))
    per_pass = max(0, _config_int("WANTED_SEARCH_PASS_ITEMS", DEFAULT_ITEM_BUDGET))
    configured = per_pass * 60 / interval
    seen = _seen()
    rate, measured = measured_rate(seen.values(), now=now, interval_minutes=interval, configured=configured)

    ordered = sorted(rows or [], key=_order_key, reverse=True)
    wanted_ids = [str(row.get("IssueID")) for row in ordered if row.get("IssueID")]
    checked = sum(1 for issue_id in wanted_ids if issue_id in seen)
    waiting = len(wanted_ids) - checked

    eta = {}
    position = 0
    for row in ordered:
        issue_id = str(row.get("IssueID") or "")
        if not issue_id or issue_id in seen:
            continue
        position += 1
        if rate > 0:
            eta[str(row.get("ComicID"))] = position / rate

    if not wanted_ids:
        state = "idle"
    elif not _rss_on(config):
        state = "off"
    elif waiting == 0:
        state = "waiting_for_feed"
    else:
        state = "checking"

    summary = {
        "state": state,
        "total": len(wanted_ids),
        "checked": checked,
        "waiting": waiting,
        "per_hour": int(round(rate)) if state == "checking" else 0,
        "measured": measured,
        "per_pass": per_pass,
        "interval_minutes": interval,
        "finishes_in_hours": (math.ceil(waiting / rate * 10) / 10) if state == "checking" and rate > 0 else None,
        "next_pass_at": _job_next_run("rss") if state in ("checking", "waiting_for_feed") else None,
        "new_issue_days": max(0, _config_int("SEARCH_TIER_CUTOFF", 14)),
        "search_interval_minutes": max(1, _config_int("SEARCH_INTERVAL", 1440)),
        "next_search_at": _job_next_run("search"),
        "indexers": _indexer_count(config),
    }
    if state != "checking":
        eta = {}
    return summary, eta
