#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Metron as a weekly pull-list source when Walksoftly is down.

ComicVine's ``store_date`` data is often thin for the current week, while
Metron lists new comics by store date reliably. Metron's issue list carries
no ComicVine ids, so rows are tied to the library by series name and start
year. Rows for series outside the library are stored without a ComicID,
which Releases shows and lets the operator search for, as it does for
Walksoftly rows without one.

Rows go through :func:`comicarr.app.weekly.locg.store_week` in the same shape
Walksoftly produces.
"""

import threading

import comicarr
from comicarr.app.common.series_names import dynamic_series_key
from comicarr.app.core import logger
from comicarr.app.weekly import cv_source, locg
from comicarr.app.weekly import queries as weekly_queries

SOURCE = "metron"

_API_LOCK = threading.Lock()
_api = [None]


def _setting(name):
    value = getattr(comicarr.CONFIG, name, None)
    return value.strip() if isinstance(value, str) else ""


def is_available() -> bool:
    """Whether Metron credentials are configured."""
    username = _setting("METRON_USERNAME")
    return bool(username) and username != "None" and bool(_setting("METRON_PASSWORD"))


def _client():
    """The running Metron client, or one made for the pull list."""
    if comicarr.METRON_API is not None:
        return comicarr.METRON_API
    with _API_LOCK:
        if _api[0] is None:
            from comicarr.app.metadata import metron

            _api[0] = metron.initialize_metron_api()
        return _api[0]


def _failure(reason: str, cause: str) -> dict:
    return {"status": "failure", "source": SOURCE, "reason": reason, "cause": cause}


def _library_index() -> dict:
    """Library comic series keyed by dynamic name, each a list of (ComicID, year)."""
    index: dict = {}
    for row in weekly_queries.get_library_comics():
        key = row.get("DynamicComicName") or dynamic_series_key(row.get("ComicName") or "")
        if key:
            index.setdefault(key, []).append((str(row["ComicID"]), str(row.get("ComicYear") or "").strip()))
    return index


def _match(index: dict, name: str, year_began) -> str | None:
    """The library ComicID for a Metron series, or None when absent or ambiguous."""
    candidates = index.get(dynamic_series_key(name or ""), [])
    if year_began:
        candidates = [c for c in candidates if c[1] == str(year_began)]
    return candidates[0][0] if len(candidates) == 1 else None


def pull_week(weeknumber, year, midweek: str) -> dict:
    """Fill the saved pull list for one week from Metron.

    Returns the same result shape as ``cv_source.pull_week()``.
    """
    if not is_available():
        return _failure("not_configured", "No Metron login is configured.")
    api = _client()
    if api is None:
        return _failure("failed", "Comicarr could not sign in to Metron.")

    start_date, end_date = cv_source.week_bounds(midweek)
    logger.info("[PULL-LIST] Asking Metron for issues on sale %s to %s" % (start_date, end_date))
    try:
        issues = api.issues_list({"store_date_range_after": start_date, "store_date_range_before": end_date})
    except Exception as e:
        logger.warn("[PULL-LIST] Metron did not return the week's releases: %s" % e)
        return _failure("failed", "Metron did not return the week's releases.")
    if not issues:
        return _failure("no_releases", "Metron lists no releases for %s to %s." % (start_date, end_date))

    index = _library_index()
    pull = []
    for issue in issues:
        series = getattr(issue, "series", None)
        name = getattr(series, "name", None)
        number = getattr(issue, "number", None)
        if not name or number in (None, ""):
            continue
        year_began = getattr(series, "year_began", None)
        store_date = getattr(issue, "store_date", None)
        cover_date = getattr(issue, "cover_date", None)
        pull.append(
            {
                "series": name,
                "alias": None,
                "issue": str(number),
                "publisher": None,
                "shipdate": store_date.isoformat() if store_date else None,
                "coverdate": cover_date.isoformat() if cover_date else None,
                "comicid": _match(index, name, year_began),
                "issueid": None,
                "weeknumber": str(int(weeknumber)),
                "annuallink": None,
                "year": str(year),
                "volume": None,
                "seriesyear": str(year_began) if year_began else None,
                "format": None,
            }
        )

    if not pull:
        return _failure("no_releases", "Metron lists no usable releases for %s to %s." % (start_date, end_date))

    locg.store_week(pull, weeknumber, year)
    return {"status": "success", "source": SOURCE, "count": len(pull), "weeknumber": weeknumber, "year": year}
