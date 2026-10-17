#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Weekly pull list router — serves week-by-week release data for Releases.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from comicarr.app.core.context import AppContext, get_context
from comicarr.app.core.security import require_session
from comicarr.app.system import service as system_service
from comicarr.app.weekly import service as weekly_service

router = APIRouter(prefix="/api/weekly", tags=["weekly"])


class AddFromWeekRequest(BaseModel):
    rowid: int
    want: bool = False
    folder: str | None = None


@router.get("", dependencies=[Depends(require_session)])
@router.get("/", dependencies=[Depends(require_session)])
def get_weekly(
    week: int | None = Query(None),
    year: int | None = Query(None),
    ctx: AppContext = Depends(get_context),
):
    """Return one Sunday-based week of industry releases, the current week by default."""
    from comicarr import logger

    if (week is None) != (year is None):
        return JSONResponse(status_code=400, content={"detail": "Pass both week and year, or neither."})
    try:
        return weekly_service.get_week(week, year)
    except weekly_service.WeekError:
        # A fixed message, so no exception text reaches the response.
        return JSONResponse(status_code=400, content={"detail": weekly_service.WEEK_RANGE_MESSAGE})
    except Exception as e:
        logger.error("[WEEKLY] Error fetching weekly data: %s" % e)
        return JSONResponse(
            status_code=500, content={"detail": "Could not load the pull list. The log has the reason."}
        )


@router.post("/add", dependencies=[Depends(require_session)])
def add_from_week(body: AddFromWeekRequest, ctx: AppContext = Depends(get_context)):
    """Add a pull-list row's series to the library, optionally wanting that issue."""
    result = weekly_service.add_from_week(ctx, body.rowid, want=body.want, folder=body.folder)
    if not result.get("success"):
        return JSONResponse(status_code=result.get("status", 500), content={"detail": result.get("error")})
    return result


@router.post("/refresh", dependencies=[Depends(require_session)])
def refresh_weekly(ctx: AppContext = Depends(get_context)):
    """Request an immediate run of the existing, coalesced weekly scheduler job."""
    result = system_service.request_weekly_refresh(ctx)
    status_code = 503 if result["state"] == "unavailable" else 202 if result["accepted"] else 200
    return JSONResponse(status_code=status_code, content=result)
