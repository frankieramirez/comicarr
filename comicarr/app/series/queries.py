#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Series domain queries — comics, issues, annuals, importresults tables.

Uses SQLAlchemy Core via the existing db module.
"""

from sqlalchemy import delete, func, select

from comicarr import db
from comicarr.tables import annuals as t_annuals
from comicarr.tables import comics as t_comics
from comicarr.tables import importresults as t_importresults
from comicarr.tables import issues as t_issues
from comicarr.tables import storyarcs as t_storyarcs
from comicarr.tables import upcoming as t_upcoming

# ---------------------------------------------------------------------------
# Column projections (matching api.py _*_COLUMNS)
# ---------------------------------------------------------------------------

COMICS_COLUMNS = [
    t_comics.c.ComicID.label("ComicID"),
    t_comics.c.ComicName.label("ComicName"),
    t_comics.c.ComicImageURL.label("ComicImage"),
    t_comics.c.Status.label("Status"),
    t_comics.c.ComicPublisher.label("ComicPublisher"),
    t_comics.c.ComicYear.label("ComicYear"),
    t_comics.c.LatestIssue.label("LatestIssue"),
    t_comics.c.Total.label("Total"),
    t_comics.c.Have.label("Have"),
    t_comics.c.DetailURL.label("DetailURL"),
    t_comics.c.ContentType.label("ContentType"),
]

ISSUES_COLUMNS = [
    t_issues.c.IssueID.label("id"),
    t_issues.c.IssueName.label("name"),
    t_issues.c.ImageURL.label("imageURL"),
    t_issues.c.Issue_Number.label("number"),
    t_issues.c.ReleaseDate.label("releaseDate"),
    t_issues.c.IssueDate.label("issueDate"),
    t_issues.c.Status.label("status"),
    t_issues.c.ComicName.label("comicName"),
    t_issues.c.ChapterNumber.label("chapterNumber"),
    t_issues.c.VolumeNumber.label("volumeNumber"),
]

ANNUALS_COLUMNS = [
    t_annuals.c.IssueID.label("id"),
    t_annuals.c.IssueName.label("name"),
    t_annuals.c.Issue_Number.label("number"),
    t_annuals.c.ReleaseDate.label("releaseDate"),
    t_annuals.c.IssueDate.label("issueDate"),
    t_annuals.c.Status.label("status"),
    t_annuals.c.ComicName.label("comicName"),
]


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------

def paginated_query(stmt, limit=None, offset=None):
    """Execute a statement with optional pagination. Returns dict with results/total/has_more."""
    count_stmt = select(func.count()).select_from(stmt.subquery())
    with db.get_engine().connect() as conn:
        total = conn.execute(count_stmt).scalar() or 0

    current_limit = int(limit) if limit is not None else total
    current_offset = int(offset) if offset else 0

    paginated_stmt = stmt
    if limit is not None:
        paginated_stmt = paginated_stmt.limit(int(limit))
        if offset is not None and int(offset) > 0:
            paginated_stmt = paginated_stmt.offset(int(offset))

    results = db.select_all(paginated_stmt)
    has_more = (current_offset + len(results)) < total

    return {
        "results": results,
        "total": total,
        "limit": current_limit,
        "offset": current_offset,
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# Series (comics) queries
# ---------------------------------------------------------------------------

def list_comics():
    """List all comics ordered by sort name."""
    return db.select_all(select(*COMICS_COLUMNS).order_by(t_comics.c.ComicSortName))


def list_comics_paginated(limit, offset=0):
    """List comics with pagination."""
    stmt = select(*COMICS_COLUMNS).order_by(t_comics.c.ComicSortName)
    return paginated_query(stmt, limit=limit, offset=offset)


def get_comic(comic_id):
    """Get a single comic's summary columns."""
    stmt = select(*COMICS_COLUMNS).where(t_comics.c.ComicID == comic_id)
    return db.select_all(stmt)


def get_comic_for_delete(comic_id):
    """Get comic name/year/location for deletion confirmation."""
    return db.select_one(
        select(t_comics.c.ComicName, t_comics.c.ComicYear, t_comics.c.ComicLocation)
        .where(t_comics.c.ComicID == comic_id)
    )


def get_comic_name(comic_id):
    """Get just the comic name for a given ID."""
    row = db.select_one(select(t_comics.c.ComicName).where(t_comics.c.ComicID == comic_id))
    return row["ComicName"] if row else None


