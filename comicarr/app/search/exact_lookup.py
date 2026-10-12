#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import re
from urllib.parse import urlsplit

from mokkari.exceptions import ApiError
from requests.exceptions import HTTPError

import comicarr
from comicarr import logger, mb


def parse_identifier(query):
    query = query.strip()
    if re.fullmatch(r"4050-[1-9][0-9]*", query):
        return "comicvine", query[5:]
    try:
        url = urlsplit(query)
        if url.scheme not in ("https", "http") or url.username or url.password or url.port:
            return None
        if url.hostname in ("comicvine.gamespot.com", "www.comicvine.gamespot.com"):
            match = re.fullmatch(r"/(?:[^/]+/)?4050-([1-9][0-9]*)/?", url.path)
            if match:
                return "comicvine", match[1]
        elif url.hostname in ("metron.cloud", "www.metron.cloud"):
            match = re.fullmatch(r"/series/([1-9][0-9]*)/?", url.path)
            if match:
                return "metron", match[1]
    except ValueError:
        return None
    return None


def lookup(ctx, provider, identifier):
    if provider == "metron":
        api = getattr(ctx, "metron_api", None) or comicarr.METRON_API
        if not getattr(ctx.config, "USE_METRON_SEARCH", False) or api is None:
            return {"error": "Metron integration is not configured"}
        try:
            series = api.series(int(identifier))
        except ApiError as e:
            # Mokkari wraps HTTP failures and API detail strings in ApiError.
            cause = e.__cause__
            if isinstance(cause, HTTPError) and cause.response is not None and cause.response.status_code == 404:
                return {"results": []}
            if str(e) in ("Not found.", "No Series matches the given query."):
                return {"results": []}
            return {"error": "Metron could not look up this series. Check credentials and try again."}
        except Exception as e:
            logger.warn("[METRON] Exact series lookup failed (%s)" % type(e).__name__)
            return {"error": "Metron could not look up this series. Check the connection and try again."}
        if series is None:
            return {"results": []}
        if str(series.id) != identifier:
            return {"error": "Metron returned a different series"}
        comic_id = "metron-" + identifier
        candidate = {
            "comicid": comic_id,
            "name": series.name,
            "comicyear": str(series.year_began or "0000"),
            "publisher": getattr(series.publisher, "name", "Unknown"),
            "issues": str(series.issue_count or 0),
            "count_of_issues": series.issue_count or 0,
            "comicimage": None,
            "url": "https://metron.cloud/series/%s/" % identifier,
            "metadata_source": "metron",
            "cv_comicid": str(series.cv_id) if series.cv_id else None,
        }
    else:
        key = getattr(ctx.config, "COMICVINE_API", None)
        if not key or key == "None":
            return {"error": "ComicVine API key is not configured"}
        try:
            limiter = getattr(ctx, "cv_rate_limiter", None) or comicarr.CV_RATE_LIMITER
            session = getattr(ctx, "cv_session", None) or comicarr.CV_SESSION
            limiter.acquire()
            response = session.get(
                comicarr.CVURL + "volume/4050-%s/" % identifier,
                params={
                    "api_key": key,
                    "format": "json",
                    "field_list": "id,name,start_year,publisher,count_of_issues,image,site_detail_url",
                },
                verify=ctx.config.CV_VERIFY,
                timeout=comicarr.CV_TIMEOUT,
            )
            if response.status_code == 404:
                return {"results": []}
            response.raise_for_status()
            data = response.json()
            if data.get("status_code") == 101:
                return {"results": []}
            if data.get("status_code") != 1:
                return {"error": "ComicVine could not look up this volume. Check the API key and try again."}
            series = data.get("results")
            if not series:
                return {"results": []}
            if str(series.get("id")) != identifier:
                return {"error": "ComicVine returned a different volume"}
            comic_id = identifier
            image = series.get("image") or {}
            candidate = {
                "comicid": comic_id,
                "name": series["name"],
                "comicyear": str(series.get("start_year") or "0000"),
                "publisher": (series.get("publisher") or {}).get("name", "Unknown"),
                "issues": str(series.get("count_of_issues") or 0),
                "count_of_issues": series.get("count_of_issues") or 0,
                "comicimage": image.get("super_url"),
                "comicthumb": image.get("thumb_url"),
                "url": series.get("site_detail_url"),
                "metadata_source": "comicvine",
            }
        except Exception as e:
            logger.warn("[COMICVINE] Exact volume lookup failed (%s)" % type(e).__name__)
            return {"error": "ComicVine could not look up this volume. Check the connection and try again."}

    library = mb.listLibrary()
    library_id = candidate.get("cv_comicid") or comic_id
    candidate["haveit"] = mb.haveit_for_comicvine(library_id, library)
    candidate["in_library"] = candidate["haveit"] != "No"
    return {"results": [candidate]}
