#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The deprecation registry (ADR-0006).

One entry per deprecated feature. An operator hears about an entry only when
its ``in_use()`` says this install relies on it: one warning in the log at
startup, and a row in Activity > Health through ``GET /api/system/deprecations``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import exists, select

import comicarr
from comicarr import db, logger
from comicarr.tables import annuals, issues, storyarcs


@dataclass(frozen=True)
class Deprecation:
    id: str
    name: str
    announced_in: str
    removable_from: str
    replacement: str
    docs_url: str
    in_use: Callable[[], bool]

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "announced_in": self.announced_in,
            "removable_from": self.removable_from,
            "replacement": self.replacement,
            "docs_url": self.docs_url,
        }


DOCS_URL = "https://comicarr.com/docs/deprecations"
ADD_MISSING_SERIES = "Add what's missing on the story arc, so its series join your library and the arc's issues download and copy to the arc folder the normal way"


def _arc_issue_wanted_without_library_issue() -> bool:
    in_library = exists().where(issues.c.IssueID == storyarcs.c.IssueID)
    in_annuals = exists().where(annuals.c.IssueID == storyarcs.c.IssueID)
    row = db.select_one(
        select(storyarcs.c.IssueArcID)
        .where(storyarcs.c.Status.in_(["Wanted", "Snatched"]), ~in_library, ~in_annuals)
        .limit(1)
    )
    return row is not None


def _arc_folder_matching_on() -> bool:
    if getattr(comicarr.CONFIG, "STORYARCDIR", False) is not True:
        return False
    return db.select_one(select(storyarcs.c.StoryArcID).limit(1)) is not None


REGISTRY: list[Deprecation] = [
    Deprecation(
        id="storyarc-oneoff",
        name="Downloading story-arc issues whose series is not in your library",
        announced_in="0.52.0",
        removable_from="1.0.0",
        replacement=ADD_MISSING_SERIES,
        docs_url=DOCS_URL + "#storyarc-oneoff",
        in_use=_arc_issue_wanted_without_library_issue,
    ),
    Deprecation(
        id="storyarc-folder-match",
        name="Matching scanned files to a story arc when their series is not in your library",
        announced_in="0.52.0",
        removable_from="1.0.0",
        replacement=ADD_MISSING_SERIES,
        docs_url=DOCS_URL + "#storyarc-folder-match",
        in_use=_arc_folder_matching_on,
    ),
]


def deprecations_in_use() -> list[Deprecation]:
    """Entries this install relies on. A predicate that raises counts as not in use."""
    found = []
    for entry in REGISTRY:
        try:
            if entry.in_use():
                found.append(entry)
        except Exception as e:
            logger.error("[DEPRECATION] Could not tell whether %s is in use: %s" % (entry.id, e))
    return found


def warn_deprecations_in_use() -> None:
    """Log one warning per entry in use. Called once at startup."""
    for entry in deprecations_in_use():
        logger.warn(
            "[DEPRECATION] %s is deprecated since %s and may be removed from %s. Use instead: %s. See %s"
            % (entry.name, entry.announced_in, entry.removable_from, entry.replacement, entry.docs_url)
        )
