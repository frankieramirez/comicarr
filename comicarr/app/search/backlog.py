#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Bounded Wanted/RSS backlog passes with a persisted resume cursor.

A scheduled pass over a large Wanted list used to run to completion while
holding SEARCHLOCK, then start again because the trigger interval was shorter
than the pass. This module gives each pass an item and wall-clock budget,
remembers which issues were already checked against the current rssdb
generation, and keeps that work off SEARCHLOCK so a manual search can proceed.
"""

from __future__ import annotations

import threading
import time

from sqlalchemy import delete, select

import comicarr
from comicarr import db, logger
from comicarr.tables import rss_search_seen, search_backlog_state

PASS_RSS_WANTED = "rss_wanted"
PASS_MANGA_RSS = "manga_rss"
PASS_RSSDB = "rssdb"

DEFAULT_ITEM_BUDGET = 250
DEFAULT_SECONDS_BUDGET = 120

_PASS_LOCK = threading.Lock()
_LOOKUP_LOCK = threading.Lock()
_LOOKUP_CACHE: dict[tuple, object] = {}
_LOOKUP_GENERATION: str | None = None


def _config_int(name: str, default: int) -> int:
    config = getattr(comicarr, "CONFIG", None)
    if config is None:
        return default
    raw = getattr(config, name, default)
    if isinstance(raw, bool):
        return default
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            return default
    return default


def _now_iso() -> str:
    from comicarr.helpers import utctimestamp

    return str(int(utctimestamp()))


def try_acquire_pass() -> bool:
    """Non-blocking lock so overlapping RSS/manga backlog jobs skip, not stack."""
    return _PASS_LOCK.acquire(blocking=False)


def release_pass() -> None:
    try:
        _PASS_LOCK.release()
    except RuntimeError:
        pass


def current_rssdb_generation() -> str:
    try:
        row = db.select_one(
            select(search_backlog_state.c.rssdb_generation).where(search_backlog_state.c.pass_kind == PASS_RSSDB)
        )
    except Exception as e:
        logger.fdebug("[SEARCH-BACKLOG] Unable to read rssdb generation: %s" % e)
        return ""
    if row is None:
        return ""
    return str(row["rssdb_generation"] or "")


def mark_rssdb_refreshed(generation: str | None = None) -> str:
    """Record a new rssdb snapshot. Does not reset an in-flight cycle."""
    new_generation = generation if generation is not None else _now_iso()
    try:
        db.upsert(
            "search_backlog_state",
            {
                "cursor_key": None,
                "rssdb_generation": new_generation,
                "updated_at": _now_iso(),
            },
            {"pass_kind": PASS_RSSDB},
        )
    except Exception as e:
        logger.warn("[SEARCH-BACKLOG] Unable to persist rssdb generation: %s" % e)
    clear_lookup_cache()
    logger.fdebug("[SEARCH-BACKLOG] rssdb generation is now %s" % new_generation)
    return new_generation


def rss_provider_lookup_key(seriesname, comicid, nzbprov, oneoff=False) -> tuple:
    provider = str(nzbprov or "")
    if comicid not in (None, "None", "") and oneoff is not True:
        return ("id", str(comicid), provider)
    return ("name", str(seriesname or "").lower(), provider)


def copy_lookup_result(result):
    if result is None or result == "no results":
        return result
    if not isinstance(result, dict):
        return result
    copied = dict(result)
    entries = result.get("entries")
    if isinstance(entries, list):
        copied["entries"] = [dict(entry) if isinstance(entry, dict) else entry for entry in entries]
    return copied


def get_rss_provider_lookup(key: tuple):
    generation = current_rssdb_generation()
    with _LOOKUP_LOCK:
        global _LOOKUP_GENERATION
        if _LOOKUP_GENERATION != generation:
            _LOOKUP_CACHE.clear()
            _LOOKUP_GENERATION = generation
        cached = _LOOKUP_CACHE.get(key)
    if cached is None:
        return None
    return copy_lookup_result(cached)


def put_rss_provider_lookup(key: tuple, result) -> None:
    generation = current_rssdb_generation()
    with _LOOKUP_LOCK:
        global _LOOKUP_GENERATION
        if _LOOKUP_GENERATION != generation:
            _LOOKUP_CACHE.clear()
            _LOOKUP_GENERATION = generation
        _LOOKUP_CACHE[key] = copy_lookup_result(result)


def clear_lookup_cache() -> None:
    with _LOOKUP_LOCK:
        _LOOKUP_CACHE.clear()


def _load_state(pass_kind: str) -> dict | None:
    try:
        return db.select_one(select(search_backlog_state).where(search_backlog_state.c.pass_kind == pass_kind))
    except Exception as e:
        logger.fdebug("[SEARCH-BACKLOG] Unable to load pass state for %s: %s" % (pass_kind, e))
        return None


def _save_state(pass_kind: str, cursor_key: str | None, cycle_generation: str) -> None:
    try:
        db.upsert(
            "search_backlog_state",
            {
                "cursor_key": cursor_key,
                "rssdb_generation": cycle_generation,
                "updated_at": _now_iso(),
            },
            {"pass_kind": pass_kind},
        )
    except Exception as e:
        logger.warn("[SEARCH-BACKLOG] Unable to persist pass state for %s: %s" % (pass_kind, e))


class PassBudget:
    """Item/time budget and persisted seen-set for one scheduled backlog pass."""

    def __init__(self, pass_kind: str, *, item_budget=None, seconds_budget=None, monotonic=time.monotonic):
        self.pass_kind = pass_kind
        self.item_budget = DEFAULT_ITEM_BUDGET if item_budget is None else item_budget
        if item_budget is None:
            self.item_budget = _config_int("WANTED_SEARCH_PASS_ITEMS", DEFAULT_ITEM_BUDGET)
        self.seconds_budget = DEFAULT_SECONDS_BUDGET if seconds_budget is None else seconds_budget
        if seconds_budget is None:
            self.seconds_budget = _config_int("WANTED_SEARCH_PASS_SECONDS", DEFAULT_SECONDS_BUDGET)
        self._monotonic = monotonic
        self.started_at = monotonic()
        self.processed = 0
        self.skipped = 0
        self.stop_reason = None
        self.rssdb_generation = current_rssdb_generation()
        state = _load_state(pass_kind) or {}
        self.cycle_generation = str(state.get("rssdb_generation") or "")
        self.cursor_key = state.get("cursor_key")
        self.seen = self._load_seen()

    def _load_seen(self) -> set[str]:
        try:
            rows = db.select_all(
                select(rss_search_seen.c.issue_id).where(rss_search_seen.c.pass_kind == self.pass_kind)
            )
        except Exception as e:
            logger.fdebug("[SEARCH-BACKLOG] Unable to load seen set for %s: %s" % (self.pass_kind, e))
            return set()
        return {str(row["issue_id"]) for row in rows if row.get("issue_id")}

    def already_seen(self, issue_id: str | None) -> bool:
        if not issue_id:
            return False
        return str(issue_id) in self.seen

    def remaining(self) -> bool:
        if self.item_budget and self.processed >= self.item_budget:
            self.stop_reason = "item_budget"
            return False
        if self.seconds_budget and (self._monotonic() - self.started_at) >= self.seconds_budget:
            self.stop_reason = "time_budget"
            return False
        return True

    def consume(self, issue_id: str | None) -> None:
        if not issue_id:
            return
        issue_id = str(issue_id)
        self.seen.add(issue_id)
        self.processed += 1
        self.cursor_key = issue_id
        try:
            db.upsert(
                "rss_search_seen",
                {"checked_at": _now_iso()},
                {"pass_kind": self.pass_kind, "issue_id": issue_id},
            )
        except Exception as e:
            logger.fdebug("[SEARCH-BACKLOG] Unable to persist seen %s/%s: %s" % (self.pass_kind, issue_id, e))
        _save_state(self.pass_kind, self.cursor_key, self.cycle_generation or self.rssdb_generation)

    def _reset_cycle(self) -> None:
        self.seen = set()
        self.cursor_key = None
        self.cycle_generation = self.rssdb_generation
        try:
            with db.get_engine().begin() as conn:
                conn.execute(delete(rss_search_seen).where(rss_search_seen.c.pass_kind == self.pass_kind))
        except Exception as e:
            logger.warn("[SEARCH-BACKLOG] Failed to reset seen set for %s: %s" % (self.pass_kind, e))
        _save_state(self.pass_kind, None, self.cycle_generation)
        logger.info(
            "[SEARCH-BACKLOG] Starting a new %s cycle against rssdb generation %s"
            % (self.pass_kind, self.cycle_generation or "(none)")
        )

    def select_candidates(self, items, issue_id_of):
        """Return the next budgeted slice of unseen items, newest-first order preserved.

        When every candidate has already been checked and rssdb has not changed
        since this cycle started, return an empty list so the pass idles.
        When rssdb *has* changed since the cycle completed, clear seen and start
        over. An in-flight cycle is not reset by an rssdb refresh.
        """
        indexed = []
        for item in items:
            issue_id = issue_id_of(item)
            if not issue_id:
                continue
            indexed.append((str(issue_id), item))

        if not indexed:
            return []

        unseen = [(issue_id, item) for issue_id, item in indexed if issue_id not in self.seen]
        if not unseen:
            if self.cycle_generation == self.rssdb_generation:
                self.stop_reason = "waiting_for_rssdb"
                logger.info(
                    "[SEARCH-BACKLOG] %s cycle complete against rssdb generation %s; waiting for a feed refresh"
                    % (self.pass_kind, self.cycle_generation or "(none)")
                )
                return []
            self._reset_cycle()
            unseen = indexed

        if not self.cycle_generation:
            self.cycle_generation = self.rssdb_generation
            _save_state(self.pass_kind, self.cursor_key, self.cycle_generation)

        self.skipped = len(indexed) - len(unseen)
        if self.item_budget:
            unseen = unseen[: self.item_budget]
        return [item for _issue_id, item in unseen]

    def log_summary(self, extra: str = "") -> None:
        elapsed = self._monotonic() - self.started_at
        parts = [
            "[SEARCH-BACKLOG] %s pass processed %s item(s) in %.1fs (skipped %s already checked)"
            % (self.pass_kind, self.processed, elapsed, self.skipped)
        ]
        if self.stop_reason:
            parts.append("stop=%s" % self.stop_reason)
        if extra:
            parts.append(extra)
        logger.info("; ".join(parts))


def take_pass_slice(items, issue_id_of, budget: PassBudget):
    """Compatibility wrapper used by tests and callers that prefer a function."""
    return budget.select_candidates(items, issue_id_of)
