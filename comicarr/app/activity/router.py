#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Activity Center HTTP read surface.

Endpoints:

* ``GET /api/activity/timeline`` — narrative events, newest first
* ``GET /api/activity/band`` — needs-attention groups (R9 predicate, grouped)
* ``GET /api/activity/status`` — derived open-work counts (never narrative)
* ``GET /api/activity/in-flight`` — the rows that status counts as in-flight

**Pagination choice:** timeline pages *events* ordered by ``created_at``.
Story grouping (25 stories per UI page) is a client concern so the API can
support arbitrary story sizes without re-querying. Clients pass optional
``scope_type`` + ``scope_id`` for series rollup or issue/annual exact match
(Activity Center ADR §§5–6).
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from comicarr.app.activity import service
from comicarr.app.activity.queries import TIMELINE_LIMIT_DEFAULT, TIMELINE_LIMIT_MAX, TIMELINE_LIMIT_MIN
from comicarr.app.core.security import require_session

router = APIRouter(prefix="/api/activity", tags=["activity"])


def _scope_error(exc):
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/timeline", dependencies=[Depends(require_session)])
def get_timeline(
    limit: int = Query(TIMELINE_LIMIT_DEFAULT, ge=TIMELINE_LIMIT_MIN, le=TIMELINE_LIMIT_MAX),
    offset: int = Query(0, ge=0),
    scope_type: str | None = Query(None, max_length=32),
    scope_id: str | None = Query(None, max_length=255),
):
    """Return a page of narrative activity events (newest first).

    Pages events, not pre-grouped stories. Optional ``scope_type`` /
    ``scope_id`` filters: ``issue``/``annual`` exact subject match; ``series``
    rollup via ``parent_series_id``, series subject rows, and series-scoped
    run events.
    """
    try:
        return service.get_timeline(
            limit=limit,
            offset=offset,
            scope_type=scope_type,
            scope_id=scope_id,
        )
    except ValueError as e:
        _scope_error(e)


@router.get("/band", dependencies=[Depends(require_session)], deprecated=True)
def get_attention_band(
    scope_type: str | None = Query(None, max_length=32),
    scope_id: str | None = Query(None, max_length=255),
):
    """Deprecated adapter for ``GET /api/attention``.

    Members are filtered by scope before grouping. The canonical route owns
    this interface; Activity retains the old path for one compatibility release.
    """
    try:
        return service.get_attention_band(scope_type=scope_type, scope_id=scope_id)
    except ValueError as e:
        _scope_error(e)


@router.get("/status", dependencies=[Depends(require_session)])
def get_status():
    """Return derived open-work counts for the quiet-counts status indicator.

    ``in_flight`` = accepted|running run items + OPEN_STAGES journal.
    ``recovery_pending`` = the subset of those run items that has survived a
    restart — a qualifier on ``in_flight``, not an addition to it (#555).
    ``attention`` = unresolved band count. Never aggregates activity_events.
    """
    return service.get_status()


@router.get("/in-flight", dependencies=[Depends(require_session)])
def get_in_flight():
    """Return the rows counted as in-flight.

    Same membership as ``GET /api/activity/status`` ``in_flight``:
    accepted|running run items plus OPEN_STAGES journal rows. Each item has a
    stable identity (``kind`` plus ``item_id`` or ``release_key``).
    """
    return service.get_in_flight()
