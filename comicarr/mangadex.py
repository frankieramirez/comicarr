#  Copyright (C) 2012–2024 Mylar3 contributors
#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Originally based on Mylar3 (https://github.com/mylar3/mylar3).
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
MangaDex API integration for manga search and metadata functionality.

Uses the MangaDex API v5 to search for manga series and retrieve chapter information.
Provides chapter-level tracking which aligns with Comicarr's issue-level tracking model.

API Documentation: https://api.mangadex.org/docs/
"""

import time
from datetime import datetime

import requests

import comicarr
from comicarr import logger
from comicarr.helpers import listLibrary

# MangaDex API base URL
MANGADEX_API_BASE = "https://api.mangadex.org"

# In-memory cache for manga images and metadata to avoid repeated API calls
_IMAGE_CACHE = {}  # {manga_id: cover_url}
_MANGA_CACHE = {}  # {manga_id: manga_details}
_CHAPTER_CACHE = {}  # {manga_id: chapters_list}

# Cache TTL in seconds
CACHE_TTL = 3600  # 1 hour

# Rate limiter state
_last_request_time = 0
_rate_limit_interval = 0.2  # 5 requests per second

# Content rating mapping
CONTENT_RATING_MAP = {"safe": "safe", "suggestive": "suggestive", "erotica": "erotica", "pornographic": "pornographic"}


def _rate_limit():
    """
    Implement rate limiting for MangaDex API (5 requests/second max).
    """
    global _last_request_time
    current_time = time.time()
    elapsed = current_time - _last_request_time
    if elapsed < _rate_limit_interval:
        time.sleep(_rate_limit_interval - elapsed)
    _last_request_time = time.time()


def _make_request(endpoint, params=None, method="GET"):
    """
    Make a rate-limited request to the MangaDex API.

    Args:
        endpoint: API endpoint (without base URL)
        params: Query parameters
        method: HTTP method (GET, POST, etc.)

    Returns:
        JSON response data or None on error
    """
    _rate_limit()

    url = f"{MANGADEX_API_BASE}{endpoint}"
    headers = {"User-Agent": comicarr.CONFIG.CV_USER_AGENT if comicarr.CONFIG else "Comicarr/1.0"}

    try:
        if method == "GET":
            response = requests.get(url, params=params, headers=headers, timeout=30)
        else:
            response = requests.request(method, url, params=params, headers=headers, timeout=30)

        response.raise_for_status()
        return response.json()

    except requests.exceptions.Timeout:
        logger.error("[MANGADEX] Request timeout for %s" % endpoint)
        return None
    except requests.exceptions.RequestException as e:
        logger.error("[MANGADEX] Request failed: %s" % e)
        return None
    except Exception as e:
        logger.error("[MANGADEX] Unexpected error: %s" % e)
        return None


def _get_content_ratings():
    """
    Get the list of content ratings to include based on config.

    Returns:
        List of content rating strings for the API
    """
    if not comicarr.CONFIG or not comicarr.CONFIG.MANGADEX_CONTENT_RATING:
        return ["safe", "suggestive"]

    ratings = comicarr.CONFIG.MANGADEX_CONTENT_RATING.split(",")
    return [r.strip().lower() for r in ratings if r.strip().lower() in CONTENT_RATING_MAP]


def _get_languages():
    """
    Get the list of languages to filter by from config.

    Returns:
        List of language codes (ISO 639-1)
    """
    if not comicarr.CONFIG or not comicarr.CONFIG.MANGADEX_LANGUAGES:
        return ["en"]

    languages = comicarr.CONFIG.MANGADEX_LANGUAGES.split(",")
    return [lang.strip().lower() for lang in languages if lang.strip()]


def _extract_cover_url(manga_data):
    """
    Extract cover image URL from manga data.

    Args:
        manga_data: Manga object from API response

    Returns:
        Cover URL string or default placeholder
    """
    manga_id = manga_data.get("id")
    relationships = manga_data.get("relationships", [])

    for rel in relationships:
        if rel.get("type") == "cover_art":
            cover_filename = rel.get("attributes", {}).get("fileName")
            if cover_filename:
                return f"https://uploads.mangadex.org/covers/{manga_id}/{cover_filename}.256.jpg"

    return None


def _extract_author(manga_data):
    """
    Extract author name from manga relationships.

    Args:
        manga_data: Manga object from API response

    Returns:
        Author name string or 'Unknown'
    """
    relationships = manga_data.get("relationships", [])

    for rel in relationships:
        if rel.get("type") == "author":
            return rel.get("attributes", {}).get("name", "Unknown")

    return "Unknown"


def _extract_artist(manga_data):
    """
    Extract artist name from manga relationships.

    Args:
        manga_data: Manga object from API response

    Returns:
        Artist name string or 'Unknown'
    """
    relationships = manga_data.get("relationships", [])

    for rel in relationships:
        if rel.get("type") == "artist":
            return rel.get("attributes", {}).get("name", "Unknown")

    return "Unknown"


def _get_localized_string(localized_dict, preferred_languages=None):
    """
    Get a string from a localized dictionary, preferring certain languages.

    Args:
        localized_dict: Dictionary with language codes as keys
        preferred_languages: List of preferred language codes

    Returns:
        String value in preferred language or first available
    """
    if not localized_dict:
        return None

    if preferred_languages is None:
        preferred_languages = _get_languages() + ["en", "ja", "ja-ro"]

    for lang in preferred_languages:
        if lang in localized_dict:
            return localized_dict[lang]

    # Fall back to first available
    if localized_dict:
        return next(iter(localized_dict.values()))

    return None


def search_manga(name, limit=None, offset=None, sort=None):
    """
    Search for manga series using MangaDex API.

    Args:
        name: Manga name to search for
        limit: Number of results per page
        offset: Offset for pagination
        sort: Sort order (relevance, latestUploadedChapter, followedCount, etc.)

    Returns:
        dict with 'results' list and 'pagination' metadata
    """
    search_start_time = time.time()
    logger.info("[MANGADEX] Starting search for: %s (limit=%s, offset=%s, sort=%s)" % (name, limit, offset, sort))

    if not comicarr.CONFIG.MANGADEX_ENABLED:
        logger.warn("[MANGADEX] MangaDex integration is not enabled")
        return {"results": [], "pagination": {"total": 0, "limit": limit or 50, "offset": offset or 0, "returned": 0}}

    # Get library for "haveit" status
    comicLibrary = listLibrary()

    # Set pagination defaults
    page_limit = min(limit, 100) if limit else 50
    page_offset = offset if offset else 0

    # Build API parameters
    params = {
        "title": name,
        "limit": page_limit,
        "offset": page_offset,
        "includes[]": ["cover_art", "author", "artist"],
        "contentRating[]": _get_content_ratings(),
        "order[relevance]": "desc",
    }

    # Apply sort if provided
    if sort:
        # Clear default sort
        params.pop("order[relevance]", None)
        sort_mapping = {
            "relevance": {"order[relevance]": "desc"},
            "latest": {"order[latestUploadedChapter]": "desc"},
            "oldest": {"order[latestUploadedChapter]": "asc"},
            "title_asc": {"order[title]": "asc"},
            "title_desc": {"order[title]": "desc"},
            "year_desc": {"order[year]": "desc"},
            "year_asc": {"order[year]": "asc"},
            "follows": {"order[followedCount]": "desc"},
        }
        if sort in sort_mapping:
            params.update(sort_mapping[sort])
        else:
            params["order[relevance]"] = "desc"

    try:
        data = _make_request("/manga", params=params)

        if not data or data.get("result") != "ok":
            logger.error("[MANGADEX] Search failed or returned no results")
            return {
                "results": [],
                "pagination": {"total": 0, "limit": page_limit, "offset": page_offset, "returned": 0},
            }

        manga_list = data.get("data", [])
        total_results = data.get("total", 0)
        comiclist = []

        for manga in manga_list:
            manga_id = manga.get("id")
            attributes = manga.get("attributes", {})

            # Extract title (prefer English, fall back to other languages)
            title = _get_localized_string(attributes.get("title", {}))
            if not title:
                # Try altTitles
                alt_titles = attributes.get("altTitles", [])
                for alt in alt_titles:
                    title = _get_localized_string(alt)
                    if title:
                        break
            if not title:
                title = "Unknown"

            # Extract other metadata
            year = attributes.get("year") or "0000"
            status = attributes.get("status", "unknown")  # ongoing, completed, hiatus, cancelled
            content_rating = attributes.get("contentRating", "safe")
            description = _get_localized_string(attributes.get("description", {})) or "No description available"

            # Get cover URL
            cover_url = _extract_cover_url(manga)

            # Get alt titles (all languages: romaji, Japanese, synonyms, etc.)
            alt_titles = []
            for alt in attributes.get("altTitles", []):
                for lang_val in alt.values():
                    if lang_val and lang_val != title:
                        alt_titles.append(lang_val)

            # Get author/artist
            author = _extract_author(manga)

            # Extract external links (MAL ID, etc.)
            links = attributes.get("links", {})
            mal_id = str(links.get("mal")) if links.get("mal") else None

            # Check if we already have this manga (using md- prefix)
            haveit = "No"
            mangadex_id = "md-" + manga_id
            if mangadex_id in comicLibrary:
                haveit = comicLibrary[mangadex_id]
            # Check by MAL ID
            elif mal_id and ("mal-" + mal_id) in comicLibrary:
                haveit = comicLibrary["mal-" + mal_id]
            # Also check by name and year
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
                    "comicyear": str(year) if year else "0000",
                    "comicid": mangadex_id,  # Use md- prefix for MangaDex IDs
                    "cv_comicid": None,  # No ComicVine ID
                    "url": f"https://mangadex.org/title/{manga_id}",
                    "issues": "0",  # Will be populated separately if needed
                    "comicimage": cover_url,
                    "comicthumb": cover_url,
                    "publisher": author,  # Use author as publisher equivalent
                    "description": description[:500] if description else None,
                    "deck": None,
                    "type": "Manga",
                    "haveit": haveit,
                    "lastissueid": None,
                    "firstissueid": None,
                    "volume": None,
                    "imprint": None,
                    "seriesrange": yearRange,
                    "status": status,
                    "content_rating": content_rating,
                    "content_type": "manga",
                    "alt_titles": alt_titles,
                    "reading_direction": "rtl",  # Right-to-left for manga
                    "metadata_source": "mangadex",
                    "external_id": manga_id,
                    "mal_id": mal_id,
                }
            )

        search_duration = time.time() - search_start_time
        logger.info("[MANGADEX] Search completed in %.2f seconds (%d results)" % (search_duration, len(comiclist)))

        return {
            "results": comiclist,
            "pagination": {
                "total": total_results,
                "limit": page_limit,
                "offset": page_offset,
                "returned": len(comiclist),
            },
        }

    except Exception as e:
        logger.error("[MANGADEX] Search failed: %s" % e)
        import traceback

        logger.error("[MANGADEX] Traceback: %s" % traceback.format_exc())
        return {"results": [], "pagination": {"total": 0, "limit": page_limit, "offset": page_offset, "returned": 0}}


def get_manga_details(manga_id):
    """
    Get detailed information about a specific manga.

    Args:
        manga_id: MangaDex manga UUID (without md- prefix)

    Returns:
        dict with manga details or None on error
    """
    # Remove md- prefix if present
    if manga_id.startswith("md-"):
        manga_id = manga_id[3:]

    # Check cache first
    cache_key = manga_id
    if cache_key in _MANGA_CACHE:
        cache_entry = _MANGA_CACHE[cache_key]
        if time.time() - cache_entry["timestamp"] < CACHE_TTL:
            logger.fdebug("[MANGADEX] Cache hit for manga %s" % manga_id)
            return cache_entry["data"]

    logger.info("[MANGADEX] Fetching details for manga: %s" % manga_id)

    params = {"includes[]": ["cover_art", "author", "artist", "tag"]}

    data = _make_request(f"/manga/{manga_id}", params=params)

    if not data or data.get("result") != "ok":
        logger.error("[MANGADEX] Failed to fetch manga details for %s" % manga_id)
        return None

    manga = data.get("data", {})
    attributes = manga.get("attributes", {})

    # Extract all relevant metadata
    title = _get_localized_string(attributes.get("title", {}))
    alt_titles = []
    for alt in attributes.get("altTitles", []):
        alt_title = _get_localized_string(alt)
        if alt_title and alt_title != title:
            alt_titles.append(alt_title)

    description = _get_localized_string(attributes.get("description", {}))

    # Extract tags/genres
    tags = []
    for tag in attributes.get("tags", []):
        tag_name = _get_localized_string(tag.get("attributes", {}).get("name", {}))
        if tag_name:
            tags.append(tag_name)

    # Extract external links (MAL, AniList, etc.)
    links = attributes.get("links", {})

    details = {
        "id": "md-" + manga_id,
        "mangadex_id": manga_id,
        "name": title,
        "alt_titles": alt_titles,
        "description": description,
        "year": attributes.get("year"),
        "status": attributes.get("status", "unknown"),
        "content_rating": attributes.get("contentRating", "safe"),
        "original_language": attributes.get("originalLanguage", "ja"),
        "last_chapter": attributes.get("lastChapter"),
        "last_volume": attributes.get("lastVolume"),
        "tags": tags,
        "author": _extract_author(manga),
        "artist": _extract_artist(manga),
        "cover_url": _extract_cover_url(manga),
        "url": f"https://mangadex.org/title/{manga_id}",
        "content_type": "manga",
        "reading_direction": "rtl",
        "metadata_source": "mangadex",
        "created_at": attributes.get("createdAt"),
        "updated_at": attributes.get("updatedAt"),
        "mal_id": str(links.get("mal")) if links.get("mal") else None,
        "links": links,
    }

    # Cache the result
    _MANGA_CACHE[cache_key] = {"data": details, "timestamp": time.time()}

    return details


def find_by_mal_id(mal_id, title_hint=None):
    """Find MangaDex manga UUID by its MyAnimeList ID.

    Searches MangaDex by title and checks each result's links.mal field
    to find the matching entry.

    Args:
        mal_id: MAL numeric ID (string or int, without mal- prefix)
        title_hint: Manga title to search MangaDex with

    Returns:
        MangaDex manga UUID (string) or None if not found
    """
    mal_id_str = str(mal_id)
    if mal_id_str.startswith("mal-"):
        mal_id_str = mal_id_str[4:]

    if not title_hint:
        logger.warn("[MANGADEX] find_by_mal_id called without title_hint for MAL %s" % mal_id_str)
        return None

    logger.info("[MANGADEX] Looking up MangaDex UUID for MAL ID %s (title: %s)" % (mal_id_str, title_hint))

    params = {
        "title": title_hint,
        "limit": 10,
        "includes[]": ["cover_art"],
        "contentRating[]": _get_content_ratings(),
        "order[relevance]": "desc",
    }

    data = _make_request("/manga", params=params)
    if not data or data.get("result") != "ok":
        return None

    # First pass: exact MAL ID match via links
    for manga in data.get("data", []):
        links = manga.get("attributes", {}).get("links", {})
        if str(links.get("mal", "")) == mal_id_str:
            manga_uuid = manga.get("id")
            logger.info("[MANGADEX] Found MAL %s -> MangaDex %s (via links.mal)" % (mal_id_str, manga_uuid))
            return manga_uuid

    # Second pass: fuzzy title match as fallback
    from comicarr.mangasync import _name_similarity

    best_uuid = None
    best_score = 0.0
    for manga in data.get("data", []):
        attributes = manga.get("attributes", {})
        candidate_title = _get_localized_string(attributes.get("title", {}))
        if not candidate_title:
            continue

        # Check primary title
        score = _name_similarity(title_hint, candidate_title)

        # Check alt titles too
        for alt in attributes.get("altTitles", []):
            alt_title = _get_localized_string(alt)
            if alt_title:
                alt_score = _name_similarity(title_hint, alt_title)
                score = max(score, alt_score)

        if score > best_score:
            best_score = score
            best_uuid = manga.get("id")

    if best_uuid and best_score >= 0.6:
        logger.info(
            "[MANGADEX] Found MAL %s -> MangaDex %s (via title match, %.1f%%)"
            % (mal_id_str, best_uuid, best_score * 100)
        )
        return best_uuid

    logger.info("[MANGADEX] No MangaDex match found for MAL %s" % mal_id_str)
    return None


def get_manga_chapters(manga_id, languages=None, limit=100, offset=0):
    """
    Get chapter list for a manga.

    Args:
        manga_id: MangaDex manga UUID (without md- prefix)
        languages: List of language codes to filter by (defaults to config)
        limit: Number of chapters per request (max 100)
        offset: Offset for pagination

    Returns:
        dict with 'chapters' list and 'pagination' metadata
    """
    # Remove md- prefix if present
    if manga_id.startswith("md-"):
        manga_id = manga_id[3:]

    logger.info("[MANGADEX] Fetching chapters for manga: %s (offset=%s, limit=%s)" % (manga_id, offset, limit))

    if languages is None:
        languages = _get_languages()

    params = {
        "manga": manga_id,
        "translatedLanguage[]": languages,
        "limit": min(limit, 100),  # MangaDex chapter endpoint max is 100
        "offset": offset,
        "order[chapter]": "asc",
        "includes[]": ["scanlation_group"],
    }

    data = _make_request("/chapter", params=params)

    if not data or data.get("result") != "ok":
        logger.error("[MANGADEX] Failed to fetch chapters for manga %s" % manga_id)
        return {"chapters": [], "pagination": {"total": 0, "limit": limit, "offset": offset, "returned": 0}}

    chapter_list = data.get("data", [])
    total_chapters = data.get("total", 0)
    chapters = []

    for chapter in chapter_list:
        chapter_id = chapter.get("id")
        attributes = chapter.get("attributes", {})

        # Get scanlation group name
        group_name = None
        for rel in chapter.get("relationships", []):
            if rel.get("type") == "scanlation_group":
                group_name = rel.get("attributes", {}).get("name")
                break

        chapter_num = attributes.get("chapter")
        volume_num = attributes.get("volume")

        chapters.append(
            {
                "id": chapter_id,
                "chapter": chapter_num,
                "volume": volume_num,
                "title": attributes.get("title"),
                "language": attributes.get("translatedLanguage"),
                "pages": attributes.get("pages", 0),
                "publish_at": attributes.get("publishAt"),
                "created_at": attributes.get("createdAt"),
                "updated_at": attributes.get("updatedAt"),
                "scanlation_group": group_name,
                "external_url": attributes.get("externalUrl"),
                # Map to Comicarr's issue structure
                "issue_number": chapter_num,
                "issue_name": attributes.get("title") or f"Chapter {chapter_num}",
                "release_date": attributes.get("publishAt", "")[:10] if attributes.get("publishAt") else None,
            }
        )

    logger.info("[MANGADEX] Found %d chapters for manga %s" % (len(chapters), manga_id))

    return {
        "chapters": chapters,
        "pagination": {"total": total_chapters, "limit": limit, "offset": offset, "returned": len(chapters)},
    }


def get_manga_aggregate(manga_id, languages=None):
    """
    Get aggregate chapter/volume info for a manga (includes unavailable chapters).

    This endpoint returns ALL chapter numbers even if they don't have uploads,
    which is useful for tracking series like Naruto where most chapters are
    licensed and not available on MangaDex.

    Args:
        manga_id: MangaDex manga UUID (with or without md- prefix)
        languages: List of language codes to filter by

    Returns:
        dict with volume/chapter structure
    """
    # Remove md- prefix if present
    if manga_id.startswith("md-"):
        manga_id = manga_id[3:]

    if languages is None:
        languages = _get_languages()

    logger.info("[MANGADEX] Fetching aggregate for manga: %s" % manga_id)

    params = {
        "translatedLanguage[]": languages,
    }

    data = _make_request(f"/manga/{manga_id}/aggregate", params=params)

    if not data or data.get("result") != "ok":
        logger.error("[MANGADEX] Failed to fetch aggregate for manga %s" % manga_id)
        return {"volumes": {}}

    return data


def get_all_chapters(manga_id, languages=None, include_unavailable=True):
    """
    Get all chapters for a manga (handles pagination automatically).

    When include_unavailable=True, generates entries for ALL chapters up to
    lastChapter from manga metadata, even if they don't have uploads.

    Args:
        manga_id: MangaDex manga UUID (without md- prefix)
        languages: List of language codes to filter by
        include_unavailable: If True, include chapters without uploads

    Returns:
        List of all chapters
    """
    # Remove md- prefix if present
    if manga_id.startswith("md-"):
        manga_id = manga_id[3:]

    # Check cache first
    cache_key = f"{manga_id}:{','.join(languages or _get_languages())}:{include_unavailable}"
    if cache_key in _CHAPTER_CACHE:
        cache_entry = _CHAPTER_CACHE[cache_key]
        if time.time() - cache_entry["timestamp"] < CACHE_TTL:
            logger.fdebug("[MANGADEX] Cache hit for chapters of manga %s" % manga_id)
            return cache_entry["data"]

    # First, get available chapters with full metadata (filtered by language)
    available_chapters = []
    offset = 0
    limit = 100  # MangaDex chapter endpoint max is 100

    while True:
        result = get_manga_chapters(manga_id, languages=languages, limit=limit, offset=offset)
        chapters = result.get("chapters", [])
        available_chapters.extend(chapters)

        pagination = result.get("pagination", {})
        total = pagination.get("total", 0)

        if offset + limit >= total or not chapters:
            break

        offset += limit

    # Create a map of available chapters by chapter number
    available_map = {}
    for ch in available_chapters:
        ch_num = ch.get("chapter")
        if ch_num is not None:
            available_map[str(ch_num)] = ch

    all_chapters = list(available_chapters)

    # If requested, add unavailable chapters based on manga's lastChapter metadata
    if include_unavailable:
        # Get manga details to find total chapter count
        manga_details = get_manga_details(manga_id)
        last_chapter_str = manga_details.get("last_chapter")

        if last_chapter_str:
            try:
                last_chapter = int(float(last_chapter_str))
                logger.info("[MANGADEX] Manga has %d total chapters (lastChapter from metadata)" % last_chapter)

                # Generate placeholder entries for all chapters from 1 to lastChapter
                for ch_num in range(1, last_chapter + 1):
                    ch_num_str = str(ch_num)
                    # Skip if we already have this chapter
                    if ch_num_str in available_map:
                        continue

                    # Create a placeholder entry for unavailable chapter
                    all_chapters.append(
                        {
                            "id": f"unavailable-{manga_id}-{ch_num}",
                            "chapter": ch_num_str,
                            "volume": None,
                            "title": None,
                            "language": "en",
                            "pages": 0,
                            "publish_at": None,
                            "created_at": None,
                            "updated_at": None,
                            "scanlation_group": None,
                            "external_url": None,
                            "unavailable": True,  # Flag to indicate no upload available
                        }
                    )
            except (ValueError, TypeError) as e:
                logger.warning('[MANGADEX] Could not parse lastChapter "%s": %s' % (last_chapter_str, e))

    # Sort chapters by chapter number
    def sort_key(ch):
        ch_num = ch.get("chapter")
        if ch_num is None:
            return float("inf")
        try:
            return float(ch_num)
        except (ValueError, TypeError):
            return float("inf")

    all_chapters.sort(key=sort_key)

    # Cache the result
    _CHAPTER_CACHE[cache_key] = {"data": all_chapters, "timestamp": time.time()}

    logger.info(
        "[MANGADEX] Retrieved total of %d chapters (%d available, %d unavailable) for manga %s"
        % (len(all_chapters), len(available_chapters), len(all_chapters) - len(available_chapters), manga_id)
    )
    return all_chapters


def get_cover_image(manga_id):
    """
    Get cover image URL for a manga.

    Args:
        manga_id: MangaDex manga UUID (without md- prefix)

    Returns:
        Cover URL string or None
    """
    # Remove md- prefix if present
    if manga_id.startswith("md-"):
        manga_id = manga_id[3:]

    # Check cache first
    if manga_id in _IMAGE_CACHE:
        return _IMAGE_CACHE[manga_id]

    # Get manga details which includes cover
    details = get_manga_details(manga_id)
    if details:
        cover_url = details.get("cover_url")
        _IMAGE_CACHE[manga_id] = cover_url
        return cover_url

    return None


def clear_cache():
    """Clear all in-memory caches."""
    global _IMAGE_CACHE, _MANGA_CACHE, _CHAPTER_CACHE
    _IMAGE_CACHE = {}
    _MANGA_CACHE = {}
    _CHAPTER_CACHE = {}
    logger.info("[MANGADEX] Caches cleared")


def is_manga_id(comic_id):
    """
    Check if a comic ID is a MangaDex manga ID.

    Args:
        comic_id: Comic/Manga ID string

    Returns:
        True if it's a MangaDex ID (starts with 'md-')
    """
    return comic_id and str(comic_id).startswith("md-")


def strip_manga_prefix(manga_id):
    """
    Remove the 'md-' prefix from a manga ID if present.

    Args:
        manga_id: Manga ID string

    Returns:
        Raw MangaDex UUID without prefix
    """
    if manga_id and str(manga_id).startswith("md-"):
        return manga_id[3:]
    return manga_id
