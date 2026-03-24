#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Metadata domain queries — cover image cache, tmp_searches table.

Uses SQLAlchemy Core via the existing db module.
"""

from sqlalchemy import select

from comicarr import db
from comicarr.tables import comics as t_comics


def get_comic_image_urls(comic_id):
    """Get image URLs for a comic."""
    stmt = select(
        t_comics.c.ComicImageURL,
        t_comics.c.ComicImageALTURL,
        t_comics.c.ComicImage,
    ).where(t_comics.c.ComicID == comic_id)
    return db.select_one(stmt)


def get_comics_needing_images(limit=50):
    """Get comics that are missing cover images."""
    stmt = (
        select(t_comics.c.ComicID, t_comics.c.ComicImageURL, t_comics.c.ComicImageALTURL)
        .where(t_comics.c.ComicImage.is_(None))
        .limit(limit)
    )
    return db.select_all(stmt)


def update_comic_image(comic_id, image_path):
    """Update the cached image path for a comic."""
    from comicarr.tables import comics
    db.upsert(comics, {"ComicID": comic_id, "ComicImage": image_path})
