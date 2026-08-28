#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""SQLAlchemy Core queries owned by the AI domain."""

import time

from sqlalchemy import Float, cast, delete, func, insert, or_, select, update
from sqlalchemy.exc import OperationalError

from comicarr import db, logger
from comicarr.tables import ai_activity_log as t_ai_activity_log
from comicarr.tables import ai_cache as t_ai_cache
from comicarr.tables import ai_metadata_history as t_ai_metadata_history
from comicarr.tables import comics as t_comics
from comicarr.tables import issues as t_issues
from comicarr.tables import storyarcs as t_storyarcs
from comicarr.tables import weekly as t_weekly

_WRITE_ATTEMPTS = 5


def _run_write(operation):
    """Run a Core mutation with the legacy shim's in-process lock/retry contract."""
    with db._db_lock:
        for attempt in range(_WRITE_ATTEMPTS):
            try:
                with db.get_engine().begin() as conn:
                    operation(conn)
                return
            except OperationalError as error:
                error_message = str(error)
                if "locked" not in error_message and "unable to open" not in error_message:
                    logger.error("[AI-QUERIES] Database error executing Core mutation: %s", error)
                    raise
                logger.warn("[AI-QUERIES] Database write retry %d: %s", attempt + 1, error)
                time.sleep(1)


def insert_activity(values):
    """Insert a durable AI activity record."""
    _run_write(lambda conn: conn.execute(insert(t_ai_activity_log).values(**values)))


def get_activity(limit=50, offset=0):
    """Return activity records in the legacy newest-id-first order."""
    stmt = select(t_ai_activity_log).order_by(t_ai_activity_log.c.id.desc()).limit(int(limit)).offset(int(offset))
    return db.select_all(stmt)


def insert_metadata_history(values):
    """Insert one metadata-history record in its own compatibility transaction."""
    _run_write(lambda conn: conn.execute(insert(t_ai_metadata_history).values(**values)))


def issue_exists(issue_id):
    """Return whether an issue exists without leaking shim empty-list semantics."""
    stmt = select(t_issues.c.IssueID).where(t_issues.c.IssueID == issue_id).limit(1)
    return db.select_one(stmt) is not None


def delete_metadata_history(entity_type, entity_id, field_name, source):
    """Delete matching AI metadata history records."""
    stmt = delete(t_ai_metadata_history).where(
        t_ai_metadata_history.c.entity_type == entity_type,
        t_ai_metadata_history.c.entity_id == entity_id,
        t_ai_metadata_history.c.field_name == field_name,
        t_ai_metadata_history.c.source == source,
    )
    _run_write(lambda conn: conn.execute(stmt))


def find_exact_library_match(series_name, dynamic_name):
    """Find the legacy exact-name or dynamic-name library match."""
    stmt = (
        select(t_comics.c.ComicID)
        .where(or_(t_comics.c.ComicName == series_name, t_comics.c.DynamicComicName == dynamic_name))
        .limit(1)
    )
    return db.select_one(stmt)


def find_case_insensitive_library_match(series_name):
    """Find a series name using the legacy LOWER(column) comparison."""
    stmt = select(t_comics.c.ComicID).where(func.lower(t_comics.c.ComicName) == func.lower(series_name)).limit(1)
    return db.select_one(stmt)


def get_alternate_search_values():
    """Return every non-null alternate-search value for client-side matching."""
    return db.select_all(select(t_comics.c.AlternateSearch).where(t_comics.c.AlternateSearch.is_not(None)))


def get_alternate_search(comic_id):
    """Return a single series's alternate-search field, or ``None`` when absent."""
    stmt = select(t_comics.c.AlternateSearch).where(t_comics.c.ComicID == comic_id).limit(1)
    return db.select_one(stmt)


def update_alternate_search(comic_id, alternate_search):
    """Persist the legacy ##-delimited alternate-search field."""
    stmt = update(t_comics).where(t_comics.c.ComicID == comic_id).values(AlternateSearch=alternate_search)
    _run_write(lambda conn: conn.execute(stmt))


def get_cache_entry(cache_key, cache_type):
    """Return the data and expiry for a typed cache key, or ``None`` when absent."""
    stmt = (
        select(t_ai_cache.c.data, t_ai_cache.c.expires_at)
        .where(t_ai_cache.c.cache_key == cache_key, t_ai_cache.c.cache_type == cache_type)
        .limit(1)
    )
    return db.select_one(stmt)


