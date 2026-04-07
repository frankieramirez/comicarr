#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""
MyAnimeList API v2 integration for manga search and metadata.

Uses MAL as the primary manga metadata source (titles, images, synopsis, status,
authors) while MangaDex provides chapter-level data.

API Documentation: https://myanimelist.net/apiconfig/references/api/v2
"""

import time
from datetime import datetime

import requests

import comicarr
from comicarr import logger
from comicarr.helpers import listLibrary

# MAL API base URL
MAL_API_BASE = "https://api.myanimelist.net/v2"

# Fields to request from MAL API
_MANGA_LIST_FIELDS = (
    "id,title,main_picture,alternative_titles,start_date,end_date,"
    "synopsis,mean,rank,num_volumes,num_chapters,status,genres,"
    "authors{first_name,last_name},media_type"
)

_MANGA_DETAIL_FIELDS = (
    "id,title,main_picture,alternative_titles,start_date,end_date,"
    "synopsis,mean,rank,popularity,num_volumes,num_chapters,status,"
    "genres,authors{first_name,last_name},media_type,pictures"
)

# Rate limiter state
_last_request_time = 0
_rate_limit_interval = 1.0  # 1 request per second for MAL

# Status mapping: MAL -> Comicarr
_STATUS_MAP = {
    "currently_publishing": "ongoing",
    "finished": "completed",
    "not_yet_published": "upcoming",
    "on_hiatus": "hiatus",
}

# Media types we consider as manga
_MANGA_TYPES = {"manga", "manhwa", "manhua", "one_shot", "light_novel"}


def _rate_limit():
    """Implement rate limiting for MAL API (~1 request/second)."""
    global _last_request_time
    current_time = time.time()
    elapsed = current_time - _last_request_time
    if elapsed < _rate_limit_interval:
        time.sleep(_rate_limit_interval - elapsed)
    _last_request_time = time.time()


def _make_request(endpoint, params=None):
    """Make a rate-limited request to the MAL API.

    Returns JSON response data or None on error.
    """
    client_id = getattr(comicarr.CONFIG, "MAL_CLIENT_ID", None) if comicarr.CONFIG else None
    if not client_id:
        logger.error("[MAL] No MAL_CLIENT_ID configured")
        return None

    _rate_limit()

    url = "%s%s" % (MAL_API_BASE, endpoint)
    headers = {
        "X-MAL-CLIENT-ID": client_id,
        "User-Agent": comicarr.CONFIG.CV_USER_AGENT if comicarr.CONFIG else "Comicarr/1.0",
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.Timeout:
        logger.error("[MAL] Request timeout for %s" % endpoint)
        return None
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            logger.error("[MAL] Invalid Client ID or forbidden: %s" % e)
        else:
            logger.error("[MAL] HTTP error: %s" % e)
        return None
    except requests.exceptions.RequestException as e:
        logger.error("[MAL] Request failed: %s" % e)
        return None
    except Exception as e:
        logger.error("[MAL] Unexpected error: %s" % e)
        return None


def search_manga(name, limit=None, offset=None, sort=None):
    """Search MAL for manga series.

    Returns dict matching mangadex.search_manga() response shape:
        {"results": [...], "pagination": {...}}
    """
    search_start = time.time()
    logger.info("[MAL] Starting search for: %s (limit=%s, offset=%s)" % (name, limit, offset))

    # Get library for "haveit" status
    comicLibrary = listLibrary()

    page_limit = min(limit, 100) if limit else 10
    page_offset = offset if offset else 0

    params = {
        "q": name,
        "limit": page_limit,
        "offset": page_offset,
        "fields": _MANGA_LIST_FIELDS,
        "nsfw": "true",
    }

    data = _make_request("/manga", params=params)

    if not data or "data" not in data:
        logger.error("[MAL] Search failed or returned no results")
        return {
            "results": [],
            "pagination": {"total": 0, "limit": page_limit, "offset": page_offset, "returned": 0},
        }

    manga_list = data.get("data", [])
    paging = data.get("paging", {})
    comiclist = []

    for entry in manga_list:
        node = entry.get("node", {})
        mal_id = node.get("id")
        if not mal_id:
            continue

        title = node.get("title", "Unknown")
        media_type = node.get("media_type", "unknown")

        # Skip non-manga types
        if media_type not in _MANGA_TYPES:
            continue

        # Extract images
        main_picture = node.get("main_picture", {})
        cover_url = _proxy_image_url(main_picture.get("large") or main_picture.get("medium") or "")

        # Extract alt titles
        alt_titles_data = node.get("alternative_titles", {})
        alt_titles = []
        if alt_titles_data.get("en") and alt_titles_data["en"] != title:
            alt_titles.append(alt_titles_data["en"])
        if alt_titles_data.get("ja"):
            alt_titles.append(alt_titles_data["ja"])
        for syn in alt_titles_data.get("synonyms", []):
            if syn and syn != title:
                alt_titles.append(syn)

        # Extract year from start_date
        start_date = node.get("start_date", "")
        year = start_date[:4] if start_date and len(start_date) >= 4 else "0000"

        # Map status
        mal_status = node.get("status", "unknown")
        status = _STATUS_MAP.get(mal_status, "unknown")

        # Extract description
        description = node.get("synopsis", "") or ""

        # Extract author
        authors = node.get("authors", [])
        author = _format_authors(authors)

        # Num chapters/volumes
        num_chapters = node.get("num_chapters", 0)
        num_volumes = node.get("num_volumes", 0)

        # Score
        score = node.get("mean")

        # Check if already in library
        mal_comic_id = "mal-%s" % mal_id
        haveit = "No"
        if mal_comic_id in comicLibrary:
            haveit = comicLibrary[mal_comic_id]
        elif title and year:
            name_key = "name:" + title.lower().strip() + ":" + str(year).strip()
            if name_key in comicLibrary:
                haveit = comicLibrary[name_key]

        # Build year range
        yearRange = [str(year)]
        if str(year).isdigit():
            current_year = datetime.now().year
            for y in range(int(year), min(int(year) + 30, current_year + 1)):
                if str(y) not in yearRange:
                    yearRange.append(str(y))

        comiclist.append(
            {
                "name": title,
                "comicyear": str(year),
                "comicid": mal_comic_id,
                "cv_comicid": None,
                "url": "https://myanimelist.net/manga/%s" % mal_id,
                "issues": str(num_chapters) if num_chapters is not None else "0",
                "comicimage": cover_url,
                "comicthumb": cover_url,
                "publisher": author,
                "description": description[:500] if description else None,
                "deck": None,
                "type": "Manga",
                "haveit": haveit,
                "lastissueid": None,
                "firstissueid": None,
                "volume": str(num_volumes) if num_volumes else None,
                "imprint": None,
                "seriesrange": yearRange,
                "status": status,
                "content_rating": "safe",
                "content_type": "manga",
                "reading_direction": "rtl",
                "metadata_source": "mal",
                "external_id": str(mal_id),
                "alt_titles": alt_titles,
                "score": score,
            }
        )

    # Estimate total from paging
    has_next = "next" in paging
    total_estimate = page_offset + len(comiclist) + (1 if has_next else 0)

    search_duration = time.time() - search_start
    logger.info("[MAL] Search completed in %.2f seconds (%d results)" % (search_duration, len(comiclist)))

    return {
        "results": comiclist,
        "pagination": {
            "total": total_estimate,
            "limit": page_limit,
            "offset": page_offset,
            "returned": len(comiclist),
        },
    }


def get_manga_details(mal_id):
    """Fetch detailed manga metadata from MAL.

    Args:
        mal_id: MAL manga ID (with or without 'mal-' prefix)

    Returns dict matching mangadex.get_manga_details() shape.
    """
    numeric_id = strip_mal_prefix(str(mal_id))
    logger.info("[MAL] Fetching details for manga ID: %s" % numeric_id)

    params = {"fields": _MANGA_DETAIL_FIELDS}
    data = _make_request("/manga/%s" % numeric_id, params=params)

    if not data or "id" not in data:
        logger.error("[MAL] Failed to get details for manga %s" % numeric_id)
        return None

    title = data.get("title", "Unknown")

    # Extract alt titles
    alt_titles_data = data.get("alternative_titles", {})
    alt_titles = []
    if alt_titles_data.get("en") and alt_titles_data["en"] != title:
        alt_titles.append(alt_titles_data["en"])
    if alt_titles_data.get("ja"):
        alt_titles.append(alt_titles_data["ja"])
    for syn in alt_titles_data.get("synonyms", []):
        if syn and syn != title:
            alt_titles.append(syn)

    # Extract images
    main_picture = data.get("main_picture", {})
    cover_url = _proxy_image_url(main_picture.get("large") or main_picture.get("medium") or "")

    # Extract year
    start_date = data.get("start_date", "")
    year = start_date[:4] if start_date and len(start_date) >= 4 else None

    # Map status
    mal_status = data.get("status", "unknown")
    status = _STATUS_MAP.get(mal_status, "unknown")

    # Extract metadata
    description = data.get("synopsis", "")
    num_chapters = data.get("num_chapters", 0)
    num_volumes = data.get("num_volumes", 0)
    authors = data.get("authors", [])
    author = _format_authors(authors)
    artist = _format_authors(authors, role="Art")
    score = data.get("mean")

    # Extract tags/genres
    tags = [g.get("name", "") for g in data.get("genres", []) if g.get("name")]

    return {
        "id": "mal-%s" % numeric_id,
        "mal_id": str(numeric_id),
        "name": title,
        "alt_titles": alt_titles,
        "description": description,
        "year": year,
        "status": status,
        "content_rating": "safe",
        "original_language": "ja",
        "last_chapter": str(num_chapters) if num_chapters is not None else None,
        "last_volume": str(num_volumes) if num_volumes is not None else None,
        "tags": tags,
        "author": author,
        "artist": artist or author,
        "cover_url": cover_url,
        "url": "https://myanimelist.net/manga/%s" % numeric_id,
        "content_type": "manga",
        "reading_direction": "rtl",
        "metadata_source": "mal",
        "score": score,
    }


def _format_authors(authors, role=None):
    """Format MAL author list into a display string.

    Args:
        authors: List of author objects from MAL API
        role: Filter by role (e.g. "Story", "Art"). None = all authors.
    """
    names = []
    for author_entry in authors:
        node = author_entry.get("node", {})
        author_role = author_entry.get("role", "")
        if role and role.lower() not in author_role.lower():
            continue
        first = node.get("first_name", "")
        last = node.get("last_name", "")
        name = ("%s %s" % (first, last)).strip()
        if name:
            names.append(name)
    return ", ".join(names) if names else "Unknown"


def _proxy_image_url(url):
    """Route an external image URL through the Comicarr image proxy."""
    if not url:
        return ""
    from urllib.parse import quote

    return "/api/metadata/image-proxy?url=%s" % quote(url, safe="")


def is_mal_id(comic_id):
    """Check if comic_id uses the MAL prefix."""
    return bool(comic_id) and str(comic_id).startswith("mal-")


def strip_mal_prefix(mal_id):
    """Remove 'mal-' prefix from a MAL ID."""
    if mal_id and str(mal_id).startswith("mal-"):
        return str(mal_id)[4:]
    return str(mal_id)
