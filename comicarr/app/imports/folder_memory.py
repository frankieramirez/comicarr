#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The series a person picked for an import inbox folder.

The inbox groups files by their top folder and keys that group
``folder:<hash of the folder path>``. When someone matches such a group by
hand, the pick is kept here, and the next inbox scan that finds new files in
the same folder uses it instead of guessing again. Files dropped loose in the
inbox root are never remembered: each one is its own group.
"""

from __future__ import annotations

import time

from sqlalchemy import select

from comicarr import db, logger
from comicarr.tables import import_folder_choices, importresults

FOLDER_PREFIX = "folder:"


def is_folder_key(group_key) -> bool:
    return isinstance(group_key, str) and group_key.startswith(FOLDER_PREFIX)


def recall(group_key):
    """``{comic_id, comic_name, folder_name, chosen_at}`` for a folder group, or ``None``."""
    if not is_folder_key(group_key):
        return None
    try:
        row = db.select_one(select(import_folder_choices).where(import_folder_choices.c.folder_key == group_key))
    except Exception as e:
        logger.fdebug("[IMPORT-MEMORY] Unable to read the folder choice for %s: %s" % (group_key, e))
        return None
    if not row:
        return None
    return {
        "comic_id": str(row["comic_id"]),
        "comic_name": row["comic_name"],
        "folder_name": row["folder_name"],
        "chosen_at": row["chosen_at"],
    }


def folder_of(imp_ids):
    """The one inbox folder group these import rows share, as ``(key, name)``, else ``None``."""
    ids = [str(i) for i in imp_ids or [] if i]
    if not ids:
        return None
    rows = db.select_all(
        select(importresults.c.DynamicName, importresults.c.ComicName, importresults.c.MatchSource).where(
            importresults.c.impID.in_(ids)
        )
    )
    keys = {row["DynamicName"] for row in rows or []}
    if len(keys) != 1:
        return None
    key = next(iter(keys))
    if not is_folder_key(key):
        return None
    return key, next((row["ComicName"] for row in rows if row["ComicName"]), None)


def remember(folder, comic_id, comic_name=None):
    """Keep the series picked for ``folder`` (from :func:`folder_of`). Never raises."""
    if not folder or not comic_id:
        return False
    key, name = folder
    try:
        db.upsert(
            "import_folder_choices",
            {
                "folder_name": name,
                "comic_id": str(comic_id),
                "comic_name": comic_name,
                "chosen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            {"folder_key": key},
        )
    except Exception as e:
        logger.warning("[IMPORT-MEMORY] Unable to remember the pick for folder '%s': %s" % (name or key, e))
        return False
    logger.fdebug("[IMPORT-MEMORY] Folder '%s' now imports as %s" % (name or key, comic_name or comic_id))
    return True
