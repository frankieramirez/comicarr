#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Series add seam: add a series from its metadata provider, or queue it.

Other modules add a series (Series add, see ``CONTEXT.md``) through here. The
comic add lives in ``app/series/comic_add.py``, the manga add in
``app/manga/add.py`` and the worker queues in ``app/series/add_workers.py``,
all moved from ``comicarr/importer.py`` (#1463, #1464).

The three worker queues are the mass-add queue (``queue_series_adds``), the
issue-want queue that the mass-add worker drains after its adds
(``queue_issue_wants``), and the refresh queue (``refresh_series``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def add_series(comic_id: str, *, metadata_only: bool = False, calledfrom: str | None = None) -> Any:
    """Add or update ``comic_id`` now, through ``comic_add.add_comic``.

    ``metadata_only`` stores the series and its issues unmonitored, without
    searching or placing files. ``calledfrom`` is the legacy caller tag;
    ``"maintenance"`` (the database import) skips the post-add searches.
    Returns whatever ``add_comic`` returns: usually a dict carrying
    ``status``, but legacy paths return a string or ``None``.
    """
    from comicarr.app.series import comic_add

    if calledfrom is None:
        return comic_add.add_comic(comic_id, metadata_only=metadata_only)
    return comic_add.add_comic(comic_id, metadata_only=metadata_only, calledfrom=calledfrom)


def add_manga(comic_id: str) -> Any:
    """Add or update the manga ``comic_id`` now, from its provider.

    MyAnimeList ids go through ``app/manga/add.add_myanimelist``; everything
    else through ``add_mangadex`` (MangaDex).
    """
    from comicarr.app.common import series_kind
    from comicarr.app.manga import add as manga_add

    if series_kind.provider_of(comic_id) is series_kind.SeriesProvider.MYANIMELIST:
        return manga_add.add_myanimelist(comic_id)
    return manga_add.add_mangadex(comic_id)


def update_issue_data(
    comic_id: str,
    comic_name: str,
    *,
    calledfrom: str | None = None,
    serieslast_updated: str | None = None,
) -> Any:
    """Re-read a series' issue list from its source, through ``comic_add.update_issue_data``.

    The pull-list match calls it with ``calledfrom="weeklycheck"`` when a
    pulled issue is not in the series yet; the refresh worker passes the
    series' ``serieslast_updated``.
    """
    from comicarr.app.series import comic_add

    if serieslast_updated is None:
        return comic_add.update_issue_data(comic_id, comic_name, calledfrom=calledfrom)
    return comic_add.update_issue_data(
        comic_id, comic_name, calledfrom=calledfrom, serieslast_updated=serieslast_updated
    )


def reload_series(comic_id: str, mismatch: Any = None, **legacy_kwargs: Any) -> Any:
    """Re-run the add for a series being refreshed, through ``comic_add.add_comic``.

    ``legacy_kwargs`` are the refresh job's ``add_comic`` arguments
    (``calledfrom``, ``annload``, ``csyear``, ``fixed_type``) passed through
    unchanged.
    """
    from comicarr.app.series import comic_add

    return comic_add.add_comic(comic_id, mismatch, **legacy_kwargs)


def store_issue_rows(issuedata: Any, *, nostatus: Any, serieslast_updated: str | None = None) -> Any:
    """Write a refreshed series' issue rows, through ``comic_add.store_issue_rows``."""
    from comicarr.app.series import comic_add

    return comic_add.store_issue_rows(issuedata, nostatus=nostatus, serieslast_updated=serieslast_updated)


def add_manual_annual(**legacy_kwargs: Any) -> Any:
    """Add or refresh a series' annuals, through ``comic_add.add_manual_annual``."""
    from comicarr.app.series import comic_add

    return comic_add.add_manual_annual(**legacy_kwargs)


def refresh_worker_should_retire(refresh_queue: Any) -> bool:
    """Whether the refresh worker may stop: its queue is empty under the producer lock."""
    from comicarr.app.series import add_workers

    return add_workers.refresh_worker_should_retire(refresh_queue)


def queue_series_adds(series: Sequence[Mapping[str, Any]]) -> None:
    """Put each series dict on the mass-add queue and start its worker if idle.

    Each dict carries ``comicid``, ``comicname`` and ``seriesyear``, and
    optionally ``location``. Delegates to ``add_workers.queue_series_adds``.
    """
    from comicarr.app.series import add_workers

    add_workers.queue_series_adds(list(series))


def queue_issue_wants(issue_ids: Sequence[str]) -> None:
    """Queue issues to be marked Wanted once the mass-add worker drains its adds.

    Delegates to ``add_workers.queue_issue_wants``, which does not start the
    worker itself.
    """
    from comicarr.app.series import add_workers

    add_workers.queue_issue_wants(list(issue_ids))


def refresh_series(series: Sequence[Mapping[str, Any]]) -> str | None:
    """Record a refresh run for each series dict and hand it to the refresh worker.

    Delegates to ``add_workers.queue_refreshes``. Returns the run id, or ``None``
    when ``series`` is empty. Raises what the handoff raises, such as
    ``MaintenanceBlocked``.
    """
    from comicarr.app.series import add_workers

    return add_workers.queue_refreshes(list(series))