def get_comic_for_refresh(comic_id):
    """Get comic name/year for refresh validation."""
    return db.select_one(
        select(t_comics.c.ComicName, t_comics.c.ComicYear).where(t_comics.c.ComicID == comic_id)
    )


def delete_comic(comic_id):
    """Delete a comic and its issues/upcoming entries in a single transaction."""
    with db.get_engine().begin() as conn:
        conn.execute(delete(t_comics).where(t_comics.c.ComicID == comic_id))
        conn.execute(delete(t_issues).where(t_issues.c.ComicID == comic_id))
        conn.execute(delete(t_upcoming).where(t_upcoming.c.ComicID == comic_id))


def pause_comic(comic_id):
    """Set comic status to Paused."""
    db.upsert("comics", {"Status": "Paused"}, {"ComicID": comic_id})


def resume_comic(comic_id):
    """Set comic status to Active."""
    db.upsert("comics", {"Status": "Active"}, {"ComicID": comic_id})


# ---------------------------------------------------------------------------
# Issue queries
# ---------------------------------------------------------------------------

def get_issues(comic_id):
    """Get all issues for a comic, ordered by issue number descending."""
    stmt = select(*ISSUES_COLUMNS).where(t_issues.c.ComicID == comic_id).order_by(t_issues.c.Int_IssueNumber.desc())
    return db.select_all(stmt)


def get_annuals(comic_id):
    """Get all annuals for a comic."""
    return db.select_all(select(*ANNUALS_COLUMNS).where(t_annuals.c.ComicID == comic_id))


def queue_issue(issue_id):
    """Mark an issue as Wanted."""
    db.upsert("issues", {"Status": "Wanted"}, {"IssueID": issue_id})


def unqueue_issue(issue_id):
    """Mark an issue as Skipped."""
    db.upsert("issues", {"Status": "Skipped"}, {"IssueID": issue_id})


# ---------------------------------------------------------------------------
# Wanted queries
# ---------------------------------------------------------------------------

def get_wanted_issues(limit=None, offset=None):
    """Get all wanted issues joined with comic info."""
    stmt = (
        select(
            t_comics.c.ComicName,
            t_comics.c.ComicYear,
            t_comics.c.ComicVersion,
            t_comics.c.Type.label("BookType"),
            t_comics.c.ComicPublisher,
            t_comics.c.PublisherImprint,
            t_issues.c.Issue_Number,
            t_issues.c.IssueName,
            t_issues.c.ReleaseDate,
            t_issues.c.IssueDate,
            t_issues.c.DigitalDate,
            t_issues.c.Status,
            t_issues.c.ComicID,
            t_issues.c.IssueID,
            t_issues.c.DateAdded,
        )
        .select_from(t_comics.join(t_issues, t_comics.c.ComicID == t_issues.c.ComicID))
        .where(t_issues.c.Status == "Wanted")
    )
    if limit is not None:
        return paginated_query(stmt, limit=limit, offset=offset)
    return db.select_all(stmt)


def get_wanted_storyarc_issues():
    """Get wanted story arc issues."""
    return db.select_all(
        select(
            t_storyarcs.c.StoryArc,
            t_storyarcs.c.StoryArcID,
            t_storyarcs.c.IssueArcID,
            t_storyarcs.c.ComicName,
            t_storyarcs.c.IssueNumber,
            t_storyarcs.c.IssueName,
            t_storyarcs.c.ReleaseDate,
            t_storyarcs.c.IssueDate,
            t_storyarcs.c.DigitalDate,
            t_storyarcs.c.Status,
            t_storyarcs.c.ComicID,
            t_storyarcs.c.IssueID,
            t_storyarcs.c.DateAdded,
        ).where(t_storyarcs.c.Status == "Wanted")
    )


def get_wanted_annuals():
    """Get wanted annuals joined with comic info."""
    return db.select_all(
        select(
            t_annuals.c.ReleaseComicName.label("ComicName"),
            t_comics.c.ComicYear,
            t_comics.c.ComicVersion,
            t_comics.c.Type.label("BookType"),
            t_comics.c.ComicPublisher,
            t_comics.c.PublisherImprint,
            t_comics.c.ComicName.label("SeriesName"),
            t_annuals.c.Issue_Number.label("Issue_Number"),
            t_annuals.c.IssueName,
            t_annuals.c.ReleaseDate,
            t_annuals.c.IssueDate,
            t_annuals.c.DigitalDate,
            t_annuals.c.Status,
            t_annuals.c.ComicID,
            t_annuals.c.IssueID,
            t_annuals.c.ReleaseComicID.label("SeriesComicID"),
            t_annuals.c.DateAdded,
        )
        .select_from(t_comics.join(t_annuals, t_comics.c.ComicID == t_annuals.c.ComicID))
        .where(t_annuals.c.Deleted != 1)
        .where(t_annuals.c.Status == "Wanted")
    )


