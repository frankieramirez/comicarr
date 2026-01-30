#  This file is part of Mylar.
#
#  Mylar is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mylar is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mylar.  If not, see <http://www.gnu.org/licenses/>.

"""
Metron API integration for comic search functionality.

Uses mokkari library to interface with Metron's API.
Provides server-side sorting which solves the CV sorting bug.
"""

import time
import mylar
from mylar import logger
from mylar.helpers import listLibrary

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

    username = mylar.CONFIG.METRON_USERNAME
    password = mylar.CONFIG.METRON_PASSWORD

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

    api = mylar.METRON_API
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
        comiclist = []
        total_results = getattr(results, 'count', 0) if hasattr(results, 'count') else len(list(results))

        for series in results:
            # Map Metron fields to Mylar format
            metron_id = str(series.id) if hasattr(series, 'id') else None

            if metron_id is None:
                continue

            # Get publisher name
            publisher = 'Unknown'
            if hasattr(series, 'publisher') and series.publisher:
                publisher = series.publisher.name if hasattr(series.publisher, 'name') else str(series.publisher)

            # Get cover image URL
            cover_url = 'cache/blankcover.jpg'
            if hasattr(series, 'image') and series.image:
                cover_url = str(series.image)

            # Get CV ID if available (for ComicTagger compatibility)
            cv_id = None
            if hasattr(series, 'cv_id') and series.cv_id:
                cv_id = str(series.cv_id)

            # Check if we already have this series
            haveit = 'No'
            # Check by Metron ID first
            if metron_id in comicLibrary:
                haveit = comicLibrary[metron_id]
            # Also check by CV ID if available
            elif cv_id and cv_id in comicLibrary:
                haveit = comicLibrary[cv_id]
            # Fallback: check by name and year for cross-provider matching
            else:
                series_name = series.name if hasattr(series, 'name') else None
                series_year = str(series.year_began) if hasattr(series, 'year_began') and series.year_began else None
                if series_name and series_year:
                    name_key = 'name:' + series_name.lower().strip() + ':' + series_year.strip()
                    if name_key in comicLibrary:
                        haveit = comicLibrary[name_key]

            # Build year range for filtering (similar to CV logic)
            start_year = str(series.year_began) if hasattr(series, 'year_began') and series.year_began else '0000'
            issue_count = series.issue_count if hasattr(series, 'issue_count') else 0

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
                'name': series.name if hasattr(series, 'name') else 'Unknown',
                'comicyear': start_year,
                'comicid': metron_id,  # Use Metron ID as primary
                'cv_comicid': cv_id,   # Store CV ID separately for ComicTagger
                'url': series.resource_url if hasattr(series, 'resource_url') else None,
                'issues': str(issue_count),
                'comicimage': cover_url,
                'comicthumb': cover_url,
                'publisher': publisher,
                'description': series.desc if hasattr(series, 'desc') else 'None',
                'deck': None,  # Metron doesn't have deck field
                'type': series.series_type.name if hasattr(series, 'series_type') and series.series_type else None,
                'haveit': haveit,
                'lastissueid': None,
                'firstissueid': None,
                'volume': series.volume if hasattr(series, 'volume') else None,
                'imprint': None,  # Would need additional API call
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
            return {
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
            return comiclist

    except Exception as e:
        logger.error('[METRON] Search failed: %s' % e)
        import traceback
        logger.error('[METRON] Traceback: %s' % traceback.format_exc())

        if limit is not None:
            return {'results': [], 'pagination': {'total': 0, 'limit': page_limit, 'offset': page_offset, 'returned': 0}}
        else:
            return []
