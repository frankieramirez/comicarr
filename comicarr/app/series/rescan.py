#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Series rescan seam: re-read a series folder and reconcile issue status.

Other modules call ``rescan_series``. The body lives in
``app/series/folder_rescan.py`` (moved from ``updater.forceRescan`` by #1459);
manga series are routed to ``app/manga/rescan.py`` from inside it.
"""

from __future__ import annotations


def rescan_series(comic_id: str, *, archive: str | None = None) -> None:
    """Rescan ``comic_id``'s folder, or ``archive`` instead when given.

    Files found there become Downloaded (Archived when scanning ``archive``);
    Downloaded issues whose file is gone become Archived unless the series is
    Paused. Raises whatever the folder rescan raises.
    """
    from comicarr.app.series import folder_rescan

    if archive is None:
        folder_rescan.force_rescan(comic_id)
    else:
        folder_rescan.force_rescan(comic_id, archive=archive)
