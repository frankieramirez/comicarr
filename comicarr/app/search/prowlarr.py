#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Prowlarr's aggregated search, run as one torrent provider (#1078).

Prowlarr searches every indexer it manages in one request and skips the ones
it knows are failing. Comicarr treats that endpoint as a single Torznab-shaped
provider named ``Prowlarr``: the plan carries a Torznab-width tuple whose host
is the ``/api/v1/search`` endpoint, and the JSON response is turned into
feedparser-shaped entries so release evaluation and the torrent handoff run
unchanged. Only torrent results are kept; usenet indexers stay on Newznab.
"""

from __future__ import annotations

import json
from datetime import datetime
from email.utils import format_datetime
from urllib.parse import quote, urlsplit

import feedparser
import requests

PROWLARR_NAME = "Prowlarr"
PROWLARR_PROVIDER_ID = 202
SEARCH_PATH = "/api/v1/search"
DEFAULT_CATEGORIES = "7030"
RESULT_LIMIT = 100


def _text(value) -> str:
    text = str(value or "").strip()
    return "" if text == "None" else text


def base_url(host) -> str:
    """Prowlarr's base URL without a trailing slash or a pasted API path."""
    host = _text(host).rstrip("/")
    for suffix in (SEARCH_PATH, "/api/v1", "/api"):
        if host.lower().endswith(suffix):
            host = host[: -len(suffix)].rstrip("/")
            break
    return host


def categories(raw) -> list[str]:
    """Numeric category ids from a comma, space or ``#`` separated list."""
    values = [part.strip() for part in _text(raw).replace("#", ",").replace(" ", ",").split(",")]
    kept = [value for value in values if value.isdigit()]
    return kept or [DEFAULT_CATEGORIES]


def configured(config) -> bool:
    return bool(
        getattr(config, "ENABLE_PROWLARR", False) is True
        and base_url(getattr(config, "PROWLARR_HOST", None))
        and _text(getattr(config, "PROWLARR_APIKEY", None))
    )


def enabled(config) -> bool:
    """Prowlarr searches only when torrent search is on, like Torznab."""
    return bool(getattr(config, "ENABLE_TORRENT_SEARCH", False) and configured(config))


def provider_entry(config) -> tuple:
    """The Torznab-width tuple the search loop runs Prowlarr through."""
    return (
        PROWLARR_NAME,
        base_url(config.PROWLARR_HOST) + SEARCH_PATH,
        "1" if getattr(config, "PROWLARR_VERIFY", True) else "0",
        _text(config.PROWLARR_APIKEY),
        "#".join(categories(getattr(config, "PROWLARR_CATEGORIES", None))),
        "1",
        PROWLARR_PROVIDER_ID,
    )


def is_search_endpoint(host) -> bool:
    return urlsplit(_text(host)).path.rstrip("/").lower().endswith(SEARCH_PATH)


def search_url(endpoint, query, category_field) -> str:
    """The aggregated search URL; the caller appends ``&apikey=``.

    ``query`` arrives already %20-encoded by the search loop.
    """
    url = "%s?type=search&limit=%s&query=%s" % (endpoint.rstrip("/"), RESULT_LIMIT, query)
    for category in categories(category_field):
        url += "&categories=" + quote(category)
    return url


def _rfc2822(value) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        return format_datetime(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def entries_from_response(content) -> list:
    """Turn Prowlarr's JSON results into feedparser-shaped torrent entries.

    Raises ``ValueError`` when the body is not a JSON list of results.
    """
    try:
        results = json.loads(content)
    except (TypeError, ValueError) as e:
        raise ValueError("Prowlarr returned a response that is not JSON") from e
    if not isinstance(results, list):
        raise ValueError("Prowlarr returned an unexpected response")

    entries = []
    for result in results:
        if not isinstance(result, dict):
            continue
        if _text(result.get("protocol")).lower() != "torrent":
            continue
        title = _text(result.get("title"))
        link = _text(result.get("downloadUrl")) or _text(result.get("magnetUrl"))
        pubdate = _rfc2822(result.get("publishDate"))
        if not title or not link or pubdate is None:
            continue
        size = result.get("size") or 0
        entry = feedparser.FeedParserDict(
            title=title,
            link=link,
            id=_text(result.get("guid")) or link,
            updated=pubdate,
            pubdate=pubdate,
            length=str(size),
            size=str(size),
            # feedparser derives ``enclosures`` from enclosure links.
            links=[feedparser.FeedParserDict(rel="enclosure", length=str(size), href=link)],
            indexer=_text(result.get("indexer")),
        )
        for key in ("seeders", "leechers", "grabs", "files"):
            if result.get(key) is not None:
                entry[key] = result[key]
        entries.append(entry)
    return entries


def check_connection(host, api_key, verify=True, timeout=15) -> dict:
    """Check the URL and API key against Prowlarr's indexer list."""
    url = base_url(host)
    if not url or not _text(api_key):
        return {"success": False, "error": "Enter the Prowlarr URL and API key"}
    try:
        response = requests.get(
            url + "/api/v1/indexer",
            headers={"X-Api-Key": _text(api_key)},
            allow_redirects=False,
            verify=bool(verify),
            timeout=timeout,
        )
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": "Could not reach Prowlarr: %s" % type(e).__name__}
    if response.status_code in (401, 403):
        return {"success": False, "error": "Prowlarr rejected the API key"}
    if response.status_code != 200:
        return {"success": False, "error": "Prowlarr answered with HTTP %s" % response.status_code}
    try:
        indexers = response.json()
    except ValueError:
        return {"success": False, "error": "That URL did not answer like Prowlarr"}
    if not isinstance(indexers, list):
        return {"success": False, "error": "That URL did not answer like Prowlarr"}
    usable = [
        indexer
        for indexer in indexers
        if isinstance(indexer, dict) and indexer.get("enable", True) and indexer.get("protocol") == "torrent"
    ]
    return {"success": True, "torrent_indexers": len(usable), "indexers": len(indexers)}
