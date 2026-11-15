#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Keep API keys sent in a query string out of uvicorn's access log.

Prowlarr's Mylar application authenticates with ``?apikey=`` and sends each
indexer's key as ``prov_apikey=``. Uvicorn logs every request line at info
level, so without this filter both keys would land in the console and in
Docker logs on every sync.
"""

from __future__ import annotations

import logging
import re

ACCESS_LOGGER = "uvicorn.access"
_QUERY_KEY = re.compile(r"(?i)([?&](?:prov_)?api_?key=)[^&\s]*")


def redact_query_keys(path: str) -> str:
    return _QUERY_KEY.sub(r"\1[redacted]", path)


class QueryKeyRedactionFilter(logging.Filter):
    """Rewrite the request path argument of a uvicorn access record."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = args[:2] + (redact_query_keys(args[2]),) + args[3:]
        return True


def install() -> None:
    """Attach the filter once; safe to call on every app start."""
    access_logger = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(existing, QueryKeyRedactionFilter) for existing in access_logger.filters):
        access_logger.addFilter(QueryKeyRedactionFilter())
