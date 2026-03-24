#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Metadata domain service — ComicVine, Metron, MangaDex provider wrappers.

Module-level functions wrapping the existing provider modules.
Preserves ThreadPoolExecutor batch enrichment for cover image backfill.
"""

import os

from comicarr import logger


def search_comics(ctx, name, issue=None, type_="comic", mode="series",
                  limit=None, offset=None, sort=None, content_type=None):
    """Search for comics across configured providers.

    Delegates to MangaDex for manga, or mb.findComic for comics/story arcs.
    Returns results with in_library boolean added.
    """
    from comicarr import mb

    if not name:
        return {"error": "Missing a Comic name"}

    # Parse pagination
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
        from operator import itemgetter
        searchresults = sorted(searchresults, key=itemgetter("comicyear", "issues"), reverse=True)
        searchresults = [add_in_library(c) for c in searchresults]
        return {"results": searchresults}


def search_manga(ctx, name, limit=None, offset=None, sort=None):
    """Search for manga via MangaDex API."""
    if not ctx.config or not getattr(ctx.config, "MANGADEX_ENABLED", False):
        return {"error": "MangaDex integration is not enabled"}

    from comicarr import mangadex

    try:
        parsed_limit = int(limit) if limit else None
        parsed_offset = int(offset) if offset else None
    except (ValueError, TypeError):
        return {"error": "Invalid pagination parameters"}

    return mangadex.search_manga(name, limit=parsed_limit, offset=parsed_offset, sort=sort)


def get_series_image(ctx, series_id):
    """Get cover image URL for a Metron series (lazy loading)."""
    try:
        int(series_id)
    except (ValueError, TypeError):
        return None

    from comicarr import metron
    return metron.get_series_image(series_id)


def get_comic_info(ctx, comic_id):
    """Get comic metadata from database."""
    from sqlalchemy import select

    from comicarr import db
    from comicarr.tables import comics as t_comics

    stmt = select(t_comics).where(t_comics.c.ComicID == comic_id)
    results = db.select_all(stmt)
    if results and len(results) == 1:
        return results[0]
    return None


def get_issue_info(ctx, issue_id):
    """Get issue metadata from database."""
    from sqlalchemy import select

    from comicarr import db
    from comicarr.tables import issues as t_issues

    stmt = select(t_issues).where(t_issues.c.IssueID == issue_id)
    results = db.select_all(stmt)
    if results and len(results) == 1:
        return results[0]
    return None


def get_artwork(ctx, comic_id):
    """Get or cache comic artwork. Returns file path or None."""
    from PIL import Image

    cache_dir = getattr(ctx.config, "CACHE_DIR", None) if ctx.config else None
    if not cache_dir:
        return None

    image_path = os.path.join(cache_dir, str(comic_id) + ".jpg")

    if os.path.isfile(image_path):
        try:
            img = Image.open(image_path)
            if img.get_format_mimetype():
                return image_path
        except Exception:
            pass

    # Try fetching from DB URLs
    import urllib.request

    from sqlalchemy import select

    from comicarr import db
    from comicarr.tables import comics as t_comics

    comic = db.select_all(select(t_comics).where(t_comics.c.ComicID == comic_id))
    if not comic:
        return None

    img_data = None
    for url_key in ["ComicImageURL", "ComicImageALTURL"]:
        url = comic[0].get(url_key)
        if url:
            try:
                img_data = urllib.request.urlopen(url).read()
                break
            except Exception:
                continue

    if img_data:
        try:
            from io import BytesIO
            img = Image.open(BytesIO(img_data))
            if img.get_format_mimetype():
                with open(image_path, "wb") as f:
                    f.write(img_data)
                return image_path
        except Exception:
            pass

    return None


def manual_metatag(ctx, issue_id, comic_id=None):
    """Tag metadata for a single issue."""
    from comicarr.webserve import WebInterface
    try:
        WebInterface().manual_metatag(issue_id, comicid=comic_id)
        return {"success": True}
    except Exception as e:
        logger.error("[METADATA] Metatag error: %s" % e)
        return {"success": False, "error": str(e)}


def bulk_metatag(ctx, comic_id, issue_ids):
    """Tag metadata for multiple issues."""
    from comicarr.webserve import WebInterface
    try:
        WebInterface().bulk_metatag(comic_id, issue_ids)
        return {"success": True, "count": len(issue_ids)}
    except Exception as e:
        logger.error("[METADATA] Bulk metatag error: %s" % e)
        return {"success": False, "error": str(e)}


def group_metatag(ctx, comic_id):
    """Tag metadata for all issues in a series."""
    from comicarr.webserve import WebInterface
    try:
        WebInterface().group_metatag(comic_id)
        return {"success": True}
    except Exception as e:
        logger.error("[METADATA] Group metatag error: %s" % e)
        return {"success": False, "error": str(e)}
