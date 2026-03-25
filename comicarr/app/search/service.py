#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Search domain service — provider search, RSS monitoring.

Module-level functions wrapping existing search.py (~4300 lines) and
rsscheck.py. Preserves ThreadPoolExecutor for parallel provider queries.
"""

from operator import itemgetter

import comicarr
from comicarr import logger


def find_comic(ctx, name, issue=None, type_="comic", mode="series",
               limit=None, offset=None, sort=None, content_type=None):
    """Search for comics across configured providers.

    Delegates to MangaDex for manga, or mb.findComic for comics/story arcs.
    Returns results with in_library boolean added.
    """
    from comicarr import mb

    if not name:
        return {"error": "Missing a Comic name"}

    try:
        parsed_limit = int(limit) if limit else None
        parsed_offset = int(offset) if offset else None
    except (ValueError, TypeError):
        return {"error": "Invalid pagination parameters"}

    # Route to appropriate provider
    if content_type == "manga":
        if not ctx.config or not getattr(ctx.config, "MANGADEX_ENABLED", False):
            return {"error": "MangaDex integration is not enabled"}
        from comicarr import mangadex
        searchresults = mangadex.search_manga(name, limit=parsed_limit, offset=parsed_offset, sort=sort)
    elif type_ == "story_arc":
        searchresults = mb.findComic(
            name, mode, issue=None, search_type="story_arc",
            limit=parsed_limit, offset=parsed_offset, sort=sort,
        )
    else:
        searchresults = mb.findComic(
            name, mode, issue=issue, limit=parsed_limit,
            offset=parsed_offset, sort=sort, content_type=content_type,
        )

    # Add in_library flag
    def add_in_library(comic):
        comic["in_library"] = comic.get("haveit") != "No"
        return comic

    if isinstance(searchresults, dict) and "results" in searchresults:
        searchresults["results"] = [add_in_library(c) for c in searchresults["results"]]
        return searchresults
    else:
        searchresults = sorted(searchresults, key=itemgetter("comicyear", "issues"), reverse=True)
        searchresults = [add_in_library(c) for c in searchresults]
        return {"results": searchresults}


def find_manga(ctx, name, limit=None, offset=None, sort=None):
    """Search for manga via MangaDex API."""
    if not ctx.config or not getattr(ctx.config, "MANGADEX_ENABLED", False):
        return {"error": "MangaDex integration is not enabled"}

    from comicarr import mangadex

    try:
        parsed_limit = int(limit) if limit else None
        parsed_offset = int(offset) if offset else None
    except (ValueError, TypeError):
        return {"error": "Invalid pagination parameters"}

    searchresults = mangadex.search_manga(name, limit=parsed_limit, offset=parsed_offset, sort=sort)

    def add_in_library(manga):
        manga["in_library"] = manga.get("haveit") != "No"
        return manga

    if isinstance(searchresults, dict) and "results" in searchresults:
        searchresults["results"] = [add_in_library(m) for m in searchresults["results"]]
        return searchresults
    return {"error": "Search returned no results"}


def add_comic(ctx, comic_id):
    """Add a comic to the watchlist via WebInterface."""
    from comicarr.webserve import WebInterface
    try:
        ac = WebInterface()
        ac.addbyid(comic_id, calledby=True, nothread=False)
    except Exception as e:
        logger.error("[SEARCH] Error adding comic %s: %s" % (comic_id, e))
        return {"success": False, "error": str(e)}
    return {"success": True, "message": "Successfully queued adding id: %s" % comic_id}


def add_manga(ctx, manga_id):
    """Add a manga by MangaDex ID."""
    if not str(manga_id).startswith("md-"):
        manga_id = "md-" + manga_id

    if not ctx.config or not getattr(ctx.config, "MANGADEX_ENABLED", False):
        return {"success": False, "error": "MangaDex integration is not enabled"}

    try:
        from comicarr import importer
        result = importer.addMangaToDB(manga_id)

        if result and result.get("status") == "complete":
            return {
                "success": True,
                "message": "Successfully added manga: %s" % result.get("comicname", manga_id),
                "comicid": manga_id,
                "content_type": "manga",
            }
        return {"success": False, "error": "Failed to add manga: %s" % manga_id}
    except Exception as e:
        logger.error("[SEARCH] Error adding manga %s: %s" % (manga_id, e))
        return {"success": False, "error": "Error adding manga: %s" % str(e)}


def force_search(ctx):
    """Trigger a full search for all wanted issues."""
    from comicarr import search
    search.searchforissue()
    return {"success": True, "message": "Search initiated"}


def force_rss(ctx):
    """Trigger an RSS feed check."""
    import threading
    try:
        rss = comicarr.rsscheckit.tehMain()
        threading.Thread(target=rss.run, args=(True,)).start()
        return {"success": True, "message": "RSS check initiated"}
    except Exception as e:
        logger.error("[SEARCH] Error starting RSS check: %s" % e)
        return {"success": False, "error": "Failed to start RSS check: %s" % str(e)}


def get_provider_stats(ctx):
    """Get provider search statistics."""
    from comicarr.app.search import queries as search_queries
    return search_queries.get_provider_stats()
