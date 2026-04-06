#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Weekly pull list router — serves weekly release data for the Weekly page.
"""

from fastapi import APIRouter, Depends

from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import require_session

router = APIRouter(prefix="/api/weekly", tags=["weekly"])


@router.get("", dependencies=[Depends(require_session)])
@router.get("/", dependencies=[Depends(require_session)])
def get_weekly(ctx: AppContext = Depends(get_context)):
    """Return weekly pull list data."""
    from comicarr import db, logger

    try:
        rows = db.DBConnection().select(
            "SELECT COMIC, ISSUE, PUBLISHER, SHIPDATE, STATUS, ComicID, IssueID FROM weekly ORDER BY COMIC ASC"
        )
        return rows or []
    except Exception as e:
        logger.error("[WEEKLY] Error fetching weekly data: %s" % e)
        return []