# ---------------------------------------------------------------------------
# Import queries
# ---------------------------------------------------------------------------

def get_import_pending(limit=50, offset=0, include_ignored=False):
    """Get pending import files grouped by DynamicName/Volume with pagination."""
    ir = t_importresults

    base_conds = [
        (ir.c.WatchMatch.is_(None)) | (ir.c.WatchMatch.like("C%")),
        ir.c.Status != "Imported",
    ]
    if not include_ignored:
        base_conds.append((ir.c.IgnoreFile.is_(None)) | (ir.c.IgnoreFile == 0))

    # Count distinct groups
    count_expr = func.count(func.distinct(func.concat(ir.c.DynamicName, func.coalesce(ir.c.Volume, ""))))
    count_stmt = select(count_expr).where(*base_conds)
    with db.get_engine().connect() as conn:
        total = conn.execute(count_stmt).scalar() or 0

    # Get paginated groups
    group_stmt = (
        select(ir, func.count().label("FileCount"))
        .where(*base_conds)
        .group_by(ir.c.DynamicName, ir.c.Volume)
        .order_by(ir.c.ComicName)
        .limit(limit)
        .offset(offset)
    )
    results = db.select_all(group_stmt)

    imports = []
    for result in results:
        dynamic_name = result["DynamicName"]
        volume = result["Volume"]

        # Get all files for this group
        file_conds = list(base_conds)
        file_conds.append(ir.c.DynamicName == dynamic_name)

        if volume is None or volume == "None":
            file_conds.append((ir.c.Volume.is_(None)) | (ir.c.Volume == "None"))
        else:
            file_conds.append(ir.c.Volume == volume)

        files = db.select_all(select(ir).where(*file_conds))

        file_list = []
        for f in files:
            file_list.append({
                "impID": f["impID"],
                "ComicFilename": f["ComicFilename"],
                "ComicLocation": f["ComicLocation"],
                "IssueNumber": f["IssueNumber"],
                "ComicYear": f["ComicYear"],
                "Status": f["Status"],
                "IgnoreFile": f["IgnoreFile"] or 0,
                "MatchConfidence": f["MatchConfidence"],
                "SuggestedComicID": f["SuggestedComicID"],
                "SuggestedComicName": f["SuggestedComicName"],
                "SuggestedIssueID": f["SuggestedIssueID"],
                "MatchSource": f["MatchSource"],
            })

        confidences = [f["MatchConfidence"] for f in file_list if f["MatchConfidence"] is not None]
        avg_confidence = sum(confidences) // len(confidences) if confidences else None

        imports.append({
            "DynamicName": dynamic_name,
            "ComicName": result["ComicName"],
            "Volume": volume,
            "ComicYear": result["ComicYear"],
            "FileCount": result["FileCount"],
            "Status": result["Status"],
            "SRID": result["SRID"],
            "ComicID": result["ComicID"],
            "MatchConfidence": avg_confidence,
            "SuggestedComicID": result["SuggestedComicID"],
            "SuggestedComicName": result["SuggestedComicName"],
            "files": file_list,
        })

    return {
        "imports": imports,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total,
        },
    }


def match_import(imp_id, comic_id, comic_name, issue_id=None):
    """Manually match an import file to a comic series."""
    update_values = {
        "ComicID": comic_id,
        "SuggestedComicID": comic_id,
        "SuggestedComicName": comic_name,
        "MatchSource": "manual",
        "MatchConfidence": 100,
        "WatchMatch": "C" + comic_id,
    }
    if issue_id:
        update_values["IssueID"] = issue_id
        update_values["SuggestedIssueID"] = issue_id

    db.upsert("importresults", update_values, {"impID": imp_id})


def ignore_import(imp_id, ignore=True):
    """Mark an import file as ignored or unignored."""
    db.upsert("importresults", {"IgnoreFile": 1 if ignore else 0}, {"impID": imp_id})


def delete_import(imp_id):
    """Delete an import record."""
    with db.get_engine().begin() as conn:
        conn.execute(delete(t_importresults).where(t_importresults.c.impID == imp_id))
