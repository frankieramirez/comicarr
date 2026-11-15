#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""``GET /api?cmd=...``: the Mylar3-compatible endpoint Prowlarr syncs through.

The API key travels in the ``apikey`` query parameter because that is where
Prowlarr's Mylar application puts it; the service checks it. Every answer is
HTTP 200 with Mylar3's envelope, because Prowlarr only shows an error message
it can read from the body.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from comicarr.app.core.context import AppContext, get_context
from comicarr.app.indexer_sync import service

router = APIRouter(tags=["indexer-sync"])


@router.get("/api", include_in_schema=False)
async def mylar_api(request: Request, ctx: AppContext = Depends(get_context)):
    result = await run_in_threadpool(service.handle, ctx, dict(request.query_params))
    return JSONResponse(content=result, headers={"Cache-Control": "no-store"})
