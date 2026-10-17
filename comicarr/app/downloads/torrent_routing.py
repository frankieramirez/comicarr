#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Pick the qBittorrent category and save path for a snatch from its Series' library root (#1062)."""

import os
from typing import NamedTuple

from comicarr import logger


class QbittorrentDestination(NamedTuple):
    category: str | None
    savepath: str | None


class _Route(NamedTuple):
    root: str
    category: str | None
    savepath: str | None


def _setting(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value or value.lower() == "none":
        return None
    return value


def parse_routes(raw, warn=True):
    """Parse `<library root> | <category> | <save path>` lines; the save path is optional.

    Lines without an absolute root, or with neither a category nor a save path,
    are logged and ignored so one typo cannot block every torrent add.
    """
    routes = []
    if not isinstance(raw, str):
        return routes
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        root = parts[0]
        category = _setting(parts[1]) if len(parts) > 1 else None
        savepath = _setting(parts[2]) if len(parts) > 2 else None
        if len(parts) > 3 or not os.path.isabs(root) or (category is None and savepath is None):
            if warn:
                logger.warn("[QBITTORRENT] Ignoring unusable library root routing line: %r" % line)
            continue
        routes.append(_Route(os.path.normpath(root), category, savepath))
    return routes


def _within(path, root):
    path, root = os.path.normcase(os.path.normpath(path)), os.path.normcase(root)
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def route_for_location(location, raw_routes):
    """Return the route whose root holds `location`, preferring the deepest root."""
    if not location:
        return None
    matches = [route for route in parse_routes(raw_routes) if _within(location, route.root)]
    if not matches:
        return None
    return max(matches, key=lambda route: len(route.root))


def _series_location(comic_id):
    from comicarr.app.series import queries as series_queries

    try:
        series = series_queries.get_series_location(comic_id)
    except Exception as e:
        logger.warn("[QBITTORRENT] Could not read the library folder for Series %s: %s" % (comic_id, e))
        return None
    return (series or {}).get("ComicLocation")


def qbittorrent_destination(config, comic_id=None):
    """Category and save path for a qBittorrent add, falling back to the global settings."""
    default = QbittorrentDestination(
        _setting(getattr(config, "QBITTORRENT_LABEL", None)),
        _setting(getattr(config, "QBITTORRENT_FOLDER", None)),
    )
    raw_routes = getattr(config, "QBITTORRENT_ROOT_ROUTES", None)
    if comic_id is None or not _setting(raw_routes):
        return default
    route = route_for_location(_series_location(comic_id), raw_routes)
    if route is None:
        return default
    return QbittorrentDestination(route.category or default.category, route.savepath or default.savepath)
