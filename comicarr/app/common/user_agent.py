#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Comicarr's own User-Agent for public metadata APIs.

``CV_USER_AGENT`` is a ComicVine setting and is often a browser string.
MangaDex redirects browser user agents to a bot challenge page, so the
manga sources identify as Comicarr instead: ``Comicarr/<version>``.
"""

import functools


@functools.lru_cache(maxsize=1)
def app_user_agent() -> str:
    try:
        from comicarr.app.system.service import get_release_version

        version = get_release_version()
    except Exception:
        version = None
    return "Comicarr/%s" % (version or "unknown")
