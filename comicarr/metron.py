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
Metron API integration for comic search functionality.

Uses mokkari library to interface with Metron's API.
Provides server-side sorting which solves the CV sorting bug.
"""

import time
import comicarr
from comicarr import logger
from comicarr.helpers import listLibrary

# In-memory cache for series images to avoid repeated API calls
_IMAGE_CACHE = {}  # {series_id: image_url}

# Mapping from frontend sort values to Metron's ordering parameter
SORT_MAPPING = {
    'year_desc': '-year_began',
    'year_asc': 'year_began',
    'issues_desc': '-issue_count',
    'issues_asc': 'issue_count',
    'name_asc': 'name',
    'name_desc': '-name',
    'date_last_updated:desc': '-modified',  # CV default sort
    'date_last_updated:asc': 'modified',
    'relevance': None,  # Use Metron's natural order for relevance
    None: '-year_began',  # Default to newest first
}


def initialize_metron_api():
    """
    Initialize the Metron API client using mokkari.

    Returns:
        mokkari.api instance or None if credentials are not configured
    """
    try:
        import mokkari
    except ImportError:
        logger.warn('[METRON] mokkari library not installed. Run: pip install mokkari')
        return None

    username = comicarr.CONFIG.METRON_USERNAME
    password = comicarr.CONFIG.METRON_PASSWORD

    if not username or not password:
        logger.warn('[METRON] Metron credentials not configured')
        return None

    try:
        api = mokkari.api(username, password)
        logger.info('[METRON] Metron API client initialized successfully')
        return api
    except Exception as e:
        logger.error('[METRON] Failed to initialize Metron API: %s' % e)
        return None


def reinitialize_metron_api():
    """
    Reinitialize the Metron API client after config changes.
    Called by setConfig API when Metron settings are updated.
    """
    global_updated = False

    if comicarr.CONFIG.USE_METRON_SEARCH:
        if comicarr.CONFIG.METRON_USERNAME and comicarr.CONFIG.METRON_PASSWORD:
            new_api = initialize_metron_api()
            if new_api:
                comicarr.METRON_API = new_api
                global_updated = True
                logger.info('[METRON] API reinitialized after config change')
            else:
                comicarr.METRON_API = None
                logger.warn('[METRON] Failed to reinitialize API after config change')
        else:
            comicarr.METRON_API = None
            logger.info('[METRON] API disabled - credentials not configured')
    else:
        comicarr.METRON_API = None
        logger.info('[METRON] API disabled via config')

    return global_updated


def search_series(name, mode='series', issue=None, limityear=None, limit=None, offset=None, sort=None):
    """
    Search for comic series using Metron API.

    Args:
        name: Series name to search for
        mode: Search mode (series, pullseries, want)
        issue: Issue number (not used for series search)
        limityear: Year filter (not currently implemented for Metron)
        limit: Number of results per page
        offset: Offset for pagination
        sort: Sort order (year_desc, year_asc, issues_desc, issues_asc, name_asc, name_desc)

    Returns:
        dict with 'results' list and 'pagination' metadata, or list for legacy mode
    """
    search_start_time = time.time()
    logger.info('[METRON] Starting search for: %s (limit=%s, offset=%s, sort=%s)' % (name, limit, offset, sort))

    api = comicarr.METRON_API
    if api is None:
        logger.error('[METRON] Metron API not initialized')
        return {'results': [], 'pagination': {'total': 0, 'limit': limit or 50, 'offset': offset or 0, 'returned': 0}}

    # Get library for "haveit" status
    comicLibrary = listLibrary()

    # Map sort parameter to Metron ordering
    metron_sort = SORT_MAPPING.get(sort, SORT_MAPPING[None])

    # Set pagination defaults
    page_limit = limit if limit else 50
    page_offset = offset if offset else 0

    try:
        # Metron uses 'page' instead of offset - calculate page number
        # Metron returns 30 results per page by default
        page_size = 30  # Metron's default page size
        page_number = (page_offset // page_size) + 1

        # Search using mokkari
        results = api.series_list({
            'name': name,
            'page': page_number,
        })

        # mokkari returns a SeriesList object with iteration support
        # BaseSeries fields: id, year_began, issue_count, volume, modified, display_name
        # Convert to list first to avoid iterator issues
        results_list = list(results)
        total_results = len(results_list)
        comiclist = []

        for series in results_list:
            # Map Metron fields to Mylar format
            metron_id = str(series.id) if hasattr(series, 'id') else None

            if metron_id is None:
                continue

            # Get display_name and parse it (format: "Series Name (Year)")
            display_name = series.display_name if hasattr(series, 'display_name') else 'Unknown'
            # Extract series name by removing the year suffix if present
            series_name = display_name
            if display_name and '(' in display_name:
                series_name = display_name.rsplit('(', 1)[0].strip()

            # Get year
            start_year = str(series.year_began) if hasattr(series, 'year_began') and series.year_began else '0000'
            issue_count = series.issue_count if hasattr(series, 'issue_count') and series.issue_count else 0
            volume = series.volume if hasattr(series, 'volume') and series.volume else None

            # Note: BaseSeries doesn't include publisher, image, cv_id, desc, series_type
            # These would require fetching full series details via api.series(id)
            # For search results, we use defaults
            publisher = 'Unknown'
            cover_url = 'cache/blankcover.jpg'
            cv_id = None  # Not available in list results

            # Check if we already have this series
            haveit = 'No'
            # Check by Metron ID first
            if metron_id in comicLibrary:
                haveit = comicLibrary[metron_id]
            # Fallback: check by name and year for cross-provider matching
            else:
                if series_name and start_year:
                    name_key = 'name:' + series_name.lower().strip() + ':' + start_year.strip()
                    if name_key in comicLibrary:
                        haveit = comicLibrary[name_key]

            # Build year range for filtering (similar to CV logic)
            yearRange = [start_year]
            if start_year.isdigit():
                possible_years = int(start_year) + (issue_count // 12) + 1
                for year in range(int(start_year), int(possible_years)):
                    if str(year) not in yearRange:
                        yearRange.append(str(year))

            # Apply year filter if specified
            if limityear and limityear != 'None':
                if not any(v in limityear for v in yearRange):
                    continue

            comiclist.append({
                'name': series_name,
                'comicyear': start_year,
                'comicid': metron_id,  # Use Metron ID as primary
                'cv_comicid': cv_id,   # Not available in list results
                'url': 'https://metron.cloud/series/%s/' % metron_id,
                'issues': str(issue_count),
                'comicimage': cover_url,
                'comicthumb': cover_url,
                'publisher': publisher,
                'description': 'None',  # Not available in list results
                'deck': None,
                'type': None,  # Not available in list results
                'haveit': haveit,
                'lastissueid': None,
                'firstissueid': None,
                'volume': volume,
                'imprint': None,
                'seriesrange': yearRange,
            })

            # Respect limit
            if limit and len(comiclist) >= limit:
                break

        search_duration = time.time() - search_start_time
        logger.info('[METRON] Search completed in %.2f seconds (%d results)' % (search_duration, len(comiclist)))

        # Apply manual sorting since mokkari may not support ordering parameter
        if sort:
            if sort in ['year_desc', 'date_last_updated:desc']:
                comiclist.sort(key=lambda x: (x['comicyear'] or '0000', x['issues'] or '0'), reverse=True)
            elif sort == 'year_asc':
                comiclist.sort(key=lambda x: (x['comicyear'] or '9999', x['issues'] or '0'), reverse=False)
            elif sort == 'issues_desc':
                comiclist.sort(key=lambda x: int(x['issues']) if x['issues'] and x['issues'].isdigit() else 0, reverse=True)
            elif sort == 'issues_asc':
                comiclist.sort(key=lambda x: int(x['issues']) if x['issues'] and x['issues'].isdigit() else 0, reverse=False)
            elif sort == 'name_asc':
                comiclist.sort(key=lambda x: x['name'].lower() if x['name'] else '', reverse=False)
            elif sort == 'name_desc':
                comiclist.sort(key=lambda x: x['name'].lower() if x['name'] else '', reverse=True)

        # Return with pagination metadata if limit was provided
        if limit is not None:
            result = {
                'results': comiclist,
                'pagination': {
                    'total': total_results,
                    'limit': page_limit,
                    'offset': page_offset,
                    'returned': len(comiclist)
                }
            }
        else:
            # Legacy format: just return the list
            result = comiclist

        return result

    except Exception as e:
        logger.error('[METRON] Search failed: %s' % e)
        import traceback
        logger.error('[METRON] Traceback: %s' % traceback.format_exc())

        if limit is not None:
            return {'results': [], 'pagination': {'total': 0, 'limit': page_limit, 'offset': page_offset, 'returned': 0}}
        else:
            return []


def get_series_image(series_id):
    """
    Fetch cover image URL for a series by getting its first issue.

    Args:
        series_id: Metron series ID

    Returns:
        Image URL string, or None if not available
    """
    global _IMAGE_CACHE

    # Check cache first
    if series_id in _IMAGE_CACHE:
        logger.fdebug('[METRON] Image cache hit for series %s' % series_id)
        return _IMAGE_CACHE[series_id]

    api = comicarr.METRON_API
    if api is None:
        logger.warn('[METRON] Metron API not initialized')
        return None

    try:
        # Fetch issues for this series, limited to first issue
        issues = api.issues_list({'series_id': series_id})
        issues_list = list(issues)

        if issues_list:
            # Get the first issue's image
            first_issue = issues_list[0]
            image_url = first_issue.image if hasattr(first_issue, 'image') else None

            if image_url:
                # Convert to string if it's a URL object
                image_url_str = str(image_url)
                # Cache the result
                _IMAGE_CACHE[series_id] = image_url_str
                logger.fdebug('[METRON] Fetched and cached image for series %s: %s' % (series_id, image_url_str))
                return image_url_str

        logger.fdebug('[METRON] No image found for series %s' % series_id)
        # Cache None to avoid repeated lookups for series without images
        _IMAGE_CACHE[series_id] = None
        return None

    except Exception as e:
        logger.error('[METRON] Failed to fetch series image for %s: %s' % (series_id, e))
        return None
