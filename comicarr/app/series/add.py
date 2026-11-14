#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Series add seam: add a series from its metadata provider, or queue it.

The only door from ``comicarr/app/`` into the legacy ``comicarr/importer.py``
(Series add, see ``CONTEXT.md``), per ADR-0005 and section 2 of
``docs/architecture/foundations-plan.md``. Behavior is unchanged; the bodies
still live in ``importer.py``.

The three worker queues are the mass-add queue (``queue_series_adds``), the
issue-want queue that the mass-add worker drains after its adds
(``queue_issue_wants``), and the refresh queue (``refresh_series``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def add_series(comic_id: str, *, metadata_only: bool = False) -> Any:
    """Add or update ``comic_id`` now, through ``importer.addComictoDB``.

    ``metadata_only`` stores the series and its issues unmonitored, without
    searching or placing files. Returns whatever ``addComictoDB`` returns:
    usually a dict carrying ``status``, but legacy paths return a string or
    ``None``.
    """
    from comicarr import importer

    return importer.addComictoDB(comic_id, metadata_only=metadata_only)


def add_manga(comic_id: str) -> Any:
    """Add or update the manga ``comic_id`` now, from its provider.

    MyAnimeList ids go through ``importer.addMangaToDB_MAL``; everything else
    through ``importer.addMangaToDB`` (MangaDex).
    """
    from comicarr import importer, series_kind

    if series_kind.provider_of(comic_id) is series_kind.SeriesProvider.MYANIMELIST:
        return importer.addMangaToDB_MAL(comic_id)
    return importer.addMangaToDB(comic_id)


def queue_series_adds(series: Sequence[Mapping[str, Any]]) -> None:
    """Put each series dict on the mass-add queue and start its worker if idle.

    Each dict carries ``comicid``, ``comicname`` and ``seriesyear``, and
    optionally ``location``. Delegates to ``importer.importer_thread``.
    """
    from comicarr import importer

    importer.importer_thread(list(series))


def queue_issue_wants(issue_ids: Sequence[str]) -> None:
    """Queue issues to be marked Wanted once the mass-add worker drains its adds.

    Delegates to ``importer.issue_watcher_thread``, which does not start the
    worker itself.
    """
    from comicarr import importer

    importer.issue_watcher_thread(list(issue_ids))


def refresh_series(series: Sequence[Mapping[str, Any]]) -> str | None:
    """Record a refresh run for each series dict and hand it to the refresh worker.

    Delegates to ``importer.refresh_thread``. Returns the run id, or ``None``
    when ``series`` is empty. Raises what the handoff raises, such as
    ``MaintenanceBlocked``.
    """
    from comicarr import importer

    return importer.refresh_thread(list(series))
