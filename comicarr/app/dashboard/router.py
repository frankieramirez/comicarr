#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Dashboard domain router — home dashboard data aggregation endpoint.
"""

from fastapi import APIRouter, Depends

from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import require_session

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", dependencies=[Depends(require_session)])
@router.get("/", dependencies=[Depends(require_session)])
def get_dashboard(ctx: AppContext = Depends(get_context)):
    """Return aggregated dashboard data for the home page."""
    from comicarr.app.dashboard import service

    return service.get_dashboard_data(ctx)
