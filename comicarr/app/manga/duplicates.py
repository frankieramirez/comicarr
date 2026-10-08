#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""Look up a manga series that is already tracked under either provider."""

from sqlalchemy import or_, select

from comicarr import db, series_kind
from comicarr.tables import comics


def find_existing_manga_series(*, comic_id=None, mal_id=None, mangadex_id=None):
    """Return the comics row that already tracks this work, or None.

    Matches on MangaDexID, MalID, or the prefixed ComicID for either provider.
    A row whose ComicID equals ``comic_id`` is ignored so a refresh of the same
    series is not treated as a duplicate.
    """
    mal_id = series_kind.strip_prefix(mal_id) if mal_id else ""
    mangadex_id = series_kind.strip_prefix(mangadex_id) if mangadex_id else ""
    comic_id = str(comic_id) if comic_id else None

    clauses = []
    if mangadex_id:
        clauses.append(comics.c.MangaDexID == mangadex_id)
        clauses.append(comics.c.ComicID == series_kind.add_prefix(mangadex_id, series_kind.SeriesProvider.MANGADEX))
    if mal_id:
        clauses.append(comics.c.MalID == mal_id)
        clauses.append(comics.c.ComicID == series_kind.add_prefix(mal_id, series_kind.SeriesProvider.MYANIMELIST))
    if not clauses:
        return None

    stmt = select(comics).where(or_(*clauses))
    if comic_id:
        stmt = stmt.where(comics.c.ComicID != comic_id)
    return db.select_one(stmt)
