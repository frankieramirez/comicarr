#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Safe cover/image URL fetching for the metadata domain.

Shared allowlists and fetch helpers used by get_artwork and /image-proxy
to prevent SSRF and oversized downloads.
"""

from urllib.parse import urlparse

import requests

from comicarr import logger

# Hosts allowed for server-side cover/image fetches (SSRF protection).
# Keep in sync with CSP img-src in middleware when adding new CDNs.
ALLOWED_IMAGE_DOMAINS = {
    "comicvine.gamespot.com",
    "static.metron.cloud",
    "uploads.mangadex.org",
    "myanimelist.net",
    "cdn.myanimelist.net",
    "api-cdn.myanimelist.net",
}

ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
}

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MiB


def is_allowed_image_url(url):
    """Return True if url is http(s), no userinfo, and host is allowlisted."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except Exception as e:
        logger.fdebug("[METADATA-artwork] Invalid URL parse: %s" % e)
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.username or parsed.password:
        return False
    if not parsed.hostname:
        return False
    return parsed.hostname in ALLOWED_IMAGE_DOMAINS


def fetch_allowed_image(url):
    """Fetch image bytes from an allowlisted URL.

    Returns (content_bytes, content_type) or None on any failure.
    """
    if not is_allowed_image_url(url):
        logger.fdebug("[METADATA-artwork] Rejected non-allowlisted image URL: %s" % url)
        return None

    try:
        resp = requests.get(
            url,
            timeout=(5, 10),
            headers={"User-Agent": "Comicarr/1.0"},
            allow_redirects=False,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.error("[METADATA-artwork] Failed to fetch image %s: %s" % (url, e))
        return None

    content_length = resp.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_IMAGE_BYTES:
                logger.error("[METADATA-artwork] Image Content-Length exceeds cap (%s): %s" % (content_length, url))
                return None
        except (ValueError, TypeError):
            pass

    content = resp.content
    if len(content) > MAX_IMAGE_BYTES:
        logger.error("[METADATA-artwork] Image body exceeds size cap: %s" % url)
        return None

    content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip().lower()
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        logger.error("[METADATA-artwork] Invalid content type %s for %s" % (content_type, url))
        return None

    return content, content_type
