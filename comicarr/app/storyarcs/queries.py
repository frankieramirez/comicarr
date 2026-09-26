#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Story Arcs domain queries — storyarcs, readlist, weekly, upcoming tables.

Uses SQLAlchemy Core via the existing db module.
"""

from sqlalchemy import Integer, case, cast, func, literal, or_, select

from comicarr import db
from comicarr.tables import comics as t_comics
from comicarr.tables import issues as t_issues
from comicarr.tables import readlist as t_readlist
from comicarr.tables import storyarcs as t_storyarcs
from comicarr.tables import weekly as t_weekly


def _year_expr():
    """Reusable expression: extract 4-digit year from IssueDate, cast to int."""
    return case(
        (
            (t_storyarcs.c.IssueDate.isnot(None)) & (t_storyarcs.c.IssueDate != "0000-00-00"),
            cast(func.substr(t_storyarcs.c.IssueDate, 1, 4), Integer),
        ),
    )


def _arc_stats_columns():
    """Reusable aggregate columns for arc summary queries."""
    return [
        t_storyarcs.c.StoryArcID,
        func.max(t_storyarcs.c.StoryArc).label("StoryArc"),
        func.max(t_storyarcs.c.CV_ArcID).label("CV_ArcID"),
        func.max(t_storyarcs.c.Publisher).label("Publisher"),
        func.max(t_storyarcs.c.ArcImage).label("ArcImage"),
        func.count().label("Total"),
        func.sum(
            case(
                (t_storyarcs.c.Status.in_(["Downloaded", "Archived"]), 1),
                else_=0,
            )
        ).label("Have"),
        func.min(_year_expr()).label("min_year"),
        func.max(_year_expr()).label("max_year"),
    ]


def list_arcs(custom_only=False):
    """List all story arcs with aggregated stats."""
    stmt = (
        select(*_arc_stats_columns())
        .where(t_storyarcs.c.ComicName.isnot(None))
        .where(t_storyarcs.c.Manual != "deleted")
        .group_by(t_storyarcs.c.StoryArcID)
        .order_by(t_storyarcs.c.StoryArc)
    )
    if custom_only:
        stmt = stmt.where(t_storyarcs.c.StoryArcID.like("C%"))

    return db.select_all(stmt)


def get_arc_stats(arc_id):
    """Get aggregate stats for a single arc."""
    stmt = (
        select(*_arc_stats_columns())
        .where(t_storyarcs.c.StoryArcID == arc_id)
        .where(t_storyarcs.c.Manual != "deleted")
        .group_by(t_storyarcs.c.StoryArcID)
    )
    return db.select_one(stmt)


def get_arc_issues(arc_id):
    """Get all issues for an arc in reading order (excluding soft-deleted)."""
    stmt = (
        select(
            t_storyarcs.c.IssueArcID,
            t_storyarcs.c.ReadingOrder,
            t_storyarcs.c.ComicID,
            t_storyarcs.c.ComicName,
            t_storyarcs.c.IssueNumber,
            t_storyarcs.c.IssueID,
            t_storyarcs.c.Status,
            t_storyarcs.c.IssueDate,
            t_storyarcs.c.IssueName,
            t_storyarcs.c.IssuePublisher,
            t_storyarcs.c.Location,
        )
        .where(t_storyarcs.c.StoryArcID == arc_id)
        .where(t_storyarcs.c.Manual != "deleted")
        .order_by(t_storyarcs.c.ReadingOrder)
    )
    return db.select_all(stmt)


def get_arc_for_refresh(arc_id):
    """Get minimal arc info needed to trigger a refresh."""
    return db.raw_select_one(
        "SELECT CV_ArcID, StoryArc, StoryArcID FROM storyarcs WHERE StoryArcID=? LIMIT 1",
        [arc_id],
    )


def set_issue_status(issue_arc_id, status):
    """Update status of a single arc issue."""
    db.upsert("storyarcs", {"Status": status}, {"IssueArcID": issue_arc_id})


def soft_delete_arc_issue(issue_arc_id, manual=None):
    """Soft-delete or hard-delete an arc issue depending on manual flag."""
    if manual == "added":
        db.raw_execute("DELETE from storyarcs WHERE IssueArcID=?", [issue_arc_id])
    else:
        db.upsert("storyarcs", {"Manual": "deleted"}, {"IssueArcID": issue_arc_id})


def delete_arc(arc_id, arc_name=None, delete_type=None):
    """Delete an entire story arc and associated nzblog entries."""
    db.raw_execute("DELETE from storyarcs WHERE StoryArcID=?", [arc_id])

    if delete_type and arc_name:
        db.raw_execute("DELETE from storyarcs WHERE StoryArc=?", [arc_name])

    stid = "S" + str(arc_id) + r"\_%"
    db.raw_execute("DELETE from nzblog WHERE IssueID LIKE ? ESCAPE '\\'", [stid])


def want_all_issues(arc_id):
    """Mark all eligible arc issues as Wanted. Returns (queued, skipped) counts."""
    skipped_rows = db.raw_select_all(
        "SELECT COUNT(*) as count FROM storyarcs WHERE StoryArcID=? AND Manual != 'deleted' "
        "AND Status NOT IN ('Downloaded', 'Archived', 'Snatched') AND Status = 'Wanted'",
        [arc_id],
    )
    skipped = skipped_rows[0]["count"] if skipped_rows else 0

    db.raw_execute(
        "UPDATE storyarcs SET Status='Wanted' WHERE StoryArcID=? AND Manual != 'deleted' "
        "AND Status NOT IN ('Downloaded', 'Archived', 'Snatched', 'Wanted')",
        [arc_id],
    )

    queued_rows = db.raw_select_all(
        "SELECT COUNT(*) as count FROM storyarcs WHERE StoryArcID=? AND Manual != 'deleted' AND Status = 'Wanted'",
        [arc_id],
    )
    total_wanted = queued_rows[0]["count"] if queued_rows else 0
    queued = total_wanted - skipped

    return queued, skipped


def get_missing_series_rows(arc_id):
    """Arc rows whose needed issues belong to series not in the library."""
    watched = select(t_comics.c.ComicID)
    stmt = (
        select(
            t_storyarcs.c.IssueArcID,
            t_storyarcs.c.ComicName,
            t_storyarcs.c.ComicID,
            t_storyarcs.c.IssueNumber,
            t_storyarcs.c.SeriesYear,
            t_storyarcs.c.Publisher,
            t_storyarcs.c.ReadingOrder,
        )
        .where(t_storyarcs.c.StoryArcID == arc_id)
        .where(t_storyarcs.c.Manual != "deleted")
        .where(t_storyarcs.c.Status.notin_(["Downloaded", "Archived", "Snatched"]))
        .where(
            or_(
                t_storyarcs.c.ComicID.is_(None),
                t_storyarcs.c.ComicID == "",
                t_storyarcs.c.ComicID.notin_(watched),
            )
        )
        .order_by(t_storyarcs.c.ReadingOrder)
    )
    return db.select_all(stmt)


def get_arc_rows(arc_id):
    stmt = (
        select(t_storyarcs)
        .where(t_storyarcs.c.StoryArcID == arc_id)
        .where(t_storyarcs.c.Manual != "deleted")
        .order_by(t_storyarcs.c.ReadingOrder)
    )
    return db.select_all(stmt)


def get_comic_status(comic_id):
    stmt = select(t_comics.c.Status).where(t_comics.c.ComicID == comic_id).limit(1)
    return db.select_one(stmt)


def link_unlinked_series_rows(arc_id, series_name, comic_id):
    db.raw_execute(
        "UPDATE storyarcs SET ComicID=? WHERE StoryArcID=? "
        "AND (ComicID IS NULL OR ComicID='') AND LOWER(ComicName)=LOWER(?)",
        [comic_id, arc_id, series_name],
    )


def find_library_issue(issue_id=None, comic_id=None, int_issue_number=None):
    stmt = select(
        t_issues.c.IssueID,
        t_issues.c.Issue_Number,
        t_issues.c.Status,
        t_comics.c.ComicID,
        t_comics.c.ComicName,
        t_comics.c.ComicYear,
        t_comics.c.Type,
    ).select_from(t_issues.join(t_comics, t_issues.c.ComicID == t_comics.c.ComicID))
    if issue_id:
        stmt = stmt.where(t_issues.c.IssueID == issue_id)
    else:
        stmt = stmt.where(t_issues.c.ComicID == comic_id, t_issues.c.Int_IssueNumber == int_issue_number)
    return db.select_one(stmt.limit(1))


def set_arc_issue_fields(issue_arc_id, values):
    db.upsert("storyarcs", values, {"IssueArcID": issue_arc_id})


def mark_issue_wanted(issue_id):
    db.upsert("issues", {"Status": "Wanted"}, {"IssueID": issue_id})


def get_readlist():
    """Get all reading list entries ordered by issue date."""
    stmt = select(
        t_readlist.c.IssueID.label("id"),
        t_readlist.c.Issue_Number.label("number"),
        t_readlist.c.IssueDate.label("issueDate"),
        t_readlist.c.Status.label("status"),
        t_readlist.c.ComicName.label("comicName"),
    ).order_by(t_readlist.c.IssueDate.asc())
    return db.select_all(stmt)


def remove_readlist_issue(issue_id):
    """Remove a single issue from the reading list."""
    db.raw_execute("DELETE from readlist WHERE IssueID=?", [issue_id])


def remove_all_read():
    """Remove all issues marked as Read from the reading list."""
    db.raw_execute("DELETE from readlist WHERE Status='Read'")


def get_upcoming(week, year, include_downloaded=False):
    """Get upcoming issues for a given week/year from weekly + comics tables."""
    if include_downloaded:
        status_list = ["Wanted", "Snatched", "Downloaded"]
    else:
        status_list = ["Wanted"]

    padded_weeknumber = func.substr(literal("0").op("||")(t_weekly.c.weeknumber), -2, 2)

    stmt = (
        select(
            t_weekly.c.COMIC.label("ComicName"),
            t_weekly.c.ISSUE.label("IssueNumber"),
            t_weekly.c.ComicID,
            t_weekly.c.IssueID,
            t_weekly.c.SHIPDATE.label("IssueDate"),
            t_weekly.c.STATUS.label("Status"),
            t_comics.c.ComicName.label("DisplayComicName"),
        )
        .select_from(t_weekly.join(t_comics, t_weekly.c.ComicID == t_comics.c.ComicID))
        .where(t_weekly.c.COMIC.isnot(None))
        .where(t_weekly.c.ISSUE.isnot(None))
        .where(padded_weeknumber == week)
        .where(t_weekly.c.year == year)
        .where(t_weekly.c.STATUS.in_(status_list))
        .order_by(t_comics.c.ComicSortName)
    )
    return db.select_all(stmt)
