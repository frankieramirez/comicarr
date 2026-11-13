#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Series refresh seam: re-pull series metadata from its provider.

The only door from ``comicarr/app/`` into the refresh job in the legacy
``comicarr/updater.py`` (``dbUpdate`` and friends), per ADR-0005 and section 2
of ``docs/architecture/foundations-plan.md``. Behavior is unchanged; the body
still lives in ``updater.py``.
"""

from __future__ import annotations

from collections.abc import Sequence


def refresh_series_metadata(comic_ids: Sequence[str], *, calledfrom: str | None = None) -> None:
    """Refresh the named series now, through ``updater.dbUpdate``.

    ``calledfrom`` is the legacy caller tag ``dbUpdate`` branches on
    (``"dupechk"``, ``"refresh"``, ...).
    """
    from comicarr import updater

    updater.dbUpdate(ComicIDList=list(comic_ids), calledfrom=calledfrom)
