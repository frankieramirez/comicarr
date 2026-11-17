#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Narrate a series add on the activity feed.

Moved from ``comicarr/importer.py`` (#1463) so the comic add and the manga add
share it.
"""

from comicarr import logger


def emit_add_activity(status, comicid, comicname=None, reason_detail=None):
    """Narrate a series add. Failures must not be swallowed silently."""
    try:
        from comicarr.app.activity.producers import emit_series_activity

        emit_series_activity(
            "add",
            status,
            comicid,
            comicname=comicname,
            reason_code="import_failed" if status == "failed" else None,
            reason_detail=reason_detail,
        )
    except Exception as e:
        logger.fdebug("[ACTIVITY] add.%s emit skipped: %s" % (status, e))
