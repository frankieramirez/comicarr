#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Canonical allowlist of third-party hosts trusted to serve cover art.

One set, two derived views:

- ``metadata.image_fetch`` compares bare hostnames, guarding server-side
  fetches against SSRF.
- ``core.middleware`` splices ``https://host`` tokens into the CSP img-src
  directive, permitting the browser to load a cover directly.

Both are needed because covers reach the browser two ways: proxied through
``/api/metadata/art/{comic_id}``, and — when the cache-on-add fetch failed —
as the raw external URL left in ``comics.ComicImage``, which the library grid
renders with no proxy fallback. This module lives in ``core`` rather than
``metadata`` because ``middleware`` may not import from a domain package.
"""

ALLOWED_IMAGE_DOMAINS = frozenset(
    {
        "comicvine.gamespot.com",
        "static.metron.cloud",
        "uploads.mangadex.org",
        "myanimelist.net",
        "cdn.myanimelist.net",
        "api-cdn.myanimelist.net",
    }
)


def csp_img_src_origins():
    """Return the allowlist as space-joined ``https://host`` CSP source tokens."""
    return " ".join("https://%s" % host for host in sorted(ALLOWED_IMAGE_DOMAINS))
