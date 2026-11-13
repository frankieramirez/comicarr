#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Seam for RSS feed checking (ADR-0005).

The only module under ``comicarr/app/`` that may import the legacy
``rsscheck`` and ``rsscheckit`` modules. Each function delegates; the bodies
stay in the legacy modules until a later step moves them here.
"""

from __future__ import annotations


def run_feed_check(forcerss: bool = False) -> bool | None:
    """Run one RSS pass: refresh every enabled feed, then search the Wanted list.

    Returns True when the pass ran, None when the check interval had not
    elapsed yet. A forced pass ignores the interval.
    """
    from comicarr import rsscheckit

    return rsscheckit.tehMain().run(forcerss)


def check_manga_releases() -> None:
    """Search the blended frontier of every active manga series against rssdb."""
    from comicarr import rsscheck

    rsscheck.mangaCheck()


def check_mangadex_new_chapters() -> None:
    """Add MangaDex chapters not yet tracked as Wanted issues."""
    from comicarr import rsscheck

    rsscheck.mangadexNewChapterCheck()
