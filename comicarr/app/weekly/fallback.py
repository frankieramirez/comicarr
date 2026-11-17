#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The backup pull-list sources, tried in order when Walksoftly fails.

Metron goes first when its login is configured, because its store dates are
reliable for the current week. ComicVine stays last.

Each attempt that does not fill the week is recorded as ``{"source", "reason"}``
so Releases can say why a week is empty. Reasons are codes, not prose:
``not_configured``, ``failed``, ``no_releases`` and ``filtered_out``.
"""

from comicarr.app.core import logger
from comicarr.app.weekly import cv_source, metron_source

SOURCES = (metron_source, cv_source)


def pull_week(weeknumber, year, midweek: str) -> dict:
    """Fill one week from the first backup source that has it."""
    attempts = []
    for source in SOURCES:
        if not source.is_available():
            attempts.append({"source": source.SOURCE, "reason": "not_configured"})
            continue
        try:
            result = source.pull_week(weeknumber, year, midweek)
        except Exception as e:
            logger.warn("[PULL-LIST] %s fetch for week %s, %s failed: %s" % (source.SOURCE, weeknumber, year, e))
            result = {"status": "failure", "reason": "failed", "cause": str(e)}
        if result.get("status") == "success":
            return {**result, "attempts": attempts}
        logger.info(
            "[PULL-LIST] %s did not fill week %s, %s: %s" % (source.SOURCE, weeknumber, year, result.get("cause"))
        )
        attempts.append({"source": source.SOURCE, "reason": result.get("reason") or "failed"})
    return {"status": "failure", "attempts": attempts, "cause": _cause(attempts)}


def _cause(attempts) -> str:
    if all(a["reason"] == "not_configured" for a in attempts):
        return "No backup pull-list source (Metron or ComicVine) is configured."
    return "; ".join("%s: %s" % (a["source"], a["reason"]) for a in attempts)
