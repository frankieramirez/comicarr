#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Dashboard domain router — one route per dashboard panel.

There is deliberately no aggregate payload: a single fan-in read makes one
slow or broken source blank the whole page, which is the failure mode
``docs/architecture/dashboard-spec.md`` §5 exists to prevent.
"""

from fastapi import APIRouter, Depends

from comicarr.app.core.security import require_session

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/library", dependencies=[Depends(require_session)])
def get_library():
    """Return the library aggregates behind the KPI strip."""
    from comicarr.app.dashboard import service

    return service.get_library_panel()


@router.get("/activity", dependencies=[Depends(require_session)])
def get_activity():
    """Return the bounded recent-activity preview."""
    from comicarr.app.dashboard import service

    return service.get_activity_panel()


@router.get("/upcoming", dependencies=[Depends(require_session)])
def get_upcoming():
    """Return this week's releases for series in the library."""
    from comicarr.app.dashboard import service

    return service.get_upcoming_panel()


@router.get("/scan-targets", dependencies=[Depends(require_session)])
def get_scan_targets():
    """Return which libraries the dashboard's scan action can start."""
    from comicarr.app.dashboard import service

    return service.get_scan_targets()
