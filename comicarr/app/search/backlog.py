#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Bounded Wanted/RSS watchlist passes and the manga RSS lookup memo.

A scheduled RSS watchlist pass over a large Wanted list used to run to
completion while holding SEARCHLOCK, then start again because the trigger
interval was shorter than the pass. ``PassBudget`` gives that pass an item and
wall-clock budget, remembers which issues were already checked against the
current rssdb generation, and keeps the work off SEARCHLOCK so a manual search
can proceed.

``rss_lookup_memo`` is a separate, pass-scoped cache for the manga RSS pass:
identical rssdb lookups inside one ``mangaCheck()`` run once. It is off unless
a caller opens it, and it never outlives the pass or crosses threads.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, timedelta

from sqlalchemy import delete, select

import comicarr
from comicarr import db, logger
from comicarr.tables import rss_search_seen, search_backlog_state

PASS_RSS_WANTED = "rss_wanted"
PASS_RSSDB = "rssdb"

DEFAULT_ITEM_BUDGET = 250
DEFAULT_SECONDS_BUDGET = 120
RECENT_RELEASE_DAYS = 14

_PASS_LOCK = threading.Lock()
_LOOKUP_MEMO: ContextVar[dict | None] = ContextVar("rss_lookup_memo", default=None)


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
    """Non-blocking lock so overlapping RSS watchlist passes skip, not stack."""
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
    logger.fdebug("[SEARCH-BACKLOG] rssdb generation is now %s" % new_generation)
    return new_generation


@contextmanager
def rss_lookup_memo():
    """Cache identical rssdb lookups for the duration of one pass on this thread."""
    token = _LOOKUP_MEMO.set({})
    try:
        yield
    finally:
        _LOOKUP_MEMO.reset(token)


def rss_provider_lookup_key(seriesname, comicid, nzbprov, searchYear=None, ComicVersion=None, oneoff=False) -> tuple:
    if comicid not in (None, "None", "") and oneoff is not True:
        series = ("id", str(comicid))
    else:
        series = ("name", str(seriesname or "").lower())
    return series + (str(nzbprov or ""), str(searchYear or ""), str(ComicVersion or ""), bool(oneoff))


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
    """Return a memoised lookup, or None when no memo is open or the key is new."""
    memo = _LOOKUP_MEMO.get()
    if memo is None or key not in memo:
        return None
    return copy_lookup_result(memo[key])


def put_rss_provider_lookup(key: tuple, result) -> None:
    memo = _LOOKUP_MEMO.get()
    if memo is not None and result is not None:
        memo[key] = copy_lookup_result(result)


def is_recent_release(row, *, today: date | None = None, days: int = RECENT_RELEASE_DAYS) -> bool:
    """True when any of the row's release dates falls within the last ``days``."""
    cutoff = (today or date.today()) - timedelta(days=days)
    for field in ("StoreDate", "IssueDate", "DigitalDate"):
        raw = row.get(field)
        if not raw or str(raw).startswith("0000"):
            continue
        try:
            released = date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        if released >= cutoff:
            return True
    return False


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
        if item_budget is None:
            item_budget = _config_int("WANTED_SEARCH_PASS_ITEMS", DEFAULT_ITEM_BUDGET)
        if seconds_budget is None:
            seconds_budget = _config_int("WANTED_SEARCH_PASS_SECONDS", DEFAULT_SECONDS_BUDGET)
        self.item_budget = max(0, item_budget)
        self.seconds_budget = max(0, seconds_budget)
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

    def remaining(self) -> bool:
        """False once the wall-clock budget is spent. select_candidates enforces the item budget."""
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

    def mark_ineligible(self, issue_id: str | None) -> None:
        """Persist as seen without spending the item budget.

        Ineligible rows (orphans, inactive series) must not be RSS-looked-up,
        but they still have to count as checked or the cycle never completes.
        """
        if not issue_id:
            return
        issue_id = str(issue_id)
        if issue_id in self.seen:
            return
        self.seen.add(issue_id)
        try:
            db.upsert(
                "rss_search_seen",
                {"checked_at": _now_iso()},
                {"pass_kind": self.pass_kind, "issue_id": issue_id},
            )
        except Exception as e:
            logger.fdebug("[SEARCH-BACKLOG] Unable to persist ineligible %s/%s: %s" % (self.pass_kind, issue_id, e))

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

    def select_candidates(self, items, issue_id_of, recent=None):
        """Return the next budgeted slice of unseen items, newest-first order preserved.

        When every candidate has already been checked and rssdb has not changed
        since this cycle started, return an empty list so the pass idles.
        When rssdb *has* changed since the cycle completed, clear seen and start
        over. An in-flight cycle is not reset by an rssdb refresh, so items for
        which ``recent(item)`` is true are re-checked on every pass on top of the
        item budget; a new release is not left waiting for the cycle to wrap.

        Callers must ``consume`` every item returned, whatever happens to it.
        An item handed out and never consumed keeps the cycle from completing.
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
        chosen = {issue_id for issue_id, _item in unseen}
        if recent is not None:
            chosen.update(issue_id for issue_id, item in indexed if issue_id in self.seen and recent(item))
        return [item for issue_id, item in indexed if issue_id in chosen]

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
