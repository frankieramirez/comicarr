#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Seam for RSS feed checking (ADR-0005).

Callers outside ``app/search`` go through these functions. Each one delegates
to ``rss_runner`` (the scheduled pass) or ``rss_feeds`` (the feed engine), which
moved here from the root ``rsscheckit.py`` and ``rsscheck.py`` (#1523).
"""

from __future__ import annotations


def run_feed_check(forcerss: bool = False) -> bool | None:
    """Run one RSS pass: refresh every enabled feed, then search the Wanted list.

    Returns True when the pass ran, None when the check interval had not
    elapsed yet. A forced pass ignores the interval.
    """
    from comicarr.app.search import rss_runner

    return rss_runner.tehMain().run(forcerss)


def check_manga_releases() -> None:
    """Search the blended frontier of every active manga series against rssdb."""
    from comicarr.app.search import rss_feeds

    rss_feeds.mangaCheck()


def check_mangadex_new_chapters() -> None:
    """Add MangaDex chapters not yet tracked as Wanted issues."""
    from comicarr.app.search import rss_feeds

    rss_feeds.mangadexNewChapterCheck()
