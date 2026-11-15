#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Prowlarr's aggregated search, run as one provider per protocol (#1078, #1140).

Prowlarr searches every indexer it manages in one request and skips the ones
it knows are failing. Comicarr treats that endpoint as up to two providers:

* ``Prowlarr`` keeps the torrent results. It is a Torznab-shaped provider and
  runs whenever torrent search is on, as it always has.
* ``Prowlarr (Usenet)`` keeps the Usenet results. It is a Newznab-shaped
  provider, so its NZBs go to the configured Usenet client the same way a
  Newznab indexer's do. It runs only when ``PROWLARR_USENET`` is on, so an
  install that already searches the same indexers directly does not start
  asking them twice after an upgrade.

Both carry a provider tuple whose host is the ``/api/v1/search`` endpoint, and
the JSON response is turned into feedparser-shaped entries so release
evaluation and the handoff run unchanged.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from email.utils import format_datetime
from urllib.parse import parse_qs, quote, urlsplit

import feedparser
import requests

PROWLARR_NAME = "Prowlarr"
PROWLARR_PROVIDER_ID = 202
PROWLARR_USENET_NAME = "Prowlarr (Usenet)"
PROWLARR_USENET_PROVIDER_ID = 203
TORRENT = "torrent"
USENET = "usenet"
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


def usenet_enabled(config) -> bool:
    """Prowlarr's Usenet results are searched only when the operator opts in."""
    return bool(getattr(config, "PROWLARR_USENET", False) is True and configured(config))


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


def usenet_provider_entry(config) -> tuple:
    """The Newznab-width tuple the search loop runs Prowlarr's Usenet side through.

    Field 5 of a Newznab tuple is ``uid#categories``; Prowlarr has no RSS uid,
    so the uid half is left empty.
    """
    return (
        PROWLARR_USENET_NAME,
        base_url(config.PROWLARR_HOST) + SEARCH_PATH,
        "1" if getattr(config, "PROWLARR_VERIFY", True) else "0",
        _text(config.PROWLARR_APIKEY),
        "#" + "#".join(categories(getattr(config, "PROWLARR_CATEGORIES", None))),
        "1",
        PROWLARR_USENET_PROVIDER_ID,
    )


def is_download_link(link) -> bool:
    """Whether ``link`` is a Prowlarr download proxy URL (``/<id>/download?apikey=&link=``)."""
    parts = urlsplit(_text(link))
    if not parts.path.rstrip("/").lower().endswith("/download"):
        return False
    query = parse_qs(parts.query)
    return "link" in query and "apikey" in query


def release_id(link) -> str:
    """A stable identity for a Prowlarr download link that never holds the API key.

    The proxy URL starts with ``apikey=``, so the generic Newznab and Torznab
    id parsers took the key itself as the release id: every Prowlarr result
    then shared one id, and that id was a secret. The ``link`` parameter is
    the indexer's own download address, which is unique per release.
    """
    target = parse_qs(urlsplit(_text(link)).query).get("link", [""])[0]
    return "prowlarr-" + hashlib.sha1(target.encode("utf-8")).hexdigest()[:20]


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


def entries_from_response(content, protocol=TORRENT) -> list:
    """Turn Prowlarr's JSON results for one ``protocol`` into feedparser-shaped entries.

    ``protocol`` is ``torrent`` or ``usenet``; results for the other protocol
    are dropped, because each one is handed off to a different client.
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
        if _text(result.get("protocol")).lower() != protocol:
            continue
        title = _text(result.get("title"))
        link = _text(result.get("downloadUrl"))
        if protocol == TORRENT:
            link = link or _text(result.get("magnetUrl"))
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
    enabled = [indexer for indexer in indexers if isinstance(indexer, dict) and indexer.get("enable", True)]
    return {
        "success": True,
        "torrent_indexers": sum(1 for indexer in enabled if indexer.get("protocol") == TORRENT),
        "usenet_indexers": sum(1 for indexer in enabled if indexer.get("protocol") == USENET),
        "indexers": len(indexers),
    }
