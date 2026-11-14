#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Record when each MCP tool name was last called (#1312).

The deprecation registry reads ``mcp_tool_calls`` to tell whether a renamed
tool's old name is still in use. A busy agent must not write on every call, so
each name is written at most once per :data:`WRITE_EVERY_SECONDS` per process.
"""

import threading
import time

from comicarr import db, logger

WRITE_EVERY_SECONDS = 3600


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ToolCallRecorder:
    """Writes the last-call row for a tool name, at most once an hour per name."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._written = {}
        self._lock = threading.Lock()

    def record(self, name):
        now = self._clock()
        with self._lock:
            last = self._written.get(name)
            if last is not None and now - last < WRITE_EVERY_SECONDS:
                return
            # Claim the slot before writing, so a failing database is retried
            # hourly instead of on every call.
            self._written[name] = now
        try:
            db.upsert("mcp_tool_calls", {"last_called_at": utc_now()}, {"tool_name": name})
        except Exception as e:
            logger.warn("[MCP] Could not record a call to %s: %s" % (name, e))
