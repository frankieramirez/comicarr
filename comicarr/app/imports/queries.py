#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Database operations owned by manual import finalization."""

from collections.abc import Sequence

from sqlalchemy import func, or_, select, update

from comicarr import db
from comicarr.tables import importresults as t_importresults
from comicarr.tables import issues as t_issues


class ImportRecordChangedError(RuntimeError):
    """A selected Import Inbox record stopped being pending before commit."""


def get_import_rows(import_ids: Sequence[str]) -> list[dict]:
    """Load selected Import Inbox records for caller-side ordering."""
    if not import_ids:
        return []
    return db.select_all(select(t_importresults).where(t_importresults.c.impID.in_(import_ids)))


def get_issue_id(series_id: str, issue_number: str | None) -> str | None:
    """Resolve an issue or chapter ID for a manual import record."""
    if issue_number is None:
        return None
    normalized = str(issue_number).strip()
    if not normalized or normalized == "None":
        return None

    row = db.select_one(
        select(t_issues.c.IssueID)
        .where(t_issues.c.ComicID == series_id)
        .where(t_issues.c.ChapterNumber == normalized)
        .limit(1)
    )
    if row:
        return row["IssueID"]

    row = db.select_one(
        select(t_issues.c.IssueID)
        .where(t_issues.c.ComicID == series_id)
        .where(t_issues.c.Issue_Number == normalized)
        .limit(1)
    )
    return row["IssueID"] if row else None


def mark_imported(
    matches: Sequence[tuple[str, str | None]],
    series_id: str,
    series_name: str,
    *,
    match_source: str = "manual",
    match_confidence: int = 100,
) -> None:
    """Mark every selected record imported in one database transaction."""
    pending = or_(t_importresults.c.Status.is_(None), func.lower(t_importresults.c.Status) != "imported")
    with db.get_engine().begin() as conn:
        for import_id, issue_id in matches:
            values = {
                "ComicID": series_id,
                "ComicName": series_name,
                "Status": "Imported",
                "SuggestedComicID": series_id,
                "SuggestedComicName": series_name,
                "MatchSource": match_source,
                "MatchConfidence": match_confidence,
                "WatchMatch": "C" + series_id,
                "IgnoreFile": 0,
            }
            if issue_id:
                values["IssueID"] = issue_id
                values["SuggestedIssueID"] = issue_id

            result = conn.execute(
                update(t_importresults).where(t_importresults.c.impID == import_id).where(pending).values(**values)
            )
            if result.rowcount != 1:
                raise ImportRecordChangedError("Import record is missing or no longer pending: %s" % import_id)
