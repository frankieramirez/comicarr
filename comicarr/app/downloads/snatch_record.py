#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Snatch bookkeeping seam (ADR-0005, Foundations plan section 2).

``record_release_link`` writes the ``nzblog`` row that ties a release to an
issue for post-processing. ``record_snatch`` marks the issue Snatched, writes
the ``snatched`` history row and the journal ``snatched`` transition. Both
delegate to ``comicarr.updater`` for now; the bodies move here later.
"""

from __future__ import annotations

from typing import Any


def record_release_link(
    issue_id: str | None,
    nzb_name: str,
    comic_name: str,
    *,
    provider: str,
    nzb_id: str | None = None,
    one_off: bool = False,
) -> dict[str, Any]:
    """Record the release-to-issue link (``updater.nzblog``)."""
    from comicarr import updater

    return updater.nzblog(issue_id, nzb_name, comic_name, id=nzb_id, prov=provider, oneoff=one_off)


def record_snatch(
    comic_id: str,
    issue_id: str,
    *,
    mode: str,
    provider: str,
    hash: str | None = None,
    journal_release_key: str | None = None,
    journal_managed: bool = False,
) -> None:
    """Record that a release was snatched (``updater.foundsearch``)."""
    from comicarr import updater

    updater.foundsearch(
        comic_id,
        issue_id,
        mode=mode,
        provider=provider,
        hash=hash,
        journal_release_key=journal_release_key,
        journal_managed=journal_managed,
    )
