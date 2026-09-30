#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""ComicVine as the fallback weekly pull-list source (#919).

Walksoftly is the only primary source, so an outage there used to empty the
pull list for the whole week. ComicVine's ``issues`` resource can be filtered by
``store_date``, and every row it returns carries the CV volume and issue ids the
library is keyed on, so the rows match by id with no title guessing.

The rows are written through :func:`comicarr.locg.store_week` in the same shape
Walksoftly produces, so ``new_pullcheck``, Releases and the AI curation read
them unchanged.
"""

import datetime

import comicarr
from comicarr import cv, locg, logger
from comicarr.helpers import ignored_publisher_check

SOURCE = "comicvine"

# ComicVine caps list resources at 100 results per request.
PAGE_SIZE = 100

# A normal week is a handful of pages; this only stops a misbehaving response
# from paging forever.
MAX_PAGES = 30


def is_available() -> bool:
    """Whether a ComicVine API key is configured to query with."""
    key = comicarr.CONFIG.COMICVINE_API
    return bool(key) and key != "None"


def week_bounds(midweek: str) -> tuple[str, str]:
    """Sunday and Saturday of the pull week whose Wednesday is ``midweek``."""
    mid = datetime.date.fromisoformat(midweek)
    return (mid - datetime.timedelta(days=3)).isoformat(), (mid + datetime.timedelta(days=3)).isoformat()


def _fetch_all(rtype: str, **kwargs) -> list[dict] | None:
    """Every result of a paged ComicVine JSON request, or None if any page failed
    or the page cap cut it short. A partial week must never replace saved rows."""
    results: list[dict] = []
    offset = 0
    for _ in range(MAX_PAGES):
        response = cv.pulldetails(None, rtype, offset=offset, **kwargs)
        if not isinstance(response, dict) or response.get("status_code") != 1:
            error = response.get("error") if isinstance(response, dict) else None
            logger.warn("[PULL-LIST] ComicVine %s request failed at offset %s: %s" % (rtype, offset, error))
            return None
        page = response.get("results") or []
        results.extend(page)
        offset += len(page)
        if not page or offset >= int(response.get("number_of_total_results") or 0):
            return results
    logger.warn(
        "[PULL-LIST] ComicVine %s returned more than %s pages; discarding the incomplete result" % (rtype, MAX_PAGES)
    )
    return None


def _fetch_volumes(volume_ids: list[str]) -> dict[str, dict] | None:
    """Publisher and start year for each volume, looked up 100 ids at a time."""
    volumes: dict[str, dict] = {}
    for start in range(0, len(volume_ids), PAGE_SIZE):
        chunk = volume_ids[start : start + PAGE_SIZE]
        page = _fetch_all("weekly_volumes", comicidlist="|".join(chunk))
        if page is None:
            return None
        for volume in page:
            volumes[str(volume.get("id"))] = volume
    return volumes


def _failure(cause: str) -> dict:
    return {"status": "failure", "source": SOURCE, "cause": cause}


def pull_week(weeknumber, year, midweek: str) -> dict:
    """Fill the saved pull list for one week from ComicVine.

    Returns the same result shape as ``locg.locg()``, plus ``source``.
    """
    if not is_available():
        return _failure("No ComicVine API key is configured.")

    start_date, end_date = week_bounds(midweek)
    logger.info("[PULL-LIST] Asking ComicVine for issues on sale %s to %s" % (start_date, end_date))

    issues = _fetch_all("weekly_releases", dateinfo={"start_date": start_date, "end_date": end_date})
    if issues is None:
        return _failure("ComicVine did not return the week's releases.")
    if not issues:
        return _failure("ComicVine lists no releases for %s to %s." % (start_date, end_date))

    volume_ids = sorted({str(issue["volume"]["id"]) for issue in issues if (issue.get("volume") or {}).get("id")})
    volumes = _fetch_volumes(volume_ids)
    if volumes is None:
        return _failure("ComicVine did not return the series for the week's releases.")

    pull = []
    for issue in issues:
        volume = issue.get("volume") or {}
        volume_id = volume.get("id")
        issue_number = issue.get("issue_number")
        if not volume_id or issue_number in (None, ""):
            continue
        details = volumes.get(str(volume_id), {})
        publisher = (details.get("publisher") or {}).get("name")
        if publisher and ignored_publisher_check(publisher):
            continue
        pull.append(
            {
                "series": details.get("name") or volume.get("name"),
                "alias": None,
                "issue": str(issue_number),
                "publisher": publisher,
                "shipdate": issue.get("store_date"),
                "coverdate": issue.get("cover_date"),
                "comicid": str(volume_id),
                "issueid": str(issue["id"]) if issue.get("id") else None,
                "weeknumber": str(int(weeknumber)),
                "annuallink": None,
                "year": str(year),
                "volume": None,
                "seriesyear": details.get("start_year"),
                "format": None,
            }
        )

    if not pull:
        return _failure("Every ComicVine release for %s to %s was filtered out." % (start_date, end_date))

    locg.store_week(pull, weeknumber, year)
    return {"status": "success", "source": SOURCE, "count": len(pull), "weeknumber": weeknumber, "year": year}
