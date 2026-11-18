#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Deprecated REST routes kept as aliases (ADR-0006, #1501).

A route in the registry still answers. Each answer carries a ``Deprecation``
header (RFC 9745) and a ``Link`` to its notice, so a script that reads headers
can tell. The first call in a process logs one warning, and every call is
recorded at most hourly, so Activity > Health lists the route for 30 days after
its last use.
"""

import threading

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

from comicarr.app.core import logger
from comicarr.app.mcp.usage import ToolCallRecorder
from comicarr.app.system import deprecations

# The day #1501 announced the first route aliases, as an RFC 9745 date.
DEPRECATED_SINCE = "@1794960000"

_calls = ToolCallRecorder()
_warned: set[str] = set()
_warned_lock = threading.Lock()


def headers(entry_id: str) -> dict[str, str]:
    entry = deprecations.entry(entry_id)
    return {"Deprecation": DEPRECATED_SINCE, "Link": '<%s>; rel="deprecation"' % entry.docs_url}


def record_call(entry_id: str) -> None:
    """Note a call to the deprecated route ``entry_id``: a usage row and, once per process, a warning."""
    entry = deprecations.entry(entry_id)
    _calls.record(deprecations.route_usage_key(entry_id))
    with _warned_lock:
        if entry_id in _warned:
            return
        _warned.add(entry_id)
    logger.warn(
        "[DEPRECATION] %s was called. It is deprecated since %s and may be removed from %s. Use instead: %s. See %s"
        % (entry.name, entry.announced_in, entry.removable_from, entry.replacement, entry.docs_url)
    )


def answer(entry_id: str, result) -> Response:
    """Record the call and return ``result`` with the deprecation headers added."""
    record_call(entry_id)
    response = result if isinstance(result, Response) else JSONResponse(content=jsonable_encoder(result))
    response.headers.update(headers(entry_id))
    return response
