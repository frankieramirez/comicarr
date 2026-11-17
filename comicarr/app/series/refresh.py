#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Series refresh seam: re-pull series metadata from its provider.

Other modules refresh a series through here. The refresh job itself lives in
``app/series/watchlist_refresh.py`` (moved from ``updater.dbUpdate`` by #1462).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def refresh_series_metadata(comic_ids: Sequence[str], *, calledfrom: str | None = None) -> Any:
    """Refresh the named series now, through ``refresh_series_list``.

    ``calledfrom`` is the legacy caller tag the refresh job branches on
    (``"dupechk"``, ``"refresh"``, ``"weekly"``, ...). Returns what the job
    returns; the pull-list match reads it for ``"weekly"``.
    """
    from comicarr.app.series import watchlist_refresh

    return watchlist_refresh.refresh_series_list(ComicIDList=list(comic_ids), calledfrom=calledfrom)
