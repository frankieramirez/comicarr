#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Activity Center read service — shapes query results for HTTP handlers."""

from comicarr.app.activity import queries
from comicarr.app.attention import PREVIEW_CAP, Scope, read
from comicarr.app.attention._serialization import serialize_view

# Deprecated local alias for the canonical Attention preview cap.
ATTENTION_PREVIEW_CAP = PREVIEW_CAP


def get_timeline(limit=None, offset=None, scope_type=None, scope_id=None):
    """Paginated narrative timeline events (not pre-grouped stories)."""
    return queries.list_timeline_events(
        limit=limit,
        offset=offset,
        scope_type=scope_type,
        scope_id=scope_id,
    )


def get_attention_band(scope_type=None, scope_id=None):
    """Deprecated Activity adapter for the canonical Attention read interface."""
    normalized_type, normalized_id = queries._normalize_scope(scope_type, scope_id)
    scope = None
    if normalized_type is not None:
        scope = Scope(type=normalized_type, id=normalized_id)
    return serialize_view(read(scope=scope), preview_cap=ATTENTION_PREVIEW_CAP)


def get_status():
    """Open-work counts for the global quiet-counts status indicator."""
    return queries.get_open_work_counts()
