#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Scheduled manga ledger refresh and in-place healing.

Uses prefix *or* ContentType so a legacy row restamped ``comic`` by alembic
0002 is still visible. Does not invent live NAS counts.
"""

from sqlalchemy import func, or_, select

from comicarr import db, logger
from comicarr.tables import comics as t_comics
from comicarr.tables import issues as t_issues

JOB_ID = "manga_sync"
JOB_NAME = "Manga ledger sync"


def active_manga_clause():
    """Active series that are manga by stored kind *or* ComicID prefix."""
    return or_(
        t_comics.c.ContentType == "manga",
        t_comics.c.ComicID.like("md-%"),
        t_comics.c.ComicID.like("mal-%"),
    )


def list_active_manga_series():
    return db.select_all(
        select(t_comics).where(
            active_manga_clause(),
            t_comics.c.Status != "Paused",
        )
    )


def empty_ledger_series():
    """Series with zero issue rows — added but never populated."""
    counted = select(t_issues.c.ComicID, func.count().label("n")).group_by(t_issues.c.ComicID).subquery()
    return db.select_all(
        select(t_comics)
        .select_from(t_comics.outerjoin(counted, t_comics.c.ComicID == counted.c.ComicID))
        .where(
            active_manga_clause(),
            t_comics.c.Status != "Paused",
            or_(counted.c.n.is_(None), counted.c.n == 0),
        )
    )


def heal_empty_ledgers():
    """Re-run add for manga series that have no chapter rows. No re-add from search."""
    from comicarr import importer, series_kind

    healed = 0
    for series in empty_ledger_series():
        comic_id = series["ComicID"]
        logger.info("[MANGA-SYNC] Healing empty ledger for %s" % comic_id)
        try:
            if series_kind.provider_of(comic_id) is series_kind.SeriesProvider.MYANIMELIST:
                importer.addMangaToDB_MAL(comic_id)
            else:
                importer.addMangaToDB(comic_id)
            healed += 1
        except Exception as e:
            logger.error("[MANGA-SYNC] Heal failed for %s: %s" % (comic_id, e))
    return healed


def run_manga_sync():
    """Scheduled: heal empty ledgers, poll MangaDex, then search wanted."""
    from comicarr.rsscheck import mangaCheck, mangadexNewChapterCheck

    healed = heal_empty_ledgers()
    mangadexNewChapterCheck()
    mangaCheck()
    return {"healed": healed}
