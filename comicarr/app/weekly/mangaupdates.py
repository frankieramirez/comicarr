#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Weekly manga, manhwa and manhua releases from MangaUpdates (#1383).

MangaUpdates (https://api.mangaupdates.com/) is free and needs no key. Its
acceptable use policy asks for credit, spaced requests and caching, so this
module:

- fetches only when Releases asks for a week and the cache is older than
  ``REFRESH_SECONDS``, on a background thread, never on a timer;
- spaces every request ``REQUEST_SPACING`` seconds apart;
- keeps everything it learned in one JSON file under the cache folder, so a
  restart does not refetch, and releases older than the window MangaUpdates
  serves stay browsable.

``/v1/releases/days`` lists roughly the last four weeks of chapter releases.
Its rows name a series but not its type or cover, so the type, cover and
weekly popularity come from ``/v1/series/search`` ordered by ``week_pos``
(the popular series) and from ``/v1/series/{id}`` for the rest, a capped
number per refresh. MangaUpdates lists chapters after they come out, so a
future week has no manga rows.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import tempfile
import threading
import time
from urllib.parse import quote

import requests

import comicarr
from comicarr.app.common.user_agent import app_user_agent
from comicarr.app.core import logger

API_BASE = "https://api.mangaupdates.com/v1"
SOURCE = "mangaupdates"
CACHE_FILE = "mangaupdates_releases.json"

TYPES = ("Manga", "Manhwa", "Manhua")
REFRESH_SECONDS = 12 * 60 * 60
# A failed refresh is retried after this long, not on every page view.
RETRY_SECONDS = 15 * 60
REQUEST_SPACING = 1.0
REQUEST_TIMEOUT = 30
MAX_RELEASE_PAGES = 20
POPULAR_PAGE_SIZE = 100
POPULAR_PAGES = 5
POPULAR_RANK = POPULAR_PAGES * POPULAR_PAGE_SIZE
DETAIL_LOOKUPS_PER_REFRESH = 150
SERIES_TTL_SECONDS = 30 * 24 * 60 * 60
KEEP_DAYS = 400

_STATE_LOCK = threading.Lock()
_REFRESH_LOCK = threading.Lock()
_state: dict = {"thread": None, "last_attempt": 0.0, "last_error": None}
_cache: dict = {"path": None, "mtime": None, "data": None}
_last_request = [0.0]


class SourceError(RuntimeError):
    """MangaUpdates could not be reached or answered with something unusable."""


def is_enabled(config=None) -> bool:
    """Manga rows only help when Comicarr can add a manga series."""
    config = config if config is not None else comicarr.CONFIG
    if config is None:
        return False
    mal_ok = bool(getattr(config, "MAL_ENABLED", False) and getattr(config, "MAL_CLIENT_ID", None))
    return bool(getattr(config, "MANGADEX_ENABLED", False)) or mal_ok


def _cache_path():
    config = comicarr.CONFIG
    folder = getattr(config, "CACHE_DIR", None) if config is not None else None
    if not folder:
        folder = os.path.join(getattr(comicarr, "DATA_DIR", None) or ".", "cache")
    return os.path.join(str(folder), CACHE_FILE)


def _empty():
    return {"fetched_at": None, "releases": {}, "series": {}, "popular": {}}


def load():
    """Return the cached data, re-reading the file only when it changed."""
    path = _cache_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return _empty()
    with _STATE_LOCK:
        if _cache["path"] == path and _cache["mtime"] == mtime and _cache["data"] is not None:
            return _cache["data"]
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as e:
        logger.warn("[MANGAUPDATES] Ignoring an unreadable release cache: %s" % e)
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    for key, default in _empty().items():
        if not isinstance(data.get(key), type(default)) and default is not None:
            data[key] = default
    with _STATE_LOCK:
        _cache.update(path=path, mtime=mtime, data=data)
    return data


def _save(data):
    path = _cache_path()
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".mangaupdates-", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    with _STATE_LOCK:
        _cache.update(path=path, mtime=os.path.getmtime(path), data=data)


def _request(method, path, *, params=None, body=None):
    wait = REQUEST_SPACING - (time.monotonic() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    headers = {"User-Agent": app_user_agent(), "Accept": "application/json"}
    try:
        response = requests.request(
            method, API_BASE + path, params=params, json=body, headers=headers, timeout=REQUEST_TIMEOUT
        )
    except requests.exceptions.RequestException as e:
        raise SourceError("MangaUpdates is unreachable: %s" % e) from e
    finally:
        _last_request[0] = time.monotonic()
    if response.status_code != 200:
        raise SourceError("MangaUpdates answered HTTP %s for %s" % (response.status_code, path))
    try:
        return response.json()
    except ValueError as e:
        raise SourceError("MangaUpdates sent a response that is not JSON for %s" % path) from e


def _image(record):
    url = ((record.get("image") or {}).get("url") or {}) if isinstance(record, dict) else {}
    return url.get("thumb") or url.get("original") or None


def _series_entry(record, now):
    return {
        "title": record.get("title") or "",
        "type": record.get("type") if record.get("type") in TYPES else None,
        "image": _image(record),
        "url": record.get("url") or None,
        "year": record.get("year") or None,
        "fetched_at": now,
    }


def _fetch_releases():
    rows, page = [], 1
    while page <= MAX_RELEASE_PAGES:
        payload = _request("GET", "/releases/days", params={"include_metadata": "true", "page": page})
        results = payload.get("results") or []
        rows.extend(results)
        if not results or len(rows) >= int(payload.get("total_hits") or 0):
            break
        page += 1
    return rows


def _fetch_popular(now):
    ranks, series = {}, {}
    for page in range(1, POPULAR_PAGES + 1):
        payload = _request(
            "POST",
            "/series/search",
            body={"orderby": "week_pos", "type": list(TYPES), "perpage": POPULAR_PAGE_SIZE, "page": page},
        )
        results = payload.get("results") or []
        for index, result in enumerate(results):
            record = result.get("record") or {}
            series_id = record.get("series_id")
            if not series_id:
                continue
            ranks[str(series_id)] = (page - 1) * POPULAR_PAGE_SIZE + index + 1
            series[str(series_id)] = _series_entry(record, now)
        if len(results) < POPULAR_PAGE_SIZE:
            break
    return ranks, series


def _release_entry(result):
    record = result.get("record") or {}
    meta = (result.get("metadata") or {}).get("series") or {}
    release_id, series_id = record.get("id"), meta.get("series_id")
    release_date = record.get("release_date") or ""
    if not release_id or not series_id or not re.match(r"^\d{4}-\d{2}-\d{2}$", release_date):
        return None
    return str(release_id), {
        "series_id": str(series_id),
        "title": meta.get("title") or record.get("title") or "",
        "url": meta.get("url") or None,
        "chapter": (record.get("chapter") or "").strip(),
        "volume": (record.get("volume") or "").strip() if record.get("volume") else "",
        "date": release_date,
    }


def refresh(now=None, today=None):
    """Fetch releases, popularity and missing series details into the cache.

    Raises :class:`SourceError` when MangaUpdates cannot be reached; the
    cache keeps what it had.
    """
    now = now if now is not None else time.time()
    today = today or datetime.date.today()
    with _REFRESH_LOCK:
        data = json.loads(json.dumps(load()))
        releases = data["releases"]
        for result in _fetch_releases():
            entry = _release_entry(result)
            if entry:
                releases[entry[0]] = entry[1]
        cutoff = (today - datetime.timedelta(days=KEEP_DAYS)).isoformat()
        data["releases"] = releases = {key: row for key, row in releases.items() if row.get("date", "") >= cutoff}

        ranks, popular_series = _fetch_popular(now)
        data["popular"] = ranks
        data["series"].update(popular_series)

        # Newest releases first, so a capped run covers this week before older ones.
        missing = []
        for row in sorted(releases.values(), key=lambda row: row["date"], reverse=True):
            series_id = row["series_id"]
            known = data["series"].get(series_id)
            if series_id in missing or (known and now - float(known.get("fetched_at") or 0) < SERIES_TTL_SECONDS):
                continue
            missing.append(series_id)
        looked_up = 0
        for series_id in missing[:DETAIL_LOOKUPS_PER_REFRESH]:
            try:
                record = _request("GET", "/series/%s" % series_id)
            except SourceError as e:
                # Remember the miss so a removed series is not asked for on every refresh.
                logger.fdebug("[MANGAUPDATES] Series %s lookup failed: %s" % (series_id, e))
                data["series"][series_id] = _series_entry({}, now)
                continue
            data["series"][series_id] = _series_entry(record, now)
            looked_up += 1
        data["fetched_at"] = now
        _save(data)
    logger.info(
        "[MANGAUPDATES] Cached %s releases, %s popular series, %s new series details (%s still to look up)"
        % (len(releases), len(ranks), looked_up, max(0, len(missing) - looked_up))
    )
    return data


def _run_refresh():
    try:
        refresh()
        with _STATE_LOCK:
            _state["last_error"] = None
    except Exception as e:
        logger.warn("[MANGAUPDATES] Release refresh failed: %s" % e)
        with _STATE_LOCK:
            _state["last_error"] = "MangaUpdates could not be reached. Comicarr retries in a few minutes."


def ensure_fresh(force=False, now=None):
    """Start a background refresh when the cache is stale; return the source state.

    ``"refreshing"`` while a refresh runs, otherwise ``"ok"`` (or
    ``"unavailable"`` after a failed refresh with nothing cached).
    """
    now = now if now is not None else time.time()
    data = load()
    fetched_at = float(data.get("fetched_at") or 0)
    with _STATE_LOCK:
        thread = _state["thread"]
        if thread is not None and thread.is_alive():
            return "refreshing"
        stale = now - fetched_at >= (60 if force else REFRESH_SECONDS)
        retry_ok = now - _state["last_attempt"] >= (60 if force else RETRY_SECONDS)
        if stale and retry_ok:
            from comicarr.app.core.workers import start_background_thread

            _state["last_attempt"] = now
            try:
                _state["thread"] = start_background_thread(_run_refresh, name="MANGAUPDATES-REFRESH", daemon=True)
            except RuntimeError as e:
                # The worker registry closes for shutdown; skip the refresh.
                logger.fdebug("[MANGAUPDATES] Refresh not started: %s" % e)
                return "ok"
            return "refreshing"
        if _state["last_error"] and not fetched_at:
            return "unavailable"
    return "ok"


def last_error():
    with _STATE_LOCK:
        return _state["last_error"]


def _chapter_number(value):
    match = re.match(r"\s*(?:c\.?\s*)?(\d+(?:\.\d+)?)", value or "", re.IGNORECASE)
    return float(match.group(1)) if match else None


def _number_text(number):
    return ("%g" % number) if number is not None else ""


def _proxied(url):
    return "/api/metadata/image-proxy?url=%s" % quote(url, safe="") if url else None


def week_rows(start, end, data=None):
    """Collapse one week's releases to one row per series.

    A series released several chapters (or several groups posted the same
    one) shows as one row: ``ISSUE`` is the newest chapter and ``chapters``
    names the range.
    """
    data = data if data is not None else load()
    by_series: dict[str, list] = {}
    for row in data.get("releases", {}).values():
        if start <= row.get("date", "") <= end:
            by_series.setdefault(row["series_id"], []).append(row)

    rows = []
    for series_id, releases in by_series.items():
        series = data.get("series", {}).get(series_id) or {}
        chapters = sorted(
            {n for n in (_chapter_number(r["chapter"]) for r in releases) if n is not None},
        )
        volumes = sorted(
            {n for n in (_chapter_number(r["volume"]) for r in releases if not r["chapter"]) if n is not None}
        )
        newest = max(releases, key=lambda r: r["date"])
        if chapters:
            issue = _number_text(chapters[-1])
            span = issue if len(chapters) == 1 else "%s–%s" % (_number_text(chapters[0]), issue)
        else:
            issue, span = "", ""
        rows.append(
            {
                "key": "mu-%s" % series_id,
                "source": SOURCE,
                "mu_series_id": series_id,
                "COMIC": series.get("title") or newest["title"],
                "ISSUE": issue,
                "chapters": span,
                "volume": _number_text(volumes[-1]) if volumes else "",
                "SHIPDATE": newest["date"],
                "PUBLISHER": None,
                "format": series.get("type"),
                "year": series.get("year"),
                "popular_rank": data.get("popular", {}).get(series_id),
                "cover": _proxied(series.get("image")),
                "url": series.get("url") or newest.get("url"),
            }
        )
    rows.sort(key=lambda row: (row["popular_rank"] or POPULAR_RANK + 1, row["COMIC"].lower()))
    return rows
