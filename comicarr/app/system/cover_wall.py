#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The opt-in cover wall behind the sign-in form.

The sign-in page is public, so this module answers to anyone. It shows
covers only: no titles, ids, counts, or version. Tiles are addressed by slot
number, and only covers already in the local cache are served, so an
anonymous visitor can never make Comicarr fetch anything.

Covers rated adult are left out. Comics and manga alternate so the wall
mixes both.
"""

import os
import random
import re
import threading
import time

from sqlalchemy import select

from comicarr import db, logger
from comicarr.tables import comics

MAX_TILES = 48
REFRESH_SECONDS = 3600

# Any rating that reads as adult keeps a series off the wall. Unrated series
# stay eligible, which is the operator's call when turning the wall on.
_ADULT_RATING = re.compile(
    r"mature|adult|explicit|erotic|porn|hentai|suggestive|nsfw|r-?18|18\s*\+|\bm\b|\bx\b",
    re.IGNORECASE,
)

_lock = threading.Lock()
_cache = {"at": 0.0, "dir": None, "ids": []}


def is_safe_rating(rating):
    """Return whether a series' age rating allows it on the public wall."""
    if rating is None:
        return True
    text = str(rating).strip()
    return not text or not _ADULT_RATING.search(text)


def _cached_cover(cache_dir, comic_id):
    if not cache_dir or not comic_id or not re.fullmatch(r"[A-Za-z0-9_.-]+", str(comic_id)):
        return None
    path = os.path.join(cache_dir, "%s.jpg" % comic_id)
    return path if os.path.isfile(path) else None


def _interleave(first, second):
    out = []
    for index in range(max(len(first), len(second))):
        if index < len(first):
            out.append(first[index])
        if index < len(second):
            out.append(second[index])
    return out


def select_covers(cache_dir, limit=MAX_TILES, rng=None):
    """Pick up to ``limit`` safe, cached covers, comics and manga alternating."""
    rng = rng or random.Random()
    rows = db.select_all(select(comics.c.ComicID, comics.c.ContentType, comics.c.AgeRating))
    picks = {"comic": [], "manga": []}
    for row in rows:
        if not is_safe_rating(row.get("AgeRating")):
            continue
        if _cached_cover(cache_dir, row.get("ComicID")) is None:
            continue
        kind = "manga" if (row.get("ContentType") or "").lower() == "manga" else "comic"
        picks[kind].append(str(row["ComicID"]))
    for ids in picks.values():
        rng.shuffle(ids)
    return _interleave(picks["comic"], picks["manga"])[:limit]


def enabled(config):
    return bool(getattr(config, "LOGIN_COVER_WALL", False))


def tiles(config, now=None):
    """Return the wall's cover ids, refreshed at most once an hour."""
    if not enabled(config):
        return []
    cache_dir = getattr(config, "CACHE_DIR", None)
    now = time.time() if now is None else now
    with _lock:
        stale = now - _cache["at"] > REFRESH_SECONDS or _cache["dir"] != cache_dir
        if stale:
            try:
                _cache["ids"] = select_covers(cache_dir)
            except Exception as e:
                logger.warn("[COVER-WALL] Could not pick covers: %s" % e)
                _cache["ids"] = []
            _cache["at"] = now
            _cache["dir"] = cache_dir
        return list(_cache["ids"])


def cover_path(config, slot):
    """Return the cached file for one tile, or None."""
    ids = tiles(config)
    if not 0 <= slot < len(ids):
        return None
    return _cached_cover(getattr(config, "CACHE_DIR", None), ids[slot])


def reset():
    """Forget the picked covers (tests, and after the setting changes)."""
    with _lock:
        _cache.update({"at": 0.0, "dir": None, "ids": []})
