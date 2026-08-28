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
from comicarr.app.core.image_hosts import ALLOWED_IMAGE_DOMAINS

ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
}

MAX_IMAGE_BYTES = 10 * 1024 * 1024
_CHUNK_SIZE = 64 * 1024


def normalize_allowed_image_url(url):
    """Return a normalized allowlisted image URL, or None when unsafe."""
    if not url or not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url)
    except Exception as e:
        logger.fdebug("[METADATA-artwork] Invalid URL parse: %s" % e)
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.username or parsed.password:
        return None
    if not parsed.hostname:
        return None
    if parsed.hostname not in ALLOWED_IMAGE_DOMAINS:
        return None

    if parsed.hostname == "myanimelist.net" and parsed.path.startswith("/images/"):
        return parsed._replace(scheme="https", netloc="cdn.myanimelist.net").geturl()

    return url


def is_allowed_image_url(url):
    """Return True if url is http(s), no userinfo, and host is allowlisted."""
    return normalize_allowed_image_url(url) is not None


def fetch_allowed_image(url):
    """Fetch image bytes from an allowlisted URL.

    Returns (content_bytes, content_type) or None on any failure.
    Streams the body and aborts once MAX_IMAGE_BYTES would be exceeded.
    """
    request_url = normalize_allowed_image_url(url)
    if request_url is None:
        logger.fdebug("[METADATA-artwork] Rejected non-allowlisted image URL: %s" % url)
        return None

    try:
        resp = requests.get(
            request_url,
            timeout=(5, 10),
            headers={"User-Agent": "Comicarr/1.0"},
            allow_redirects=False,
            stream=True,
        )
    except Exception as e:
        logger.error("[METADATA-artwork] Failed to fetch image %s: %s" % (url, e))
        return None

    try:
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