def upsert_cache_entry(cache_key, cache_type, data, created_at, expires_at):
    """Atomically replace an AI cache entry using its declared unique key."""
    values = {
        "cache_type": cache_type,
        "data": data,
        "created_at": created_at,
        "expires_at": expires_at,
    }
    _run_write(
        lambda conn: db.upsert_conn(
            conn,
            "ai_cache",
            values,
            {"cache_key": cache_key},
        )
    )


def get_active_publisher_counts():
    """Return the ten most common active-library publishers."""
    count = func.count().label("count")
    stmt = (
        select(t_comics.c.ComicPublisher, count)
        .where(t_comics.c.Status == "Active")
        .group_by(t_comics.c.ComicPublisher)
        .order_by(count.desc())
        .limit(10)
    )
    return db.select_all(stmt)


def get_active_series_count():
    """Return the active-library series count."""
    stmt = select(func.count().label("count")).select_from(t_comics).where(t_comics.c.Status == "Active")
    return (db.select_one(stmt) or {}).get("count", 0) or 0


def get_active_series_names():
    """Return active series in the established sort-name order."""
    stmt = (
        select(t_comics.c.ComicName).where(t_comics.c.Status == "Active").order_by(t_comics.c.ComicSortName).limit(30)
    )
    return [row["ComicName"] for row in db.select_all(stmt) if row.get("ComicName")]


def get_active_completion_rate():
    """Return the legacy average per-series completion percentage, if any."""
    completion = cast(t_comics.c.Have, Float) / func.nullif(cast(t_comics.c.Total, Float), 0) * 100
    stmt = select(func.avg(completion).label("avg_pct")).where(t_comics.c.Status == "Active", t_comics.c.Total > 0)
    return (db.select_one(stmt) or {}).get("avg_pct")


def get_untracked_weekly_releases():
    """Return untracked weekly releases in publisher/title order."""
    stmt = (
        select(t_weekly.c.COMIC, t_weekly.c.PUBLISHER, t_weekly.c.ISSUE, t_weekly.c.STATUS)
        .where(or_(t_weekly.c.STATUS.is_(None), t_weekly.c.STATUS == ""))
        .order_by(t_weekly.c.PUBLISHER, t_weekly.c.COMIC)
        .limit(100)
    )
    return db.select_all(stmt)


def find_series_candidates(series_name):
    """Return the first five legacy LIKE candidates for an AI story-arc issue."""
    stmt = (
        select(t_comics.c.ComicID, t_comics.c.ComicName)
        .where(t_comics.c.ComicName.like("%%%s%%" % series_name))
        .limit(5)
    )
    return db.select_all(stmt)


def find_issue_by_comic_and_number(comic_id, issue_number):
    """Return the first matching issue identifier, or ``None``."""
    stmt = (
        select(t_issues.c.IssueID)
        .where(t_issues.c.ComicID == comic_id, t_issues.c.Issue_Number == issue_number)
        .limit(1)
    )
    return db.select_one(stmt)


def get_issue_status_by_id(issue_id):
    """Return an issue status by identifier, or ``None``."""
    return db.select_one(select(t_issues.c.Status).where(t_issues.c.IssueID == issue_id).limit(1))


def get_issue_status_by_comic_and_number(comic_id, issue_number):
    """Return an issue status by comic and issue number, or ``None``."""
    stmt = (
        select(t_issues.c.Status)
        .where(t_issues.c.ComicID == comic_id, t_issues.c.Issue_Number == issue_number)
        .limit(1)
    )
    return db.select_one(stmt)


def replace_storyarc(values):
    """Replace one AI story-arc row, clearing fields omitted by the save payload.

    The legacy ``INSERT OR REPLACE`` behavior intentionally discarded values
    not included in the generated-arc payload. A conventional upsert would
    retain stale columns, so use an explicit delete/insert pair in one
    transaction for portable equivalent semantics.
    """

    def replace(conn):
        conn.execute(delete(t_storyarcs).where(t_storyarcs.c.IssueArcID == values["IssueArcID"]))
        conn.execute(insert(t_storyarcs).values(**values))

    _run_write(replace)
