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
_CHUNK_SIZE = 64 * 1024


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
    Streams the body and aborts once MAX_IMAGE_BYTES would be exceeded.
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
            stream=True,
        )
    except Exception as e:
        logger.error("[METADATA-artwork] Failed to fetch image %s: %s" % (url, e))
        return None

    try:
        # raise_for_status only fails 4xx/5xx; with allow_redirects=False, 3xx must not succeed
        if resp.status_code != 200:
            logger.error("[METADATA-artwork] Unexpected HTTP %s for image %s" % (resp.status_code, url))
            return None

        content_length = resp.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > MAX_IMAGE_BYTES:
                    logger.error("[METADATA-artwork] Image Content-Length exceeds cap (%s): %s" % (content_length, url))
                    return None
            except (ValueError, TypeError):
                pass

        raw_ct = resp.headers.get("Content-Type")
        if not raw_ct:
            logger.error("[METADATA-artwork] Missing Content-Type for %s" % url)
            return None
        content_type = raw_ct.split(";")[0].strip().lower()
        if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            logger.error("[METADATA-artwork] Invalid content type %s for %s" % (content_type, url))
            return None

        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                logger.error("[METADATA-artwork] Image body exceeds size cap: %s" % url)
                return None
            chunks.append(chunk)

        content = b"".join(chunks)
        if not content:
            logger.error("[METADATA-artwork] Empty image body for %s" % url)
            return None

        return content, content_type
    finally:
        try:
            resp.close()
        except Exception:
            pass
